---
title: Makefile et scripts de la racine
description: Les scripts pnpm de la racine et les cibles make — démarrage, base de données, qualité — make help faisant foi.
---

# Makefile et scripts de la racine

La racine du dépôt expose deux interfaces de commande — les scripts pnpm côté JavaScript, et les
cibles `make` qui réunissent les chaînes Python et TypeScript derrière une façade unique. Cette page
les recense toutes deux ; sur le poste, `make help` fait foi.

## Scripts racine

| Commande            | Effet                                                         |
| ------------------- | ------------------------------------------------------------- |
| `pnpm prepare`      | Installe les hooks Git. Lancé seul par `pnpm install`.        |
| `pnpm dev`          | Démarre en parallèle les serveurs de développement.           |
| `pnpm build`        | Construit chaque workspace, dans l'ordre de ses dépendances.  |
| `pnpm lint`         | Analyse statique ESLint sur tout le dépôt.                    |
| `pnpm lint:fix`     | Idem, en appliquant les corrections automatiques.             |
| `pnpm typecheck`    | Vérification des types TypeScript.                            |
| `pnpm test`         | Suites de tests des workspaces.                               |
| `pnpm generate:api` | Régénère le client d'API depuis l'`openapi.json` (SHARED-03). |
| `pnpm format`       | Reformate le dépôt avec Prettier.                             |
| `pnpm format:check` | Vérifie le formatage sans rien réécrire (CI).                 |

`prepare` est un script de **cycle de vie** : personne ne le lance à la main,
pnpm s'en charge après chaque installation.

`dev`, `build`, `typecheck` et `test` délèguent aux workspaces qui définissent le
script de même nom ; ceux qui ne le définissent pas sont simplement ignorés.

`lint` et `format` fonctionnent autrement : ils parcourent le dépôt en une seule
passe depuis la racine. Depuis ESLint 10, la recherche de configuration part du
répertoire du **fichier analysé** et remonte l'arborescence — un `eslint .` lancé
à la racine applique donc déjà à chaque application sa propre configuration, et
celle de la racine au reste. Prettier procède de même. Déléguer aux workspaces
serait un double parcours, et laisserait de côté les fichiers de la racine, que
`pnpm -r` n'atteint pas.

`lint` s'appuie sur les types depuis SETUP-06, ce qui lui coûte quelques
secondes : le chiffre avant/après est dans [Configurations
partagées](../frontend/configurations-partagees.md).

:::note Portée des scripts pnpm
Ces scripts ne couvrent que les workspaces pnpm ; le backend a les
siens, décrits dans la [section Backend](../backend/index.md). Les
cibles `make` de la racine réunissent les deux chaînes derrière une interface
unique — voir [Cibles `make` de la racine](#cibles-make-de-la-racine).
:::

## Cibles `make` de la racine

Le `Makefile` de la racine (INFRA-06) complète le tableau de la
section [La pile complète, avec Docker](../getting-started/demarrage.md#la-pile-complète-avec-docker) par les
cibles de base de données et de qualité :

| Cible                         | Effet                                                         |
| ----------------------------- | ------------------------------------------------------------- |
| `make db-migrate m="message"` | Génère une révision Alembic autogénérée — à relire.           |
| `make db-upgrade`             | Applique les migrations jusqu'à `head`.                       |
| `make db-downgrade`           | Annule la dernière migration appliquée.                       |
| `make db-reset`               | Détruit le volume PostgreSQL, recrée la base, migre et seede. |
| `make seed`                   | Injecte le jeu de données de démonstration (INFRA-08).        |
| `make lint`                   | Ruff et contrats d'architecture, puis ESLint.                 |
| `make format`                 | Ruff côté Python, puis Prettier sur tout le dépôt.            |
| `make typecheck`              | mypy en mode strict, puis TypeScript workspace par workspace. |
| `make test`                   | Enchaîne `test-back` et `test-front`.                         |
| `make test-back`              | La suite pytest du backend (PostgreSQL démarré).              |
| `make test-front`             | Les suites des workspaces pnpm qui en déclarent une.          |
| `make generate-api`           | Exporte l'OpenAPI puis régénère le client (SHARED-03).        |
| `make generate-api-check`     | Échoue si le client généré ne correspond plus au contrat.     |
| `make verify-api-client`      | Appelle l'API avec le client généré, pile démarrée.           |

**Cette liste est un résumé de lecture, et elle périmera.** `make help`, qui
s'auto-documente en extrayant les commentaires `##` du fichier, fait foi.

Trois règles gouvernent ces cibles, et elles sont écrites en tête du `Makefile` :

- **Les cibles `db-*` tournent sur le poste**, jamais dans un conteneur, par
  délégation à `backend/api/Makefile` : la génération
  d'une révision déclenche les hooks Ruff d'Alembic, absents des images
  servies. Elles supposent `uv`, le port PostgreSQL publié et
  `backend/api/.env`.
- **`make db-reset` ne détruit que le volume de PostgreSQL.** Les fichiers de
  MinIO, le cache Redis et la configuration de pgAdmin survivent ; la cible
  demande confirmation, `force=1` la saute.
- **Le `Makefile` ne lit pas le `.env`.** C'est `docker compose` qui le lit, et
  lui seul : l'importer dans `make` exporterait `POSTGRES_HOST=postgres` vers
  les cibles `db-*` du poste — et les secrets vers tout sous-processus.

`make test-back` délègue à la suite pytest du backend, et `make test` l'enchaîne
avec `make test-front` — un vrai `pnpm test`, qui ignore en silence les
workspaces sans script `test`. Depuis FRONT-04, `packages/api-client` en déclare
un — la preuve hors ligne de la portée des clés de cache — et c'est le seul
jusqu'à QA-02. **Seule `make seed`
reste déclarée sans rien exécuter** : elle nomme INFRA-08 et sort en succès.

Les écarts assumés avec le ticket INFRA-06 sont consignés au
[registre des écarts](../ecarts/infra.md#écarts-assumés-avec-le-ticket-infra-06).
