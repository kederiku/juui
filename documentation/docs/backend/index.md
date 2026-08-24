---
title: Backend
description: Le service d'API — page d'attente, remplie par les tickets BACK.
---

# Backend

Le service d'API vit dans `backend/api/`. Il est écrit en **Python** avec **FastAPI**, suit une
architecture **hexagonale à l'intérieur de modules métier**, et il est outillé par `uv`, Ruff, Mypy
et Pytest.

Il est volontairement **absent des workspaces pnpm** : c'est un projet Python, piloté par sa propre
chaîne d'outils, et le dépôt assume d'en avoir deux.

## Ce qui viendra ici

- La structure d'un **module** : domaine, application, infrastructure, et sa frontière avec les
  autres modules.
- La **configuration** applicative et les variables d'environnement qui la peuplent.
- La **persistance** : modèles, migrations Alembic, transactions.
- L'**authentification** et le contexte de tenance appliqué aux requêtes.
- Les **tâches de fond** et le worker qui les consomme.
- Comment **lancer et tester** le service, hors conteneur comme dans la pile.

:::note Apportée par les tickets BACK
En attendant, le [README de `backend/api/`](https://github.com/kederiku/juui/tree/main/backend/api)
décrit l'état réel du service, et les règles qui l'encadrent seront reprises dans
[Architecture](../architecture/index.md).
:::
