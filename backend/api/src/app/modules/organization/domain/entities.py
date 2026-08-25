"""Agregats du module organization (BACK-16).

`identity` repond a « peux-tu prouver qui tu es » ; ce module repond a « dans
quelle structure ce compte travaille-t-il, et affecte ou ». Quatre agregats :

- `Group` : LE TENANT, la frontiere d'isolation entre structures (ADR-0004).
  Une clinique travaillant seule est simplement un groupe d'une clinique.
- `Clinic` : N par groupe. Un perimetre de TRAVAIL, pas une frontiere de
  securite -- c'est le groupe qui isole, la clinique ne fait que situer.
- `Membership` (appartenance) : relation N:M DATEE entre un compte et un
  groupe, avec un role de perimetre groupe (ADR-0005). Un veterinaire
  remplacant intervient dans plusieurs groupes avec un seul compte : aucun
  `group_id` immuable n'existe sur le compte, et l'appartenance porte la date
  parce que la question d'audit est « ou travaillait-il A CET INSTANT ».
- `Assignment` (affectation) : relation N:M DATEE entre un compte et une
  clinique, avec un role metier de perimetre clinique. Elle est CONTRAINTE aux
  cliniques d'un groupe ou le compte detient une appartenance active --
  `ensure_assignment_allowed` fait respecter la regle.

LES ROLES SONT DEUX ENUMS, PAS UN
Le mot « role » designe deux choses distinctes dans ce projet : le role de
perimetre GROUPE (porte par le jeton, BACK-10a) et le role metier de perimetre
CLINIQUE (resolu a la requete, BACK-10c). Deux types separes font de la
confusion une erreur Mypy plutot qu'un bug d'autorisation. Le type de compte
(pro / particulier / admin), lui, reste dans identity et ne descend pas ici.

PAS DE `group_id` SUR `Clinic` NI SUR `Assignment`, ET C'EST DELIBERE
Ces deux agregats sont TENANT : leur colonne de groupe est estampillee par le
socle a l'insertion (BACK-06b), jamais par le mapping du module. `Membership`
est l'inverse exact : son `group_id` est la DONNEE elle-meme -- l'appartenance
ne vit pas dans la frontiere, elle la definit -- et l'entite le porte donc en
champ, comme troisieme contre-exemple qui vaut regle apres `Animal` et le
compte (docstring de `TenantMixin`).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Self
from uuid import UUID, uuid7

from app.modules.organization.domain.exceptions import (
    AssignmentOutsideMembershipError,
    InvalidWindowError,
)
from app.modules.organization.domain.policies import is_window_active


class GroupRole(StrEnum):
    """Role de perimetre GROUPE, porte par l'appartenance.

    C'est le role que le jeton embarque (claim `group_role`, BACK-10a) et que
    `require_role(scope="group")` lit sans requete (BACK-10c). `MANAGER` est le
    Gerant du cahier des charges : il gere le GROUPE, pas une clinique.
    `SUPERADMIN` est bien un role de perimetre groupe, cote interface
    d'administration -- pas un role de plateforme.
    """

    MANAGER = "manager"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class ClinicRole(StrEnum):
    """Role metier de perimetre CLINIQUE, porte par l'affectation.

    Resolu a la requete via le port d'affectation (`require_role`
    scope="clinic", BACK-10c), jamais depuis le jeton. `ASV` garde l'acronyme
    metier consacre -- auxiliaire specialise veterinaire -- plutot qu'une
    traduction que personne n'emploie.
    """

    VETERINARIAN = "veterinarian"
    ASV = "asv"


def ensure_aware_instant(at: datetime) -> None:
    """Refuse un instant de reference naif, avant qu'il ne fausse une reponse.

    La regle de `_ensure_valid_window`, etendue au parametre `at` des ports.
    Les deux chemins divergeraient sinon : le domaine leverait un `TypeError`
    brut a la comparaison, et le SQL accepterait l'instant EN SILENCE --
    PostgreSQL interprete un naif lie a un `timestamptz` dans le fuseau de la
    session, et une appartenance expiree redeviendrait active a deux heures
    pres. La garde est appelee par les entites ET par les adaptateurs : les
    deux chemins repondent d'une seule voix, en erreur metier.

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
    contrainte `ck_*_window_bounds` : des instants AVEC fuseau -- une borne
    naive rendrait `is_window_active` indecidable entre deux serveurs, le
    probleme exact que `TimestampMixin` ferme cote persistance -- et une fin
    strictement posterieure au debut, `[start_at, end_at)` etant demi-ouvert.

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


@dataclass(slots=True, kw_only=True)
class Group:
    """Structure veterinaire : LE tenant, la frontiere d'isolation.

    Construire l'objet directement est reserve a la RECONSTITUTION depuis la
    persistance ; une creation metier passe par `Group.create()`.
    """

    id: UUID
    name: str

    @classmethod
    def create(cls, *, name: str) -> Self:
        """Cree un groupe neuf, identifie par le domaine.

        Args:
            name: le nom de la structure, debarrasse de ses espaces de garde.

        Returns:
            Un groupe pret a etre persiste.
        """
        return cls(id=uuid7(), name=name.strip())


@dataclass(slots=True, kw_only=True)
class Clinic:
    """Lieu d'exercice d'un groupe : un perimetre de travail, pas de securite.

    PAS de champ de groupe : l'agregat est tenant, et l'estampillage est
    l'affaire du socle (BACK-06b), jamais de l'entite.
    """

    id: UUID
    name: str

    @classmethod
    def create(cls, *, name: str) -> Self:
        """Cree une clinique neuve, identifiee par le domaine.

        Args:
            name: le nom du lieu, debarrasse de ses espaces de garde.

        Returns:
            Une clinique prete a etre persistee, dans le groupe du contexte.
        """
        return cls(id=uuid7(), name=name.strip())


@dataclass(slots=True, kw_only=True)
class Membership:
    """Appartenance datee d'un compte a un groupe, avec son role de groupe.

    Le `group_id` est ici un CHAMP de l'entite -- la relation EST la donnee --
    a l'inverse des agregats tenant, ou la colonne de groupe appartient au
    socle. Les chevauchements d'appartenances restent possibles par
    construction (ADR-0005) : c'est le port de lecture qui desambiguise, et
    BACK-25 qui empechera d'en creer au sein d'un meme groupe.
    """

    id: UUID
    account_id: UUID
    group_id: UUID
    role: GroupRole
    start_at: datetime
    end_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        account_id: UUID,
        group_id: UUID,
        role: GroupRole,
        start_at: datetime,
        end_at: datetime | None = None,
    ) -> Self:
        """Cree une appartenance neuve, fenetre validee.

        Args:
            account_id: le compte concerne -- identifiant nu, jamais l'entite
                d'identity : les deux modules ne s'importent pas.
            group_id: le groupe rejoint.
            role: le role de perimetre groupe qui accompagne l'appartenance.
            start_at: le debut de validite, inclus.
            end_at: la fin de validite, exclue -- None pour une appartenance
                sans terme connu.

        Returns:
            Une appartenance prete a etre persistee.

        Raises:
            InvalidWindowError: si la fenetre est naive ou inversee.
        """
        _ensure_valid_window(start_at, end_at)
        return cls(
            id=uuid7(),
            account_id=account_id,
            group_id=group_id,
            role=role,
            start_at=start_at,
            end_at=end_at,
        )

    def is_active(self, at: datetime) -> bool:
        """Dit si l'appartenance est active a l'instant donne.

        Args:
            at: l'instant interroge -- celui de l'emission du jeton chez
                BACK-10a, celui des faits dans une question d'audit.

        Returns:
            Vrai si la fenetre `[start_at, end_at)` couvre l'instant.

        Raises:
            InvalidWindowError: si l'instant est naif.
        """
        ensure_aware_instant(at)
        return is_window_active(self.start_at, self.end_at, at)


@dataclass(slots=True, kw_only=True)
class Assignment:
    """Affectation datee d'un compte a une clinique, avec son role metier.

    PAS de champ de groupe : l'agregat est tenant, estampille par le socle.
    La coherence clinique/groupe est garantie deux fois -- par
    `ensure_assignment_allowed` dans le domaine, et par la cle etrangere
    composite de la table (`models.py`).
    """

    id: UUID
    account_id: UUID
    clinic_id: UUID
    role: ClinicRole
    start_at: datetime
    end_at: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        account_id: UUID,
        clinic_id: UUID,
        role: ClinicRole,
        start_at: datetime,
        end_at: datetime | None = None,
    ) -> Self:
        """Cree une affectation neuve, fenetre validee.

        La fabrique ne verifie PAS l'appartenance active : elle n'a pas les
        appartenances en main, et les lui passer ferait de chaque
        reconstitution un aller-retour de plus. C'est
        `ensure_assignment_allowed` qui porte cette regle, et tout cas d'usage
        createur d'affectation (BACK-25) DOIT l'appeler avant la fabrique.

        Args:
            account_id: le compte affecte -- identifiant nu, jamais l'entite
                d'identity.
            clinic_id: la clinique d'exercice.
            role: le role metier exerce dans cette clinique.
            start_at: le debut de validite, inclus.
            end_at: la fin de validite, exclue -- None pour une affectation
                sans terme connu.

        Returns:
            Une affectation prete a etre persistee, dans le groupe du contexte.

        Raises:
            InvalidWindowError: si la fenetre est naive ou inversee.
        """
        _ensure_valid_window(start_at, end_at)
        return cls(
            id=uuid7(),
            account_id=account_id,
            clinic_id=clinic_id,
            role=role,
            start_at=start_at,
            end_at=end_at,
        )

    def is_active(self, at: datetime) -> bool:
        """Dit si l'affectation est active a l'instant donne.

        Args:
            at: l'instant interroge.

        Returns:
            Vrai si la fenetre `[start_at, end_at)` couvre l'instant.

        Raises:
            InvalidWindowError: si l'instant est naif.
        """
        ensure_aware_instant(at)
        return is_window_active(self.start_at, self.end_at, at)


def ensure_assignment_allowed(
    memberships: Sequence[Membership],
    clinic_group_id: UUID,
    at: datetime,
) -> None:
    """Refuse une affectation vers une clinique hors appartenance active.

    LA regle du ticket : un compte ne peut etre affecte qu'aux cliniques d'un
    groupe ou il detient une appartenance ACTIVE a l'instant de la decision.
    Elle vit ici et non dans `policies.py`, parce qu'elle s'exprime sur des
    `Membership` -- une regle qui connait l'entite est un comportement du
    domaine de l'entite, pas une politique sur valeurs nues.

    Elle est une fonction de service et non une methode, parce qu'aucune des
    deux entites ne la contient : l'affectation ne connait pas les
    appartenances, et une appartenance seule ne sait rien de la clinique
    visee. Tout cas d'usage createur d'affectation (BACK-25) DOIT l'appeler ;
    la cle etrangere composite de `models.py` garantit de son cote la moitie
    structurelle -- clinique et affectation dans le meme groupe -- mais la
    moitie TEMPORELLE, « active a cet instant », n'est demontrable qu'ici.

    Args:
        memberships: les appartenances du compte a affecter, telles que rendues
            par le port de lecture.
        clinic_group_id: le groupe auquel appartient la clinique visee.
        at: l'instant de la decision d'affectation.

    Raises:
        InvalidWindowError: si l'instant est naif.
        AssignmentOutsideMembershipError: si aucune appartenance au groupe de
            la clinique n'est active a cet instant.
    """
    ensure_aware_instant(at)
    if any(
        membership.group_id == clinic_group_id and membership.is_active(at)
        for membership in memberships
    ):
        return
    message = (
        "Affectation refusee : le compte ne detient aucune appartenance active "
        "au groupe de la clinique visee."
    )
    raise AssignmentOutsideMembershipError(message)
