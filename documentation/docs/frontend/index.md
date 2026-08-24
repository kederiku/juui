---
title: Frontend
description: Les trois applications Next.js et leurs packages partagés — page d'attente.
---

# Frontend

Trois applications **Next.js** se partagent le dossier `frontend/`, une par public :

| Application             | Public                          | Port |
| ----------------------- | ------------------------------- | ---- |
| `frontend-professional` | B2B — cliniques et vétérinaires | 3001 |
| `frontend-individual`   | B2C — propriétaires d'animaux   | 3002 |
| `frontend-admin`        | Back-office de la plateforme    | 3003 |

Elles ne sont **pas** le découpage du backend : ce sont des canaux de livraison, pas des contextes
métier. Le cœur d'authentification leur est commun et n'est écrit qu'une fois, côté API.

## Ce qui viendra ici

- La **bibliothèque de composants partagée** `@repo/ui` et son usage en monorepo.
- Les **configurations communes** — ESLint, Prettier, TypeScript, Tailwind — et la règle qui veut
  qu'un réglage ne se modifie qu'à un seul endroit.
- Le **client d'API généré** depuis le contrat OpenAPI, et l'interdiction d'éditer son code.
- Les conventions de **données côté client** : cache, formulaires, validation.
- Le rendu, les routes protégées et l'**accessibilité**.

:::note Apportée par les tickets FRONT et SHARED
La section « Configurations partagées » du README de la racine décrit déjà les quatre packages
communs et la façon de les consommer.
:::
