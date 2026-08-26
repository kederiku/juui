---
title: Backend
description: "Le service d'API FastAPI : ce qu'il est, où il en est, et la carte des pages de cette section."
---

# Backend

Le service d'API vit dans `backend/api/`. Il est écrit en **Python** avec **FastAPI**, suit une
architecture **hexagonale à l'intérieur de modules métier**, et il est outillé par `uv`, Ruff, Mypy
et Pytest.

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
| [Migrations](./migrations.md)                               | Alembic piloté par Settings, un seul migrateur à la fois.                  |
| [Cache](./cache.md)                                         | Le port de cache Redis et sa dégradation gracieuse.                        |
| [Stockage objet](./stockage-objet.md)                       | Le port S3/MinIO et les URLs pré-signées.                                  |
| [Tâches de fond](./taches-de-fond.md)                       | TaskIQ : le broker, le worker, la politique de reprise.                    |
| [Vérification d'adresse (OTP)](./verification-email-otp.md) | Le code à six chiffres : haché, poivré, à usage unique, borné.             |
| [Surface HTTP](./surface-http.md)                           | Le routeur `/api/v1`, les sondes, le contrat OpenAPI.                      |
| [Erreurs](./erreurs.md)                                     | La hiérarchie `DomainError`, le format d'erreur unique, le 404-jamais-403. |
| [Journalisation](./journalisation.md)                       | Les deux formats, l'identifiant de requête, le masquage, le CORS.          |
| [Dépendances](./dependances.md)                             | Les dépendances déclarées, `--frozen`/`--locked`, la version d'`uv`.       |
| [Qualité et typage](./qualite-et-typage.md)                 | Ruff, Mypy strict et les contrats Import Linter.                           |

## Où en est le service

La structure modulaire et hexagonale est posée (BACK-04) et ses règles sont
désormais tenues par [Import Linter](./qualite-et-typage.md#import-linter) (BACK-04b), le socle de
persistance est en place (BACK-05), l'[unité de travail](./unite-de-travail.md)
avec son dépôt générique le coiffe (BACK-06a) et le schéma est sous contrôle de
version par les [migrations](./migrations.md) (BACK-07), six des sept ports
techniques du noyau partagé sont livrés — [cache](./cache.md) (BACK-14),
[stockage objet](./stockage-objet.md) (BACK-13), transport e-mail (BACK-22), unité
de travail et dépôt générique (BACK-06a), contrôle de fuite de mot de passe
(BACK-06c, son adaptateur restant à BACK-10b), `TokenService` restant à
BACK-10a —, leurs [doublures en mémoire](./doublures-en-memoire.md) et la suite de
conformité qui les tient au contrat (BACK-06c), la
[surface HTTP](./surface-http.md) versionnée et ses sondes sont en place (BACK-08)
et toute [erreur](./erreurs.md) y sort désormais au format unique, codes namespacés
et 404-jamais-403 compris (BACK-09,
[ADR-0014](../adr/0014-traduction-des-erreurs-a-la-bordure.md)),
les [tâches de fond](./taches-de-fond.md) ont leur broker, leur worker et leur
politique de reprise (BACK-15) — et leur premier consommateur métier, la
[vérification d'adresse par code OTP](./verification-email-otp.md), dont le code
est haché, poivré et engendré dans le worker (BACK-17,
[ADR-0020](../adr/0020-otp-hache-et-echec-ferme.md)) —, le service est
[observable](./journalisation.md) — journaux structurés, identifiant de requête
propagé de bout en bout, contexte de tenance automatique, secrets masqués — et
joignable depuis les trois frontends (BACK-11,
[ADR-0018](../adr/0018-journalisation-bibliotheque-standard.md)),
le filtrage multi-tenant est mécanique et prouvé
par les premiers tests du service — la suite `tenant_isolation`, `make test` —
(BACK-06b, [ADR-0013](../adr/0013-filtre-de-tenance-dans-le-depot.md)), Ruff et
Mypy sont configurés (BACK-02). Ce qui
n'est pas encore là est listé dans le
[README du service](https://github.com/kederiku/juui/blob/main/backend/api/README.md#ce-qui-nest-pas-encore-là).
