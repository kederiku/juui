"""Socle de persistance partage par tous les modules.

Un seul fichier a ce stade : `base.py`, qui porte la `Base` declarative dont
heritent les modeles de persistance de chaque module. Le module pilote
`identity` en a besoin des maintenant pour declarer son `AccountModel`.

CE QUE BACK-05 AJOUTERA ICI
`engine.py` (moteur asynchrone asyncpg), `session.py` (`async_sessionmaker`
avec `expire_on_commit=False`), `mixins.py` (`TimestampMixin`, `UUIDPrimaryKey`
et le `TenantMixin` OPT-IN), ainsi que la convention de nommage des contraintes
sur la `Base` -- sans laquelle Alembic (BACK-07) produirait des migrations
instables.

Puis BACK-06a : `unit_of_work.py` et `repositories/base.py`. Puis BACK-06b :
`tenant_context.py`.
"""
