---
title: Authentification des routes
description: "Les quatre dépendances FastAPI qui protègent une route : identification du porteur, contrôle de l'audience, périmètre de tenance et autorisation par rôle scopé."
---

# Authentification des routes

Livré par **BACK-10c**. [Les jetons](./jetons.md) savaient déjà s'émettre et se vérifier ; cette page
décrit ce qui les branche sur une requête HTTP. C'est le point où l'isolation multi-tenant cesse
d'être une convention écrite ([ADR-0004](../adr/0004-tenance-par-groupe.md),
[ADR-0012](../adr/0012-perimetre-de-requete.md)) pour devenir du code exécuté à chaque appel.

Les décisions et leurs alternatives sont consignées dans
l'[ADR-0030](../adr/0030-perimetre-obligatoire-a-la-bordure.md).

## Protéger une route, en pratique

Deux gestes, et le premier se fait une fois par routeur.

```python
from app.shared.infrastructure.api.dependencies.auth import CurrentActiveAccount, audience_of
from app.shared.infrastructure.api.dependencies.tenant import ActiveClinic, require_role
from app.shared.infrastructure.security.jwt_service import ACCOUNT_TYPE_PROFESSIONAL

router = APIRouter(
    prefix="/consultations",
    tags=["medical_records"],
    dependencies=[Depends(audience_of(ACCOUNT_TYPE_PROFESSIONAL))],
)


@router.get("", operation_id="list_consultations")
async def list_consultations(account: CurrentActiveAccount, clinic: ActiveClinic) -> Page[...]: ...


@router.post(
    "",
    operation_id="create_consultation",
    dependencies=[Depends(require_role("veterinarian", scope="clinic"))],
)
async def create_consultation(clinic: ActiveClinic) -> ...: ...
```

**`audience_of` se déclare au routeur, jamais route par route.** C'est ce qui empêche de l'oublier
sur la trente-huitième. Une route protégée sans ce marqueur répond **500** — échec fermé, jamais un
accès accordé.

## Les quatre dépendances

| Dépendance                   | Répond à                                        | Coût                                 |
| ---------------------------- | ----------------------------------------------- | ------------------------------------ |
| `get_current_account`        | qui est le porteur, et son compte est-il ouvert | un `SELECT` sur le compte            |
| `get_current_active_account` | son adresse est-elle vérifiée                   | aucun (il s'appuie sur le précédent) |
| `require_role(scope=…)`      | a-t-il le droit, dans ce périmètre              | aucun en périmètre groupe            |
| `get_active_clinic`          | où travaille-t-il en ce moment                  | deux `SELECT`                        |

Les alias `CurrentAccount`, `CurrentActiveAccount` et `ActiveClinic` sont la forme à employer dans
les signatures. **`CurrentActiveAccount` est le défaut** ; `CurrentAccount` est réservé aux parcours
qui doivent servir un compte non vérifié — [la vérification d'adresse](./verification-email-otp.md),
et elle seule.

### Ce que le porteur porte

`AuthenticatedAccount` compose les claims vérifiés plutôt que de les recopier : `account.claims`
donne le sujet, l'audience, le groupe actif, le rôle de groupe et le `jti`, et `account.account_id`
est un raccourci vers le sujet. Le **statut** n'y figure pas : il a été contrôlé et refusé à la
bordure, rien en aval n'en a l'usage.

## Le mot « rôle » désigne deux choses

C'est pour cela que le périmètre est obligatoire, et vérifié par le **typage** :

- `scope="group"` — gérant, administrateur, superadministrateur. Lu dans le claim `group_role`,
  **aucune requête**. Le rôle est figé pour la durée du jeton : jusqu'à quinze minutes de latence sur
  une rétrogradation, budget assumé par l'[ADR-0024](../adr/0024-jetons-audience-par-application.md),
  et BACK-10d couvrira l'urgence.
- `scope="clinic"` — vétérinaire, ASV. Résolu **par requête** sur l'affectation de la clinique
  active, jamais depuis le jeton.

`require_role("asv", scope="group")` ne compile pas : les deux vocabulaires sont deux `Literal`
distincts. Omettre `scope` non plus.

**Un rôle de groupe n'active pas une clinique.** La gérante d'un groupe qui n'est affectée à aucune
de ses cliniques n'obtient pas de périmètre clinique : la seule preuve disponible est l'affectation.
Ses routes à elle sont de périmètre groupe.

## La clinique active, et ses deux vérifications

L'en-tête `X-Clinic-Id` **sélectionne** un périmètre parmi ceux déjà autorisés ; il n'en ouvre aucun.
`get_active_clinic` vérifie donc deux choses, par deux chemins qui ne partagent pas leur point de
défaillance :

1. **la clinique appartient au groupe actif** — lecture **non tenante** de son groupe propriétaire,
   comparée en clair à `require_current_group_id()` ;
2. **le compte y est affecté à cet instant** — la ligne existe dans la lecture filtrée par le
   contexte de tenance.

S'y ajoute une garde qui ferme la seule échappatoire réaliste : sous
[le mode « tous groupes »](./persistance.md), le filtre disparaît et la lecture rendrait les
affectations de tous les groupes. `require_current_group_id()` refuse ce mode.

`get_active_clinic` rend **l'affectation**, pas l'identifiant. Sans cela, un ASV d'une clinique
également vétérinaire dans une autre poserait un acte vétérinaire là où il est ASV : le rôle vient de
**la ligne** de la clinique active, jamais d'une agrégation sur le compte.

**Affectations chevauchantes** : rien ne les interdit ([ADR-0005](../adr/0005-appartenance-datee.md)),
et le dépôt trie du début le plus ancien. La bordure retient celle au début le **plus récent** — la
doctrine déjà écrite pour les appartenances, « la dernière décision prise l'emporte ». Sans cette
règle, une rétrogradation faite sans fermer l'affectation précédente serait sans effet, pour toujours.

## Ce que le client voit

La table complète des statuts vit dans
l'[ADR-0030](../adr/0030-perimetre-obligatoire-a-la-bordure.md). Trois règles suffisent à l'usage :

**Un seul 401, pour toutes les causes.** Jeton absent, illisible, expiré, mal signé, du mauvais type,
de la mauvaise audience, ou dont le sujet ne désigne aucun compte : même statut, même code, même
message, `WWW-Authenticate: Bearer` nu. Le contrat client est donc simple — **tout 401 déclenche un
rafraîchissement, et son échec une déconnexion**. Le client lit `exp` dans son propre jeton, il n'a
pas besoin du serveur pour savoir qu'il a expiré.

**403 pour un compte, 404 pour une clinique.** Suspendu et non vérifié sont des 403 à codes
distincts, parce que le front doit conduire l'un vers le support et l'autre vers son écran de
vérification — et parce que le porteur a déjà prouvé qu'il détient ce compte. Une clinique introuvable,
d'un autre groupe, ou sur laquelle le compte n'est pas affecté partagent en revanche **un seul 404** :
un 403 ferait de l'API un oracle d'énumération des cliniques concurrentes.

**500 pour un défaut de câblage.** Marqueur d'audience absent, montage non ouvert, mode « tous
groupes » actif. Jamais un 401 : un service incapable de juger un jeton ne dit pas « mauvais jeton ».

## Le montage, et pourquoi il est dans `main.py`

Les dépendances vivent dans `shared`, que le contrat `service-spaces` empêche d'importer un module ;
elles n'y connaissent donc que des **formes** — des `Protocol` et des alias de fonctions — que
`identity.Account` et `organization.Assignment` satisfont telles quelles. C'est le `lifespan` de
`main.py`, seul endroit autorisé à connaître deux modules à la fois, qui remplit ces formes et range
le résultat dans `app.state`.

Les quatre résolveurs ouvrent chacun leur unité de travail : une lecture brève, close avant que la
route ne commence la sienne. L'authentification ne s'inscrit pas dans la transaction du cas d'usage.

Corollaire pour les tests : une application montée **sans son `lifespan`** — ce que fait tout test qui
l'oublie — répond 500 sur toute route protégée.

## Ce que cette page ne couvre pas

La **révocation** d'un jeton avant son expiration (BACK-10d) : son point d'accroche est marqué dans
`get_current_account`, et rien n'y est câblé. La **bascule de groupe** (BACK-10e). Les routes
`/auth/login` et `/auth/refresh` (BACK-29). Enfin, la ligne du
[journal d'accès](./journalisation.md) ne porte ni `account_id`, ni `group_id`, ni `clinic_id` :
les dépendances à `yield` sont démontées à l'intérieur de l'intergiciel qui l'écrit. Toutes les
lignes émises _pendant_ la requête, elles, les portent — c'est ce que le critère de BACK-11 demandait.

## Vérifier que les règles tiennent

Depuis `backend/api/`, la pile Docker démarrée.

```bash
uv run pytest -m authorization
```
