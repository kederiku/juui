# Juui

Plateforme SaaS B2B2C de prise de rendez-vous et de gestion pour cliniques
vétérinaires : agenda et gestion du cabinet côté professionnels, carnet de santé
numérique et réservation en ligne côté propriétaires d'animaux, back-office
d'administration côté plateforme.

## Arborescence du monorepo

| Dossier | Rôle |
|---|---|
| `docker/` | Configurations de conteneurisation : Dockerfiles des services et scripts d'initialisation. |
| `backend/api/` | Service d'API backend (FastAPI, architecture hexagonale et DDD). |
| `frontend/frontend-professional/` | Interface **B2B** — application des cliniques et des vétérinaires. |
| `frontend/frontend-individual/` | Interface **B2C** — application des propriétaires d'animaux. |
| `frontend/frontend-admin/` | Interface d'**administration** — back-office de la plateforme. |
| `packages/` | Bibliothèques et composants partagés par les trois frontends (UI shadcn en mode monorepo, configurations communes, client API généré). |
| `documentation/` | Documentation technique du projet, publiée avec Docusaurus. |

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

> **À venir.** Le squelette du dépôt est en place, mais aucun service n'est encore
> démarrable. Les prérequis, les variables d'environnement et la séquence de
> démarrage seront documentés ici une fois l'environnement de développement en
> place (tickets SETUP-05 et INFRA-06).

## Conventions

- Fins de ligne LF, UTF-8, indentation à 2 espaces (4 pour Python) : voir
  [`.editorconfig`](.editorconfig).
- `main` est la branche de référence ; toute modification passe par une branche
  dédiée puis une pull request.

## Licence

[MIT](LICENSE).
