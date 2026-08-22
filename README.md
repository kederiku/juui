# Juui

Plateforme SaaS B2B2C de prise de rendez-vous et de gestion pour cliniques
vétérinaires : agenda et gestion du cabinet côté professionnels, carnet de santé
numérique et réservation en ligne côté propriétaires d'animaux, back-office
d'administration côté plateforme.

## Arborescence du monorepo

| Dossier                           | Rôle                                                                                                                                   |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `docker/`                         | Configurations de conteneurisation : Dockerfiles des services et scripts d'initialisation.                                             |
| `backend/api/`                    | Service d'API backend (FastAPI, architecture hexagonale et DDD).                                                                       |
| `frontend/frontend-professional/` | Interface **B2B** — application des cliniques et des vétérinaires.                                                                     |
| `frontend/frontend-individual/`   | Interface **B2C** — application des propriétaires d'animaux.                                                                           |
| `frontend/frontend-admin/`        | Interface d'**administration** — back-office de la plateforme.                                                                         |
| `packages/`                       | Bibliothèques et composants partagés par les trois frontends (UI shadcn en mode monorepo, configurations communes, client API généré). |
| `documentation/`                  | Documentation technique du projet, publiée avec Docusaurus.                                                                            |

Les dossiers encore vides contiennent un `.gitkeep` afin que l'arborescence soit
versionnée dès maintenant : chacun sera rempli par le ticket qui lui correspond.

## Stack technique

- **Backend** — Python 3, FastAPI, Pydantic, PostgreSQL (pgAdmin en développement),
  SQLAlchemy, Alembic, PyJWT ; outillage `uv`, Ruff, Mypy, Pytest.
- **Frontend** — React, Next.js, TypeScript, TanStack Query, TanStack Form, Zod,
  Tailwind CSS, shadcn/ui ; outillage pnpm, ESLint, Prettier, Vitest, Orval.
- **Infrastructure** — Docker, Redis (broker et cache), MinIO en développement et
  Amazon S3 en production, TaskIQ pour les tâches de fond.

Le détail des choix et de leur justification se trouve dans le document
[Stack Technique et Architecture](https://docs.google.com/document/d/1m_16LSQk7WWyykR0nsbySHtD1M0HP3OTmc_KoB09bj0/edit).
Il sera repris et enrichi dans le site `documentation/`.

## Démarrage rapide

### Prérequis

- **Node 24 LTS** — la version de référence est déclarée dans [`.nvmrc`](.nvmrc) :
  avec `nvm` ou `fnm`, `nvm use` suffit à s'y aligner.
- **pnpm** — rien à installer soi-même : le champ `packageManager` du
  `package.json` racine épingle la version exacte, que pnpm récupère seul.

### Installation

```bash
pnpm install
```

Le dépôt est piloté par les workspaces pnpm — `frontend/*`, `packages/*` et
`documentation`, déclarés dans [`pnpm-workspace.yaml`](pnpm-workspace.yaml).
`backend/api` en est exclu à dessein : c'est un projet Python, outillé par `uv`.

### Scripts racine

| Commande            | Effet                                                        |
| ------------------- | ------------------------------------------------------------ |
| `pnpm dev`          | Démarre en parallèle les serveurs de développement.          |
| `pnpm build`        | Construit chaque workspace, dans l'ordre de ses dépendances. |
| `pnpm lint`         | Analyse statique ESLint sur tout le dépôt.                   |
| `pnpm lint:fix`     | Idem, en appliquant les corrections automatiques.            |
| `pnpm typecheck`    | Vérification des types TypeScript.                           |
| `pnpm test`         | Suites de tests des workspaces.                              |
| `pnpm format`       | Reformate le dépôt avec Prettier.                            |
| `pnpm format:check` | Vérifie le formatage sans rien réécrire (CI).                |

`dev`, `build`, `typecheck` et `test` délèguent aux workspaces qui définissent le
script de même nom ; ceux qui ne le définissent pas sont simplement ignorés.

`lint` et `format` fonctionnent autrement : ils parcourent le dépôt en une seule
passe depuis la racine. Depuis ESLint 10, la recherche de configuration part du
répertoire du **fichier analysé** et remonte l'arborescence — un `eslint .` lancé
à la racine applique donc déjà à chaque application sa propre configuration, et
celle de la racine au reste. Prettier procède de même. Déléguer aux workspaces
serait un double parcours, et laisserait de côté les fichiers de la racine, que
`pnpm -r` n'atteint pas.

> **Note.** Aucun service n'est encore démarrable : les variables
> d'environnement et la séquence de démarrage complète arrivent avec les tickets
> SETUP-05 et INFRA-06.

## Conventions

- Fins de ligne LF, UTF-8, indentation à 2 espaces (4 pour Python) : voir
  [`.editorconfig`](.editorconfig).
- `main` est la branche de référence ; toute modification passe par une branche
  dédiée puis une pull request.

### Style de code

Point-virgule final, guillemets simples, virgule finale partout, largeur de ligne
à 100 caractères. La configuration fait foi — personne n'a à retenir cette liste :

```bash
pnpm format && pnpm lint
```

À lancer **avant chaque commit**. SETUP-04 automatisera cette étape via un hook
de pre-commit, qui ne traitera que les fichiers indexés.

Prettier ne remet jamais la prose à la ligne (`proseWrap: 'preserve'`) : les
paragraphes du Markdown restent découpés à la main. Il réaligne en revanche les
tableaux, ce qui allonge leurs lignes source.

### Configurations partagées

| Package                                             | Rôle                                                                                  |
| --------------------------------------------------- | ------------------------------------------------------------------------------------- |
| [`@repo/eslint-config`](packages/config-eslint)     | Presets ESLint : `base`, `react`, `next`.                                             |
| [`@repo/prettier-config`](packages/config-prettier) | Configuration Prettier, ré-exportée par [`prettier.config.mjs`](prettier.config.mjs). |

Les trois presets ESLint forment une chaîne — `next` étend `react`, qui étend
`base` — et partagent donc exactement le même socle de règles :

- **`base`** — TypeScript et Node, sans rien de spécifique à React. Pour
  `packages/*` et les scripts d'outillage.
- **`react`** — `base` plus les règles des hooks. Pour `packages/ui` (SHARED-01),
  qui est du React sans Next.
- **`next`** — `react` plus les 22 règles de `@next/eslint-plugin-next`. Pour les
  trois applications (FRONT-01 et suivants).

Une application les consomme ainsi :

```js
// frontend/frontend-admin/eslint.config.mjs
import next from '@repo/eslint-config/next';
import { defineConfig, globalIgnores } from 'eslint/config';

export default defineConfig([...next, globalIgnores(['.next/**'])]);
```

Le socle de règles se modifie en un seul endroit :
[`packages/config-eslint/rules.js`](packages/config-eslint/rules.js).

## Licence

[MIT](LICENSE).
