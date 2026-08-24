---
title: Décisions d'architecture (ADR)
description: Registre des décisions structurantes — page d'attente, remplie par DOC-02b.
---

# Décisions d'architecture (ADR)

Un **ADR** — _Architecture Decision Record_ — consigne une décision structurante : son contexte, ce
qui a été décidé, les alternatives écartées, et les conséquences acceptées.

L'objet n'est pas de documenter pour documenter. C'est d'éviter qu'une décision déjà prise soit
rediscutée par accident à chaque ticket, faute de trace de son motif — et de rendre visible ce
qu'elle coûte.

## Deux règles pour ce registre

1. **Un gabarit commun** : contexte, décision, alternatives écartées, conséquences, statut.
2. **Une décision revisitée ne s'efface pas.** Elle est remplacée par un nouvel ADR qui référence
   l'ancien, lequel passe au statut « remplacé ». L'historique d'une décision vaut souvent autant
   que la décision elle-même.

## Décisions à consigner

- Le monolithe modulaire, et le découpage en modules métier.
- La stratégie de tenance : le groupe comme frontière, filtre applicatif explicite.
- L'appartenance datée d'un vétérinaire à plusieurs structures.
- Le dossier médical attaché à l'animal, et la détention datée.
- Le monorepo.
- Les choix d'outillage : `uv`, le client d'API généré, la file de tâches.

:::note Apportée par DOC-02b
Chaque ADR renverra aux tickets qui l'appliquent, et les règles qui en découlent seront reprises
dans [Architecture](../architecture/index.md).
:::
