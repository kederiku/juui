---
title: Décisions d'architecture (ADR)
description: Registre des décisions structurantes — gabarit commun, vocabulaire des statuts et règle de remplacement.
---

# Décisions d'architecture (ADR)

Un **ADR** — _Architecture Decision Record_ — consigne une décision structurante : son contexte, ce
qui a été décidé, les alternatives écartées, et les conséquences acceptées.

L'objet n'est pas de documenter pour documenter. C'est d'éviter qu'une décision déjà prise soit
rediscutée par accident à chaque ticket, faute de trace de son motif — et de rendre visible ce
qu'elle coûte.

## Comment lire ce registre

**Un gabarit commun.** Chaque ADR ouvre sur un tableau — statut, date de consignation, tickets qui
appliquent la décision — puis déroule les mêmes sections : _Contexte_, _Décision_, _Alternatives
écartées_ (une sous-section par alternative, avec un motif honnête), _Conséquences_ (ce que cela
donne, puis ce que cela coûte — jamais vide), _Références_ (les fichiers du dépôt qui portent la
décision). Les tickets sont cités par leur code ; le détail des cartes vit sur le tableau de
pilotage du projet, qui n'est pas public.

**Trois statuts.** **Accepté** : la décision s'applique. **Remplacé par ADR-XXXX** : une nouvelle
décision a pris sa place. **Déprécié** : la décision ne s'applique plus, sans remplaçante.

**Une décision revisitée ne s'efface pas.** Elle est remplacée par un nouvel ADR — numéro suivant,
jamais réutilisé — dont le contexte ouvre par « Remplace ADR-XXXX » avec le lien. L'ancien ADR ne
subit qu'une seule modification : son statut devient « Remplacé par », avec le lien inverse. Tout
le reste est gelé — l'historique d'une décision vaut souvent autant que la décision elle-même.

## Le registre

| ADR                                           | Décision                                                         | Statut  |
| --------------------------------------------- | ---------------------------------------------------------------- | ------- |
| [ADR-0001](./0001-monorepo.md)                | Un monorepo pour tout le produit, deux chaînes d'outils          | Accepté |
| [ADR-0002](./0002-uv-outillage-python.md)     | uv comme outillage Python unique, épinglé partout                | Accepté |
| [ADR-0003](./0003-monolithe-modulaire.md)     | Un monolithe modulaire découpé en modules métier                 | Accepté |
| [ADR-0004](./0004-tenance-par-groupe.md)      | Le groupe de cliniques est la frontière de tenance               | Accepté |
| [ADR-0005](./0005-appartenance-datee.md)      | L'appartenance à un groupe est une relation N:M datée            | Accepté |
| [ADR-0006](./0006-dossier-medical-animal.md)  | Le dossier médical appartient à l'animal, la détention est datée | Accepté |
| [ADR-0007](./0007-client-api-genere-orval.md) | Le client d'API des frontends est généré par Orval               | Accepté |
| [ADR-0008](./0008-taskiq-taches-de-fond.md)   | TaskIQ exécute les tâches de fond                                | Accepté |

Les huit premiers ADR ont été rédigés a posteriori (DOC-02b) : les décisions dataient des tickets
cités dans leur contexte, seule leur consignation date d'août 2026. À partir d'ici, un ADR s'écrit
au moment où la décision se prend.

Les règles opérationnelles qui découlent de ces décisions — comment structurer un module, écrire
un cas d'usage, déclarer un agrégat tenant — seront reprises dans
[Architecture](../architecture/index.md) (DOC-02a).
