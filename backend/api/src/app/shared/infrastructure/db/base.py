"""Base declarative commune aux modeles de persistance (BACK-04, enrichie par BACK-05).

UNE SEULE `Base` pour tout le service, alors que les modules sont etanches par
ailleurs. Ce n'est pas une entorse a leur independance : les modules ne
s'importent pas les uns les autres, mais ils partagent une meme base de donnees,
donc un meme registre de metadonnees. Deux `Base` distinctes produiraient deux
jeux de metadonnees, et Alembic (BACK-07) n'en verrait qu'un a la fois.

Le module de persistance qui herite d'ici reste, lui, strictement interne a son
module : `identity` ne lit jamais la table de `organization`, il passe par les
cas d'usage publics de ce module.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Ancetre declaratif de tous les modeles SQLAlchemy du service.

    Volontairement NUE a ce stade. BACK-05 lui ajoutera la convention de nommage
    des contraintes (pk, fk, ix, uq, ck), sans laquelle deux executions
    d'Alembic sur le meme schema ne produisent pas le meme nom d'index -- et
    donc pas la meme migration.
    """
