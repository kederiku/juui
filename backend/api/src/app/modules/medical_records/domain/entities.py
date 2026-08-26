"""Agregats du module medical_records (BACK-19).

`organization` repond a « dans quelle structure travailles-tu » ; ce module
repond a « de quels animaux s'agit-il ». Deux agregats, et une frontiere qui
est LA decision du ticket (ADR-0006) :

- `Animal` : LA RACINE du dossier medical. Le dossier appartient a l'animal,
  pas au proprietaire : il le suit lors d'un changement de detenteur, pour que
  les soins continuent. Nom, espece, race, naissance, sexe, sterilisation,
  numero de puce -- rien d'autre : les faits cliniques (vaccins, allergies,
  pathologies, chirurgies, poids) seront des entites DATEES de tickets futurs,
  jamais des colonnes de la fiche.
- `Custody` (la « detention » du ticket) : la garde datee d'un animal par un
  compte particulier -- animal, compte, debut, fin. PLUSIEURS dans le temps,
  UNE SEULE ACTIVE. Surtout pas un `owner_id` que l'on ecrase : une
  consultation de 2024 a ete demandee par le detenteur de l'epoque, et
  repointer un champ ferait apparaitre chez le nouveau proprietaire des actes
  qu'il n'a jamais demandes.

CE QUI SUIT L'ANIMAL, CE QUI RESTE A LA DETENTION
Les faits cliniques suivent l'animal. Les coordonnees du detenteur, la
facturation et les notes de contexte restent attachees a la detention qui les
a produites : les livrer au detenteur suivant reviendrait a transmettre les
donnees personnelles d'un tiers. Les actes cliniques a venir referencent donc
la DETENTION en vigueur au moment des faits (`custody_id`), jamais le
proprietaire courant.

TENANCE
`Animal` ne porte PAS le mixin de tenance : il est cree a l'etape 3 de
l'inscription d'un particulier, avant qu'un groupe existe dans sa vie -- le
contre-exemple fondateur annonce par la docstring de `TenantMixin` devient
reel ici. Ce sont les actes cliniques, produits par un groupe, qui la
porteront (ADR-0004).

ACTIVE = OUVERTE, ET LES DEUX COUCHES DISENT LA MEME CHOSE
La detention active d'un animal est sa detention OUVERTE (`end_at is None`).
`ensure_custody_openable` refuse d'en ouvrir une seconde sur ce predicat
exact, le meme que l'index unique partiel de `models.py` : aucun etat que le
domaine accepte et que la base refuse, ni l'inverse. Corollaire assume : la
cloture programmee dans le futur n'est pas supportee -- `end_at` se pose a
l'instant de la cession, jamais d'avance.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid7

from app.modules.medical_records.domain.exceptions import (
    CustodyAlreadyActiveError,
    InvalidWindowError,
)
from app.modules.medical_records.domain.policies import is_window_active


class Species(StrEnum):
    """Espece de l'animal : ensemble FERME, avec `OTHER` pour soupape.

    Un texte libre produirait « Chien », « chien  » et « chein » des la
    premiere semaine, et empoisonnerait la reconciliation par numero de puce
    (BACK-20) comme tout protocole par espece. L'enum est stocke en texte
    (`String(20)`, jamais d'enum natif PostgreSQL) : ajouter une espece est
    une livraison de code, pas une migration. `OTHER` accueille l'espece
    imprevue vue a l'accueil ; les trois premieres valeurs sont les especes a
    identification obligatoire (I-CAD).
    """

    DOG = "dog"
    CAT = "cat"
    FERRET = "ferret"
    RABBIT = "rabbit"
    RODENT = "rodent"
    BIRD = "bird"
    REPTILE = "reptile"
    HORSE = "horse"
    OTHER = "other"


class AnimalSex(StrEnum):
    """Sexe de l'animal, l'inconnu etant une VALEUR du domaine.

    Une fiche creee a l'accueil pour un client presse ne connait pas toujours
    le sexe : `UNKNOWN` le dit explicitement, la ou un booleen nullable
    laisserait chaque lecteur interpreter le NULL a sa facon.
    """

    MALE = "male"
    FEMALE = "female"
    UNKNOWN = "unknown"


class SterilizationStatus(StrEnum):
    """Statut de sterilisation : les trois etats de l'etape 3 d'inscription.

    Oui / non / inconnu (BACK-30). Meme doctrine que pour `AnimalSex` :
    l'inconnu est une valeur explicite, jamais un NULL ambigu.
    """

    STERILIZED = "sterilized"
    INTACT = "intact"
    UNKNOWN = "unknown"


def ensure_aware_instant(at: datetime) -> None:
    """Refuse un instant de reference naif, avant qu'il ne fausse une reponse.

    La regle de `_ensure_valid_window`, etendue au parametre `at` des ports.
    Les deux chemins divergeraient sinon : le domaine leverait un `TypeError`
    brut a la comparaison, et le SQL accepterait l'instant EN SILENCE --
    PostgreSQL interprete un naif lie a un `timestamptz` dans le fuseau de la
    session, et une detention close redeviendrait active a deux heures pres.
    La garde est appelee par les entites ET par les adaptateurs : les deux
    chemins repondent d'une seule voix, en erreur metier.

    Args:
        at: l'instant interroge.

    Raises:
        InvalidWindowError: si l'instant ne porte pas de fuseau.
    """
    if at.utcoffset() is None:
        message = "L'instant de reference porte un fuseau, jamais naif."
        raise InvalidWindowError(message)


def _ensure_valid_window(start_at: datetime, end_at: datetime | None) -> None:
    """Refuse une fenetre de validite mal formee, avant qu'elle n'existe.

    Deux exigences, verifiees a la fabrique et doublees en base par la
    contrainte `ck_custodies_window_bounds` : des instants AVEC fuseau -- une
    borne naive rendrait `is_window_active` indecidable entre deux serveurs --
    et une fin strictement posterieure au debut, `[start_at, end_at)` etant
    demi-ouvert.

    Args:
        start_at: le debut de la fenetre.
        end_at: la fin de la fenetre, ou None pour une fenetre ouverte.

    Raises:
        InvalidWindowError: si une borne est naive, ou si la fin ne suit pas
            strictement le debut.
    """
    for bound in (start_at, end_at):
        if bound is not None and bound.utcoffset() is None:
            message = "Les bornes d'une fenetre de validite portent un fuseau, jamais naives."
            raise InvalidWindowError(message)
    if end_at is not None and end_at <= start_at:
        message = "La fin d'une fenetre de validite suit strictement son debut."
        raise InvalidWindowError(message)


def _normalize_optional_text(value: str | None) -> str | None:
    """Debarrasse un champ facultatif de ses espaces, la chaine vide devenant None.

    Le grand classique des formulaires : une puce saisie `""` ou `"  "` n'est
    pas une puce. La normalisation vit a la fabrique, seul point d'entree des
    creations metier ; le pendant en base attendra l'unicite partielle de
    BACK-20.

    Args:
        value: la valeur brute, ou None.

    Returns:
        La valeur nettoyee, ou None si rien ne reste.
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


@dataclass(slots=True, kw_only=True)
class Animal:
    """Fiche d'un animal : la racine du dossier medical (ADR-0006).

    Elle ne porte que l'etat civil de l'animal -- AUCUNE donnee du detenteur,
    pas meme un identifiant de compte : c'est la detention qui dit qui garde
    l'animal, et c'est ce qui rend le transfert sur par construction.

    Construire l'objet directement est reserve a la RECONSTITUTION depuis la
    persistance ; une creation metier passe par `Animal.create()`.
    """

    id: UUID
    name: str
    species: Species
    breed: str | None = None
    birth_date: date | None = None
    sex: AnimalSex = AnimalSex.UNKNOWN
    sterilization: SterilizationStatus = SterilizationStatus.UNKNOWN
    microchip_number: str | None = None

    @classmethod
    def create(
        cls,
        *,
        name: str,
        species: Species,
        breed: str | None = None,
        birth_date: date | None = None,
        sex: AnimalSex = AnimalSex.UNKNOWN,
        sterilization: SterilizationStatus = SterilizationStatus.UNKNOWN,
        microchip_number: str | None = None,
    ) -> Self:
        """Cree une fiche neuve, identifiee par le domaine.

        Tout est facultatif hors nom et espece : une fiche MINIMALE se cree a
        l'etape 3 de l'inscription et se complete ensuite. La puce est un
        simple champ nettoye -- la validation du format I-CAD, l'unicite
        partielle et la detection de doublon appartiennent a BACK-20.

        Args:
            name: le nom d'usage de l'animal, debarrasse de ses espaces.
            species: l'espece, dans l'ensemble ferme du domaine.
            breed: la race, texte libre -- « croise » est une reponse.
            birth_date: la date de naissance, au jour pres et souvent estimee ;
                None est un etat legitime, jamais une date inventee.
            sex: le sexe, inconnu par defaut.
            sterilization: le statut de sterilisation, inconnu par defaut.
            microchip_number: le numero de puce, facultatif -- la chaine vide
                devient None.

        Returns:
            Une fiche prete a etre persistee.
        """
        return cls(
            id=uuid7(),
            name=name.strip(),
            species=species,
            breed=_normalize_optional_text(breed),
            birth_date=birth_date,
            sex=sex,
            sterilization=sterilization,
            microchip_number=_normalize_optional_text(microchip_number),
        )


@dataclass(slots=True, kw_only=True)
class Custody:
    """Detention datee d'un animal par un compte particulier.

    La relation EST la donnee : `animal_id` et `account_id` sont des champs de
    l'entite, et `account_id` reste un identifiant NU -- le compte vit chez
    identity, et les deux modules ne s'importent pas (ADR-0015). Les actes
    cliniques a venir referenceront `custody.id`, jamais le compte courant :
    c'est ce qui fige « qui a demande quoi » au moment des faits.
    """

    id: UUID
    animal_id: UUID
    account_id: UUID
    start_at: datetime
    end_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        animal_id: UUID,
        account_id: UUID,
        start_at: datetime,
        end_at: datetime | None = None,
    ) -> Self:
        """Cree une detention neuve, fenetre validee.

        `start_at` est l'instant d'ENREGISTREMENT dans le systeme, pas la date
        d'acquisition reelle de l'animal : la fenetre dit « qui repondait de
        l'animal aux yeux du service », pas sa biographie. L'instant est
        fourni par l'appelant, comme partout -- aucune horloge cachee.

        Args:
            animal_id: l'animal garde.
            account_id: le compte particulier detenteur -- identifiant nu,
                jamais l'entite d'identity.
            start_at: le debut de validite, inclus.
            end_at: la fin de validite, exclue -- None pour la detention en
                cours. Se pose a la cession, jamais d'avance.

        Returns:
            Une detention prete a etre persistee.

        Raises:
            InvalidWindowError: si la fenetre est naive ou inversee.
        """
        _ensure_valid_window(start_at, end_at)
        return cls(
            id=uuid7(),
            animal_id=animal_id,
            account_id=account_id,
            start_at=start_at,
            end_at=end_at,
        )

    def is_open(self) -> bool:
        """Dit si la detention est OUVERTE : sans fin posee.

        C'est LE predicat de l'invariant « une seule active » -- exactement
        celui de l'index unique partiel (`WHERE end_at IS NULL`). Le domaine
        et la base ne peuvent pas diverger : ils testent la meme chose.

        Returns:
            Vrai si aucune fin n'est posee.
        """
        return self.end_at is None

    def is_active(self, at: datetime) -> bool:
        """Dit si la detention couvre l'instant donne.

        La question des actes passes : « qui detenait l'animal A CET
        INSTANT ». Pour la detention en cours, `is_open` est le bon predicat.

        Args:
            at: l'instant interroge -- celui des faits dans une question
                d'audit.

        Returns:
            Vrai si la fenetre `[start_at, end_at)` couvre l'instant.

        Raises:
            InvalidWindowError: si l'instant est naif.
        """
        ensure_aware_instant(at)
        return is_window_active(self.start_at, self.end_at, at)


def ensure_custody_openable(custodies: Sequence[Custody]) -> None:
    """Refuse d'ouvrir une detention tant qu'une autre reste ouverte.

    LA regle du ticket : un animal a UNE detention active a la fois
    (ADR-0006), « active » se jugeant sur le predicat OUVERTE (`end_at is
    None`) -- le meme que l'index unique partiel de `models.py`, pour que le
    domaine et la base repondent d'une seule voix. Tout cas d'usage createur
    de detention (BACK-30) DOIT l'appeler avant la fabrique : la regle donne
    un refus metier propre la ou l'index ne sait lever qu'une violation
    d'integrite. Le transfert clot l'ancienne detention PUIS ouvre la
    nouvelle, dans la meme transaction -- l'index partiel n'etant pas
    differable, l'ordre inverse echoue meme si la transaction finissait
    coherente.

    Elle est une fonction de service et non une methode, parce qu'aucune
    detention ne connait ses voisines : la liste vient du port de lecture.

    Args:
        custodies: les detentions deja enregistrees de l'animal, telles que
            rendues par le port de lecture.

    Raises:
        CustodyAlreadyActiveError: si une detention de la sequence est encore
            ouverte.
    """
    if any(custody.is_open() for custody in custodies):
        message = (
            "Ouverture refusee : l'animal a deja une detention ouverte -- "
            "une seule detention active a la fois."
        )
        raise CustodyAlreadyActiveError(message)
