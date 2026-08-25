"""Socle de persistance partage par tous les modules.

Six entrees, et une frontiere nette entre ce qui vit le temps du PROCESSUS, le
temps d'une REQUETE, et le temps d'un BLOC :

| Fichier           | Ce qu'il porte                                              |
| ----------------- | ----------------------------------------------------------- |
| `base.py`         | la `Base` declarative, la convention de nommage, `check_schema` |
| `mixins.py`       | `UUIDPrimaryKey`, `TimestampMixin`, `TenantMixin` (opt-in)  |
| `engine.py`       | le moteur asyncpg et son pool -- duree de vie du processus  |
| `session.py`      | la fabrique de sessions et l'acces aux ressources ouvertes  |
| `unit_of_work.py` | l'adaptateur de l'unite de travail -- une session par BLOC  |
| `repositories/`   | le depot generique dont les depots des modules heritent     |

Rien ici ne s'ouvre a l'import : c'est le `lifespan` de `app.main` qui construit
le moteur, eprouve la connexion et le referme.

CE QUE CE PAQUET NE LIVRE PAS, ET POURQUOI
Aucune dependance `get_session()`. Ouvrir une session, la refermer et decider du
commit reviennent a l'unite de travail (BACK-06a), dont le but est que la couche
application ne voie jamais une `AsyncSession` -- publier la dependance ici
suffirait a rendre la promesse intenable. Ce qui se publie, c'est l'unite de
travail de CHAQUE module (`get_identity_uow`, a la racine du module identity),
jamais une dependance globale.

CE QUE LES TICKETS SUIVANTS AJOUTERONT ICI
BACK-06b : le filtre de tenance, applique dans `repositories/` aux seuls
agregats declarant `TenantMixin`.

CORRECTION DE CE QUE BACK-04 ANNONCAIT ICI
La contextvar `current_group_id` ne vit PAS dans ce paquet : elle est montee d'un
cran, dans `../tenancy.py`, parce que BACK-14 en a eu besoin le premier. Le cache
n'a aucune raison d'importer le socle de persistance pour savoir nommer une cle,
et l'appartenance a un groupe n'est pas une notion de persistance -- c'est une
notion de requete, que la persistance et le cache lisent tous deux.
"""
