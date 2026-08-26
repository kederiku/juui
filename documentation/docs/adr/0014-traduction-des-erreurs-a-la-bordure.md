---
title: ADR-0014 — Les erreurs métier se traduisent en HTTP à la bordure, en un format unique
description: Le domaine lève des exceptions typées à code namespacé ; un adaptateur unique les traduit en statut HTTP et en un corps à quatre clés — et une ressource d'un autre groupe répond 404, jamais 403.
---

# ADR-0014 — Les erreurs métier se traduisent en HTTP à la bordure, en un format unique

| Statut      | Date       | Tickets                             |
| ----------- | ---------- | ----------------------------------- |
| **Accepté** | 2026-08-25 | BACK-09, BACK-11, BACK-28 (à venir) |

## Contexte

Décision rendue par BACK-09. Depuis BACK-04, le domaine lève `DomainError` et ses spécialisations
de module ; depuis BACK-08, l'application répond en HTTP. Entre les deux, rien : un refus métier
remontait en 500 brut, les erreurs de validation Pydantic sortaient au format par défaut de
FastAPI (`{"detail": [...]}`), et un 404 de routage à un troisième format encore. Trois questions
à trancher avant la première route métier (BACK-28) : **où** la traduction s'effectue-t-elle sans
que le domaine apprenne le protocole ? **Quelle forme** donne-t-on à la réponse pour que le client
généré par Orval ([ADR-0007](./0007-client-api-genere-orval.md)) normalise les erreurs en un seul
endroit ? Et **que répond-on** à une ressource d'un autre groupe, sachant que le dépôt tenant
([ADR-0013](./0013-filtre-de-tenance-dans-le-depot.md)) la rend déjà indistincte d'une ressource
inexistante ?

## Décision

**Le domaine lève des exceptions typées à code namespacé ; un adaptateur unique —
`error_handlers.py`, enregistré par `create_app()` — les traduit en statut HTTP et en un corps à
quatre clés `{ code, message, details, request_id }`, et une ressource d'un autre groupe répond
404, jamais 403.**

Concrètement :

- la hiérarchie vit dans `shared/domain/exceptions.py`, en Python standard pur (le contrat
  `domain-purity` l'exige) : `DomainError`, puis `NotFoundError` (404), `AlreadyExistsError` et
  `ConflictError` (409), `ValidationError` (422), `PermissionDeniedError` (403) — une erreur
  restée sans catégorie sort en 400, signal de revue ;
- chaque classe porte un code `<module>.<ressource>.<erreur>` (`identity.account.not_found`) en
  attribut de **classe** : le code identifie la classe de refus, il se greppe en production sans
  ouvrir le code ;
- les quatre clés du corps sont **toujours présentes**, `null` compris ; les erreurs de validation
  Pydantic sont reformatées au même gabarit, en ne gardant que `loc`, `msg` et `type` — jamais
  `input`, qui renverrait la saisie brute, mot de passe compris ;
- les `HTTPException` de routage (404 de chemin inconnu, 405) adoptent le même format : sans
  elles, « toutes les erreurs partagent le même format » serait faux dès le premier chemin
  erroné ;
- une exception hors hiérarchie répond un 500 au corps figé — ni type, ni message, ni stack — et
  part au journal en niveau error avec sa stack complète ; les pannes techniques
  (`FileStorageUnavailableError` comprise, re-levée exprès par le handler) suivent ce chemin ;
- le dépôt générique déclare son erreur d'absence en `type[NotFoundError]` : un dépôt ne **peut**
  pas déclarer une absence qui sorte autrement qu'en 404 — le typage verrouille la
  non-divulgation prouvée par les tests `tenant_isolation`.

## Alternatives écartées

### `HTTPException` levée depuis le domaine

Le réflexe FastAPI : lever `HTTPException(404)` là où l'absence se constate. Mais le domaine
apprendrait le protocole — le même code deviendrait inutilisable depuis une tâche de fond ou une
CLI, où personne n'attend de statut HTTP — et la correspondance erreur→statut se disperserait sur
chaque site d'appel, indéfendable en revue.

### Un middleware attrape-tout sans hiérarchie

Un seul `except DomainError` qui répondrait 400 partout. Simple, mais faux : une absence n'est pas
un conflit, et un client ne peut rien décider d'un 400 uniforme. La hiérarchie est précisément ce
qui permet à l'adaptateur de choisir le statut sans que le domaine le connaisse.

### Un code d'erreur par instance, choisi au site d'appel

Passer le code en argument du constructeur. Deux levées de la même classe auraient fini par porter
deux codes, et la promesse « un code se lit en production sans ouvrir le code » serait morte en
quelques tickets. L'attribut de classe rend le code aussi stable que le type.

### 403 pour une ressource d'un autre groupe

Plus « exact » en apparence — l'accès est bien refusé. Mais un 403 confirme que la ressource
existe chez un concurrent : le formulaire devient un oracle. Le dépôt tenant lève déjà la même
erreur d'absence qu'un identifiant inexistant ; la traduction n'a rien à distinguer, et c'est le
point.

## Conséquences

**Ce que cela donne.** Un seul format d'erreur sur toute la surface — refus métier, validation,
routage, 500 — que le mutator d'Orval (SHARED-03) normalisera en un endroit. Des codes greppables
en production. Un 500 qui ne fuit rien mais journalise tout. Et la non-divulgation cross-groupe
prouvée au niveau HTTP, plus seulement au niveau dépôt.

**Ce que cela coûte.** Chaque nouvelle erreur doit choisir sa catégorie et son code — une classe
levée sans catégorie sort en 400 générique, et c'est un signal de revue, pas un confort. Le champ
`request_id` vaut `null` hors de toute requête HTTP — une `DomainError` levée depuis une tâche de
fond ou un script —, et l'intergiciel de BACK-11 le renseigne partout ailleurs. Le schéma
OpenAPI n'annonce le format réel que sur le 422 du routeur v1 ; l'alignement complet viendra avec
les premières routes métier (BACK-28). Et uvicorn journalise la stack des 500 une seconde fois —
`ServerErrorMiddleware` re-lève après la réponse, doublon assumé.

## Références

- `backend/api/src/app/shared/domain/exceptions.py` — la hiérarchie et ses codes.
- `backend/api/src/app/shared/infrastructure/api/error_handlers.py` — les quatre handlers, et la
  mécanique à deux couches de Starlette expliquée en docstring.
- `backend/api/src/app/shared/infrastructure/api/schemas/error.py` — le corps à quatre clés.
- `backend/api/tests/shared/test_error_handlers_tenancy.py` — la preuve HTTP du 404-jamais-403.
- [ADR-0013](./0013-filtre-de-tenance-dans-le-depot.md) — l'erreur d'absence indistincte que
  cette traduction prolonge.
- [ADR-0007](./0007-client-api-genere-orval.md) — le client généré qui consommera ce format.
