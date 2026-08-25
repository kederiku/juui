---
title: ADR-0009 — Une unité de travail par module, jamais globale
description: Chaque module métier porte sa propre unité de travail, qui n'expose que ses dépôts ; l'atomicité inter-modules est une frontière visible, pas un service partagé.
---

# ADR-0009 — Une unité de travail par module, jamais globale

| Statut      | Date       | Tickets                      |
| ----------- | ---------- | ---------------------------- |
| **Accepté** | 2026-08-25 | BACK-06a, BACK-06b, BACK-06c |

## Contexte

Décision rendue par BACK-06a, qui livre le pattern Unit of Work — annoncée dès BACK-04, qui
avait réservé `modules/identity/unit_of_work.py` à la racine du module, hors de toute couche.

Le pattern répond à une question technique : comment un cas d'usage lit-il et écrit-il
atomiquement sans jamais voir une session SQLAlchemy ? Mais sa mise en place en pose une
seconde, structurante celle-là : **quelle est la portée d'une transaction ?** Une unité de
travail unique pour tout le service exposerait tous les dépôts de tous les modules à chaque cas
d'usage — et permettrait, sans un import suspect ni une revue alertée, d'écrire `identity` et
`organization` dans la même transaction. Or l'[ADR-0003](./0003-monolithe-modulaire.md) fait du
module la frontière du système : les échanges entre modules passent par leurs surfaces
publiques, jamais par leurs entrailles.

## Décision

**Chaque module porte sa propre unité de travail, qui n'expose que les dépôts de ce module. Il
n'existe pas d'unité de travail globale.**

Concrètement, sur le module pilote :

- le **port partagé** `AbstractUnitOfWork` (`shared/domain/ports/unit_of_work.py`) fixe le
  contrat commun — bloc `async with`, commit explicite, rollback automatique à la sortie codé
  dans le port lui-même — et ne déclare **aucun dépôt** ;
- chaque module dérive son **port de module** dans son domaine (`IdentityUnitOfWork`, qui
  expose `accounts`) : c'est lui que les cas d'usage reçoivent ;
- l'**implémentation** vit à la racine du module (`SqlAlchemyIdentityUnitOfWork` dans
  `identity/unit_of_work.py`) — le point d'assemblage fixé par BACK-04, ni domaine ni tout à
  fait infrastructure — avec la dépendance FastAPI `get_identity_uow` qui en livre une par
  requête.

Ce qu'on ne peut pas placer dans une seule transaction devient ainsi une frontière **visible** :
un cas d'usage qui aurait besoin d'écrire deux modules d'un seul tenant ne trouve simplement pas
d'outil pour le faire, et doit poser la question — événement de domaine, surface publique du
module cible, ou déplacement de la frontière — au lieu d'enterrer un couplage que le premier
incident révélera.

## Alternatives écartées

### L'unité de travail globale

Une seule classe exposant tous les dépôts du service. Confortable au premier ticket, elle
transforme chaque transaction en couplage potentiel entre modules — invisible en revue, puisque
aucun import inter-modules n'apparaît : c'est l'unité qui importe tout, pour tout le monde. Elle
ferait aussi mentir l'[ADR-0003](./0003-monolithe-modulaire.md) : l'indépendance des modules
tenue par Import Linter serait contournable par le point d'assemblage lui-même.

### La session injectée dans les cas d'usage

L'alternative « sans pattern » : chaque cas d'usage reçoit une `AsyncSession` et décide de son
commit. C'est l'anti-patron nommé par le guide DDD et proscrit depuis BACK-04 — le métier
devient indissociable de SQLAlchemy, intestable sans base, et la discipline transactionnelle
repose sur chaque développeur à chaque écriture.

### Une transaction par requête HTTP, ouverte par la dépendance

Ouvrir la session et la transaction dans `get_identity_uow` (avec `yield`), les refermer à la
fin de la requête. La transaction épouserait alors la requête HTTP et non le cas d'usage : une
tâche de fond ou une commande en ligne n'aurait plus de contrat, et un cas d'usage ne pourrait
plus délimiter deux transactions successives. La dépendance livre donc une unité **fermée**, et
c'est le bloc `async with` du cas d'usage qui délimite la transaction — où qu'il s'exécute.

## Conséquences

**Ce que cela donne.** L'atomicité a un propriétaire clair : le cas d'usage, dans son module.
Les frontières transactionnelles coïncident avec les frontières du système, et une écriture
inter-modules est impossible par construction, pas par convention. Le rollback automatique est
du code partagé (`__aexit__` concret du port), hérité par l'adaptateur SQLAlchemy comme par les
doublures de BACK-06c — une fake dont le rollback ne ferait rien ne peut pas naître conforme.
Chaque module nouveau suit un chemin balisé : un port dans son domaine, une implémentation d'une
propriété par dépôt à sa racine, une dépendance nommée.

**Ce que cela coûte.** Un dédoublement assumé par module — le port dans le domaine,
l'implémentation à la racine — exigé par le contrat `module-layers` : la racine importe
l'infrastructure, donc les cas d'usage ne peuvent typer que le port. Les besoins réellement
transverses (écrire un événement d'audit avec chaque écriture métier, par exemple) devront
passer par des événements de domaine ou par la surface publique du module cible, jamais par une
transaction commune — c'est plus de cérémonie, et c'est le prix de la frontière. Enfin, la
cohérence inter-modules est **à terme** (éventuelle), pas transactionnelle : un incident entre
deux écritures liées mais séparées laisse un état intermédiaire, que la conception des cas
d'usage doit accepter d'avance.

## Références

- `backend/api/src/app/shared/domain/ports/unit_of_work.py` — le port et son `__aexit__`
  concret, le rollback automatique rendu structurel.
- `backend/api/src/app/modules/identity/domain/ports.py` — `IdentityUnitOfWork`, le port de
  module que les cas d'usage typent.
- `backend/api/src/app/modules/identity/unit_of_work.py` — l'implémentation à la racine du
  module, `get_identity_uow` et l'arbitrage de nommage.
- `backend/api/src/app/shared/infrastructure/db/unit_of_work.py` — l'adaptateur SQLAlchemy :
  une session neuve par bloc, fermée définitivement à la sortie.
