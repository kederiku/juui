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
├── Makefile           raccourcis de lint, formatage et typage
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

## Qualité et typage

Ruff et Mypy sont configurés dans [`pyproject.toml`](pyproject.toml), chaque
réglage accompagné de sa justification. Trois vérifications, toutes lançables
depuis ce dossier :

| Commande                       | Raccourci           | Rôle                      |
| ------------------------------ | ------------------- | ------------------------- |
| `uv run ruff check .`          | `make lint`         | Lint                      |
| `uv run ruff format --check .` | `make format-check` | Formatage (lecture seule) |
| `uv run mypy src`              | `make typecheck`    | Typage strict             |

`make check` enchaîne les trois **dans l'ordre qu'aura la CI** (QA-01) : un échec
local reproduit donc un échec de CI. `make` seul liste toutes les cibles.

Deux cibles réécrivent le code : `make format` (`ruff format .`) et `make lint-fix`
(`ruff check --fix .`, corrections sûres uniquement).

Ces deux-là s'appliquent aussi **toutes seules au moment du commit** : le hook de
pre-commit du monorepo (SETUP-04) passe chaque fichier `.py` indexé par
`ruff check --fix` puis `ruff format`, et interrompt le commit sur ce qui reste.
Voir [Hooks de pre-commit](../../README.md#hooks-de-pre-commit). Le typage, lui,
n'entre pas dans le hook — il reste à lancer à la main, et la CI le vérifiera.

### Ruff

Lint **et** formatage : `ruff format` remplace Black, il n'y a aucune autre
dépendance de formatage. Ligne à 100 caractères, cible `py314`.

Le jeu de règles : `E`/`F` (socle), `I` (tri des imports), `N` (nommage), `UP`
(modernisation de la syntaxe), `B` (pièges classiques), `A` (masquage des
builtins), `C4`, `SIM`, `RUF`, `ANN` (annotations obligatoires), `S` (sécurité)
et `D` (docstrings).

Dans `tests/` — à venir en BACK-12 — `assert` (S101) et les docstrings (D1xx)
sont relâchés. Les annotations, non : `-> None` sur une fonction de test coûte
huit caractères.

À noter : `ruff format` traite aussi les blocs de code Python **de la
documentation Markdown**, ce qui garde les exemples conformes. Un extrait
volontairement incomplet est ignoré sans erreur, et `ruff check` ne lint jamais
les fichiers Markdown.

### Mypy

Mode `strict`, plugin Pydantic activé, périmètre `src/` (les tests y entreront
avec BACK-12 si ce ticket le décide). `strict` couvre à lui seul
`disallow_untyped_defs`, `warn_return_any` et `warn_unused_ignores`, entre
autres — d'où l'absence de ces clés dans le `pyproject.toml`.

Aucune dépendance ne réclame `ignore_missing_imports` : toutes livrent un
`py.typed`, et `boto3` est couvert par `boto3-stubs[s3]`. Si une librairie sans
stubs entre un jour, la dérogation se déclare **par module** — jamais
globalement, ce qui aveuglerait Mypy sur tout le projet. Le modèle est en
commentaire dans le `pyproject.toml`.

Pour vérifier que le filet tient, une fonction non annotée doit faire échouer
Mypy :

```bash
printf '"""Sonde."""\n\n\ndef f(x):\n    """Doc."""\n    return x\n' > src/app/_sonde.py
uv run mypy src ; uv run ruff check src/app/_sonde.py ; rm src/app/_sonde.py
```

Attendu : `[no-untyped-def]` côté Mypy, `ANN001` et `ANN202` côté Ruff — les deux
barrières répondent.

### Écarts assumés avec le ticket BACK-02

| Écart                                               | Raison                                                                                                                           |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `target-version = "py314"` et non `py312`           | Le projet est verrouillé sur Python 3.14. Cibler py312 ferait réécrire par Ruff du code déjà moderne.                            |
| ANN101/ANN102 ne sont pas ignorées                  | Ruff les a **retirées**. Les nommer dans `ignore` ne produirait qu'un avertissement à chaque exécution et dans chaque log de CI. |
| `S` et `D` ajoutés au jeu de règles                 | Sans eux, l'assouplissement demandé pour `tests/` (« assert autorisé, docstrings non requises ») n'aurait relâché rien du tout.  |
| Les trois drapeaux Mypy nommés ne sont pas réécrits | `strict = true` les active déjà tous les trois.                                                                                  |
| Aucun `[[tool.mypy.overrides]]` vivant              | Aucune dépendance n'en a besoin ; le motif est documenté en commentaire.                                                         |

## Ce qui n'est pas encore là

| Sujet                                         | Ticket   |
| --------------------------------------------- | -------- |
| Configuration applicative (Pydantic Settings) | BACK-03  |
| Structure hexagonale des dossiers             | BACK-04  |
| Moteur SQLAlchemy et session asynchrone       | BACK-05  |
| Sonde de santé et métadonnées OpenAPI         | BACK-08  |
| Suite de tests                                | BACK-12  |
| `Dockerfile` et `.dockerignore`               | INFRA-04 |
| Intégration continue                          | QA-01    |

Ruff et Mypy sont désormais configurés (BACK-02). Les dépendances de test, elles,
restent **déclarées sans être configurées** : c'est volontaire, chaque ticket
porte son propre outil.
