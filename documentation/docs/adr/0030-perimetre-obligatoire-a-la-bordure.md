---
title: "ADR-0030 — L'audience vient de la route, le périmètre est obligatoire"
description: "L'audience attendue est déclarée par le routeur et jamais dérivée de la requête ni du jeton ; toute défaillance d'authentification produit un unique 401 sans détail ; et `require_role` exige un périmètre explicite, le rôle de groupe venant du claim et le rôle de clinique d'une résolution par requête."
---

# ADR-0030 — L'audience vient de la route, le périmètre est obligatoire

| Statut      | Date       | Tickets                                                           |
| ----------- | ---------- | ----------------------------------------------------------------- |
| **Accepté** | 2026-08-28 | BACK-10c, BACK-10a, BACK-16, BACK-29 (à venir), BACK-25 (à venir) |

## Contexte

Décision rendue par BACK-10c, qui livre les dépendances FastAPI protégeant les routes.

[BACK-10a](../backend/jetons.md) savait émettre et vérifier un jeton, mais rien ne le branchait sur
une requête HTTP. Trois questions restaient ouvertes, et aucune n'a de réponse évidente.

**Quelle audience une route attend-elle ?** L'[ADR-0024](./0024-jetons-audience-par-application.md)
a posé une audience par application — professionnelle, particulier, administration — précisément
parce qu'un simple champ « type de compte » ne tient pas l'isolation : sans vérification
d'audience, un jeton particulier valide reste techniquement présentable à l'API professionnelle.
Encore faut-il que la vérification sache **quelle** audience exiger.

**Que voit le client d'un refus ?** BACK-10a définit dix erreurs distinctes pour que le code
appelant sache ce qui s'est passé, et sa docstring laissait explicitement la bordure libre de les
fondre.

**Que signifie « rôle » ?** Le mot en désigne deux dans ce projet ([BACK-16](../backend/index.md)) :
un rôle de périmètre **groupe**, porté par le jeton, et un rôle de périmètre **clinique**, qui n'y
figure jamais. Une signature qui ne dirait pas lequel donnerait une autorisation fausse.

## Décision

**L'audience est une propriété de la route.** Elle est déclarée au montage, par le routeur —
`include_router(..., dependencies=[Depends(audience_of(...))])` —, écrite dans le `scope` ASGI, et
lue là par la dépendance d'authentification. Une route protégée sans ce marqueur répond **500** :
échec fermé, jamais un accès accordé. Une seconde déclaration divergente lève bruyamment.

**Toute défaillance d'authentification produit un unique 401, sans détail.** Jeton absent, illisible,
expiré, mal signé, du mauvais type, de la mauvaise audience, ou dont le sujet ne désigne aucun
compte : même statut, même code `http.request.unauthorized`, même message, et un en-tête
`WWW-Authenticate: Bearer` **nu**. Toutes les causes passent par une fabrique de refus unique, ce qui
rend l'indistinguabilité structurelle plutôt que vérifiable à la relecture.

**`require_role` exige un périmètre explicite**, mot-clé sans défaut et discriminant de surcharge :
`scope="group"` lit le rôle dans le claim sans aucune requête, `scope="clinic"` le résout par requête
sur l'affectation de la clinique active. Omettre le périmètre, ou mêler les deux vocabulaires, est
une erreur de typage.

**`get_active_clinic` fait deux vérifications indépendantes** : que le compte est affecté à la
clinique — lecture filtrée par le contexte de tenance — et que la clinique appartient au groupe
actif — lecture **non tenante** du groupe propriétaire, comparée en clair dans la dépendance. Elle
rend l'**affectation**, pas l'identifiant, et retient la plus récemment commencée en cas de
chevauchement.

### Table des statuts

| Situation                                                                                                                                                                             | Statut  | Code                                |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | ----------------------------------- |
| Jeton absent, schéma non `Bearer`, en-tête répété, jeton illisible / expiré / mal signé / mauvais type / mauvaise audience / audience contredisant le type de compte ; compte inconnu | **401** | `http.request.unauthorized`         |
| Compte suspendu                                                                                                                                                                       | 403     | `shared.account.suspended`          |
| Compte dont l'adresse n'est pas vérifiée                                                                                                                                              | 403     | `shared.account.email_not_verified` |
| Rôle de groupe ou de clinique insuffisant                                                                                                                                             | 403     | `shared.resource.forbidden`         |
| `X-Clinic-Id` absent, vide ou malformé                                                                                                                                                | 422     | `http.request.validation_error`     |
| `X-Clinic-Id` **répété**                                                                                                                                                              | 422     | `shared.resource.invalid`           |
| Clinique inconnue, d'un autre groupe, non affectée, fenêtre close, ou jeton sans groupe actif                                                                                         | **404** | `shared.clinic.not_active`          |
| Marqueur d'audience absent **ou inconnu**, montage manquant, mode « tous groupes » actif                                                                                              | 500     | défaut de câblage                   |

**Contrat client**, pour SHARED-03 et FRONT-08 : _tout 401 déclenche une tentative de
rafraîchissement ; si elle échoue, déconnexion._ Le client n'a pas besoin de distinguer « expiré » de
« invalide » — il lit `exp` dans son propre jeton.

## Alternatives écartées

### Déduire l'audience du type de compte porté par le jeton

Le piège séduisant, et le plus dangereux du ticket. `audience_for(claims.account_type)` compilerait,
se lirait bien, et **supprimerait le contrôle en donnant l'illusion de le faire** : l'émission pose
l'audience et le type de compte ensemble, la comparaison serait donc vraie pour tout jeton
authentique. C'est l'erreur exacte contre laquelle l'ADR-0024 a été écrit.

### L'audience dans un en-tête, ou déduite du préfixe d'URL

Un en-tête laisserait l'appelant choisir la porte qu'il franchit — une déclaration ne délimite pas
une frontière, même raisonnement que pour le groupe en [ADR-0012](./0012-perimetre-de-requete.md).
Un préfixe d'URL est déplaçable par `root_path`, par un montage ou par une réécriture de mandataire :
la frontière entre trois applications ne peut pas dépendre de la configuration d'un reverse proxy.

### Distinguer l'expiration dans la réponse

`WWW-Authenticate: Bearer error="expired_token"` (RFC 6750) rendrait service au client. Il dit aussi
à un attaquant que sa forgerie est **cryptographiquement bonne** mais périmée — c'est-à-dire un
oracle sur la clé de signature. Le service rendu est nul : le client possède le jeton et sait lire
son `exp`.

### Un dépôt de cliniques **tenant** pour la seconde vérification

La forme la plus courte, et elle ne tient pas : un `get(clinic_id)` sur un dépôt tenant rend déjà
l'absence pour une clinique d'un autre groupe — _par le même filtre_, donc avec le même point de
défaillance que la première vérification. Deux contrôles qui partagent leur point de défaillance ne
font pas deux contrôles. D'où une lecture **non tenante** du groupe propriétaire, et une comparaison
écrite dans la dépendance.

### S'appuyer sur la clé étrangère composite seule

`(clinic_id, group_id) → clinics(id, group_id)` garantit structurellement qu'une affectation lue sous
un groupe désigne une clinique de ce groupe. C'était suffisant, et invisible : la vérification aurait
vécu dans le schéma, où une migration écrite à la main peut la faire disparaître sans un mot. Elle
reste, et un test d'invariant l'épingle — mais elle n'est plus **la** seconde vérification.

### Un intergiciel ASGI plutôt qu'une dépendance

`BaseHTTPMiddleware` était exclu d'emblée (il exécute l'aval dans une tâche distincte). Un
intergiciel ASGI pur aurait fonctionné, mais il s'appliquerait à **toutes** les routes, y compris
publiques, et n'aurait aucun moyen de savoir quelle audience chacune attend. La dépendance, elle, se
déclare route par route et compose.

## Conséquences

**Ce que cela donne.** L'isolation entre les trois applications est tenue en un point, testable, et
un oubli de déclaration se voit en 500 plutôt qu'en faille. Le périmètre de tenance est posé à partir
du claim signé et jamais à la main : le filtre de [BACK-06b](../backend/persistance.md) devient
effectif sur toute route protégée. Le mot « rôle » cesse d'être ambigu — Mypy refuse
`require_role("asv", scope="group")`.

**Ce que cela coûte.** Deux lectures pour une route à périmètre clinique — les affectations et le
groupe propriétaire —, chacune dans sa propre unité de travail : l'authentification ne s'inscrit pas
dans la transaction du cas d'usage. Le vocabulaire des rôles et le statut « suspendu » sont
**recopiés** côté `shared`, que le contrat `service-spaces` empêche d'importer un module ; deux tests
de dérive tiennent la promesse, en égalité d'ensembles et dans les deux sens — les noms de rôles sont
d'ailleurs _dérivés_ des `Literal` que Mypy fait respecter, pour que le test garde le garde-fou et non
une copie posée à côté. Le statut du compte, lui, est décidé en **liste blanche** : ce qui n'est pas
explicitement actif est refusé, faute de quoi un statut ajouté demain franchirait la bordure par
omission. Et une route protégée montée sans son marqueur d'audience ne se
révèle qu'à l'exécution : le garde-fou statique attend la première route métier.

**Ce que cela ne couvre pas.** La révocation d'un jeton avant son expiration (BACK-10d) : son point
d'accroche est marqué dans `get_current_account`, rien n'y est câblé. La bascule de groupe
(BACK-10e). La confrontation audience / type de compte **à l'émission** (BACK-29) — elle est faite
ici, à la vérification. Et la ligne du journal d'accès ne porte ni `account_id`, ni `group_id`, ni
`clinic_id` : les dépendances à `yield` sont démontées à l'intérieur de l'intergiciel qui l'écrit.
Toutes les lignes émises _pendant_ la requête, elles, les portent.

## Références

- `backend/api/src/app/shared/infrastructure/api/dependencies/` — les deux fichiers de la décision.
- [Authentification des routes](../backend/authentification.md) — le mode d'emploi.
- [ADR-0012](./0012-perimetre-de-requete.md) — le jeton dit qui tu es et chez qui, l'en-tête où tu travailles.
- [ADR-0024](./0024-jetons-audience-par-application.md) — une audience par application.
- [ADR-0013](./0013-filtre-de-tenance-dans-le-depot.md) — le filtre de tenance, et la règle de non-divulgation que le 404 de clinique applique.
