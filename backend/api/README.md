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

Deux drapeaux interdisent la re-résolution — `--frozen` et `--locked` — et ils ne disent pas la
même chose : la nuance est sur la page
[Dépendances](https://kederiku.github.io/juui/backend/dependances) du site de documentation.

## Démarrage

Un fichier `.env` est nécessaire depuis BACK-03 : l'API valide sa configuration au
démarrage et refuse de partir sans elle. Les valeurs livrées conviennent telles quelles
sur un poste vierge.

**PostgreSQL doit tourner** depuis BACK-05 : l'API ouvre son pool de connexions au
démarrage et refuse de partir si le serveur ne répond pas. Le plus simple est de lever
la base seule depuis la racine du dépôt :

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d postgres
```

Puis, depuis `backend/api/` :

```bash
cp .env.example .env
uv run uvicorn app.main:app --reload
```

La documentation interactive répond alors sur <http://localhost:8000/docs>, et
le contrat OpenAPI sur <http://localhost:8000/openapi.json>.

> Ce contrat est la **source du client des trois frontends** : `@repo/api-client`
> le régénère à la commande `make generate-api` (SHARED-03). Renommer une
> étiquette ou un `operation_id` après coup se traite donc comme une migration de
> schéma —
> [Le client d'API généré](https://kederiku.github.io/juui/frontend/client-api-genere).

> L'API sert les
> [sondes de santé](https://kederiku.github.io/juui/backend/surface-http) (`/health/live`,
> `/health/ready`, BACK-08) ; les routes **métier**, elles, restent à venir —
> le routeur du module `identity` est bien monté sous `/api/v1` (BACK-04,
> BACK-08), mais ses routes relèvent de BACK-28 et BACK-29. `/docs` n'affiche
> donc que le groupe `health`, et c'est attendu.

## Documentation

Le détail du service vit dans la
[section Backend du site de documentation](https://kederiku.github.io/juui/backend) ; ce README
ne garde que l'entrée en matière. Quand une information existe aux deux endroits, le site fait
foi.

| Sujet                                               | Page                                                                                           |
| --------------------------------------------------- | ---------------------------------------------------------------------------------------------- |
| L'arborescence du service et `main.py`              | [Structure du service](https://kederiku.github.io/juui/backend/structure)                      |
| Les trois espaces, les trois couches, les 3 modèles | [Architecture du service](https://kederiku.github.io/juui/backend/architecture-du-service)     |
| Les Settings Pydantic et le `.env` strict           | [Configuration](https://kederiku.github.io/juui/backend/configuration)                         |
| Le moteur SQLAlchemy, les mixins, la tenance        | [Persistance](https://kederiku.github.io/juui/backend/persistance)                             |
| Le port UnitOfWork et le dépôt générique            | [Unité de travail](https://kederiku.github.io/juui/backend/unite-de-travail)                   |
| Alembic et le cycle d'une migration                 | [Migrations](https://kederiku.github.io/juui/backend/migrations)                               |
| Le port de cache Redis                              | [Cache](https://kederiku.github.io/juui/backend/cache)                                         |
| Le port S3/MinIO et les URLs pré-signées            | [Stockage objet](https://kederiku.github.io/juui/backend/stockage-objet)                       |
| TaskIQ : broker, worker, politique de reprise       | [Tâches de fond](https://kederiku.github.io/juui/backend/taches-de-fond)                       |
| Le code de vérification d'adresse, haché et borné   | [Vérification d'adresse (OTP)](https://kederiku.github.io/juui/backend/verification-email-otp) |
| Le routeur `/api/v1` et les sondes                  | [Surface HTTP](https://kederiku.github.io/juui/backend/surface-http)                           |
| La hiérarchie d'erreurs et le format unique         | [Erreurs](https://kederiku.github.io/juui/backend/erreurs)                                     |
| Journaux, identifiant de requête, masquage, CORS    | [Journalisation](https://kederiku.github.io/juui/backend/journalisation)                       |
| Les dépendances et la version d'`uv`                | [Dépendances](https://kederiku.github.io/juui/backend/dependances)                             |
| Ruff, Mypy et Import Linter                         | [Qualité et typage](https://kederiku.github.io/juui/backend/qualite-et-typage)                 |
| Les écarts entre tickets BACK et livrables          | [Écarts assumés — tickets BACK](https://kederiku.github.io/juui/ecarts/back)                   |

## Ce qui n'est pas encore là

| Sujet                                                                                                 | Ticket   |
| ----------------------------------------------------------------------------------------------------- | -------- |
| Doublures en mémoire (fakes)                                                                          | BACK-06c |
| Harnais de tests complet (BACK-06b a ouvert `tests/` avec la suite `tenant_isolation` et `make test`) | BACK-12  |
| Pipeline CI complet du backend                                                                        | QA-01    |
