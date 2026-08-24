"""Base declarative commune aux modeles de persistance (BACK-04, enrichie par BACK-05).

UNE SEULE `Base` pour tout le service, alors que les modules sont etanches par
ailleurs. Ce n'est pas une entorse a leur independance : les modules ne
s'importent pas les uns les autres, mais ils partagent une meme base de donnees,
donc un meme registre de metadonnees. Deux `Base` distinctes produiraient deux
jeux de metadonnees, et Alembic (BACK-07) n'en verrait qu'un a la fois.

Le module de persistance qui herite d'ici reste, lui, strictement interne a son
module : `identity` ne lit jamais la table de `organization`, il passe par les
cas d'usage publics de ce module.

LA CONVENTION DE NOMMAGE EST FIGEE
Les cinq motifs ci-dessous nomment toutes les contraintes et tous les index du
service. Ils se figent a la PREMIERE migration (BACK-07) : en changer un ensuite
donnerait a chaque contrainte deja creee un nom que les metadonnees ne savent
plus reproduire, et l'autogeneration proposerait de tout supprimer pour tout
recreer. C'est le seul reglage de ce fichier qui coute cher a corriger tard.

CE QUE `ck` IMPOSE AU RESTE DU CODE
Le motif des contraintes de controle reclame un `%(constraint_name)s`. Toute
`CheckConstraint` doit donc porter un `name=` explicite, et tout `Enum(...)`
construit de valeurs litterales aussi -- sans quoi la construction de la `Table`
leve `InvalidRequestError`, et c'est l'IMPORT du modele qui echoue. L'echec est
bruyant et immediat, ce qui est le bon moment. Un `Mapped[bool]` n'est pas
concerne : PostgreSQL a un booleen natif et n'emet aucune contrainte de
controle pour lui.
"""

from typing import Final

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.schema import Constraint, Index, Table

# Longueur maximale d'un identifiant PostgreSQL, en octets.
_MAX_IDENTIFIER_BYTES: Final = 63

# Motifs de nommage, un par type d'objet de schema.
#
# `column_0_N_name` et NON `column_0_label` pour les index et les contraintes
# d'unicite. Avec `column_0_label`, deux index composites commencant par la meme
# colonne recoivent le MEME nom -- sans erreur ni avertissement, jusqu'a ce que
# PostgreSQL refuse la seconde creation. Or `TenantMixin` impose precisement que
# tout index d'une table de tenance commence par `group_id` : la collision
# serait la regle, pas l'exception.
#
# `%(table_name)s_%(column_0_N_name)s` plutot que `%(column_0_N_label)s` : la
# forme « label » repete le nom de la table une fois PAR COLONNE, ce qui pousse
# un index a deux colonnes bien au-dela des 63 octets admis.
_NAMING_CONVENTION: Final[dict[str, str]] = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class SchemaConventionError(RuntimeError):
    """Le schema declare enfreint une convention que la base ne rattrapera pas.

    Distincte de `ConfigurationError` (BACK-03) : il ne s'agit pas d'une
    variable d'environnement mal renseignee mais d'un modele SQLAlchemy ecrit de
    travers. Corriger le code, pas le `.env`.
    """


class Base(DeclarativeBase):
    """Ancetre declaratif de tous les modeles SQLAlchemy du service.

    Porte le registre de metadonnees du service, et avec lui la convention de
    nommage des contraintes. Un modele qui n'en herite pas serait invisible pour
    Alembic (BACK-07) : c'est `Base.metadata` qui sert de cible a
    l'autogeneration.
    """

    metadata = MetaData(naming_convention=_NAMING_CONVENTION)


def _schema_object_names(table: Table) -> list[str]:
    """Retourne les noms deja resolus des contraintes et index d'une table.

    Lire `.name` sur un objet de schema DECLENCHE l'application de la convention
    de nommage : c'est ce qui permet de controler les noms reels avant qu'une
    migration ne les grave.

    Args:
        table: la table a inspecter.

    Returns:
        Les noms non nuls de ses contraintes et de ses index.
    """
    objects: list[Constraint | Index] = [*table.constraints, *table.indexes]
    return [str(item.name) for item in objects if isinstance(item.name, str)]


def check_schema(metadata: MetaData) -> None:
    """Refuse un schema dont un identifiant depasse la limite de PostgreSQL.

    POURQUOI CE CONTROLE EXISTE
    SQLAlchemy ne leve rien au-dela de 63 octets : il TRONQUE, en remplacant la
    fin du nom par un condensat de quatre caracteres. Le DDL passe, la migration
    aussi. Le degat vient ensuite : Alembic relit en base le nom tronque, le
    compare au nom entier porte par les metadonnees, ne les reconnait pas
    identiques, et propose une suppression suivie d'une recreation -- a chaque
    autogeneration, indefiniment. Le symptome se lit alors comme un defaut
    d'Alembic, ce qu'il n'est pas.

    Appelee par le `lifespan` (BACK-05) et destinee a l'etre aussi par l'`env.py`
    d'Alembic (BACK-07) : un schema qui echoue ici doit empecher le demarrage ET
    la generation d'une migration.

    Args:
        metadata: le registre a controler, en pratique `Base.metadata`.

    Raises:
        SchemaConventionError: si au moins un identifiant est trop long.
    """
    too_long = sorted(
        {
            name
            for table in metadata.tables.values()
            for name in _schema_object_names(table)
            if len(name.encode("utf-8")) > _MAX_IDENTIFIER_BYTES
        }
    )
    if too_long:
        details = "\n".join(f"  - {name} ({len(name.encode('utf-8'))} octets)" for name in too_long)
        message = (
            f"Identifiants trop longs pour PostgreSQL "
            f"(limite {_MAX_IDENTIFIER_BYTES} octets) :\n{details}\n"
            f"Raccourcir le nom de la table ou nommer l'objet a la main."
        )
        raise SchemaConventionError(message)
