"""Modeles de persistance du module medical_records (BACK-19).

Deux tables, et le contre-exemple fondateur devenu reel : `TenantMixin`
(BACK-05) promettait qu'`Animal` ne le porterait pas -- l'animal est cree a
l'inscription d'un particulier, avant qu'un groupe existe dans sa vie. C'est
fait ici : AUCUNE des deux tables n'est tenant, la garde d'index du mixin ne
s'applique donc pas, et leurs depots heritent du generique NU. Ce sont les
actes cliniques, produits par un groupe, qui porteront la tenance (ADR-0004,
ADR-0006).

L'INDEX UNIQUE PARTIEL, OU L'INVARIANT DEVIENT PHYSIQUE
« Plusieurs detentions dans le temps, une seule active » (ADR-0006) : active =
OUVERTE (`end_at IS NULL`), et l'unicite ne porte que sur elle. Une
`UniqueConstraint` ne sait pas etre partielle : seule la forme `Index(...,
unique=True, postgresql_where=...)` dit « au plus une ligne ouverte par
animal » tout en laissant l'historique s'accumuler librement. Le pendant
domaine, `ensure_custody_openable`, teste le MEME predicat. Deux consequences
assumees :
- l'index n'est pas DIFFERABLE (une contrainte differable ne peut pas etre
  partielle) : le transfert doit clore l'ancienne detention AVANT d'ouvrir la
  nouvelle, meme au sein d'une transaction qui finirait coherente ;
- le chevauchement de fenetres FERMEES n'est pas contraint : la fusion de
  fiches (BACK-20) conservera TOUTES les detentions des deux fiches, et en
  produira de legitimes.

`account_id` SANS CLE ETRANGERE, ET NOT NULL
La table `accounts` appartient au module identity : l'identifiant reste nu,
l'integrite est applicative (ADR-0015, comme `memberships.account_id`). NOT
NULL est la dette NOMMEE de ce ticket : si BACK-20 decide que la fiche creee a
l'accueil pour un client sans compte porte une detention, la relaxation sera
un `DROP NOT NULL` -- migration de metadonnees, reversible. Un nullable pose
d'avance imposerait le traitement du NULL a toutes les requetes de BACK-30
pour un design que personne n'a encore tranche.

`animals.id` NE SE SUPPRIME PAS A LA LEGERE
La cle etrangere de `custodies` est declaree SANS `ondelete` : supprimer un
animal portant des detentions echoue bruyamment. Un dossier medical se
conserve ; la fusion de fiches (BACK-20) definira ses propres etats, traces
et reversibles -- jamais un DELETE.

Les enums du domaine sont stockes en TEXTE, comme partout : le mapping
explicite vers `Species` / `AnimalSex` / `SterilizationStatus` reste visible
dans le depot, et ajouter une valeur ne coute pas une migration d'enum natif.
La puce reste un simple `String(32)` nullable : format, unicite partielle et
doublons appartiennent a BACK-20.
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base
from app.shared.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKey


class AnimalModel(UUIDPrimaryKey, TimestampMixin, Base):
    """Table des fiches animal : la racine du dossier medical.

    AUCUNE donnee du detenteur ici -- pas meme un `owner_id` : c'est la
    detention qui dit qui garde l'animal, et c'est ce qui rend le transfert
    sur par construction. Ceder l'animal ne cede que l'animal.
    """

    __tablename__ = "animals"

    name: Mapped[str] = mapped_column(String(100))
    species: Mapped[str] = mapped_column(String(20))
    breed: Mapped[str | None] = mapped_column(String(100), default=None)
    birth_date: Mapped[date | None] = mapped_column(Date, default=None)
    sex: Mapped[str] = mapped_column(String(20))
    sterilization: Mapped[str] = mapped_column(String(20))
    microchip_number: Mapped[str | None] = mapped_column(String(32), default=None)


class CustodyModel(UUIDPrimaryKey, TimestampMixin, Base):
    """Table des detentions datees d'un animal par un compte particulier.

    L'index unique partiel sur `animal_id` (`WHERE end_at IS NULL`) est
    l'invariant du ticket rendu physique : au plus une detention OUVERTE par
    animal. `(animal_id, start_at)` sert l'historique ordonne et la detention
    en vigueur a un instant donne ; `(account_id, end_at)` sert « les animaux
    de ce compte » (BACK-30), leur comptage (BACK-26) et l'historique par
    compte, la condition `end_at IS NULL` s'appuyant sur le B-tree.
    """

    __tablename__ = "custodies"
    __table_args__ = (
        Index(None, "animal_id", unique=True, postgresql_where=text("end_at IS NULL")),
        Index(None, "animal_id", "start_at"),
        Index(None, "account_id", "end_at"),
        CheckConstraint("end_at IS NULL OR end_at > start_at", name="window_bounds"),
    )

    animal_id: Mapped[UUID] = mapped_column(ForeignKey("animals.id"))
    account_id: Mapped[UUID] = mapped_column(Uuid)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
