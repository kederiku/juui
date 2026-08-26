---
title: ADR-0017 — Les listes se paginent par offset, dans une enveloppe unique
description: Pagination page/page_size avec total, enveloppe { items, total, page, page_size }, refus des bornes plutôt que troncature, tri sur liste blanche — le curseur écarté pour les écrans d'administration.
---

# ADR-0017 — Les listes se paginent par offset, dans une enveloppe unique

| Statut      | Date       | Tickets                                       |
| ----------- | ---------- | --------------------------------------------- |
| **Accepté** | 2026-08-26 | BACK-24, BACK-25 (à venir), BACK-26 (à venir) |

## Contexte

Décision rendue par BACK-24. Aucun endpoint de liste n'existe encore, et c'est le moment choisi :
chaque écran d'administration en consommera un (BACK-25, BACK-26, puis tous les tableaux à venir),
et Orval ([ADR-0007](./0007-client-api-genere-orval.md)) générera les types et les hooks des
frontends à partir de ces signatures. Une convention posée après le premier endpoint se paierait
en refonte de toutes les listes **et** de tout le client généré — le renommage d'un champ de
l'enveloppe après SHARED-03 est une migration de schéma, pas un rename local
([ADR-0011](./0011-routage-versionne-par-module.md)). Le code réservait explicitement la
décision : `Repository.list` se déclarait « sans borne, et c'est assumé », en nommant BACK-24
comme propriétaire des paramètres, de l'enveloppe et du maximum imposé.

## Décision

**Les listes se paginent par décalage — `page` et `page_size` — et répondent toutes par la même
enveloppe `{ items, total, page, page_size }` ; les bornes se refusent, le tri se valide contre
une liste blanche par endpoint.** Concrètement :

- **Paramètres normalisés.** `page` (≥ 1, défaut 1), `page_size` (1 à 100, défaut 20 — les deux
  constantes vivent dans le domaine, `shared/domain/pagination.py`, et la bordure HTTP les
  importe). Le tri s'écrit `sort=champ` ou `sort=-champ` — un seul champ, `-` pour descendre.
- **Refuser, jamais tronquer.** Un `page_size` au-delà du maximum sort en 422, aux deux niveaux :
  les contraintes Pydantic de la bordure (`http.request.validation_error`), et le constructeur de
  `PageRequest` (`shared.pagination.invalid`) pour les chemins qui ne traversent pas HTTP. Un
  client qui demande 10 000 lignes et en reçoit 100 sans le savoir produirait des pages
  incomplètes sans erreur.
- **Le tri est un nom public.** Chaque endpoint déclare sa liste blanche (`sort_param(...)`), et
  le dépôt du module porte la correspondance nom → colonne (`_sortable`) — un champ hors liste
  sort en 422 `shared.pagination.unknown_sort`, à la bordure comme au dépôt. Rien de ce que le
  client envoie n'approche le SQL. La clé primaire départage toujours les égalités, dans le sens
  du tri : deux pages consécutives ne se recouvrent jamais.
- **L'enveloppe est un objet, jamais un tableau nu** — même doctrine que le `details` du format
  d'erreur ([ADR-0014](./0014-traduction-des-erreurs-a-la-bordure.md)) : un objet s'étend sans
  casser le contrat, et Orval le type proprement.
- **Chaque endpoint nomme son enveloppe.** `class AccountPage(Page[AccountRead])` — deux lignes —
  parce qu'un `Page[AccountRead]` paramétré en signature de route sortirait dans l'OpenAPI sous le
  nom mutilé `Page_AccountRead_`, qu'Orval reprendrait tel quel. Un test de spec refuse
  mécaniquement tout nom de composant hors gabarit ; un second consigne le contre-exemple.
- **Le dépôt applique la convention en un seul endroit.** `Repository.list(page)` rend un
  `PageResult` ; `_paginate` — la couture que les finders paramétrés réutilisent — part de
  `self._select()`, si bien que le filtre de tenance ([ADR-0013](./0013-filtre-de-tenance-dans-le-depot.md))
  s'applique au compte comme à la fenêtre : `total` est le total du périmètre courant,
  mécaniquement. Une page au-delà de la fin est vide et porte le total réel — une page est une
  fenêtre, pas une ressource, jamais un 404.

## Alternatives écartées

### La pagination par curseur (keyset)

Les identifiants UUIDv7, horodatés et ordonnés, s'y prêtaient — et le curseur reste plus stable
sous insertions concurrentes et plus rapide en profondeur. Mais il ne sait répondre ni « combien
en tout ? » ni « page 7 » — exactement ce qu'un écran d'administration affiche — et le
`DataTable` des frontends raisonne déjà en `pageIndex`/`pageSize`. Le flux à fort volume qui
exigerait un curseur (timeline, journal d'audit) fera l'objet d'une décision dédiée le jour où il
existera ; les deux formes ne se mélangeront pas sans motif.

### Le tableau nu, quitte à envelopper plus tard

La forme la plus courte aujourd'hui, et la plus chère demain : ajouter `total` à une réponse
tableau casse tous les appelants et tout le code généré, précisément la refonte que ce ticket
existe pour éviter. L'enveloppe coûte quatre clés maintenant et ne coûte plus rien ensuite.

### La troncature silencieuse du `page_size`

Ramener 10 000 à 100 « rend service » et ment : le client reçoit une page incomplète sans aucune
erreur, et l'incident se découvre en production, côté données manquantes. Le refus est brutal et
honnête — et il se teste.

### Le tri libre sur nom de colonne

Accepter `sort=<colonne>` et l'interpoler est le chemin court vers l'injection SQL et le couplage
du contrat public au schéma physique. La liste blanche coûte une déclaration par endpoint et rend
les deux dérives impossibles par construction.

### Le modèle de query `Query()` de FastAPI

La forme moderne (`Annotated[PageParams, Query()]`) aplatit bien les paramètres à l'exécution,
mais cette version de FastAPI la sérialise dans l'OpenAPI en un **unique paramètre `params` en
`$ref`** — le client généré enverrait un objet imbriqué là où le serveur attend
`?page=&page_size=`. La forme retenue, `Annotated[PageParams, Depends()]`, aplatit aussi le
spec : chaque champ y devient un vrai paramètre de query, bornes et défauts visibles. Le test de
spec des bornes verrouille ce comportement.

## Conséquences

**Ce que cela donne.** Tous les critères du ticket sont prouvés par la suite de tests : refus des
bornes (aux deux niveaux), tri sur liste blanche, enveloppe unique, déterminisme des pages sous
égalités, total borné au groupe actif — et le critère Orval, vérifiable sans Orval par les tests
de spec, a été validé de bout en bout par une génération réelle (type `NotePage` propre,
paramètres bornés, hook TanStack Query). BACK-25 et BACK-26 n'ont plus qu'à déclarer leurs listes
blanches et leurs sous-classes nommées.

**Ce que cela coûte.** Deux requêtes par liste, toujours — le COUNT n'est jamais économisé, même
sur une page courte : un seul chemin de code. L'offset profond se paie en parcours d'index — un
non-problème aux volumes d'un back-office, à réévaluer si une liste dépasse ce cadre. Chaque
endpoint porte deux lignes de sous-classe et deux listes blanches (la sienne, celle du dépôt)
qu'un test devra garder alignées. Et l'enveloppe est un contrat public : la renommer après
SHARED-03 sera une migration de schéma.

## Références

- `backend/api/src/app/shared/domain/pagination.py` — les objets-valeurs de la convention :
  bornes, `PageRequest` qui refuse, `PageResult`, les deux erreurs nommées.
- `backend/api/src/app/shared/infrastructure/api/pagination.py` — `PageParams`, `sort_param` et
  l'enveloppe `Page`, avec la règle de la sous-classe nommée sur place.
- `backend/api/src/app/shared/domain/ports/repository.py` — `list(page)` sur le protocole
  générique, comme promis par sa docstring d'origine.
- `backend/api/src/app/shared/infrastructure/db/repositories/base.py` — `_paginate`,
  `_order_terms` et la liste blanche `_sortable` des dépôts.
- `backend/api/tests/shared/test_pagination.py` — les deux volets de preuve : bordure HTTP et
  spec OpenAPI sans base, fenêtrage et tenance du total sur PostgreSQL.
- [ADR-0007](./0007-client-api-genere-orval.md) — le client généré qui consommera l'enveloppe.
- [ADR-0011](./0011-routage-versionne-par-module.md) — `operation_id` et étiquettes, l'autre
  moitié du contrat OpenAPI.
- [ADR-0013](./0013-filtre-de-tenance-dans-le-depot.md) — le filtre que `total` hérite par
  construction.
- [ADR-0014](./0014-traduction-des-erreurs-a-la-bordure.md) — les 422 nommés que les refus
  empruntent.
