---
title: Journalisation
description: Deux formats selon l'environnement, un identifiant de requête propagé de bout en bout, un contexte de tenance automatique, le masquage des secrets, et la pile d'intergiciels HTTP avec la politique CORS.
---

# Journalisation

Livrée par BACK-11. La décision — bibliothèque standard plutôt que structlog ou python-json-logger
— est consignée dans l'[ADR-0018](../adr/0018-journalisation-bibliotheque-standard.md).

Tout passe par un seul module, `core/logging.py`. Partout ailleurs, le code écrit
`logging.getLogger(__name__)` et n'a rien à savoir de plus : ni du format, ni du flux, ni du
masquage. C'est ce qui rend la promesse tenable — une ligne mal formatée ou un secret journalisé se
corrige à un endroit, pas en trente.

## Deux formats, un seul critère

`ENVIRONMENT=development` rend une ligne alignée et colorée, faite pour l'œil :

```
11:14:24.108 INFO     shared.infrastructure.clients.redis_cache  Cache Redis joignable sur redis:6379 (base 0).
11:14:55.581 WARNING  shared.infrastructure.api.middlewares      Acces HTTP.  · request_id=8f2e1c04 method=GET path=/api/v1/inconnu status=404 duration_ms=0.8 query=token=***&page=2
```

Tout le reste — `staging` comme `production` — rend un objet JSON par ligne, fait pour un
agrégateur :

```json
{
  "timestamp": "2026-08-26T11:16:25.299Z",
  "level": "WARNING",
  "logger": "app.shared.infrastructure.api.middlewares",
  "message": "Acces HTTP.",
  "request_id": "sonde-json",
  "account_id": "…-0007",
  "clinic_id": "…-0009",
  "group_id": "…-0001",
  "method": "GET",
  "path": "/api/v1/inconnu",
  "status": 404,
  "duration_ms": 0.7,
  "query": "otp=***&page=2",
  "client_ip": "127.0.0.1"
}
```

**Le pré-production suit la production, pas le développement.** Il existe pour la _répéter_, et
c'est là qu'on valide l'ingestion des journaux : un format différent entre les deux rendrait cette
répétition sans objet. La règle ne s'écrit donc pas `is_production`, qui ne sert plus qu'à fermer
`/docs`.

`LOG_LEVEL` fixe le seuil de la racine. Il ne rend pas SQLAlchemy verbeux — c'est `POSTGRES_ECHO`
qui s'en charge ([Persistance](./persistance.md)) — et un plancher `WARNING` s'applique sans
condition à `botocore`, `boto3`, `s3transfer`, `urllib3`, `watchfiles` et `asyncio`, pour que
`LOG_LEVEL=DEBUG` reste utilisable sur _notre_ code.

### Le schéma de la ligne JSON

Ordre fixe, et **clés absentes plutôt que nulles** — l'inverse de l'enveloppe d'erreur
([Erreurs](./erreurs.md)), qui est un contrat client typé par Orval, là où un journal se lit par
`grep`, où l'absence est une valeur.

| Clé                                       | Présence      | Rôle                                                |
| ----------------------------------------- | ------------- | --------------------------------------------------- |
| `timestamp`                               | toujours      | RFC 3339, UTC, à la milliseconde                    |
| `level`, `logger`, `message`              | toujours      | le triplet de base                                  |
| `request_id`                              | si posé       | l'identifiant de corrélation                        |
| `account_id`, `group_id`, `clinic_id`     | si posés      | le contexte de requête, posé par BACK-10c           |
| `method`, `path`, `status`, `duration_ms` | ligne d'accès | l'issue de la requête                               |
| `query`, `client_ip`, `origin`            | ligne d'accès | la chaîne de requête masquée, l'appelant            |
| `exception_type`, `exception`             | si `exc_info` | la trace complète, sur une seule ligne JSON         |
| tout `extra=`                             | selon l'appel | fusionné à la racine, sans recouvrir ce qui précède |

Écartés délibérément : `pid` et `thread` (Docker identifie déjà le conteneur), `hostname` et
`environment` (le collecteur les ajoute par étiquettes), `module` et `lineno` (`logger` situe déjà
le code, et la trace porte le reste quand il y a une erreur).

## L'identifiant de requête

Un intergiciel le pose à l'entrée de chaque requête : celui du client s'il franchit
`[A-Za-z0-9._~+/=-]{1,64}`, un `uuid4().hex` neuf sinon. Une valeur cliente est **jetée, jamais
rectifiée** — tronquée ou épurée, elle serait un jeton menteur, qui ne correspondrait plus à rien
chez celui qui l'a émise. Les trois dangers que ce filtre ferme sont réels : un `\r\n` renvoyé en
en-tête est une scission de réponse HTTP, un caractère de contrôle casse le rendu console, et une
valeur de dix kilo-octets se recopie sur chaque ligne de la requête.

L'identifiant vit ensuite à **deux endroits** pour la durée de la requête :

- la contextvar `current_request_id`, que le formateur lit **dans** le contexte de la requête ;
- la clé de `scope` `juui.request_id`, que le handler du 500 lit **hors** de ce contexte.

Cette redondance n'en est pas une, et c'est le point le plus subtil du ticket. `ServerErrorMiddleware`
de Starlette est la couche la plus extérieure : sur une exception imprévue, il construit sa réponse
**après** que l'intergiciel a rendu la main — donc après le `reset(token)` — et il répond avec le
`send` **d'origine**, hors de toute enveloppe de sortie. Sans la clé de `scope`, le corps du 500
dirait `request_id: null` et la réponse n'aurait pas d'en-tête, précisément là où l'on en a le plus
besoin.

| Réponse                         | 2xx / 4xx | 500                 |
| ------------------------------- | --------- | ------------------- |
| en-têtes CORS                   | oui       | **non**             |
| en-tête `X-Request-ID`          | oui       | posé par le handler |
| `request_id` dans le corps JSON | oui       | oui, lu du `scope`  |

L'absence d'en-têtes CORS sur un 500 est une limite de Starlette qu'aucun ordre d'empilement ne
rattrape ; elle est consignée au [registre des écarts](../ecarts/back.md).

**Vers les tâches de fond**, l'identifiant suit sans qu'on l'y aide : le `CorrelationMiddleware` de
BACK-15 le pose en label du message et le repose dans la contextvar du worker
([Tâches de fond](./taches-de-fond.md)). Les journaux du worker le portent donc, y compris les
lignes de TaskIQ lui-même.

## Le contexte, automatique

`account_id`, `group_id` et `clinic_id` apparaissent sur **chaque** ligne d'une requête, sans
qu'aucun appelant y pense. Sans le groupe dans les journaux, aucun incident multi-tenant n'est
diagnosticable après coup.

Ils arrivent par deux chemins, et il le faut. L'identifiant de requête, le compte et la clinique
vivent dans `core/correlation.py` : le formateur les lit directement. Le groupe actif, lui, vit dans
`shared/infrastructure/tenancy.py` — c'est la frontière d'isolation
([ADR-0004](../adr/0004-tenance-par-groupe.md)), lue par la persistance et par le cache — et le
contrat `service-spaces` interdit à `core` d'importer `shared`. Il arrive donc par injection :

```python
configure_logging(settings.app, context_providers={"group_id": current_group_label})
```

Cet appel est fait par les **deux points d'entrée du processus** : le `lifespan` de `main.py` et
`worker_startup()`. Une seule source de vérité, aucune copie à tenir synchrone — et tout ce qui pose
un groupe, dépendance d'authentification comme `use_group` d'une tâche de fond, apparaît dans les
journaux gratuitement. Le mode « tous groupes » se rend `"*"` : la raison de l'échappatoire n'a pas
sa place sur chaque ligne.

Ces valeurs sont posées par la dépendance d'authentification (BACK-10c), **jamais renseignées à la
main** par un cas d'usage — qui ferait mentir les journaux.

## Le masquage

Ne s'écrivent jamais dans un journal : `password`, `token`, `authorization`, `secret`, `otp`,
`chip_number` — et `cookie`, ajouté aux six du ticket parce que le jour où une ligne journalisera
des en-têtes HTTP, `authorization` sans `cookie` serait une règle à moitié tenue.

**Le mécanisme porte sur les noms de clé**, en sous-chaîne et sans égard à la casse. Une
correspondance exacte laisserait passer `hashed_password`, `access_token`, `refresh_token`,
`jwt_secret` et `otp_code`, c'est-à-dire la quasi-totalité des noms réels. Le masque est figé à
`***` : un masque proportionnel divulguerait la longueur du secret.

**Un second mécanisme, par forme, rattrape ce qui est déjà interpolé** dans une phrase : les
affectations (`clé=valeur`, `"clé": "valeur"`), les identifiants d'URL
(`postgresql+asyncpg://juui:***@hôte/base`) et les jetons porteurs (`Bearer ***`). Les chaînes de
requête passent par `parse_qsl`, ce qui est exact plutôt qu'approximatif.

> **C'est un filet, pas le mécanisme.** Un secret passé en argument positionnel sans nom de clé aux
> alentours — `_LOGGER.info("valeur : %s", motdepasse)` — passe entre les mailles, et un secret nu
> dans un message d'exception n'est masquable par aucune règle fondée sur les noms. La règle reste
> de ne pas l'écrire ; ceci en rattrape l'oubli. La limite est épinglée par un test qui consigne le
> contre-exemple.

Le masquage vit dans des **fonctions pures appelées par les formateurs**, jamais dans un
`logging.Filter` : un filtre devrait _muter_ l'enregistrement, or celui-ci est partagé avec tout
autre handler présent — celui de `caplog` en test, un handler d'audit demain (BACK-27).

## La pile d'intergiciels

`add_middleware` insère en position 0 : le **dernier ajouté est le plus extérieur**.

```
ServerErrorMiddleware      <- Starlette, hors de notre portée
  RequestIdMiddleware
    AccessLogMiddleware
      CORSMiddleware
        ExceptionMiddleware  <- les handlers d'erreur
          Router
```

- **L'identifiant en premier**, donc le plus extérieur : toute réponse que l'application sait
  produire le porte, y compris la réponse de préflight que le CORS fabrique et qui ne descend jamais
  plus bas.
- **Le journal d'accès au-dessus du CORS**, délibérément : un refus de préflight
  (`400 Disallowed CORS origin`) est fabriqué _par_ le CORS et n'atteint jamais l'application. Placé
  en dessous, le journal serait aveugle au seul symptôme exploitable d'une origine mal configurée —
  côté navigateur, l'erreur est muette côté serveur.

**Les deux intergiciels sont des intergiciels ASGI purs**, et ce n'est pas une question de style :
`BaseHTTPMiddleware` exécute l'aval de la chaîne dans une **tâche distincte**, dont la copie de
contexte part avant le `set()`. L'endpoint ne verrait jamais l'identifiant. Un test le prouve, et
lui seul.

### Le journal d'accès

Une ligne par requête, sur les `extra` plutôt que dans le message : rien n'est écrit deux fois, la
ligne JSON porte des champs indexables, la ligne lisible se grepe par `path=`.

Le niveau suit le statut — `≥ 500 → ERROR`, `≥ 400 → WARNING`, sinon `INFO` —, ce qui achète une
propriété gratuite : `LOG_LEVEL=WARNING` en production réduit le journal d'accès aux seules requêtes
en échec. `/health/live` et `/health/ready` sont **silencieuses tant que leur statut est bon** : le
healthcheck du conteneur frappe la sonde de vie six fois par minute, soit 8 640 lignes par jour et
par conteneur qui disent toutes la même chose. Un 503 de la sonde de disponibilité, lui, est une
information.

**Il remplace la ligne d'uvicorn, il ne s'y ajoute pas.** `configure_logging()` éteint
`uvicorn.access` en lui retirant ses handlers _et_ sa propagation : uvicorn interroge
`hasHandlers()` à chaque connexion pour décider s'il émet, et la réponse devient fausse. Aucun
argument de ligne de commande n'est nécessaire — et cela ferme un vecteur de fuite, sa ligne
journalisant le chemin **avec** sa chaîne de requête.

### La politique CORS

Liste blanche lue de `CORS_ORIGINS`, `allow_credentials=True`, méthodes et en-têtes explicites.

| Réglage          | Valeur                                                        |
| ---------------- | ------------------------------------------------------------- |
| `allow_methods`  | `GET, HEAD, POST, PUT, PATCH, DELETE, OPTIONS`                |
| `allow_headers`  | `Authorization`, `X-Clinic-Id`, `X-Request-ID` (+ safelisted) |
| `expose_headers` | `X-Request-ID`                                                |
| `max_age`        | 600 s                                                         |

`HEAD` y figure parce que Starlette l'ajoute d'office à toute route `GET` : l'omettre ferait échouer
un préflight parfaitement légitime. `X-Clinic-Id` vient de
l'[ADR-0012](../adr/0012-perimetre-de-requete.md). `expose_headers` n'est pas décoratif : sans lui,
`response.headers.get('X-Request-ID')` rend `null` côté frontend.

**Un joker `*` dans `CORS_ORIGINS` fait refuser le démarrage**, avec le nom de la variable. C'est le
seul endroit où ce critère soit vérifiable : sous `allow_credentials=True`, Starlette échoïse
l'origine du client **même** configuré avec `allow_origins=["*"]` — observer une réponse ne
distinguerait donc pas les deux configurations. `allow_origin_regex` n'est jamais employé : une
expression mal ancrée est la porte par laquelle le joker revient.

Une liste **vide** hors développement produit un avertissement et non un refus : sans origine, l'API
répond toujours — aux clients qui ne sont pas des navigateurs. Même asymétrie que le cache dans le
`lifespan`. Le CORS reste monté malgré tout : un `400` qui nomme la cause vaut mieux qu'un `405` de
routage.

> Une **barre finale** dans une origine la rend inopérante : Starlette compare caractère par
> caractère. C'est pourquoi `cors_origins` est typé `list[str]` et non `list[AnyHttpUrl]`, qui
> normalise en ajoutant cette barre. Le champ `origin` de la ligne d'accès en cas de refus existe
> pour que ce cas se lise en une ligne de journal.

## Où la configuration est appliquée

`configure_logging()` est appelée par les **deux points d'entrée du processus** — le `lifespan` de
`main.py` et `worker_startup()` — et jamais à l'import ni depuis `create_app()`. Deux raisons :
`import app.main` doit rester sans effet de bord, et reconfigurer la racine à chaque construction
d'application arracherait le handler de `caplog` en plein test.

Elle est **idempotente** : les handlers de la racine sont retirés avant que le nôtre ne soit posé.

Uvicorn configure sa journalisation dans `Config.__init__`, donc **avant** d'importer l'application :
la nôtre gagne toujours, sans `--log-config`. Les lignes émises _avant_ le `lifespan`
(`Started server process`, et en développement le processus parent de `--reload`) gardent son
format — quelques lignes au démarrage, aucune en régime. Le worker, lui, appelle `basicConfig`
avant d'importer le broker : ses deux commandes portent `--no-configure-logging`.

## Ce qui a été vérifié avant livraison

Cinq sondes, jouées sur la pile `make dev`, en plus des 142 tests du marqueur `observability`.

**1 — Les trois frontends appellent sans erreur CORS.** Préflight depuis `localhost:3001`, `:3002`
et `:3003`, puis depuis une origine étrangère.

```
localhost:3001 -> HTTP/1.1 200 OK  access-control-allow-credentials: true  access-control-allow-origin: http://localhost:3001
localhost:3002 -> HTTP/1.1 200 OK  access-control-allow-credentials: true  access-control-allow-origin: http://localhost:3002
localhost:3003 -> HTTP/1.1 200 OK  access-control-allow-credentials: true  access-control-allow-origin: http://localhost:3003
origine étrangère -> 400 Disallowed CORS origin
access-control-expose-headers: X-Request-ID
```

**2 — Deux formats.** `docker compose logs api` en développement rend des lignes alignées et
colorées ; le même code sous `ENVIRONMENT=production` rend un objet JSON par ligne, que `jq` avale.
Les deux exemples ouvrent cette page.

**3 — L'identifiant jusque dans le worker.** Un `kiq` déclenché sous `use_request_id` :

```
11:16:08.726 INFO  taskiq.receiver.receiver  Executing task shared.demo.record_ping with ID: 9dfa18a8…  · request_id=sonde-worker-back-11
```

**4 — Aucun doublon.** Une requête portant un identifiant connu, comptée dans les journaux : **1**
ligne de notre intergiciel, **0** d'uvicorn. Le jeton de la chaîne de requête n'apparaît nulle part
(`query=token=***&page=2`). Cinq appels à `/health/live` : **0** ligne.

**5 — Panne et reprise de Redis.** `docker compose stop redis` puis `start` :

```
11:15:37.631 WARNING  …clients.redis_cache  Cache Redis injoignable sur redis:6379 (base 0) (sonde) : le service continue SANS cache.  · request_id=4d2c3db7…
11:15:43.830 INFO     …clients.redis_cache  Cache Redis de nouveau joignable sur redis:6379 (base 0).  · request_id=0bab1a8f…
```

La reprise est en `INFO` — elle était en `WARNING` tant qu'aucune journalisation n'était configurée,
faute de quoi la fin d'une panne aurait été invisible. La dette est soldée, et la sonde le prouve.

## Écrire un appel de journalisation

```python
_LOGGER: Final = logging.getLogger(__name__)

_LOGGER.info("Compte cree.", extra={"account_id": str(account.id), "role": role.value})
```

- **Rien à importer d'autre.** Le contexte de requête s'ajoute tout seul.
- **Les valeurs dans `extra`, pas dans le message.** Elles deviennent des champs indexables en JSON
  et restent lisibles en développement, sans être écrites deux fois.
- **`extra` ne peut pas porter le nom d'un attribut de `LogRecord`** — `module`, `name`, `msg`,
  `args`, `levelname`, `filename`, `lineno`, `process`, `thread`, `taskName` : `logging` lève un
  `KeyError` sur le chemin de journalisation, c'est-à-dire au pire endroit. `pathname` est réservé,
  `path` ne l'est pas.
- **Ne jamais journaliser un secret**, même en comptant sur le filet.

## Ce qui n'est pas encore là

| Sujet                                                      | Ticket   |
| ---------------------------------------------------------- | -------- |
| Les contextvars posées par une vraie authentification      | BACK-10c |
| Le journal d'accès administrateur aux données personnelles | BACK-27  |
| L'export des journaux vers un agrégateur                   | à venir  |
