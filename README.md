# Juui

Plateforme SaaS B2B2C de prise de rendez-vous et de gestion pour cliniques
vétérinaires : agenda et gestion du cabinet côté professionnels, carnet de santé
numérique et réservation en ligne côté propriétaires d'animaux, back-office
d'administration côté plateforme.

## Arborescence du monorepo

| Dossier                           | Rôle                                                                                                                                                                   |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.github/`                        | Workflows GitHub Actions : la CI du backend, celle des frontends, la dérive du client d'API, et la construction puis la publication du site de documentation (DOC-01). |
| `docker/`                         | Configurations de conteneurisation : le `docker-compose.yml` qui assemble la pile, les Dockerfiles des services et les scripts d'initialisation.                       |
| `scripts/`                        | Scripts shell appelés par le `Makefile` de la racine (INFRA-06) : ouverture de la boîte Mailpit, remise à zéro de la base.                                             |
| `backend/api/`                    | Service d'API backend (FastAPI, architecture hexagonale et DDD).                                                                                                       |
| `frontend/frontend-professional/` | Interface **B2B** — application des cliniques et des vétérinaires.                                                                                                     |
| `frontend/frontend-individual/`   | Interface **B2C** — application des propriétaires d'animaux.                                                                                                           |
| `frontend/frontend-admin/`        | Interface d'**administration** — back-office de la plateforme.                                                                                                         |
| `packages/`                       | Bibliothèques et composants partagés par les trois frontends (UI shadcn en mode monorepo, configurations communes, client API généré).                                 |
| `documentation/`                  | Documentation technique du projet, publiée avec Docusaurus.                                                                                                            |

Les dossiers encore vides contiennent un `.gitkeep` afin que l'arborescence soit
versionnée dès maintenant : chacun sera rempli par le ticket qui lui correspond.

## Stack technique

- **Backend** — Python 3, FastAPI, Pydantic, PostgreSQL (pgAdmin en développement),
  SQLAlchemy, Alembic, PyJWT ; outillage `uv`, Ruff, Mypy, Pytest.
- **Frontend** — React, Next.js, TypeScript, TanStack Query, TanStack Form, Zod,
  Tailwind CSS, shadcn/ui ; outillage pnpm, ESLint, Prettier, Vitest, Orval.
- **Infrastructure** — Docker, Redis (broker et cache), MinIO en développement et
  Amazon S3 en production, TaskIQ pour les tâches de fond.

Les choix structurants et leurs motifs — monorepo, uv, monolithe modulaire,
tenance, Orval, TaskIQ… — sont consignés dans les
[ADR](documentation/docs/adr/index.md), publiés sur le
[site de documentation](https://kederiku.github.io/juui/adr).

## Documentation

Le détail du dépôt vit sur le [site de documentation](https://kederiku.github.io/juui/) —
consultable en local avec `pnpm --filter documentation dev` sur <http://localhost:3004>. Ce
README ne garde que l'entrée en matière et le démarrage express ; quand une information existe
aux deux endroits, le site fait foi.

| Sujet                                                | Page                                                                                                                                                                                                    |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Installer le poste — prérequis, chaînes d'outils     | [Installation](https://kederiku.github.io/juui/getting-started/installation)                                                                                                                            |
| Démarrer la pile — les deux parcours                 | [Démarrage](https://kederiku.github.io/juui/getting-started/demarrage)                                                                                                                                  |
| L'allocation des ports et les URLs                   | [Ports et URLs des services](https://kederiku.github.io/juui/infrastructure/ports-et-services)                                                                                                          |
| Les images Docker construites depuis le dépôt        | [Image de l'API](https://kederiku.github.io/juui/infrastructure/image-api), [Image des frontends](https://kederiku.github.io/juui/infrastructure/image-frontends)                                       |
| Le mode développement — rechargement à chaud         | [Mode développement](https://kederiku.github.io/juui/infrastructure/mode-developpement)                                                                                                                 |
| Vérifier les services de développement               | [MinIO](https://kederiku.github.io/juui/infrastructure/minio), [Mailpit](https://kederiku.github.io/juui/infrastructure/mailpit), [le worker](https://kederiku.github.io/juui/infrastructure#le-worker) |
| Le Makefile et les scripts de la racine              | [Makefile et scripts](https://kederiku.github.io/juui/infrastructure/makefile-et-scripts)                                                                                                               |
| Le site de documentation lui-même                    | [Site de documentation](https://kederiku.github.io/juui/infrastructure/site-de-documentation)                                                                                                           |
| Les conventions — style, hooks, commits              | [Conventions du dépôt](https://kederiku.github.io/juui/getting-started/conventions-du-depot)                                                                                                            |
| Les packages de configuration partagés               | [Configurations partagées](https://kederiku.github.io/juui/frontend/configurations-partagees)                                                                                                           |
| La bibliothèque de composants et le thème            | [La bibliothèque @repo/ui](https://kederiku.github.io/juui/frontend/bibliotheque-ui)                                                                                                                    |
| Le client d'API généré depuis l'OpenAPI              | [Le client d'API généré](https://kederiku.github.io/juui/frontend/client-api-genere)                                                                                                                    |
| Les trois applications Next.js                       | [Les trois applications](https://kederiku.github.io/juui/frontend/les-trois-applications)                                                                                                               |
| Le vocabulaire du projet, terme par terme            | [Vocabulaire](https://kederiku.github.io/juui/architecture/glossaire)                                                                                                                                   |
| Les règles d'architecture — comment écrire un module | [Comment écrire un module conforme](https://kederiku.github.io/juui/architecture/ecrire-un-module-conforme)                                                                                             |
| Ce qui est interdit, et ce qui l'attrape             | [Ce qui est interdit](https://kederiku.github.io/juui/architecture/anti-patterns)                                                                                                                       |
| Les modules, ce qu'ils exposent, qui consomme quoi   | [Carte de contexte](https://kederiku.github.io/juui/architecture/carte-de-contexte)                                                                                                                     |
| Les décisions structurantes et leurs motifs          | [Décisions (ADR)](https://kederiku.github.io/juui/adr)                                                                                                                                                  |
| Les écarts entre tickets et livrables                | [Écarts assumés](https://kederiku.github.io/juui/ecarts)                                                                                                                                                |

## Démarrage rapide

### Prérequis

- **Node 24 LTS** — la version de référence est déclarée dans [`.nvmrc`](.nvmrc).
- **pnpm** — rien à installer soi-même : le champ `packageManager` du
  [`package.json`](package.json) racine épingle la version exacte.
- **[`uv`](https://docs.astral.sh/uv/)** — uniquement pour `backend/api` ; la version attendue
  est déclarée dans [`backend/api/pyproject.toml`](backend/api/pyproject.toml).
- **Docker** — [Docker Desktop](https://docs.docker.com/desktop/),
  [OrbStack](https://orbstack.dev/) ou [Colima](https://github.com/abiosoft/colima), avec la
  sous-commande `docker compose` — pas l'ancien binaire `docker-compose`.
- **`make`** — sur macOS, il vient des Command Line Tools : `xcode-select --install`.

Le détail de chaque prérequis — versions exactes, motifs, pièges — est sur la page
[Installation](https://kederiku.github.io/juui/getting-started/installation).

### Installation

```bash
git clone git@github.com:kederiku/juui.git && cd juui
```

Aucun `.env` n'est versionné : chaque fichier d'environnement se crée à partir de son gabarit,
en retirant le suffixe `.example`. **Chaque variable est documentée dans son gabarit** — les
commentaires y font foi.

| Gabarit versionné               | Fichier à créer    | Lu par                           |
| ------------------------------- | ------------------ | -------------------------------- |
| `.env.example`                  | `.env`             | `docker compose` — toute la pile |
| `backend/api/.env.example`      | `backend/api/.env` | l'API lancée **hors** Docker     |
| `frontend/*/.env.local.example` | `.env.local`       | chaque application Next.js       |

```bash
cp .env.example .env
cp backend/api/.env.example backend/api/.env
```

Les valeurs livrées conviennent telles quelles sur un poste vierge. Une seule mérite d'être
changée dès qu'on quitte le poste : `JWT_SECRET_KEY`, à régénérer par environnement avec
`openssl rand -hex 32`.

Puis les deux chaînes d'outils — pnpm, qui installe aussi les
[hooks Git](https://kederiku.github.io/juui/getting-started/conventions-du-depot#hooks-de-pre-commit),
et uv :

```bash
pnpm install
cd backend/api && uv sync
```

### Démarrer

Toute la pile en conteneurs :

```bash
make up
```

| Cible                   | Effet                                                                     |
| ----------------------- | ------------------------------------------------------------------------- |
| `make help`             | Cible par défaut : liste toutes les cibles — c'est elle qui fait foi.     |
| `make up`               | Démarre toute la pile en arrière-plan, sur les images servies.            |
| `make dev`              | Démarre la pile en mode développement — code monté, rechargement à chaud. |
| `make down`             | Arrête la pile et libère les ports ; les volumes survivent.               |
| `make logs service=api` | Suit les logs d'un service.                                               |

Ou, pour travailler hors conteneurs — l'infrastructure en Docker, l'API sur le poste, les
interfaces avec pnpm :

```bash
docker compose --project-directory . -f docker/docker-compose.yml up -d
```

```bash
cd backend/api && uv run uvicorn app.main:app --reload
```

```bash
pnpm dev
```

Une fois la pile debout :

| Service                         | URL                          |
| ------------------------------- | ---------------------------- |
| API — documentation interactive | <http://localhost:8000/docs> |
| Interface professionnelle       | <http://localhost:3001>      |
| Interface des particuliers      | <http://localhost:3002>      |
| Back-office                     | <http://localhost:3003>      |
| Documentation                   | <http://localhost:3004>      |
| pgAdmin                         | <http://localhost:5050>      |
| MinIO — console web             | <http://localhost:9001>      |
| Mailpit — boîte de réception    | <http://localhost:8025>      |

Le reste — les deux parcours pas à pas, l'allocation complète des ports et leurs identifiants,
le mode développement, la remise à zéro de la base (`make db-reset`) — est sur les pages
[Démarrage](https://kederiku.github.io/juui/getting-started/demarrage) et
[Ports et URLs des services](https://kederiku.github.io/juui/infrastructure/ports-et-services).

## Conventions

- Fins de ligne LF, UTF-8, indentation à 2 espaces (4 pour Python) : voir
  [`.editorconfig`](.editorconfig).
- `main` est la branche de référence ; toute modification passe par une branche
  dédiée puis une pull request.
- **Identifiants en anglais, commentaires et docstrings en français** ; les
  accents s'arrêtent au Markdown.
- Le style est appliqué par l'outillage — `pnpm format && pnpm lint` côté
  JavaScript, Ruff et Mypy côté Python — et les **hooks de pre-commit**
  installés par `pnpm install` le vérifient à chaque commit.
- Les messages de commit suivent
  [Conventional Commits](https://www.conventionalcommits.org/fr/) :
  `type(scope): sujet` à l'infinitif, huit types, vérifiés par commitlint.

Le détail — style, langue, hooks, convention de commit, presets partagés,
bibliothèque `@repo/ui` — vit sur les pages
[Conventions du dépôt](https://kederiku.github.io/juui/getting-started/conventions-du-depot),
[Configurations partagées](https://kederiku.github.io/juui/frontend/configurations-partagees) et
[La bibliothèque @repo/ui](https://kederiku.github.io/juui/frontend/bibliotheque-ui).

## Licence

[MIT](LICENSE).
