---
title: ADR-0001 — Un monorepo pour tout le produit
description: Backend, frontends, packages, documentation et conteneurisation vivent dans un seul dépôt, avec deux chaînes d'outils assumées.
---

# ADR-0001 — Un monorepo pour tout le produit

| Statut      | Date       | Tickets            |
| ----------- | ---------- | ------------------ |
| **Accepté** | 2026-08-25 | SETUP-01, SETUP-02 |

## Contexte

Décision rendue par SETUP-01, le ticket racine du projet. Le produit est un seul système : une API
FastAPI, trois applications Next.js (professionnelle, grand public, back-office), des packages
partagés entre elles (interface, configurations), un site de documentation et les configurations
Docker qui assemblent le tout. Ces morceaux ne vivent pas indépendamment : le contrat OpenAPI de
l'API devient le client TypeScript des frontends ([ADR-0007](./0007-client-api-genere-orval.md)),
les trois applications consomment les mêmes packages, et une évolution du backend appelle presque
toujours une évolution en face.

## Décision

**Tout le produit vit dans un seul dépôt** : `backend/api/`, `frontend/frontend-professional/`,
`frontend/frontend-individual/`, `frontend/frontend-admin/`, `packages/`, `documentation/`,
`docker/`.

Le TypeScript est piloté par les workspaces pnpm — `frontend/*`, `packages/*` et `documentation`,
déclarés dans `pnpm-workspace.yaml` (SETUP-02). `backend/api` en est **volontairement absent** :
c'est un projet Python outillé par uv ([ADR-0002](./0002-uv-outillage-python.md)). Le dépôt assume
donc **deux chaînes d'outils** indépendantes, pnpm et uv, chacune souveraine sur son territoire.

## Alternatives écartées

### Un dépôt par application

Le découpage naturel à plusieurs équipes : chaque application a son cycle de vie, ses permissions,
sa CI. Ici, il aurait fallu publier les packages partagés sur un registre privé et ouvrir des
pull requests croisées pour chaque évolution transverse — et surtout, un changement de contrat
d'API ne serait jamais **atomique** avec le client qui le consomme : la fenêtre entre les deux
merges est exactement l'endroit où une dérive de contrat s'installe en silence.

### Le backend dans les workspaces pnpm

Un `package.json` de façade dans `backend/api/` aurait donné l'illusion d'une chaîne unique. En
pratique, deux gestionnaires auraient prétendu au même dossier, et `pnpm -r` aurait tenté des
scripts sur un projet Python qui n'en veut pas. L'exclusion franche est plus honnête : la
frontière entre les deux chaînes d'outils est celle du langage, et elle se lit dans
`pnpm-workspace.yaml`.

## Conséquences

**Ce que cela donne.** Une évolution transverse — contrat d'API et client, package partagé et ses
trois consommateurs — tient dans une seule branche et une seule pull request. Deux verrous font
foi : le lockfile pnpm à la racine et `backend/api/uv.lock`. Les workflows CI se déclenchent par
filtres `paths`, si bien qu'une modification de documentation ne rejoue pas les vérifications du
backend.

**Ce que cela coûte.** Chaque workflow doit tenir sa liste `paths` à jour — un dossier oublié est
un dossier non vérifié. Le dépôt porte deux outillages à documenter côte à côte, et tout ce qui
est versionné à dessein (comme le futur client généré) grossit l'historique de chacun.

## Références

- `pnpm-workspace.yaml` — le périmètre des workspaces et l'exclusion commentée de `backend/api`.
- `package.json` — la version de pnpm épinglée et les scripts racine.
- `backend/api/pyproject.toml` — le pendant Python, piloté par uv.
