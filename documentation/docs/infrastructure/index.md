---
title: Infrastructure
description: Conteneurs, services de développement et publication — page d'attente.
---

# Infrastructure

La pile de développement est décrite par un unique `docker/docker-compose.yml` : PostgreSQL et sa
console pgAdmin, Redis, MinIO pour le stockage objet, Mailpit pour le courrier, et les images
construites depuis le dépôt pour l'API et les trois frontends.

Un principe y est déjà tenu : **un service sans authentification n'est publié que sur la boucle
locale**. Redis, sa console et Mailpit ne sont donc joignables que depuis le poste.

## Ce qui viendra ici

- L'**allocation des ports**, aujourd'hui tenue dans le README de la racine.
- La construction des **images**, leurs étages et ce que chacun met en cache.
- Les **volumes**, la persistance des données de développement et la façon de repartir à zéro.
- L'**intégration continue** : ce que chaque pipeline vérifie et ce qui bloque un merge.
- La **publication de ce site**, aujourd'hui la seule chaîne automatisée du dépôt.

## La publication de ce site

Un workflow GitHub Actions construit ce site à chaque pull request touchant `documentation/`, et le
publie sur GitHub Pages à chaque `push` sur `main`. Le déploiement se fait par artefact — rien
n'est commité dans une branche `gh-pages`.

:::note Apportée par les tickets INFRA et QA
Le détail des pipelines et des règles de protection de branche revient aux tickets QA.
:::
