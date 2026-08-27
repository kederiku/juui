---
title: Frontend
description: Les trois applications Next.js, leurs packages partagés et la carte des pages de cette section.
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

## Les pages de cette section

| Page                                                      | Ce qu'on y trouve                                                            |
| --------------------------------------------------------- | ---------------------------------------------------------------------------- |
| [Configurations partagées](./configurations-partagees.md) | Les quatre packages de configuration et la chaîne de presets qui les relie.  |
| [La bibliothèque @repo/ui](./bibliotheque-ui.md)          | Les composants shadcn/ui partagés, le thème, la `DataTable`.                 |
| [Le client d'API généré](./client-api-genere.md)          | Le package `@repo/api-client` : régénérer, consommer un hook, le mutator.    |
| [Données côté client](./donnees-cote-client.md)           | Le `QueryProvider` partagé, la politique de cache, les clés et leur portée.  |
| [Les trois applications](./les-trois-applications.md)     | Le socle commun FRONT-01 à 03, le volet SEO, le back-office et sa garde.     |
| [Structure par domaine](./structure-par-domaine.md)       | Le rangement par sujet, la surface d'une feature, le garde-fou qui la tient. |

## Ce qui viendra ici

- Les **formulaires** et leur validation : le patron de référence, et les schémas Zod du contrat.
- L'**accessibilité** au-delà du lint : parcours clavier et lecteurs d'écran.

:::note Apportée par les tickets FRONT et SHARED
Le client d'API généré est arrivé avec SHARED-03, et la couche de **cache** posée au-dessus avec
FRONT-04 : chacun a désormais sa page. Les tickets à venir — FRONT-05 et suivants — rempliront les
deux sujets restants à leur livraison.
:::
