---
title: Backend
description: "Le service d'API FastAPI : ce qu'il est, où il en est, et la carte des pages de cette section."
---

# Backend

Le service d'API vit dans `backend/api/`. Il est écrit en **Python** avec **FastAPI**, suit une
architecture **hexagonale à l'intérieur de modules métier**, et il est outillé par `uv`, Ruff, Mypy
et Pytest.

Cette section décrit **ce qui est posé aujourd'hui**, où, et par quel ticket. Les **règles** à
suivre pour écrire du code conforme vivent à part, dans la section
[Architecture](../architecture/index.md) — dont le
[vocabulaire](../architecture/glossaire.md) définit les termes employés dans toutes les pages
ci-dessous.

Il est volontairement **absent des workspaces pnpm** : c'est un projet Python, piloté par sa propre
chaîne d'outils, et le dépôt assume d'en avoir deux. Son
[README](https://github.com/kederiku/juui/blob/main/backend/api/README.md) garde l'entrée en
matière — prérequis, installation, démarrage — et cette section porte le détail.

## Les pages de cette section

| Page                                                        | Ce qu'on y trouve                                                          |
| ----------------------------------------------------------- | -------------------------------------------------------------------------- |
| [Structure du service](./structure.md)                      | L'arborescence de `backend/api` et ce que fait `main.py` au démarrage.     |
| [Architecture du service](./architecture-du-service.md)     | Les trois espaces, les trois couches d'un module, la règle des 3 modèles.  |
| [Configuration](./configuration.md)                         | Les Settings Pydantic et la validation au démarrage.                       |
| [Persistance](./persistance.md)                             | Le moteur SQLAlchemy, la convention de nommage, les mixins, la tenance.    |
| [Unité de travail](./unite-de-travail.md)                   | Le port UnitOfWork, le dépôt générique, l'injection par requête.           |
| [Doublures en mémoire](./doublures-en-memoire.md)           | Les fakes du projet et la suite de conformité qui les tient au contrat.    |
| [Tests](./tests.md)                                         | Lancer la suite, lire ses `skip`, et écrire les trois formes de test.      |
| [Migrations](./migrations.md)                               | Alembic piloté par Settings, un seul migrateur à la fois.                  |
| [Cache](./cache.md)                                         | Le port de cache Redis et sa dégradation gracieuse.                        |
| [Stockage objet](./stockage-objet.md)                       | Le port S3/MinIO et les URLs pré-signées.                                  |
| [Tâches de fond](./taches-de-fond.md)                       | TaskIQ : le broker, le worker, la politique de reprise.                    |
| [Vérification d'adresse (OTP)](./verification-email-otp.md) | Le code à six chiffres : haché, poivré, à usage unique, borné.             |
| [Notifications](./notifications.md)                         | Les préférences par événement, le catalogue, la résolution des canaux.     |
| [Jetons d'authentification](./jetons.md)                    | Les neuf claims, l'audience par application, l'appartenance vérifiée.      |
| [Authentification des routes](./authentification.md)        | Les quatre dépendances qui protègent une route, et ce que le client voit.  |
| [Mots de passe](./mots-de-passe.md)                         | La politique 14–128 sans composition, argon2id, la k-anonymity HIBP.       |
| [Surface HTTP](./surface-http.md)                           | Le routeur `/api/v1`, les sondes, le contrat OpenAPI.                      |
| [Erreurs](./erreurs.md)                                     | La hiérarchie `DomainError`, le format d'erreur unique, le 404-jamais-403. |
| [Journalisation](./journalisation.md)                       | Les deux formats, l'identifiant de requête, le masquage, le CORS.          |
| [Dépendances](./dependances.md)                             | Les dépendances déclarées, `--frozen`/`--locked`, la version d'`uv`.       |
| [Qualité et typage](./qualite-et-typage.md)                 | Ruff, Mypy strict et les contrats Import Linter.                           |

## Où en est le service

Le socle est en place. Plutôt qu'une phrase qui périmerait, voici ce qui existe, par famille.

| Ce qui est posé                                                                                        | Où le lire                                                                                   |
| ------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| La structure modulaire et hexagonale, et ses règles rendues **mécaniques**                             | [Structure](./structure.md), [Qualité et typage](./qualite-et-typage.md#import-linter)       |
| Le socle de persistance, l'unité de travail, le dépôt générique et le filtrage multi-tenant **prouvé** | [Persistance](./persistance.md), [Unité de travail](./unite-de-travail.md)                   |
| Le schéma sous contrôle de version                                                                     | [Migrations](./migrations.md)                                                                |
| Les **huit** ports techniques du noyau partagé, et leurs doublures tenues par une suite de conformité  | [Doublures en mémoire](./doublures-en-memoire.md)                                            |
| La surface HTTP versionnée, ses sondes, la pagination, et le format d'erreur unique                    | [Surface HTTP](./surface-http.md), [Erreurs](./erreurs.md)                                   |
| Les tâches de fond, et leur premier consommateur métier                                                | [Tâches de fond](./taches-de-fond.md), [Vérification d'adresse](./verification-email-otp.md) |
| Les jetons, les mots de passe et le contrôle de fuite                                                  | [Jetons](./jetons.md), [Mots de passe](./mots-de-passe.md)                                   |
| Le service observable — journaux structurés, identifiant de requête, secrets masqués                   | [Journalisation](./journalisation.md)                                                        |
| Une suite pytest qui tourne sur le poste, mais que la CI ne rejoue pas encore                          | [Tests](./tests.md)                                                                          |
| Cinq modules métier, dont `identity` complet                                                           | [Carte de contexte](../architecture/carte-de-contexte.md)                                    |

**Ce tableau est un résumé de lecture, et il périmera.** Ce qui existe vraiment se lit sur
l'arbre de [Structure du service](./structure.md) et sur la
[carte de contexte](../architecture/carte-de-contexte.md), qui font foi. Ce qui n'est pas encore
là est listé dans le
[README du service](https://github.com/kederiku/juui/blob/main/backend/api/README.md#ce-qui-nest-pas-encore-là).
