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

| Ticket                                                          | Livrable                                               |
| --------------------------------------------------------------- | ------------------------------------------------------ |
| [SETUP-05](./setup.md#écarts-assumés-avec-le-ticket-setup-05)   | Les gabarits d'environnement et l'allocation des ports |
| [INFRA-01](./infra.md#écarts-assumés-avec-le-ticket-infra-01)   | PostgreSQL et pgAdmin                                  |
| [INFRA-02](./infra.md#écarts-assumés-avec-le-ticket-infra-02)   | Redis et RedisInsight                                  |
| [INFRA-03](./infra.md#écarts-assumés-avec-le-ticket-infra-03)   | MinIO et l'amorçage du bucket                          |
| [INFRA-04](./infra.md#écarts-assumés-avec-le-ticket-infra-04)   | L'image Docker du service d'API                        |
| [INFRA-05a](./infra.md#écarts-assumés-avec-le-ticket-infra-05a) | L'image Docker des trois frontends                     |
| [INFRA-05b](./infra.md#écarts-assumés-avec-le-ticket-infra-05b) | La pile compose complète                               |
| [INFRA-06](./infra.md#écarts-assumés-avec-le-ticket-infra-06)   | Le Makefile de la racine                               |
| [INFRA-07](./infra.md#écarts-assumés-avec-le-ticket-infra-07)   | Mailpit, le SMTP de développement                      |
| [DOC-01](./doc.md#écarts-assumés-avec-le-ticket-doc-01)         | Le site de documentation Docusaurus                    |
| [DOC-02b](./doc.md#écarts-assumés-avec-le-ticket-doc-02b)       | Le registre des ADR                                    |

Les familles BACK, SHARED et FRONT — et les tickets SETUP restants — rejoindront ce registre avec
la migration des README restants.
