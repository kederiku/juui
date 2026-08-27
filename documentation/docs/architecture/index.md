---
title: Architecture
description: Les règles d'architecture du service — le vocabulaire, comment écrire un module conforme, ce qui est interdit, et la carte de contexte des modules.
---

# Architecture

Cette section est **normative** : elle dit ce qu'il faut faire pour écrire du code conforme, et
ce qui se passe quand on ne le fait pas. Elle s'adresse autant à quelqu'un qui arrive sur le
projet qu'à un agent chargé d'y produire du code — ni l'un ni l'autre ne devrait avoir à deviner
les conventions.

Elle ne décrit pas l'existant. Pour savoir ce qui est posé aujourd'hui, où, et par quel ticket,
la section [Backend](../backend/index.md) est là pour ça.

Les cinq règles ci-dessous emploient le vocabulaire du projet — module, couche, port, entité,
cas d'usage. **Chacun est défini au [glossaire](./glossaire.md)**, qui est la première page de
la section pour cette raison.

## La doctrine en cinq règles

Tout le reste de cette section découle de ces cinq phrases.

1. **L'architecture est hexagonale à l'intérieur de modules métier.** C'est le module qui porte
   la frontière ; la couche ne décrit que le sens des dépendances.
2. **Les dépendances pointent vers l'intérieur.** L'infrastructure dépend du domaine, jamais
   l'inverse. C'est la seule direction que l'architecture interdit.
3. **Un module n'importe jamais l'intérieur d'un autre.** Les échanges passent par la surface
   que le module cible a choisi d'exposer.
4. **La même notion se représente trois fois** — schéma d'API, entité, modèle de persistance —
   et le passage de l'une à l'autre s'écrit à la main.
5. **Un cas d'usage reçoit un port, jamais une session.** C'est ce qui le rend appelable depuis
   une route, un test ou une tâche de fond sans changer de signature.

Ces règles ne reposent pas sur la discipline : **cinq contrats d'architecture** les font échouer
en intégration continue.

## Les pages de cette section

| Page                                                                | Ce qu'on y trouve                                                                                                                                             |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [Le vocabulaire du projet](./glossaire.md)                          | Chaque terme d'architecture et de métier, sa définition, le fichier qui l'incarne, et les quatre confusions qui coûtent cher.                                 |
| [Comment écrire un module conforme](./ecrire-un-module-conforme.md) | Le guide : sens des dépendances, cycle de vie d'une requête, squelette complet d'un module, règle des 3 modèles, ports, unité de travail, doublures, erreurs. |
| [Ce qui est interdit](./anti-patterns.md)                           | La liste de contrôle des anti-patterns, ce qui les arrête, et comment lire un contrat d'architecture qui casse.                                               |
| [Carte de contexte](./carte-de-contexte.md)                         | Les cinq modules, ce que chacun expose et à qui, les flux réels, les flux prévus. Explicitement provisoire.                                                   |

:::tip Par où commencer
Quelqu'un qui arrive sur le projet gagne à lire le [vocabulaire](./glossaire.md) d'abord, puis la
[carte de contexte](./carte-de-contexte.md) pour situer les modules, et enfin le
[guide](./ecrire-un-module-conforme.md) au moment d'écrire sa première ligne.

Quelqu'un qui vient corriger une violation de contrat va directement à
[Ce qui est interdit](./anti-patterns.md#quand-un-contrat-casse-lire-le-message).
:::

## Où sont les autres règles

Le dépôt tient quatre registres distincts, et ils ne disent pas la même chose. Savoir lequel
ouvrir fait gagner du temps.

| Registre                             | Ce qu'il porte                                                                      | Quand l'ouvrir                                     |
| ------------------------------------ | ----------------------------------------------------------------------------------- | -------------------------------------------------- |
| **Architecture** — cette section     | La règle : ce qu'il faut faire, et ce qui se passe sinon.                           | Avant d'écrire du code.                            |
| [Backend](../backend/index.md)       | L'état des lieux : ce qui est posé aujourd'hui, dans quel fichier, par quel ticket. | Pour trouver où vit quelque chose.                 |
| [Décisions (ADR)](../adr/index.md)   | Le motif d'une décision structurante, et les alternatives écartées.                 | Quand on est tenté de faire autrement.             |
| [Écarts assumés](../ecarts/index.md) | Les entorses délibérées, ticket par ticket, avec leur raison.                       | Quand le code ne fait pas ce que la règle annonce. |

Les contrats qui rendent ces règles mécaniques — leur déclaration, les violations jouées pour
prouver qu'ils mordent — sont décrits sur
[Qualité et typage](../backend/qualite-et-typage.md#import-linter).
