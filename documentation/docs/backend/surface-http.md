---
title: Surface HTTP
description: Le routeur /api/v1, les deux sondes de santé, les operation_id du contrat OpenAPI et le périmètre de requête.
---

# Surface HTTP

Ce que le service expose au monde extérieur — le routeur versionné, les sondes de santé et le
contrat OpenAPI dont Orval tirera le client des frontends.

La surface publique du service, posée par BACK-08 pour ses trois consommateurs **mécaniques** :
le healthcheck du conteneur Docker, la CI, et Orval
([ADR-0007](../adr/0007-client-api-genere-orval.md)), qui générera le
client des frontends à partir du schéma OpenAPI (SHARED-03). Les conventions de routage sont
consignées dans
l'[ADR-0011](../adr/0011-routage-versionne-par-module.md) ; cette section
dit comment elles se matérialisent ici.

## Le routeur racine `/api/v1`

Toutes les routes **métier** vivent sous `/api/v1`. Le préfixe de version se pose une fois, dans
`shared/infrastructure/api/router.py` — la
**version** est un choix du service, le chemin de la **ressource** (`/auth`, …) reste celui du
module, chacun maître de sa moitié de l'URL. Le routeur racine est une **fonction**
(`build_api_router`) et non un routeur pré-assemblé : `shared` n'a pas le droit d'importer les
modules (contrat d'Import Linter n° 5), c'est donc `main.py` qui possède la
liste `_MODULE_ROUTERS` et la passe en argument.

## Deux sondes, deux questions

`shared/infrastructure/api/health.py` répond à
deux questions distinctes, et l'URL des deux vit **hors** de `/api/v1` : une sonde est un
contrat d'exploitation — compose, orchestrateur, supervision — qui doit survivre à une v2 sans
reconfiguration.

- **`GET /health/live`** — « le processus répond-il ? ». Aucune dépendance externe : c'est la
  sonde du conteneur, et une base arrêtée ne doit pas faire redémarrer l'API en boucle.
- **`GET /health/ready`** — « le service peut-il servir ? ». PostgreSQL (le `SELECT 1` de
  `verify_connectivity`, BACK-05) et Redis (PING, BACK-14) sont interrogés **en parallèle** ;
  le premier composant défaillant vaut `503`, avec un corps qui le nomme :
  `{"status":"unready","components":{"postgres":"ok","redis":"unreachable"}}`.

Redis est **bloquant ici, et seulement ici** : les routes métier dégradent sans cache
([l'asymétrie du service](./stockage-objet.md#lasymétrie-du-service-a-trois-temps-pas-deux)), mais la sonde de
disponibilité doit dire la vérité d'une panne — retirer l'instance du trafic n'est pas casser le
service. Le stockage objet, lui, n'est **pas** sondé : aucune route n'en dépend (BACK-13), et
ses opérations lèvent d'elles-mêmes.

## Étiquettes, `operation_id` et le client généré

L'étiquette OpenAPI vaut le **nom du module** — une par contexte métier, plus `health`. Orval
découpe le client généré par étiquette (`tags-split`) : le découpage du code frontend coïncide
ainsi avec la carte des modules, gratuitement. Chaque route porte un **`operation_id` explicite,
égal au nom de sa fonction**, en snake_case verbe-objet (`check_liveness`, `check_readiness`) :
Orval en dérive le nom des hooks, et l'égalité rend la convention vérifiable au grep — puis par
un test de BACK-12.

## Métadonnées OpenAPI et la production

`create_app()` pose title, description, version, contact et les descriptions d'étiquettes
(`_OPENAPI_TAGS`). Quand `ENVIRONMENT=production`, la surface de documentation se ferme
**entièrement** : `/docs`, `/redoc` et `/openapi.json` répondent 404. La fermeture se décide à
la **construction** de l'application, d'après `AppSettings` seul — voir les écarts ci-dessous.

## Le périmètre de requête

Le groupe actif voyage dans le **jeton** (claim `active_group_id`), la clinique active dans
l'**en-tête** `X-Clinic-Id`, jamais l'inverse — et l'en-tête n'autorise rien. La convention, ses
alternatives écartées et ce qu'elle coûte sont consignés dans
l'[ADR-0012](../adr/0012-perimetre-de-requete.md) ; son application
revient à BACK-10c (dépendance d'authentification) et BACK-10e (bascule de groupe). Le CORS
autorise déjà cet en-tête, et les journaux portent déjà `clinic_id`.

## Les intergiciels, et le CORS

Toute requête traverse trois intergiciels, montés par `create_app()` du plus extérieur au plus
intérieur : l'**identifiant de requête**, le **journal d'accès**, puis le **CORS**. L'ordre n'est
pas indifférent, et le détail — avec la politique CORS complète — vit sur la page
[Journalisation](./journalisation.md).

Ce qu'il faut en retenir ici : la liste blanche d'origines vient de `CORS_ORIGINS`,
`allow_credentials=True` interdit le joker `*` — qui fait **refuser le démarrage** —, et
`X-Request-ID` est exposé au JavaScript des frontends. Toute réponse porte cet en-tête, y compris
les erreurs ; une réponse **500**, elle, ne porte pas les en-têtes CORS, limite de Starlette
consignée au [registre des écarts](../ecarts/back.md).

## La pagination

Toute route de liste répond par l'**enveloppe unique** `{ items, total, page, page_size }` —
jamais un tableau nu : un objet s'étend sans casser le contrat, et Orval le type proprement. Les
paramètres sont normalisés : `page` (≥ 1, défaut 1), `page_size` (1 à 100, défaut 20), et un
`page_size` au-delà du maximum vaut un **refus explicite** en 422
(`http.request.validation_error`) — jamais une troncature silencieuse. Le tri s'écrit
`sort=champ` ou `sort=-champ`, validé contre la **liste blanche de l'endpoint**
(`sort_param(...)`) ; un champ hors liste sort en 422 `shared.pagination.unknown_sort`, et le nom
public ne touche jamais le SQL — la correspondance nom → colonne vit dans le dépôt du module.

Deux conventions d'écriture pour les routes à venir : les paramètres se reçoivent par
`Annotated[PageParams, Depends()]` — pas la forme `Query()`, qui sérialise un unique paramètre
objet dans l'OpenAPI — et chaque endpoint déclare sa **sous-classe nommée** de l'enveloppe
(`class AccountPage(Page[AccountRead])`) : un `Page[...]` paramétré en signature sortirait sous le
nom mutilé `Page_AccountRead_` dans le schéma, donc dans le client généré. L'offset est un choix
écrit — « page 7 » et un total pour les écrans d'administration, le curseur restant réservé aux
futurs flux volumineux ; le motif complet, les alternatives écartées et ce que cela coûte sont
consignés dans l'[ADR-0017](../adr/0017-pagination-par-offset.md), et les tests de
`tests/shared/test_pagination.py` verrouillent le tout — noms de composants propres compris.

## Le format d'erreur

Toute réponse d'erreur de la surface — refus métier, validation, routage, 500 — porte le même
corps à quatre clés `{ code, message, details, request_id }`, traduit à un seul endroit depuis la
hiérarchie `DomainError` (BACK-09). La hiérarchie, les codes namespacés et la règle 404-jamais-403
sont détaillés dans [Erreurs](./erreurs.md) ; la décision est consignée dans
l'[ADR-0014](../adr/0014-traduction-des-erreurs-a-la-bordure.md).

## Vérifier que la surface tient

Cinq sondes. Les trois premières se jouent depuis la **racine du monorepo**, pile lancée ; les
deux dernières depuis `backend/api`.

**1. Les deux sondes répondent.**

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d --build api
curl -s http://localhost:8000/health/live
# {"status":"alive"}
curl -s http://localhost:8000/health/ready
# {"status":"ready","components":{"postgres":"ok","redis":"ok"}}
```

**2. La panne se nomme.** Composant par composant, et le code passe à 503.

```bash
docker compose --project-directory . -f docker/docker-compose.yml stop postgres
curl -si http://localhost:8000/health/ready | head -1
# HTTP/1.1 503 Service Unavailable
curl -s http://localhost:8000/health/ready
# {"status":"unready","components":{"postgres":"unreachable","redis":"ok"}}
docker compose --project-directory . -f docker/docker-compose.yml start postgres

docker compose --project-directory . -f docker/docker-compose.yml stop redis
curl -s http://localhost:8000/health/ready
# {"status":"unready","components":{"postgres":"ok","redis":"unreachable"}}
docker compose --project-directory . -f docker/docker-compose.yml start redis
```

**3. Le conteneur se déclare sain** — sa sonde vise désormais `/health/live` (interval 10 s).

```bash
docker compose --project-directory . -f docker/docker-compose.yml ps api
# STATUS ... (healthy)
```

**4. La production ferme la documentation.** Le `JWT_SECRET_KEY` est nécessaire : la
configuration refuse de partir en production avec la clé du gabarit
([BACK-03](./configuration.md)) — et le `lifespan` exige toujours PostgreSQL, donc la pile reste
lancée.

```bash
uv run uvicorn app.main:app --port 8001 &
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8001/docs          # 200
kill %1

ENVIRONMENT=production JWT_SECRET_KEY=$(openssl rand -hex 32) \
  uv run uvicorn app.main:app --port 8001 &
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8001/docs          # 404
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8001/redoc         # 404
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8001/openapi.json  # 404
kill %1
```

**5. Le schéma dit qui il est.** Métadonnées, étiquettes et `operation_id` — ce que verra Orval.

```bash
curl -s http://localhost:8000/openapi.json | uv run python -c "
import json, sys
spec = json.load(sys.stdin)
info = spec['info']
print(info['title'], info['version'], info.get('contact'))
print([tag['name'] for tag in spec.get('tags', [])])
for path, ops in spec['paths'].items():
    for method, op in ops.items():
        print(method.upper(), path, '->', op.get('operationId'), op.get('tags'))
"
# Juui API 0.1.0 {'name': 'Equipe Juui', 'url': 'https://github.com/kederiku/juui'}
# ['health', 'identity']
# GET /health/live -> check_liveness ['health']
# GET /health/ready -> check_readiness ['health']
```

Les écarts assumés avec le ticket BACK-08 sont consignés au
[registre des écarts](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-08).
