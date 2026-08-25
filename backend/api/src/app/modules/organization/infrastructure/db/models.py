"""Modeles de persistance du module organization (BACK-16).

Quatre tables, et la levee d'une dette nommee : `TenantMixin` (BACK-05)
promettait que « BACK-16 posera la contrainte table par table, quand `groups`
existera et que chaque module pourra y consentir explicitement ». C'est fait
ici : la cle etrangere vers `groups` se declare dans le `__table_args__` de
chaque table qui y consent, jamais dans le mixin -- une FK partant de `shared/`
rendrait tous les modules structurellement dependants de celui-ci (ADR-0015).

QUI EST TENANT, QUI NE L'EST PAS
- `groups` : PAS de `TenantMixin` -- le groupe EST le tenant, se filtrer par
  soi-meme n'aurait pas de sens.
- `clinics` : tenant. Produite par un groupe, gardee par lui, toujours lue
  dans un groupe actif.
- `memberships` : PAS tenant, et c'est le contre-exemple qui vaut regle. La
  table est lue a l'emission du jeton, AVANT tout groupe actif -- le filtre
  automatique leverait faute de contexte, et l'echappatoire « tous groupes »
  deviendrait le chemin nominal, l'inverse de sa doctrine. Son `group_id` est
  une colonne PROPRE au module, portee par l'entite : l'appartenance ne vit
  pas dans la frontiere, elle la definit.
- `assignments` : tenant. Sa requete (BACK-10c) tourne toujours dans le groupe
  actif, et la colonne du mixin porte la cle composite ci-dessous.

LA CLE COMPOSITE D'`assignments`, OU L'INVARIANT DEVIENT PHYSIQUE
`(clinic_id, group_id)` reference `clinics (id, group_id)`, adossee a la
contrainte d'unicite `uq_clinics_id_group_id`. Une affectation dont la
clinique n'appartient pas a son propre groupe est ainsi IMPOSSIBLE a inserer :
la moitie structurelle de la regle du ticket tient par la base, la moitie
temporelle -- « appartenance ACTIVE » -- par `ensure_assignment_allowed` dans
le domaine. Pas de FK directe d'`assignments` vers `groups` : la validite du
groupe est transitive par `clinics`.

`account_id` SANS CLE ETRANGERE, ET C'EST DELIBERE
La table `accounts` appartient au module identity, et une FK inter-modules
serait un couplage structurel que la frontiere interdit -- le schema
d'identity deviendrait ingelable sans l'accord d'organization, et
reciproquement (ADR-0015). L'identifiant reste nu ; l'integrite est
applicative, les identifiants venant des jetons et des cas d'usage d'identity.

Les roles sont stockes en TEXTE, comme `account_type` chez identity : le
mapping explicite vers `GroupRole` / `ClinicRole` reste visible dans le depot,
et ajouter une valeur ne coute pas une migration d'enum natif.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base
from app.shared.infrastructure.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey


class GroupModel(UUIDPrimaryKey, TimestampMixin, Base):
    """Table des groupes : la frontiere d'isolation elle-meme."""

    __tablename__ = "groups"

    name: Mapped[str] = mapped_column(String(150))


class ClinicModel(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Table des cliniques d'un groupe.

    `uq_clinics_id_group_id` semble redondante avec la cle primaire -- elle
    l'est, et c'est son role : elle donne a la paire `(id, group_id)` l'index
    unique qu'une cle etrangere composite exige pour la referencer, celle
    d'`assignments`.
    """

    __tablename__ = "clinics"
    __table_args__ = (
        ForeignKeyConstraint(["group_id"], ["groups.id"]),
        UniqueConstraint("id", "group_id"),
        Index(None, "group_id", "name"),
    )

    name: Mapped[str] = mapped_column(String(150))


class MembershipModel(UUIDPrimaryKey, TimestampMixin, Base):
    """Table des appartenances datees d'un compte a un groupe.

    `group_id` est ici une colonne PROPRE, avec sa cle etrangere inline : la
    table n'est pas tenant, le socle n'estampille rien, c'est le mapping du
    depot qui la renseigne depuis l'entite. L'index `(account_id, group_id)`
    sert les deux requetes du port par son prefixe : toutes les appartenances
    d'un compte, puis son role dans un groupe donne.
    """

    __tablename__ = "memberships"
    __table_args__ = (
        Index(None, "account_id", "group_id"),
        CheckConstraint("end_at IS NULL OR end_at > start_at", name="window_bounds"),
    )

    account_id: Mapped[UUID] = mapped_column(Uuid)
    group_id: Mapped[UUID] = mapped_column(ForeignKey("groups.id"))
    role: Mapped[str] = mapped_column(String(20))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class AssignmentModel(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Table des affectations datees d'un compte a une clinique.

    Le `group_id` du mixin, estampille par le socle a l'insertion, entre dans
    la cle etrangere composite : une affectation ne peut referencer qu'une
    clinique de SON groupe. L'index `(group_id, account_id)` satisfait la
    garde du mixin et sert la requete de BACK-10c -- les affectations d'un
    compte dans le groupe actif.
    """

    __tablename__ = "assignments"
    __table_args__ = (
        ForeignKeyConstraint(["clinic_id", "group_id"], ["clinics.id", "clinics.group_id"]),
        Index(None, "group_id", "account_id"),
        CheckConstraint("end_at IS NULL OR end_at > start_at", name="window_bounds"),
    )

    account_id: Mapped[UUID] = mapped_column(Uuid)
    clinic_id: Mapped[UUID] = mapped_column(Uuid)
    role: Mapped[str] = mapped_column(String(20))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
