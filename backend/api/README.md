# Juui — service d'API

API du SaaS vétérinaire Juui : FastAPI, architecture hexagonale et DDD.

Ce projet est **hors des workspaces pnpm** à dessein. C'est un projet Python,
outillé par [`uv`](https://docs.astral.sh/uv/) ; les deux chaînes d'outils
coexistent dans le monorepo sans se croiser.

## Prérequis

**`uv` seul.** Nul besoin d'installer Python soi-même ni de créer un
environnement virtuel : `uv` lit [`.python-version`](.python-version), télécharge
l'interpréteur 3.14 s'il manque, et gère `.venv/` de bout en bout.

```bash
brew install uv
```

## Installation

Depuis ce dossier :

```bash
uv sync
```

La commande crée `.venv/`, y installe les dépendances applicatives **et** celles
du groupe `dev`, puis le projet lui-même en mode éditable — c'est ce qui rend le
paquet `app` importable depuis `src/`.

Ajouter `--frozen` pour interdire toute re-résolution : l'installation échoue
alors si [`uv.lock`](uv.lock) ne correspond plus au `pyproject.toml`, au lieu de
mettre le verrou à jour en silence. C'est le mode qu'utiliseront la CI (QA-01) et
le build Docker (INFRA-04).

## Démarrage

```bash
uv run uvicorn app.main:app --reload
```

La documentation interactive répond alors sur <http://localhost:8000/docs>, et
le contrat OpenAPI sur <http://localhost:8000/openapi.json>.

> L'API ne sert **aucune route** pour l'instant : `/docs` s'affiche donc vide.
> C'est attendu — la sonde de santé et les métadonnées OpenAPI relèvent de
> BACK-08.

## Structure

```
backend/api/
├── pyproject.toml     dépendances, métadonnées, configuration des outils
├── uv.lock            versions résolues — versionné, jamais édité à la main
├── .python-version    interpréteur du projet (3.14)
└── src/app/
    ├── __init__.py
    └── main.py        assemblage de l'application FastAPI
```

Le paquet s'appelle `app` alors que le projet se nomme `juui-api` : la
correspondance est déclarée par `[tool.uv.build-backend] module-name`.

L'arborescence en couches — `domain/`, `application/`, `infrastructure/` — est
posée par BACK-04. Ne rien anticiper ici : le sens des dépendances (l'extérieur
dépend du domaine, jamais l'inverse) se décide là-bas.

### `main.py`

Le module d'assemblage, et rien d'autre : aucune logique métier n'y a sa place.

- **`create_app()`** construit une instance neuve de l'application. Les tests
  (BACK-12) en dépendront pour repartir d'une application propre à chaque cas.
- **`app = create_app()`** est le point d'entrée ASGI, celui que désigne
  `uvicorn app.main:app`. Un serveur ASGI attend un objet, pas une fonction.
- **`lifespan`** est le point d'accroche des ressources de longue durée : pool
  PostgreSQL (BACK-05), client Redis (BACK-14), broker TaskIQ (BACK-15). Il est
  vide aujourd'hui, mais il fixe déjà la règle : rien ne s'ouvre à l'import du
  module, tout passe par lui.

## Dépendances

Deux groupes, strictement séparés. Le build Docker d'INFRA-04 installera le
premier seulement (`uv sync --frozen --no-dev`).

### Applicatives

| Paquet                | Rôle                                                                  |
| --------------------- | --------------------------------------------------------------------- |
| `fastapi`             | Framework HTTP et génération du contrat OpenAPI.                      |
| `uvicorn[standard]`   | Serveur ASGI. L'extra apporte uvloop, httptools et le `--reload`.     |
| `pydantic`            | Validation et sérialisation des schémas d'API.                        |
| `pydantic-settings`   | Configuration typée, lue de l'environnement (BACK-03).                |
| `sqlalchemy[asyncio]` | ORM. L'extra tire `greenlet`, sans lequel l'asynchrone ne marche pas. |
| `asyncpg`             | Pilote PostgreSQL asynchrone.                                         |
| `alembic`             | Migrations de schéma (BACK-07).                                       |
| `pyjwt`               | Émission et vérification des jetons d'authentification (BACK-10).     |
| `redis`               | Cache applicatif (BACK-14) et, plus tard, broker de TaskIQ.           |
| `taskiq`              | Tâches de fond (BACK-15). Le broker Redis viendra avec ce ticket.     |
| `boto3`               | Stockage objet S3 en production, MinIO en développement (BACK-13).    |

### Développement (`dev`)

| Paquet            | Rôle                                                  |
| ----------------- | ----------------------------------------------------- |
| `ruff`            | Lint et formatage. Épinglé à l'exact — voir plus bas. |
| `mypy`            | Vérification de types en mode strict.                 |
| `pytest`          | Cadre de test.                                        |
| `pytest-asyncio`  | Support des tests asynchrones.                        |
| `pytest-cov`      | Mesure de couverture.                                 |
| `httpx`           | Client HTTP de test, via `ASGITransport`.             |
| `boto3-stubs[s3]` | Stubs de typage de boto3, limités au service S3.      |

`boto3` est le seul paquet de la liste à ne pas embarquer ses propres
annotations : tous les autres livrent un `py.typed`, et leurs paquets `types-*`
d'antan ont été retirés de PyPI.

**Ruff est épinglé à la version exacte**, contrairement à tout le reste. Un
linter qui change d'avis tout seul entre deux `uv sync` ferait échouer la CI sans
qu'une ligne de code ait bougé : sa montée de version doit rester un commit
délibéré.

## Ce qui n'est pas encore là

| Sujet                                         | Ticket   |
| --------------------------------------------- | -------- |
| Configuration de Ruff et Mypy                 | BACK-02  |
| Configuration applicative (Pydantic Settings) | BACK-03  |
| Structure hexagonale des dossiers             | BACK-04  |
| Moteur SQLAlchemy et session asynchrone       | BACK-05  |
| Sonde de santé et métadonnées OpenAPI         | BACK-08  |
| Suite de tests                                | BACK-12  |
| `Dockerfile` et `.dockerignore`               | INFRA-04 |
| Intégration continue                          | QA-01    |

Les dépendances de qualité et de test sont **déclarées** ici, mais aucune n'est
configurée : c'est volontaire, chaque ticket porte son propre outil.
