---
title: Écarts assumés — tickets SETUP
description: Les écarts entre les tickets SETUP et ce qui a été livré, avec leur raison.
---

# Écarts assumés — tickets SETUP

Chaque ticket SETUP consigne ici les écarts entre son énoncé et ce qui a été livré — le principe de
ce registre est expliqué sur [la page d'index](./index.md).

## Écarts assumés avec le ticket SETUP-05

| Écart                                                             | Raison                                                                                                                                                                                                                                                                       |
| ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Deux parcours au lieu de la seule séquence `make up`              | Au moment de SETUP-05, `make up` n'existait pas — le Makefile racine relevait d'INFRA-06. **INFRA-06 a levé l'écart** : `make up` existe. Les deux parcours restent documentés, l'un faisant tourner l'API sur le poste, l'autre toute la pile en conteneurs.                |
| Docker et `make` signalés comme pas encore nécessaires            | Le ticket les liste en prérequis. Les présenter sans réserve ferait installer Docker Desktop à qui veut seulement lancer un `uvicorn`.                                                                                                                                       |
| `env_prefix` par sous-modèle plutôt que `env_nested_delimiter`    | BACK-03 prévoit `DB__`, `JWT__`… mais `POSTGRES_*`, `MINIO_ROOT_*` et `PGADMIN_DEFAULT_*` sont imposés par les images Docker. Le préfixe simple donne les mêmes sous-modèles sans couche de traduction.                                                                      |
| `ACCESS_TOKEN_EXPIRE_MINUTES` → `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | Pour que le bloc JWT tienne dans un unique `env_prefix`. Seul renommage appliqué à la liste du ticket.                                                                                                                                                                       |
| `DATABASE_URL` et `REDIS_URL` documentées mais commentées         | Valeurs dérivées : BACK-03 recompose l'URL à partir des composants. Les activer créerait une seconde source de vérité, qui divergerait au premier changement de mot de passe.                                                                                                |
| `.env.local.example` côté frontend plutôt que `.env.example`      | `.env` est ignoré par le `.gitignore` : `.env.local` est le seul fichier que Next.js puisse charger, et la règle « retirer `.example` » reste vraie partout.                                                                                                                 |
| Port de pgAdmin fixé à 5050                                       | Ni SETUP-05 ni INFRA-01 ne le fixent. Un tableau qui doit garantir l'absence de collision ne peut pas laisser de case vide : le choix se fait ici, INFRA-01 en hérite.                                                                                                       |
| Deux services de plus que la liste du ticket                      | Le tableau ne vaut comme garantie d'absence de collision que s'il est exhaustif. DOC-01 réserve déjà 3004 et INFRA-02 prévoit RedisInsight — les omettre rendrait la garantie fausse.                                                                                        |
| Variables ajoutées hors de la liste du ticket                     | `CORS_ORIGINS` (BACK-11), `JWT_REFRESH_TOKEN_EXPIRE_DAYS` (BACK-10), `POSTGRES_TEST_DB` (INFRA-01), `REDIS_CACHE_DB` et `REDIS_BROKER_DB` (INFRA-02), `S3_REGION` (boto3), `API_INTERNAL_URL` (INFRA-05), `COMPOSE_PROJECT_NAME` et les `*_HOST_PORT` (INFRA-01 à INFRA-05). |
| Identifiants nommés par leur variable, jamais recopiés            | INFRA-03 demande de documenter ceux de la console MinIO. Les nommer renvoie à `.env.example`, seule source de vérité.                                                                                                                                                        |

:::note Registre en cours de migration
Les tableaux des tickets SETUP-04, SETUP-06 et SETUP-07 vivent encore dans le README de la racine
et rejoindront cette page avec la migration de sa section « Conventions ».
:::
