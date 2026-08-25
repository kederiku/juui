---
title: Installer le poste de travail
description: Les prérequis du poste — Node, pnpm, uv, Docker, make — et l'installation des deux chaînes d'outils du monorepo.
---

# Installer le poste de travail

Avant de lancer quoi que ce soit, le poste doit réunir une poignée d'outils — Node, pnpm, `uv`,
Docker et `make` — puis mettre en place les deux chaînes d'outils du monorepo, indépendantes
l'une de l'autre. Cette page couvre ce parcours, du clone du dépôt au premier `uv sync`.

## Prérequis

Pour le parcours qui fonctionne aujourd'hui :

- **Node 24 LTS** — la version de référence est déclarée dans `.nvmrc` :
  avec `nvm` ou `fnm`, `nvm use` suffit à s'y aligner.
- **pnpm** — rien à installer soi-même : le champ `packageManager` du
  `package.json` racine épingle la version exacte, que pnpm récupère seul.
- **[`uv`](https://docs.astral.sh/uv/)** — uniquement pour `backend/api`. Il
  télécharge lui-même l'interpréteur Python attendu : rien d'autre à installer.
  La version attendue est déclarée par `required-version` dans
  `backend/api/pyproject.toml`, et fait foi pour
  le poste comme pour la CI et l'image Docker
  ([ADR-0002](../adr/0002-uv-outillage-python.md)).
  `brew upgrade uv` suffit à s'y aligner.

- **Docker** — [Docker Desktop](https://docs.docker.com/desktop/),
  [OrbStack](https://orbstack.dev/) ou [Colima](https://github.com/abiosoft/colima).
  Requis depuis INFRA-01 : c'est lui qui fait tourner PostgreSQL et pgAdmin.
  Depuis BACK-05, même un `uvicorn` lancé sur le poste en dépend : l'API ouvre
  son pool de connexions au démarrage et refuse de partir si la base ne répond
  pas. C'est bien `docker compose`, sous-commande du client, qui est attendue —
  pas l'ancien binaire `docker-compose`, qui n'est plus maintenu.

Un outil de plus pour le parcours conteneurisé, requis depuis INFRA-06 — c'est
lui qui porte `make up`, `make db-reset` et les autres cibles du
`Makefile` de la racine :

- **`make`** — sur macOS, il vient des Command Line Tools :
  `xcode-select --install`. La version 3.81 livrée par Apple suffit : c'est elle
  qui exécute les deux `Makefile` du dépôt.

## Installation

```bash
git clone git@github.com:kederiku/juui.git && cd juui
```

Aucun `.env` n'est versionné — `.gitignore` les exclut tous et
n'excepte que les gabarits. Chaque fichier d'environnement se crée à partir du
sien, en retirant le suffixe `.example` :

| Gabarit versionné               | Fichier à créer    | Lu par                                 |
| ------------------------------- | ------------------ | -------------------------------------- |
| `.env.example`                  | `.env`             | `docker compose` — toute la pile       |
| `backend/api/.env.example`      | `backend/api/.env` | l'API lancée **hors** Docker (BACK-03) |
| `frontend/*/.env.local.example` | `.env.local`       | chaque application Next.js             |

```bash
cp .env.example .env
cp backend/api/.env.example backend/api/.env
```

Les valeurs livrées conviennent telles quelles sur un poste vierge : rien n'est
à modifier pour un premier démarrage. **Chaque variable est documentée dans son
gabarit** — les commentaires y font foi, cette page ne les recopie pas pour
éviter qu'ils divergent. Une seule mérite d'être changée dès qu'on quitte le
poste : `JWT_SECRET_KEY`, à régénérer par environnement avec
`openssl rand -hex 32`.

:::note Gabarits des frontends
Des trois gabarits `frontend/*/.env.local.example`, seul celui de
`frontend-professional` a aujourd'hui une application pour le lire. Sa copie
n'est d'ailleurs pas nécessaire pour démarrer : les deux variables qu'il porte
désignent l'API, que l'interface n'appelle pas encore (SHARED-03).
:::

Le dépôt a **deux chaînes d'outils**, indépendantes l'une de l'autre
([ADR-0001](../adr/0001-monorepo.md)).

Côté JavaScript, les workspaces pnpm — `frontend/*`, `packages/*` et
`documentation`, déclarés dans `pnpm-workspace.yaml` :

```bash
pnpm install
```

Cette commande installe aussi les **hooks Git** — voir
[Hooks de pre-commit](./conventions-du-depot.md#hooks-de-pre-commit).

Côté Python, le seul service `backend/api`, absent de ces workspaces et piloté
par `uv` :

```bash
cd backend/api && uv sync
```

Les écarts assumés avec le ticket SETUP-05 sont consignés au
[registre des écarts](../ecarts/setup.md#écarts-assumés-avec-le-ticket-setup-05).
