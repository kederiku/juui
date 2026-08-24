---
title: Architecture
description: Règles d'architecture du monorepo — page d'attente, remplie par DOC-02a.
---

# Architecture

Cette section consignera les **règles d'architecture** du projet, pour qu'un développeur comme un
agent puissent produire du code conforme sans avoir à deviner les conventions.

## Ce qui viendra ici

- La **règle des 3 modèles** : schéma Pydantic pour l'API, entité de domaine, modèle SQLAlchemy —
  trois représentations distinctes, avec un mapping explicite entre elles.
- **Ports et adaptateurs**, Unit of Work, gestion des erreurs, et le choix de tests par _fakes_
  plutôt que par mocks.
- La **carte de contexte** des modules métier — `identity`, `organization`, `medical_records`,
  `scheduling`, `notifications` — sous forme de diagramme, avec ce que chacun expose et qui le
  consomme. Elle sera explicitement **provisoire** : une frontière peut encore bouger tant qu'aucune
  API publique de module n'est consommée.
- Le **sens des dépendances** : l'infrastructure dépend du domaine, jamais l'inverse.
- La liste des **anti-patterns interdits** : entité anémique, session de base de données injectée
  dans un cas d'usage, exception HTTP levée depuis le domaine.

## En attendant

L'ossature décrite ici existe déjà dans le dépôt : `backend/api/src/app/` porte la structure
modulaire et hexagonale, avec `identity` en module de référence. Les commentaires de ces fichiers
font foi tant que cette section n'est pas écrite.

:::note Apportée par DOC-02a
Le contenu de cette section dépend de plusieurs tickets backend encore à faire. Les décisions déjà
prises, elles, sont consignées à part, dans les [ADR](../adr/index.md).
:::
