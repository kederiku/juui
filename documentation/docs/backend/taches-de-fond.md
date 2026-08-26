---
title: Tâches de fond
description: 'TaskIQ sur les streams Redis : le broker, le worker, les règles des tâches et la politique de reprise.'
---

# Tâches de fond

Les traitements longs quittent le fil des requêtes HTTP pour une file Redis, que TaskIQ
orchestre entre l'API et [le worker](../infrastructure/index.md#le-worker) — broker, règles
communes à toute tâche et politique de reprise sont détaillés ici.

Un traitement long — un e-mail, un PDF, une image — ne s'exécute jamais dans le fil d'une
requête HTTP : il part dans une file Redis (base 1) et s'exécute dans le **worker**, un second
processus du même code, déclaré par le compose (INFRA-05b). TaskIQ orchestre les deux bouts
([ADR-0008](../adr/0008-taskiq-taches-de-fond.md)) ; tout le code vit dans
`shared/infrastructure/tasks/`, et la contextvar de corrélation dans `core/correlation.py`.

## Le broker, et pourquoi les streams

`broker.py` expose l'objet que la CLI du worker attend : `taskiq worker
app.shared.infrastructure.tasks.broker:broker`. **Ce chemin et ce nom sont un contrat** — figés
par le `docker/api/Dockerfile` (INFRA-04) et le
`docker/docker-compose.yml` (INFRA-05b), les renommer casserait le conteneur
worker sans qu'aucun test local ne le voie.

Le broker est un `RedisStreamBroker`, pas le `ListQueueBroker` des exemples de la
documentation : les streams Redis portent des **acquittements**. Un worker tué en pleine
exécution ne perd pas le message — non acquitté, le stream le représente à un autre
consommateur après l'`idle_timeout` (10 minutes). Avec la liste, le message sorti par `BRPOP`
disparaît avec le worker qui le tenait.

La base 1 n'a ni TTL ni éviction (c'est la promesse d'INFRA-02 envers la file), donc tout ce
que le service y écrit porte sa propre borne : le stream est élagué au-delà de `STREAM_MAXLEN`
entrées, chaque résultat expire après `RESULT_TTL_SECONDS`, et la file de rejets est tronquée
(voir plus bas). Les résultats voyagent en **JSON**, pas dans le pickle par défaut du backend :
la règle de BACK-14 — jamais désserialiser du pickle relu de Redis — vaut pour la base 1 comme
pour la base 0. En échange, une valeur de retour de tâche doit être sérialisable en JSON, comme
ses arguments.

Côté API, le `lifespan` ne démarre que le versant **client** du broker — le backend de
résultats, nécessaire au `kiq` — sous la garde `is_worker_process` : le worker, qui importe le
même module, a son propre cycle de vie. Le module `broker.py` est la seule entorse assumée à
« rien ne se construit à l'import » : la CLI exige un objet de module, construire n'ouvre
aucune connexion, et `main.py` ne l'importe que dans le corps du `lifespan` pour qu'`import
app.main` reste sans exigence d'environnement.

## Le worker ouvre les mêmes ressources que l'API

`lifecycle.py` rejoue au `WORKER_STARTUP` la séquence du `lifespan` — validation de la
configuration, moteur PostgreSQL (`verify_connectivity` **lève** : un worker sans base meurt,
compose le relance), contrôle du schéma, cache Redis (`ping()` journalise : sans cache le
worker tourne, plus lentement) — avec les mêmes fabriques `build_*`, conçues dès BACK-05 pour
recevoir `Settings` en argument. Les ressources se rangent dans `TaskiqState` sous les mêmes
clés que dans `app.state`, et une tâche les reçoit par `TaskiqDepends(get_task_cache)` ou
`TaskiqDepends(get_task_database)` — l'équivalent worker de `get_cache(request)`, `isinstance`
défensif compris.

Les tâches des **modules** (`modules/<m>/infrastructure/tasks/`) arrivent par `discovery.py` :
le contrat `service-spaces` interdit à `shared` d'importer `app.modules.*`, et la commande du
worker est figée sans argument de modules — l'import **dynamique** au démarrage du worker est
le point d'assemblage qui résout la contradiction. BACK-17 et BACK-22 n'auront qu'à créer le
sous-paquet, sans toucher ni au Dockerfile ni au compose. L'entorse à l'esprit du contrat est
assumée et confinée à ce seul fichier, où un commentaire la déclare ; une erreur d'import dans
un fichier de tâches tue le worker — seule l'**absence** du sous-paquet est silencieuse.

## Les règles qui engagent toute tâche

**Des identifiants sérialisables, jamais d'objets ORM.** Une tâche reçoit des identifiants
(`UUID`, `str`, nombres), jamais une entité ni un modèle SQLAlchemy. Interdit :
`await send_welcome.kiq(account)`. Attendu :
`await send_welcome.kiq(group_id=account.group_id, account_id=account.id)` — et la tâche
**recharge** l'agrégat par son identifiant, dans sa propre unité de travail construite depuis
`get_task_database`, jamais via `get_identity_uow(request)`, qui suppose une requête HTTP.
Trois raisons, chacune suffisante : un objet ORM est détaché de sa session et ses accès
paresseux lèvent ; son état date du `kiq` et peut être périmé à l'exécution ; le fil transporte
du JSON, ce qui ne s'y sérialise pas ne part pas. Les annotations font le reste : un argument
typé `UUID` part en chaîne et le receiver le retype à l'arrivée.

**Le groupe actif ne traverse pas la file tout seul.** Toute tâche liée à un tenant prend
`group_id` en premier argument et ouvre son corps par `with use_group(group_id):` — sinon la
composition des clés de cache `TENANT` et le filtre de persistance (BACK-06b) lèvent
`MissingTenantContextError` au lieu d'écrire hors groupe. Le patron est `demo.record_ping`, et
le contrat est prouvé contre le vrai filtre par le test
`test_background_task_pattern_reapplies_the_filter` de la suite `tenant_isolation`.

**Toute tâche est rejouable.** La politique de reprise rejoue les échecs, et un stream
représente un message dont l'acquittement s'est perdu : une tâche doit pouvoir s'exécuter deux
fois sans effet cumulatif. `record_ping` l'obtient en dérivant sa valeur des seuls arguments et
en l'écrivant par un SET absolu. Les anti-patrons : incrémenter un compteur, écrire un
horodatage, relire-puis-écrire sans verrou.

**L'identifiant de requête suit, sans qu'on l'y aide.** `CorrelationMiddleware` lit la
contextvar `current_request_id` (`core/correlation.py`) au `kiq` et la repose dans le worker.
L'intergiciel HTTP qui la pose à l'entrée de chaque requête et le format de journal qui l'écrit sont
livrés par BACK-11 ([Journalisation](./journalisation.md)) : les journaux du worker portent donc
l'identifiant de la requête qui a demandé la tâche, y compris sur les lignes de TaskIQ lui-même. Le
worker hérite de la même configuration par `worker_startup()`, et ses deux commandes portent
`--no-configure-logging` pour que le `basicConfig` de TaskIQ ne pose pas un second handler.

## La politique de reprise : relances, repli, rejets

`RetryWithDeadLetterMiddleware` reprend la mécanique de re-émission de `SimpleRetryMiddleware`
— mêmes labels `_retries` / `max_retries`, même `task_id` conservé, donc un `wait_result` suit
toute la chaîne — et y ajoute ce qui manque : un délai **exponentiel** avant chaque relance
(1 s, 2 s, 4 s… plafonné à 30 s), et une **file de rejets** à l'épuisement. Par défaut toute
tâche a droit à `3` exécutions ; une tâche non rejouable déclare `@broker.task(max_retries=1)`
— un seul bouton.

Pourquoi pas `SmartRetryMiddleware`, qui existe pourtant : vérifié dans le paquet installé,
sans `schedule_source` son délai part comme label `delay` — que ni le receiver (qui ne lit que
`ack_type` et `timeout`) ni les brokers Redis n'interprètent. Le repli « exponentiel » serait
un renvoi immédiat. La variante `schedule_source` exigerait un processus `taskiq scheduler`
que l'infrastructure n'a pas ; et à l'épuisement, il se contente d'un avertissement. Le
`asyncio.sleep` dans `on_error` est le compromis : il occupe un créneau de concurrence du
worker — pas le worker entier — et l'acquittement n'ayant pas encore eu lieu, un worker tué
pendant l'attente ne perd rien.

À l'épuisement, le rejet part en `LPUSH` dans la liste `taskiq:dead-letter` (base 1) : un
document JSON — tâche, arguments, labels, erreur, nombre d'exécutions, horodatage — tronqué aux
`1000` entrées les plus récentes, doublé d'une ligne `ERROR` dans le journal. TaskIQ n'a
**aucune** file de rejets native ; celle-ci est une construction du service, sa relecture est
manuelle (`LRANGE`, `LPOP`) tant qu'aucun ticket d'exploitation ne l'outille.

## Vérifier que les tâches de fond tiennent

La pile compose démarrée (`docker compose … up -d`), d'abord le worker lui-même — le
crash-loop `worker-0 is dead` d'avant BACK-15 a disparu :

```bash
docker compose --project-directory . -f docker/docker-compose.yml logs worker | tail -4
```

```
worker-1  | [...][taskiq.worker][INFO   ][MainProcess] Pid of a main process: 1
worker-1  | [...][taskiq.worker][INFO   ][MainProcess] Starting 2 worker processes.
worker-1  | [...][taskiq.process-manager][INFO   ][MainProcess] Started process worker-0 with pid 15
worker-1  | [...][taskiq.process-manager][INFO   ][MainProcess] Started process worker-1 with pid 16
```

**Sonde 1 — l'aller-retour complet.** Depuis `backend/api/`, kiquer la tâche de démonstration
et attendre son résultat — elle traverse la file, s'exécute dans le worker, et le backend de
résultats rend la valeur :

```bash
uv run python - <<'PY'
import asyncio
from uuid import UUID

from app.shared.infrastructure.tasks.broker import broker
from app.shared.infrastructure.tasks.demo import record_ping

GROUP_ID = UUID("11111111-2222-3333-4444-555555555555")


async def main() -> None:
    await broker.startup()
    try:
        task = await record_ping.kiq(group_id=GROUP_ID, ping_id="sonde-1")
        result = await task.wait_result(timeout=15)
        print("return_value :", result.return_value)
        print("is_err       :", result.is_err)
    finally:
        await broker.shutdown()


asyncio.run(main())
PY
```

```
return_value : pong:sonde-1
is_err       : False
```

**Sonde 2 — le groupe a traversé la file.** La clé écrite est une clé `TENANT` : sa
composition appelle `require_current_group_id()`, elle n'a donc pas pu naître sans que le
worker ait reposé le `group_id` dans la contextvar. Depuis la racine du dépôt :

```bash
docker compose --project-directory . -f docker/docker-compose.yml exec -T redis \
  redis-cli -n 0 --scan --pattern 'dev:g-*demo*'
```

```
dev:g-11111111-2222-3333-4444-555555555555:demo:ping:sonde-1
```

**Sonde 3 — l'idempotence.** Rejouer la sonde 1 avec les mêmes arguments : même
`return_value`, et toujours **une seule** clé au scan — aucun effet cumulatif.

**Sonde 4 — relances, repli et rejets, corrélation comprise.** Kiquer la tâche qui échoue
toujours, sous un identifiant de requête posé :

```bash
uv run python - <<'PY'
import asyncio

from app.core.correlation import use_request_id
from app.shared.infrastructure.tasks.broker import broker
from app.shared.infrastructure.tasks.demo import fail_on_purpose


async def main() -> None:
    await broker.startup()
    try:
        with use_request_id("sonde-rid-42"):
            task = await fail_on_purpose.kiq(reason="sonde echec force")
        result = await task.wait_result(timeout=30)
        print("is_err :", result.is_err)
        print("error  :", type(result.error).__name__)
    finally:
        await broker.shutdown()


asyncio.run(main())
PY
```

```
is_err : True
error  : DemoFailureError
```

Le journal du worker montre le repli exponentiel — deux relances espacées de 1 s puis 2 s, le
même `task_id` de bout en bout, le `request_id` propagé — puis le versement :

```bash
docker compose --project-directory . -f docker/docker-compose.yml logs worker | grep -E 'relance|epuisee'
```

```
worker-1  | Tache shared.demo.fail_on_purpose en echec (execution 1/3, id 3c7cc17…, request_id sonde-rid-42) : relance dans 1.0 s. DemoFailureError('sonde echec force')
worker-1  | Tache shared.demo.fail_on_purpose en echec (execution 2/3, id 3c7cc17…, request_id sonde-rid-42) : relance dans 2.0 s. DemoFailureError('sonde echec force')
worker-1  | Tache shared.demo.fail_on_purpose epuisee apres 3 executions (id 3c7cc17…, request_id sonde-rid-42) : versee dans la file de rejets taskiq:dead-letter. DemoFailureError('sonde echec force')
```

Et le document de rejet est dans la liste, `request_id` compris :

```bash
docker compose --project-directory . -f docker/docker-compose.yml exec -T redis \
  redis-cli -n 1 LRANGE taskiq:dead-letter 0 0
```

```
{"task_id":"3c7cc17…","task_name":"shared.demo.fail_on_purpose","args":[],"kwargs":{"reason":"sonde echec force"},"labels":{"request_id":"sonde-rid-42","_retries":2},"error":{"type":"DemoFailureError","message":"sonde echec force"},"attempts":3,"failed_at":"2026-08-25T15:41:02.099982+00:00"}
```

**Sonde 5 — le cycle de vie est observable.** Même geste qu'en BACK-14 : chaque pool se nomme,
et `CLIENT LIST` dit qui occupe l'instance — le stream, les résultats, la file de rejets et le
cache du worker :

```bash
docker compose --project-directory . -f docker/docker-compose.yml exec -T redis \
  redis-cli client list | grep -o 'name=juui[^ ]*' | sort | uniq -c
```

```
   5 name=juui-api-broker/development
   3 name=juui-api-cache/development
   2 name=juui-api-results/development
   1 name=juui-worker-dlq/development
```

Les écarts assumés avec le ticket BACK-15 sont consignés au
[registre des écarts](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-15).
