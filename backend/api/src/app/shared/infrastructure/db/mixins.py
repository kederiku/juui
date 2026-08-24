"""Mixins de persistance partages par les modeles de tous les modules (BACK-05).

Trois mixins, et le choix de les prendre ou non appartient a chaque agregat. Ce
ne sont pas des classes de base : ils ne sont pas mappes, ils n'ont pas de table,
et SQLAlchemy 2.0 recopie leurs colonnes dans chaque modele qui les declare.

`Mapped[...]` et `mapped_column(...)` directement, sans `declared_attr` : depuis
la 2.0 le decorateur n'est plus necessaire pour de simples colonnes, cle
etrangere comprise. Il reste indispensable pour `__tablename__`,
`__table_args__`, `__mapper_args__` (variante `declared_attr.directive`), pour
`relationship()`, et pour tout objet de schema qu'on ne peut pas rattacher a
deux tables a la fois.

L'ORDRE DES COLONNES SE FIGE AVEC LA PREMIERE MIGRATION
`sort_order` n'est pas decoratif. Sans lui, les colonnes heritees se rangent
avant ou apres celles du modele selon l'ordre de resolution des classes, et le
resultat se lit mal dans une description de table comme en revue. Les valeurs retenues
donnent partout la meme silhouette : identite, tenance, colonnes propres au
modele, horodatage. Aucune migration n'existe encore (BACK-07), c'est donc
gratuit aujourd'hui et couteux demain.
"""

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import DateTime, Index, Table, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import SchemaConventionError

# Nom de la colonne de tenance. Constante plutot que litteral repete : le
# controle ci-dessous et la colonne doivent parler du meme nom.
_TENANT_COLUMN: Final = "group_id"


class UUIDPrimaryKey:
    """Cle primaire UUID, premiere colonne de la table.

    AUCUN DEFAUT, ET C'EST LE POINT
    C'est le DOMAINE qui bat la monnaie : `Account.create()` produit l'identifiant
    avant meme qu'il soit question de persistance, et le depot le passe toujours
    explicitement. Un `default=` ici -- comme un `server_default` -- ne serait
    jamais atteint, et laisserait croire que la strategie d'identite se decide
    dans l'infrastructure. Elle se decide dans le domaine.

    POURQUOI UUID VERSION 7
    La version 7 est ORDONNEE DANS LE TEMPS : ses 48 premiers bits sont un
    horodatage en millisecondes. Les insertions se rangent donc en fin d'index
    B-tree, sur quelques pages chaudes, la ou la version 4 -- uniformement
    aleatoire -- vise une feuille au hasard a chaque ligne, multiplie les
    divisions de page et alourdit le journal d'ecriture. Sur des tables qui ne
    font que croitre (rendez-vous, actes cliniques, journal de notifications),
    l'ecart se paie a l'echelle, pas au premier millier de lignes.

    CE QU'ELLE COUTE, ET QU'IL FAUT SAVOIR
    Cet horodatage est EN CLAIR. Qui detient un identifiant connait la date de
    creation de la ligne a la milliseconde pres, et deux identifiants livrent
    leur ordre et le temps qui les separe. Ce n'est pas une faille
    d'enumeration -- 74 bits restent aleatoires, on ne devine pas le voisin --
    mais c'est une fuite d'anteriorite. Un agregat qui aurait besoin d'un
    identifiant public reellement opaque devra porter un second identifiant
    aleatoire, plutot que degrader la cle primaire de toutes les tables.
    """

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, sort_order=-100)


class TimestampMixin:
    """Horodatage de creation et de derniere modification, en UTC.

    `DateTime(timezone=True)` donne un `timestamptz` PostgreSQL. Le type nu
    stockerait une heure sans fuseau, que chaque lecteur interpreterait dans le
    sien : la seule question qui compte ensuite -- « cette consultation
    a-t-elle eu lieu avant celle-la » -- deviendrait indecidable entre deux
    serveurs.

    LE SERVEUR EST L'HORLOGE
    `server_default=func.now()` plutot qu'un defaut calcule en Python. Trois
    processus uvicorn, un worker TaskIQ (BACK-15), une migration et une session
    `psql` n'ont aucune raison d'etre d'accord entre eux ; PostgreSQL, si. C'est
    aussi ce qui donne un horodatage aux lignes inserees a la main ou par une
    migration de donnees, ce qu'un defaut Python ne fait jamais.

    `func.now()` compile vers `now()`, c'est-a-dire `transaction_timestamp()` :
    la valeur est GELEE pour toute la transaction. Toutes les lignes ecrites
    dans un meme commit partagent donc exactement le meme `created_at`, ce qui
    rend « creees ensemble » exprimable par une egalite. En contrepartie, ce
    n'est pas une horloge d'evenement a haute resolution : dans une transaction
    longue, `created_at` precede l'insertion reelle.

    CE QUE `updated_at` NE COUVRE PAS
    `onupdate=func.now()` est orchestre par SQLAlchemy : c'est lui qui ajoute
    `updated_at = now()` a l'UPDATE qu'il emet. Un UPDATE qui ne passe pas par
    l'ORM -- migration de donnees, correction manuelle en `psql` -- ne le
    declenchera donc pas. `server_onupdate` ne reglerait rien : il est purement
    informatif et n'emet aucun DDL. Le jour ou `updated_at` deviendra porteur
    pour une synchronisation ou un ETag, il faudra un declencheur `BEFORE
    UPDATE`, et sa place sera dans une migration (BACK-07), pas ici.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        sort_order=100,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        sort_order=101,
    )


def _has_tenant_index(table: Table) -> bool:
    """Dit si la table porte un index dont la PREMIERE colonne est `group_id`.

    Une contrainte d'unicite compte autant qu'un index : PostgreSQL la sert par
    un index unique, et l'exiger en plus reviendrait a reclamer un doublon.

    Args:
        table: la table du modele qui declare `TenantMixin`.

    Returns:
        Vrai si au moins un index ou une contrainte d'unicite commence par la
        colonne de tenance.
    """
    indexed: list[Index | UniqueConstraint] = [
        *table.indexes,
        *(item for item in table.constraints if isinstance(item, UniqueConstraint)),
    ]
    return any(
        next((column.name for column in item.columns), None) == _TENANT_COLUMN for item in indexed
    )


class TenantMixin:
    """Appartenance a un groupe : la frontiere d'isolation entre structures.

    OPT-IN, AGREGAT PAR AGREGAT
    Le mixin ne se declare que sur les agregats PRODUITS par un groupe et
    conserves sous sa garde. Les deux contre-exemples valent regle : une
    `Consultation` le porte, un `Animal` non -- l'animal est cree a l'inscription
    d'un particulier, avant qu'un groupe existe dans sa vie. Un compte non plus :
    l'appartenance a un groupe est une relation N:M DATEE portee par le module
    `organization` (BACK-16), parce qu'un veterinaire remplacant intervient dans
    plusieurs groupes avec un seul compte.

    Le filtre correspondant ne doit JAMAIS etre applique globalement dans le
    depot de base. C'est BACK-06b qui l'appliquera, et aux seuls agregats
    declarant ce mixin.

    PAS DE CLE ETRANGERE VERS `groups`, POUR L'INSTANT
    La table `groups` n'existe pas avant BACK-16. Une `ForeignKey("groups.id")`
    posee ici se declarerait sans erreur mais casserait
    `metadata.sorted_tables` -- donc `alembic revision --autogenerate` pour TOUT
    le projet -- des le premier modele adoptant le mixin. S'y ajoute une raison
    d'architecture : une cle etrangere partant de `shared/` vers une table
    d'`organization` rendrait tous les modules structurellement dependants de
    celui-la. La dette est assumee et nommee : BACK-16 posera la contrainte
    table par table, quand `groups` existera et que chaque module pourra y
    consentir explicitement. En attendant, l'integrite tient par le filtre du
    depot, pas par la base.
    """

    group_id: Mapped[UUID] = mapped_column(Uuid, nullable=False, sort_order=-99)

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse une table de tenance depourvue d'index prefixe par `group_id`.

        POURQUOI UNE GARDE ET NON UNE CONSIGNE
        Un index manquant ne casse rien : il produit un balayage sequentiel, donc
        une requete lente, invisible sur un jeu de developpement et sensible le
        jour ou un client a des donnees. Ce genre d'oubli ne se rattrape pas a la
        relecture -- il se rattrape a la declaration.

        `super()` D'ABORD, ce n'est pas une politesse : c'est
        `DeclarativeBase.__init_subclass__` qui construit `__table__`, et le
        controle n'aurait rien a inspecter avant lui. Le refus tombe donc a
        l'IMPORT du modele, ou un simple `python -c "import app.main"` le
        rencontre -- la ou les points d'accroche `__declare_last__` et
        `after_configured` n'auraient tire qu'a la premiere requete ORM,
        c'est-a-dire en erreur 500 depuis une route.

        Args:
            **kwargs: les arguments de classe transmis a la chaine d'heritage.

        Raises:
            SchemaConventionError: si la table ne porte aucun index ni aucune
                contrainte d'unicite commencant par `group_id`.
        """
        super().__init_subclass__(**kwargs)

        table = getattr(cls, "__table__", None)
        # Classe intermediaire `__abstract__`, ou mapping differe : pas de table
        # a inspecter, et rien a reprocher.
        if not isinstance(table, Table):
            return

        if not _has_tenant_index(table):
            message = (
                f"{cls.__name__} declare TenantMixin mais la table « {table.name} » "
                f"ne porte aucun index dont la premiere colonne est « {_TENANT_COLUMN} ». "
                f"Toute requete filtree par groupe y finirait en balayage sequentiel. "
                f"Ajouter par exemple :\n"
                f'    __table_args__ = (Index(None, "{_TENANT_COLUMN}", "<colonne>"),)'
            )
            raise SchemaConventionError(message)
