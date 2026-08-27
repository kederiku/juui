"""Modeles de persistance du module scheduling (BACK-21).

Trois tables : la fiche technique, ses plages d'intervention, ses especes prises
en charge. Sept decisions meritent d'etre lues avant d'y toucher.

PREMIERE TABLE TENANT HORS D'`organization`, ET PREMIERE A S'ABSTENIR DE LA FK
`practitioner_profiles` declare `TenantMixin` mais NE pose PAS de cle etrangere
vers `groups` : la table appartient a organization, et ADR-0015 interdit
l'inter-modules. C'est le cas que la docstring du mixin prevoyait par ecrit --
« un modele qui s'en abstiendrait garde l'integrite par le filtre du depot, pas
par la base ». Corollaire ASSUME : le tour de la cle composite d'`assignments`
-- `(clinic_id, group_id)` vers `clinics (id, group_id)` -- est indisponible
ici, puisqu'il traverserait la frontiere. Une fiche peut donc physiquement
pointer une clinique d'un autre groupe ; elle ne sera jamais LUE hors de son
groupe (le filtre de tenance s'en charge), et c'est au cas d'usage qui ECRIRA
la fiche de verifier l'affectation, via le port public d'organization et au
point de composition -- seul `main` connait deux modules a la fois.

UNE SEULE CONTRAINTE POUR QUATRE BESOINS, ET L'ORDRE DE SES COLONNES EST PORTEUR
`UniqueConstraint("group_id", "clinic_id", "account_id")` sert a elle seule :
1. la garde `__init_subclass__` de `TenantMixin` -- `_has_tenant_index` n'exige
   que la PREMIERE colonne, et compte les contraintes d'unicite autant que les
   index ;
2. l'unicite metier « une fiche par praticien et par clinique » ;
3. la requete de `list_available`, par son prefixe `(group_id, clinic_id)` ;
4. l'egalite complete de `find_for_account_in_clinic`.
Un seul B-tree, donc, et AUCUN index supplementaire. Reordonner les colonnes en
`(group_id, account_id, clinic_id)` degraderait la requete EN SILENCE et
obligerait a poser un second index pour rattraper. Consequence nommee : « toutes
les fiches d'un compte, toutes cliniques confondues » n'est couverte par aucun
prefixe et reclamera son propre index le jour ou un port la posera.

DES TABLES ENFANTS, ET NON UN DOCUMENT JSONB
`notifications` a ecrit lui-meme la condition de sortie du JSONB : « le jour ou
une requete par canal existera, elle justifiera sa table ». Ce jour est
celui-ci -- la requete du ticket interroge le CONTENU des deux collections, en
travers des lignes, avec un predicat d'intervalle. En JSONB elle exigerait un
`jsonb_array_elements` lateral non indexable, et la base ne saurait plus
controler `end_minute > start_minute`.

DES CLES PRIMAIRES NATURELLES COMPOSITES, PAS `UUIDPrimaryKey`
Une plage horaire et une espece sont des VALEURS sans identite : le domaine ne
les adresse jamais seules. Un identifiant de substitution allongerait les noms
et surtout inviterait a les referencer depuis l'exterieur -- ce qu'un rendez-vous
ne doit jamais faire. Bonus mesurable : la cle EST l'index dont les `EXISTS` du
depot ont besoin, par son prefixe `profile_id`. Les enfants ne portent pas non
plus `TimestampMixin` (aucun cycle de vie propre) ni `TenantMixin` : ils ne se
lisent qu'a travers la fiche, dont le `_select()` est deja filtre, et une
colonne de groupe creerait la possibilite d'un desaccord qu'il faudrait ensuite
interdire.

DES HEURES MURALES, EN MINUTES DEPUIS MINUIT
0 a 1440 inclus, 1440 valant « minuit, fin de journee » -- forme que
`datetime.time` ne sait pas produire. Aucune colonne de type `time` ni
`timestamp` sur ces trois tables : le module ne possede aucun fuseau et n'en
invente aucun (voir `domain/policies.py`).

LA CONVENTION DE JOUR EST CELLE DE PYTHON, ET IL FAUT LE SAVOIR
`weekday` stocke ce que rendent `date.weekday()` et `calendar.Day` : lundi = 0
... dimanche = 6. Ce n'est NI `EXTRACT(DOW)` (dimanche = 0) NI
`EXTRACT(ISODOW)` (lundi = 1). Une requete SQL future qui deriverait un jour
depuis une date doit ecrire `EXTRACT(ISODOW FROM d) - 1`. Le nom de la
contrainte, `ck_practitioner_hours_weekday_python_range`, porte la convention
jusque dans le schema.

`updated_at` DATE LA LIGNE, PAS L'AGREGAT
Un changement portant uniquement sur les plages ou les especes n'emet aucun
UPDATE sur la ligne parente et ne declenche donc pas `onupdate` :
`practitioner_profiles` est la premiere table du depot ou les deux divergent.
`updated_at` n'a aucun consommateur a ce jour, et le declencheur `BEFORE UPDATE`
reporte par BACK-07 ne couvrirait pas davantage ce cas.
"""

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, SmallInteger, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.infrastructure.db.base import Base
from app.shared.infrastructure.db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKey

# Les deux enfants sont declares AVANT le parent : les `order_by` des relations
# referencent ainsi de vraies colonnes plutot qu'une chaine a resoudre plus tard.


class PractitionerHoursModel(Base):
    """Table des plages d'intervention hebdomadaires d'une fiche technique.

    La cle primaire `(profile_id, weekday, start_minute)` interdit deja deux
    plages commencant a la meme heure le meme jour ; le recouvrement PARTIEL,
    lui, reste tenu par le domaine (`ensure_hours_disjoint`) -- PostgreSQL n'a
    pas de type intervalle natif sur des minutes, et une contrainte `EXCLUDE`
    demanderait `btree_gist`.
    """

    __tablename__ = "practitioner_hours"
    __table_args__ = (
        CheckConstraint("end_minute > start_minute", name="range_bounds"),
        CheckConstraint("start_minute >= 0 AND end_minute <= 1440", name="minute_of_day_range"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_python_range"),
    )

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("practitioner_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    weekday: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    start_minute: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    end_minute: Mapped[int] = mapped_column(SmallInteger)


class PractitionerSpeciesModel(Base):
    """Table des especes prises en charge par une fiche technique.

    Une ligne par espece, la cle primaire rendant le doublon impossible -- ce
    qu'un `frozenset` fait deja cote domaine. Pas d'index sur `species` seul :
    aucune requete ne part de l'espece sans clinique, et l'ajouter « au cas ou »
    couterait une ecriture de plus a chaque enregistrement.
    """

    __tablename__ = "practitioner_species"

    profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("practitioner_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    species: Mapped[str] = mapped_column(String(20), primary_key=True)


class PractitionerProfileModel(UUIDPrimaryKey, TenantMixin, TimestampMixin, Base):
    """Table des fiches techniques : un praticien, une clinique, un groupe.

    `account_id` et `clinic_id` sont des identifiants NUS, sans cle etrangere :
    `accounts` appartient a identity, `clinics` a organization, et une FK
    inter-modules souderait les schemas (ADR-0015). L'integrite est
    applicative, les identifiants venant des jetons et des cas d'usage des
    modules proprietaires.
    """

    __tablename__ = "practitioner_profiles"
    __table_args__ = (UniqueConstraint("group_id", "clinic_id", "account_id"),)

    account_id: Mapped[UUID] = mapped_column(Uuid)
    clinic_id: Mapped[UUID] = mapped_column(Uuid)

    # `lazy="selectin"` sur les deux collections, et ce n'est pas une
    # optimisation : en asynchrone, un chargement PARESSEUX leverait
    # `MissingGreenlet` a la premiere lecture d'attribut hors contexte greenlet.
    # Le chargement anticipe regle la question partout -- `select()` comme
    # `session.get()` --, sans surcharger une seconde fois `_select` et `_load`
    # que `TenantSqlAlchemyRepository` surcharge deja pour la tenance.
    #
    # `cascade="all, delete-orphan"` : les enfants sont des PARTIES de
    # l'agregat, ils naissent et meurent avec lui. Le remplacement integral
    # d'une collection par le mapping du depot produit donc les INSERT et les
    # DELETE attendus, et `ON DELETE CASCADE` cote base est la seconde ceinture
    # -- pour les suppressions qui ne passeraient pas par l'ORM.
    hours: Mapped[list[PractitionerHoursModel]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by=[PractitionerHoursModel.weekday, PractitionerHoursModel.start_minute],
    )
    treated_species: Mapped[list[PractitionerSpeciesModel]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by=[PractitionerSpeciesModel.species],
    )
