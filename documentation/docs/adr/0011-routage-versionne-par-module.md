---
title: ADR-0011 — Un routeur par module, monté sous /api/v1
description: Chaque module publie son routeur sur un routeur racine versionné ; étiquettes et operation_id sont fixés d'avance, parce que le client généré par Orval en fera des noms publics.
---

# ADR-0011 — Un routeur par module, monté sous /api/v1

| Statut      | Date       | Tickets            |
| ----------- | ---------- | ------------------ |
| **Accepté** | 2026-08-25 | BACK-08, SHARED-03 |

## Contexte

Décision rendue par BACK-08, qui livre les premières routes réelles du service — annoncée dès
BACK-04, qui posait un routeur par module (`identity` possède `/auth` et `tags=["identity"]`)
sans fixer ni racine, ni version, ni règle de nommage.

Les premiers consommateurs **mécaniques** de l'API arrivent : la sonde du conteneur Docker, la
CI, et surtout Orval ([ADR-0007](./0007-client-api-genere-orval.md)), qui générera le client des
trois frontends à partir du schéma OpenAPI. Ce client rend le nommage quasi irréversible : en
mode `tags-split`, Orval dérive le découpage des fichiers générés des **étiquettes** et le nom
des hooks des **`operation_id`** — renommer l'un ou l'autre après SHARED-03 est une rupture de
contrat sur trois applications. Les règles doivent donc être fixées **avant** la première route
métier (BACK-28), pas corrigées après elle.

## Décision

**Toutes les routes métier vivent sous un routeur racine unique préfixé `/api/v1` ; chaque
module y publie son propre routeur, et le nommage OpenAPI appartient au contrat public.**

Concrètement :

- le routeur racine (`shared/infrastructure/api/router.py`) porte le préfixe `/api/v1` — et lui
  seul : la **version** est un choix du service, le chemin de la **ressource** (`/auth`, …)
  reste celui du module, chacun maître de sa moitié de l'URL ;
- la liste des routeurs de modules vit dans `app.main`, seul point d'assemblage autorisé à
  connaître plusieurs modules : `router.py` expose une fonction `build_api_router(...)` et
  n'importe aucun module — le contrat d'Import Linter « sens des dépendances entre les espaces »
  place `shared` sous `modules` ;
- l'**étiquette OpenAPI vaut le nom du module** — une par contexte métier, plus `health` : le
  découpage du client généré coïncide ainsi avec la carte des modules de
  l'[ADR-0003](./0003-monolithe-modulaire.md), la même frontière des deux côtés du schéma ;
- chaque route porte un **`operation_id` explicite**, en snake_case verbe-objet, égal au nom de
  sa fonction (`check_liveness`, `check_readiness`) : Orval en dérive des hooks lisibles
  (`useCheckLiveness`), et l'égalité avec le nom de fonction rend la convention vérifiable au
  grep — puis par un test de BACK-12 ;
- les métadonnées OpenAPI (title, description, version, contact, étiquettes documentées) sont
  posées par la factory `create_app()` ; en production, `/docs`, `/redoc` **et** `/openapi.json`
  sont fermés ;
- les **sondes de santé restent hors de `/api/v1`** (`/health/live`, `/health/ready`) : leur URL
  est un contrat d'exploitation — compose, orchestrateur, supervision — qui doit survivre à une
  v2 sans reconfiguration.

## Alternatives écartées

### La version dans un en-tête

`Accept: application/vnd.juui.v1+json` ou un `X-API-Version`. Invisible dans les journaux, dans
un curl recopié d'un ticket d'incident et dans les chemins du client généré — un préfixe d'URL
se lit partout où l'appel apparaît, et le changement de version se voit dans chaque diff.

### Pas de version du tout

`/api/v1` coûte sept caractères aujourd'hui. L'ajouter après coup, une fois trois clients
générés épinglés sur des chemins nus, coûterait une migration d'URL sur toutes les applications
— exactement le genre de rupture que le versionnage existe pour absorber.

### Un tag fourre-tout, ou un tag par ressource

Un tag unique produirait un client généré monolithique ; un tag par ressource, un nuage de
fichiers sans cohérence. Le module est la seule granularité qui recoupe une frontière déjà
défendue par ailleurs — celle de l'[ADR-0003](./0003-monolithe-modulaire.md), tenue par Import
Linter côté serveur.

### Laisser FastAPI dériver les `operation_id`

Les identifiants par défaut (`check_liveness_health_live_get`) deviendraient les noms de hooks
de trois frontends. L'`operation_id` est du vocabulaire public, pas un détail d'implémentation —
et la laideur du défaut est précisément ce qui rend un oubli visible en revue.

## Conséquences

**Ce que cela donne.** Le client généré se découpe par contexte métier sans configuration, avec
des hooks nommés comme le backend nomme ses gestes. `/docs` se lit par module. Une future v2 est
un second routeur racine, pas une migration. Et la règle complète tient en une ligne de revue :
préfixe de ressource dans le module, version dans le service, étiquette = module, `operation_id`
= nom de fonction.

**Ce que cela coûte.** Chaque route doit déclarer son étiquette et son `operation_id`, et rien
ne l'impose mécaniquement avant le test prévu à BACK-12 — d'ici là, c'est une discipline de
revue. Renommer un `operation_id` après SHARED-03 se traite comme une migration de schéma, plus
jamais comme un renommage local. Enfin, le préfixe de version apparaît partout **sauf** sur les
sondes, et cette exception-là doit rester la seule.

## Références

- `backend/api/src/app/shared/infrastructure/api/router.py` — le routeur racine et l'arbitrage
  « une fonction, et non un routeur pré-assemblé ».
- `backend/api/src/app/shared/infrastructure/api/health.py` — les sondes, hors versionnage.
- `backend/api/src/app/main.py` — l'assemblage, les métadonnées OpenAPI et la fermeture de la
  documentation en production.
- `backend/api/src/app/modules/identity/infrastructure/api/routes.py` — le premier routeur de
  module, et la convention rappelée aux routes de BACK-28/29.
- [ADR-0003](./0003-monolithe-modulaire.md) — la frontière que les étiquettes recopient.
- [ADR-0007](./0007-client-api-genere-orval.md) — le générateur qui rend le nommage public.
