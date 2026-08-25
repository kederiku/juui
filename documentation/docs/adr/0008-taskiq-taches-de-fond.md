---
title: ADR-0008 — TaskIQ exécute les tâches de fond
description: Les traitements longs sortent des requêtes HTTP vers un worker TaskIQ sur broker Redis — async natif, comme le reste de la pile.
---

# ADR-0008 — TaskIQ exécute les tâches de fond

| Statut      | Date       | Tickets                    |
| ----------- | ---------- | -------------------------- |
| **Accepté** | 2026-08-25 | BACK-15, BACK-22 (à venir) |

## Contexte

Décision portée par BACK-15, qui l'a depuis appliquée : le broker, le cycle de vie du worker et
la tâche de démonstration vivent dans `backend/api/src/app/shared/infrastructure/tasks/`, le
service `worker` de la pile Docker Compose consomme la file, et `taskiq` comme `taskiq_redis`
figurent dans la liste des paquets interdits au domaine.

Les traitements longs — envoi d'e-mails, génération de documents, notifications — ne doivent
jamais bloquer une requête HTTP. Or toute la pile est **async-native** : FastAPI, SQLAlchemy en
asyncio, asyncpg, redis. L'outil de tâches de fond doit parler la même langue, sans pont ni
adaptation.

## Décision

**TaskIQ exécute les tâches de fond, sur un broker Redis** — la base 1, le cache occupant la
base 0 — avec un backend de résultats sur Redis également. Le worker initialise, via les
événements de cycle de vie du broker, les mêmes ressources que l'API : pool de base de données,
réglages.

Deux règles accompagnent la décision. Les tâches reçoivent des **identifiants sérialisables,
jamais des objets ORM** : un objet attaché à une session n'a aucun sens dans un autre processus.
Et le **groupe actif ne traverse pas la file tout seul** : une tâche déclenchée dans un contexte
tenant reçoit le `group_id` en argument et le repose dans la variable de contexte au démarrage —
faute de quoi le traitement lève, comme le veut
[l'ADR-0004](./0004-tenance-par-groupe.md).

## Alternatives écartées

### Celery

Le standard de fait, éprouvé depuis quinze ans, avec l'écosystème le plus riche — et y renoncer
est un coût réel, qu'il faut nommer. Mais Celery est synchrone d'origine : le code async du
projet devrait tourner derrière des ponts d'adaptation, à rebours de toute la pile. Payer cette
friction à chaque tâche pour conserver un écosystème dont le projet n'utilise qu'une fraction
serait le mauvais côté de l'échange.

### ARQ

Async natif et minimal, l'esprit le plus proche. Son développement avance cependant au ralenti,
il ne cible que Redis, et il n'offre pas la mécanique d'injection de dépendances qui rapproche
TaskIQ de FastAPI — la même façon de déclarer et de recevoir ses ressources des deux côtés.

### Dramatiq

Plus simple que Celery et robuste, mais synchrone lui aussi : la même friction fondamentale,
sans l'argument de l'écosystème.

### Les `BackgroundTasks` de FastAPI

L'outil intégré, séduisant pour commencer — et disqualifié dès qu'une tâche compte : les tâches
vivent dans le processus de l'API, disparaissent au redéploiement, sans reprise, sans file, sans
visibilité. Un rappel de rendez-vous perdu en silence n'est pas un compromis acceptable.

## Conséquences

**Ce que cela donne.** Un seul modèle d'exécution du serveur au worker : le même code async, les
mêmes ressources, initialisées de la même façon. Le broker est une abstraction : Redis
aujourd'hui, remplaçable sans réécrire les tâches.

**Ce que cela coûte.** Un écosystème plus jeune que celui de Celery : moins de recettes
éprouvées, et une politique de reprise — tentatives, backoff, file de rejets — à assembler
explicitement là où d'autres en livrent davantage tout faits. Et la discipline de tenance repose
sur la convention de passage du `group_id` : le garde-fou est l'erreur qui lève côté worker, pas
un mécanisme qui propagerait le contexte à la place du développeur.

## Références

- `backend/api/src/app/shared/infrastructure/tasks/broker.py` — le broker `RedisStreamBroker`
  (base 1) et le backend de résultats, au chemin que la CLI du worker fige.
- `backend/api/src/app/shared/infrastructure/tasks/middlewares.py` — la politique de reprise
  assemblée explicitement : tentatives, repli exponentiel, file de rejets.
- `backend/api/src/app/shared/infrastructure/tasks/demo.py` — le patron de référence :
  identifiants sérialisables, `group_id` en argument reposé par `use_group`, idempotence.
- `backend/api/pyproject.toml` — les dépendances `taskiq` et `taskiq-redis`, la liste interdite
  au domaine.
- `backend/api/src/app/shared/infrastructure/tenancy.py` — l'erreur de contexte manquant, que la
  tâche de fond lancée sans `group_id` déclenche.
- `docker/docker-compose.yml` — le service `worker`, qui exécute la commande de BACK-15.
- `backend/api/README.md`, section « Tâches de fond » — les règles d'écriture d'une tâche et les
  sondes de bout en bout.
