---
title: Infrastructure
description: La pile Docker de développement — les douze services, le principe de la boucle locale, le worker et la carte des pages de la section.
---

# Infrastructure

La pile de développement est décrite par un unique `docker/docker-compose.yml` : PostgreSQL et sa
console pgAdmin, Redis, MinIO pour le stockage objet, Mailpit pour le courrier, et les images
construites depuis le dépôt pour l'API, son worker et les trois frontends.

Un principe y est tenu : **un service sans authentification n'est publié que sur la boucle
locale**. Redis, sa console et Mailpit ne sont donc joignables que depuis le poste.

## Les pages de cette section

| Page                                                   | Ce qu'on y trouve                                                          |
| ------------------------------------------------------ | -------------------------------------------------------------------------- |
| [Ports et URLs des services](./ports-et-services.md)   | L'allocation des ports — la garantie d'absence de collision — et les URLs. |
| [L'image du service d'API](./image-api.md)             | Les étages de l'image, l'entrypoint, l'IP réelle du client, la taille.     |
| [L'image des trois frontends](./image-frontends.md)    | Les valeurs figées au build, la sortie standalone, le poids des images.    |
| [Le mode développement](./mode-developpement.md)       | L'override compose, les montages, le rechargement à chaud.                 |
| [MinIO](./minio.md)                                    | Vérifier le stockage objet de développement.                               |
| [Mailpit](./mailpit.md)                                | Vérifier le SMTP de développement.                                         |
| [Le site de documentation](./site-de-documentation.md) | Lancer ce site en local, et la chaîne qui le publie.                       |
| [Makefile et scripts](./makefile-et-scripts.md)        | Les scripts pnpm de la racine et les cibles make.                          |

## Le worker

Le service `worker` exécute la cible du même nom de l'image d'API — la même
image que le service `api`, avec `taskiq worker` pour commande. Il ne publie
aucun port, ne porte aucun `container_name` et se met donc à l'échelle :

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d --scale worker=2
```

Depuis **BACK-15**, le module `app.shared.infrastructure.tasks.broker` que
désigne sa commande existe : le worker démarre, se connecte au broker Redis
(base 1) et consomme la file. Les journaux en font foi :

```bash
docker compose --project-directory . -f docker/docker-compose.yml logs worker
```

```
[taskiq.worker][INFO   ][MainProcess] Starting 2 worker processes.
[taskiq.process-manager][INFO   ][MainProcess] Started process worker-0 with pid 15
```

Le crash-loop d'avant BACK-15 — `worker-0 is dead. Scheduling reload.` en
boucle sur un `ModuleNotFoundError`, conteneur pourtant `Up` — a disparu, mais
le réflexe reste bon à garder : le worker n'a pas de healthcheck, **seuls ses
journaux disent la vérité**. Le fonctionnement, les règles d'écriture d'une
tâche et les sondes de bout en bout sont sur la page
[Tâches de fond](../backend/taches-de-fond.md).

:::note Apportée par les tickets QA
L'**intégration continue** — ce que chaque pipeline vérifie et ce qui bloque un merge — viendra
ici avec les tickets QA, comme les règles de protection de branche.
:::
