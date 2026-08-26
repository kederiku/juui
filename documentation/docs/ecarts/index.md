---
title: Écarts assumés
description: Registre des écarts entre ce que demandaient les tickets et ce qui a été livré — la règle du registre et la table des tickets.
---

# Écarts assumés

Un **écart assumé** consigne un ticket livré autrement que sa lettre — délibérément, et avec la
raison de l'arbitrage. C'est le proche parent des [ADR](../adr/index.md) : un écart est une
décision en miniature, à l'échelle d'un ticket. Le registre existe pour la même raison — qu'un
arbitrage déjà rendu ne soit pas rejugé par accident, faute de trace de son motif.

## Comment lire ce registre

**Une page par famille de tickets.** Chaque page porte un tableau « Écart | Raison » par ticket,
repris tel quel du ticket qui l'a livré. Les tickets sont cités par leur code ; le détail des
cartes vit sur le tableau de pilotage du projet, qui n'est pas public.

**Un écart levé ne s'efface pas.** Quand un ticket ultérieur lève un écart, celui-ci reste
consigné, complété de la mention « X a levé l'écart ».

**La règle.** Tout ticket livré avec un écart ajoute son tableau à la page de sa famille, dans la
même PR. Un ticket sans écart n'apparaît pas.

## Le registre

| Ticket                                                           | Livrable                                                     |
| ---------------------------------------------------------------- | ------------------------------------------------------------ |
| [SETUP-04](./setup.md#écarts-assumés-avec-le-ticket-setup-04)    | Les hooks de pre-commit et commitlint                        |
| [SETUP-05](./setup.md#écarts-assumés-avec-le-ticket-setup-05)    | Les gabarits d'environnement et l'allocation des ports       |
| [SETUP-06](./setup.md#écarts-assumés-avec-le-ticket-setup-06)    | Le lint type-aware                                           |
| [SETUP-07](./setup.md#écarts-assumés-avec-le-ticket-setup-07)    | Les règles d'accessibilité du lint                           |
| [INFRA-01](./infra.md#écarts-assumés-avec-le-ticket-infra-01)    | PostgreSQL et pgAdmin                                        |
| [INFRA-02](./infra.md#écarts-assumés-avec-le-ticket-infra-02)    | Redis et RedisInsight                                        |
| [INFRA-03](./infra.md#écarts-assumés-avec-le-ticket-infra-03)    | MinIO et l'amorçage du bucket                                |
| [INFRA-04](./infra.md#écarts-assumés-avec-le-ticket-infra-04)    | L'image Docker du service d'API                              |
| [INFRA-05a](./infra.md#écarts-assumés-avec-le-ticket-infra-05a)  | L'image Docker des trois frontends                           |
| [INFRA-05b](./infra.md#écarts-assumés-avec-le-ticket-infra-05b)  | La pile compose complète                                     |
| [INFRA-06](./infra.md#écarts-assumés-avec-le-ticket-infra-06)    | Le Makefile de la racine                                     |
| [INFRA-07](./infra.md#écarts-assumés-avec-le-ticket-infra-07)    | Mailpit, le SMTP de développement                            |
| [INFRA-09](./infra.md#écarts-assumés-avec-le-ticket-infra-09)    | Les extensions PostgreSQL et l'unicité d'e-mail              |
| [BACK-02](./back.md#écarts-assumés-avec-le-ticket-back-02)       | L'outillage qualité Python (Ruff, Mypy)                      |
| [BACK-03](./back.md#écarts-assumés-avec-le-ticket-back-03)       | La configuration validée au démarrage                        |
| [BACK-04](./back.md#écarts-assumés-avec-le-ticket-back-04)       | Le socle hexagonal et le module pilote                       |
| [BACK-04b](./back.md#écarts-assumés-avec-le-ticket-back-04b)     | Les contrats d'architecture Import Linter                    |
| [BACK-05](./back.md#écarts-assumés-avec-le-ticket-back-05)       | Le socle SQLAlchemy et le pool                               |
| [BACK-06a](./back.md#écarts-assumés-avec-le-ticket-back-06a)     | L'unité de travail et le dépôt générique                     |
| [BACK-06b](./back.md#écarts-assumés-avec-le-ticket-back-06b)     | Le filtrage multi-tenant et les tests d'isolation            |
| [BACK-07](./back.md#écarts-assumés-avec-le-ticket-back-07)       | Alembic et la première migration                             |
| [BACK-08](./back.md#écarts-assumés-avec-le-ticket-back-08)       | La sonde de santé et les métadonnées OpenAPI                 |
| [BACK-09](./back.md#écarts-assumés-avec-le-ticket-back-09)       | La traduction des erreurs métier en HTTP                     |
| [BACK-11](./back.md#écarts-assumés-avec-le-ticket-back-11)       | Le CORS, les journaux structurés et l'identifiant de requête |
| [BACK-13](./back.md#écarts-assumés-avec-le-ticket-back-13)       | Le port de stockage objet                                    |
| [BACK-14](./back.md#écarts-assumés-avec-le-ticket-back-14)       | Le port de cache Redis                                       |
| [BACK-15](./back.md#écarts-assumés-avec-le-ticket-back-15)       | Le broker TaskIQ et la tâche de démonstration                |
| [BACK-16](./back.md#écarts-assumés-avec-le-ticket-back-16)       | Le socle du module organization                              |
| [BACK-17](./back.md#écarts-assumés-avec-le-ticket-back-17)       | La vérification d'adresse par code OTP                       |
| [BACK-19](./back.md#écarts-assumés-avec-le-ticket-back-19)       | Le socle du module medical_records                           |
| [BACK-24](./back.md#écarts-assumés-avec-le-ticket-back-24)       | La convention de pagination des listes                       |
| [SHARED-01](./shared.md#écarts-assumés-avec-le-ticket-shared-01) | La bibliothèque @repo/ui                                     |
| [SHARED-02](./shared.md#écarts-assumés-avec-le-ticket-shared-02) | Les configurations partagées                                 |
| [SHARED-03](./shared.md#écarts-assumés-avec-le-ticket-shared-03) | Le client d'API généré par Orval                             |
| [FRONT-01](./front.md#écarts-assumés-avec-le-ticket-front-01)    | L'application des professionnels                             |
| [FRONT-02](./front.md#écarts-assumés-avec-le-ticket-front-02)    | L'application des particuliers                               |
| [FRONT-03](./front.md#écarts-assumés-avec-le-ticket-front-03)    | Le back-office d'administration                              |
| [DOC-01](./doc.md#écarts-assumés-avec-le-ticket-doc-01)          | Le site de documentation Docusaurus                          |
| [DOC-02b](./doc.md#écarts-assumés-avec-le-ticket-doc-02b)        | Le registre des ADR                                          |

Le registre est complet : chaque ticket livré avec un écart y a son tableau, et les prochains
ajouteront le leur dans la PR qui les livre.
