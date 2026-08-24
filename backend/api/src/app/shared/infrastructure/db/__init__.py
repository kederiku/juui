"""Socle de persistance partage par tous les modules.

Quatre fichiers, et une frontiere nette entre ce qui vit le temps du PROCESSUS
et ce qui vit le temps d'une REQUETE :

| Fichier      | Ce qu'il porte                                              |
| ------------ | ----------------------------------------------------------- |
| `base.py`    | la `Base` declarative, la convention de nommage, `check_schema` |
| `mixins.py`  | `UUIDPrimaryKey`, `TimestampMixin`, `TenantMixin` (opt-in)  |
| `engine.py`  | le moteur asyncpg et son pool -- duree de vie du processus  |
| `session.py` | la fabrique de sessions et l'acces aux ressources ouvertes  |

Rien ici ne s'ouvre a l'import : c'est le `lifespan` de `app.main` qui construit
le moteur, eprouve la connexion et le referme.

CE QUE CE PAQUET NE LIVRE PAS, ET POURQUOI
Aucune dependance `get_session()`. Ouvrir une session, la refermer et decider du
commit reviennent a l'unite de travail (BACK-06a), dont le but est que la couche
application ne voie jamais une `AsyncSession` -- publier la dependance ici
suffirait a rendre la promesse intenable.

CE QUE LES TICKETS SUIVANTS AJOUTERONT ICI
BACK-06a : `unit_of_work.py` et `repositories/base.py`. Puis BACK-06b :
`tenant_context.py`, la contextvar `current_group_id` et le filtre applique aux
seuls agregats declarant `TenantMixin`.
"""
