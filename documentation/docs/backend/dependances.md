---
title: Dépendances
description: Les dépendances applicatives et de développement, la nuance --frozen/--locked, la version d'uv et la borne du backend de build.
---

# Dépendances

Ce que l'API embarque en production et ce qui n'existe qu'en développement —
deux groupes strictement séparés dans `pyproject.toml`, un installeur épinglé à
la suite d'un incident, et une borne de build qu'il faut lire pour ce qu'elle
déclare vraiment.

## `--frozen` et `--locked`

Deux drapeaux interdisent la re-résolution, et ils ne disent pas la même chose.
`--frozen` installe ce que contient `uv.lock` **sans le regarder** :
un `pyproject.toml` modifié sans `uv lock` passe en silence. `--locked` refuse de
partir dans ce cas — « the lockfile at `uv.lock` needs to be updated ». C'est
`--locked` qu'emploie la CI backend (`.github/workflows/ci-backend.yml`),
pour que l'environnement vérifié soit exactement celui du dépôt ; le build Docker
(INFRA-04) et QA-01 s'en tiennent à `--frozen`.

Deux groupes, strictement séparés. Le build Docker d'INFRA-04 installera le
premier seulement (`uv sync --frozen --no-dev`).

## Applicatives

| Paquet                | Rôle                                                                   |
| --------------------- | ---------------------------------------------------------------------- |
| `fastapi`             | Framework HTTP et génération du contrat OpenAPI.                       |
| `uvicorn[standard]`   | Serveur ASGI. L'extra apporte uvloop, httptools et le `--reload`.      |
| `pydantic`            | Validation et sérialisation des schémas d'API.                         |
| `pydantic-settings`   | Configuration typée, lue de l'environnement (BACK-03).                 |
| `sqlalchemy[asyncio]` | ORM. L'extra tire `greenlet`, sans lequel l'asynchrone ne marche pas.  |
| `asyncpg`             | Pilote PostgreSQL asynchrone.                                          |
| `alembic`             | Migrations de schéma — voir [Migrations](./migrations.md).             |
| `pyjwt`               | Émission et vérification des [jetons](./jetons.md) (BACK-10a).         |
| `redis`               | Cache applicatif (BACK-14) et broker de TaskIQ (BACK-15).              |
| `taskiq`              | Tâches de fond (BACK-15) — voir [Tâches de fond](./taches-de-fond.md). |
| `taskiq-redis`        | Le broker `RedisStreamBroker` et le backend de résultats (BACK-15).    |
| `boto3`               | Stockage objet S3 en production, MinIO en développement (BACK-13).     |

## Développement (`dev`)

| Paquet            | Rôle                                                  |
| ----------------- | ----------------------------------------------------- |
| `ruff`            | Lint et formatage. Épinglé à l'exact — voir plus bas. |
| `mypy`            | Vérification de types en mode strict.                 |
| `import-linter`   | Contrats d'architecture. Épinglé à l'exact lui aussi. |
| `pytest`          | Cadre de test.                                        |
| `pytest-asyncio`  | Support des tests asynchrones.                        |
| `pytest-cov`      | Mesure de couverture.                                 |
| `httpx`           | Client HTTP de test, via `ASGITransport`.             |
| `boto3-stubs[s3]` | Stubs de typage de boto3, limités au service S3.      |

`boto3` est le seul paquet de la liste à ne pas embarquer ses propres
annotations : tous les autres livrent un `py.typed`, et leurs paquets `types-*`
d'antan ont été retirés de PyPI.

**Ruff et Import Linter sont épinglés à la version exacte**, contrairement à
tout le reste. Un outil qui change d'avis tout seul entre deux `uv sync` ferait
échouer la CI sans qu'une ligne de code ait bougé : leur montée de version doit
rester un commit délibéré.

## La version d'`uv`, et la borne du backend de build

Même raisonnement, appliqué à l'outil qui installe tous les autres — mais il a
fallu un incident pour l'y appliquer.

`uv` tourne dans **trois** environnements, et chacun portait sa propre
politique : le `docker/api/Dockerfile` l'épinglait à l'exact
(`ARG UV_VERSION`), la `.github/workflows/ci-backend.yml` le
laissait flotter, le poste suivait son gestionnaire de paquets. Rien ne les
obligeait à s'accorder. La CI a donc glissé en 0.12.5 pendant que le poste
restait en 0.11.7, et le seul symptôme fut une ligne dans chaque log de CI :

```
warning: `build_system.requires = ["uv-build>=0.11.7,<0.12.0"]` does not contain the current uv version 0.12.5
```

Les trois sont désormais alignés sur **0.12.5**, et `[tool.uv]
required-version` fait de cet accord une **contrainte** plutôt qu'une
convention : un `uv` hors de la plage déclarée s'arrête net —

```
error: Required uv version `>=0.12.5, <0.13` does not match the running version `0.11.7`
```

— au lieu de réussir en le murmurant dans un log. Une plage, et non un `==` :
l'arbitrage est consigné dans
l'[ADR-0002](../adr/0002-uv-outillage-python.md).

**La borne haute du backend de build est passée de `<0.12.0` à `<0.13.0`.** Elle
ne venait d'aucune décision : c'était la sortie littérale d'`uv init` sous uv
0.11, jamais commentée. Deux vérifications avant de l'élargir. Les notes de
version d'uv 0.12.0, d'abord, qui sont explicites — « _There are no breaking
changes to the configuration of the uv build backend_ », avec la recommandation
d'ouvrir jusqu'à 0.13. Ce projet ensuite, où `module-name = "app"` et la
disposition `src/` sont ce qui pourrait souffrir : les roues construites sous
0.11.7 et sous 0.12.5 portent 37 fichiers, dont **35 identiques octet pour
octet**. Les deux autres sont la ligne `Generator:` du fichier `WHEEL`, qui
nomme le constructeur, et son empreinte dans `RECORD`. Le paquet `app/` et le
`METADATA` ne bougent pas.

Le plancher reste à `>=0.11.7`, et non au `>=0.11.32` de l'exemple amont : c'est
la version qui a construit ce projet et celle qu'embarquait l'image Docker. Le
relever rendrait la déclaration fausse pour les roues déjà produites.

:::warning Une borne purement déclarative

**Cette borne ne contraint rien**, et le savoir évite de s'y fier. uv emploie
son backend intégré dès que la version déclarée tombe dans sa plage connue
compatible, et ne va chercher le paquet `uv_build` sur PyPI qu'en dehors. La
CI construisait donc **déjà** avec `uv_build` 0.12.5 quand la borne disait
`<0.12.0` : l'avertissement signalait une déclaration périmée, pas un
changement de backend. Ce que la borne déclare, ce sont les versions sous
lesquelles cette roue est _vérifiée_.

:::

Les deux bornes s'arrêtent à 0.13 — celle d'`uv_build` et celle de
`required-version` — et se rediscutent ensemble, comme le consigne
l'[ADR-0002](../adr/0002-uv-outillage-python.md).

`uv.lock` n'entre pas dans l'affaire : uv ne verrouille pas les dépendances de
build, le fichier ne contient aucune entrée `uv-build`, et changer cette borne
ne le désaccorde pas. Aucun `uv lock` n'est à relancer.
