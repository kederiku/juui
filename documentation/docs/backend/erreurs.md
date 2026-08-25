---
title: Erreurs
description: La hiérarchie DomainError, les codes namespacés, le format d'erreur unique { code, message, details, request_id } et la règle 404-jamais-403.
---

# Erreurs

Comment un refus métier devient une réponse HTTP — la hiérarchie d'exceptions du domaine, les
codes namespacés, le format unique à quatre clés, et ce qu'un 500 ne dit jamais.

Livré par BACK-09, consigné dans
l'[ADR-0014](../adr/0014-traduction-des-erreurs-a-la-bordure.md) : le domaine lève des exceptions
**métier**, jamais des erreurs de protocole, et un adaptateur unique —
`shared/infrastructure/api/error_handlers.py`, enregistré par `create_app()` — les traduit toutes
au même format. Les modules n'importent jamais rien de l'adaptateur : ils lèvent, la bordure
traduit.

## La hiérarchie et sa correspondance

`shared/domain/exceptions.py` pose la racine `DomainError` et cinq catégories, en Python standard
pur — le contrat `domain-purity` interdit Pydantic dans le domaine, c'est pourquoi la hiérarchie
et le schéma du corps de réponse vivent dans deux fichiers séparés.

| Catégorie               | Statut | Sens                                                  |
| ----------------------- | ------ | ----------------------------------------------------- |
| `NotFoundError`         | 404    | la ressource n'existe pas — ou pas **pour ce groupe** |
| `AlreadyExistsError`    | 409    | l'unicité serait violée                               |
| `ConflictError`         | 409    | l'opération est incompatible avec l'état courant      |
| `ValidationError`       | 422    | une règle **métier** refuse la valeur                 |
| `PermissionDeniedError` | 403    | l'appelant est identifié mais n'a pas ce droit        |
| `DomainError` non typée | 400    | refus métier sans catégorie — un signal de revue      |

Chaque module spécialise ces catégories chez lui (`AccountNotFoundError` chez `identity`) ; le
dépôt générique déclare son erreur d'absence en `type[NotFoundError]`, ce qui **verrouille par le
typage** qu'une absence sorte toujours en 404.

## Les codes se lisent en production

Chaque classe porte un code `<module>.<ressource>.<erreur>` — `identity.account.not_found`,
`shared.file.too_large` — en attribut de **classe**, jamais choisi au site d'appel : le code
identifie la classe de refus, il est aussi stable que le type, et il se greppe en production sans
ouvrir le code. Un test parcourt la hiérarchie entière et refuse tout code hors gabarit.

## Le format unique à quatre clés

Toute réponse d'erreur — refus métier, validation, 404 de routage, 500 — porte les mêmes quatre
clés, **toujours présentes**, `null` compris :

```json
{
  "code": "identity.account.not_found",
  "message": "Aucun compte ne porte l'identifiant demandé.",
  "details": null,
  "request_id": null
}
```

Le schéma vit dans `shared/infrastructure/api/schemas/error.py` ; c'est lui que le mutator d'Orval
([ADR-0007](../adr/0007-client-api-genere-orval.md)) normalisera en un seul endroit. `details` est
toujours un **objet** ou `null`, jamais une liste au sommet : un objet s'étend sans casser le
contrat. `request_id` vaut `null` tant que l'intergiciel de corrélation (BACK-11) n'est pas posé —
la plomberie (`core/correlation.py`) est prête et testée, seul l'intergiciel manque.

## Les erreurs de validation Pydantic, reformatées

Le handler dédié remplace le `{"detail": [...]}` de FastAPI : un corps invalide répond 422 au
format unique, les violations sous `details.errors`, chacune réduite à `loc`, `msg` et `type`.
`input` est **exclu** — il renverrait la saisie brute à l'identique, mot de passe compris — et
`ctx` aussi, qui n'est pas toujours sérialisable. Les 404 de chemin inconnu et les 405 adoptent le
même format (`http.request.not_found`, `http.request.method_not_allowed`) : sans eux, « toutes
les erreurs partagent le même format » serait faux dès le premier chemin erroné.

## Ce qu'un 500 ne dit jamais

Une exception hors hiérarchie — un bug, une panne technique — répond un corps **figé** :
`http.server.internal_error`, message générique, aucun détail. Tout part au journal, niveau
error, avec la stack complète. `FileStorageUnavailableError` suit ce chemin exprès : elle descend
de `DomainError` (le contrat du port l'exige) mais reste une panne technique, et le handler la
re-lève vers le 500 plutôt que de la déguiser en refus métier. À savoir : uvicorn journalise la
stack une seconde fois — `ServerErrorMiddleware` re-lève après la réponse, doublon assumé.

## 404, jamais 403

Une ressource d'un autre groupe répond **exactement** comme une ressource inexistante — un 403
confirmerait l'existence de la ressource chez un concurrent. Le dépôt tenant
([ADR-0013](../adr/0013-filtre-de-tenance-dans-le-depot.md)) lève déjà la même erreur d'absence
dans les deux cas ; la traduction n'a rien à distinguer, et
`tests/shared/test_error_handlers_tenancy.py` le prouve désormais au niveau HTTP : deux corps de
réponse identiques, octet pour octet.

La même logique de non-divulgation s'applique à l'inscription : ne jamais révéler qu'une adresse
e-mail est déjà utilisée. `EmailAlreadyUsedError` existe et se traduit en 409, mais elle ne doit
**pas** ressortir telle quelle sur ce parcours — la réponse est identique que l'adresse soit
libre ou prise, et c'est BACK-28 qui portera cette règle dans le cas d'usage.

## Vérifier que la traduction tient

Cinq sondes. Les deux premières se jouent pile lancée (`make dev` à la racine), les trois
dernières depuis `backend/api`, sans docker pour les deux du milieu.

**1. L'inconnu répond au format unique.** Quatre clés, un code dérivé du statut.

```bash
curl -si http://localhost:8000/api/v1/inexistant | head -1
# HTTP/1.1 404 Not Found
curl -s http://localhost:8000/api/v1/inexistant
# {"code":"http.request.not_found","message":"Not Found","details":null,"request_id":null}
```

**2. La méthode refusée aussi.**

```bash
curl -s -X POST http://localhost:8000/health/live
# {"code":"http.request.method_not_allowed","message":"Method Not Allowed","details":null,"request_id":null}
```

**3. Le format exact, mécaniquement.**

```bash
curl -s http://localhost:8000/api/v1/inexistant | uv run python -c "
import json, sys
body = json.load(sys.stdin)
assert set(body) == {'code', 'message', 'details', 'request_id'}, body
print('format unique tenu')
"
```

**4. La matrice complète, sans docker.** Statuts, reformatage Pydantic, 500 sans fuite,
`request_id` — sur l'application minimale et sur `create_app()`.

```bash
uv run pytest tests/shared/test_error_handlers.py tests/shared/test_exceptions.py -q
# 29 passed
```

**5. La non-divulgation, preuve HTTP.** PostgreSQL requis (`make up` à la racine).

```bash
uv run pytest tests/shared/test_error_handlers_tenancy.py -q
# 2 passed
```

Les sondes `curl` d'un 422 reformaté ou d'un refus métier réel arriveront avec les premières
routes à corps (BACK-28) : aucune route métier n'existe encore, et c'est assumé.

Les écarts assumés avec le ticket BACK-09 sont consignés au
[registre des écarts](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-09).
