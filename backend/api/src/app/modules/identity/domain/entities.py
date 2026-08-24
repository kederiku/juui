"""Agregat `Account` du module identity (BACK-04).

L'entite du guide DDD : une dataclass, ZERO dependance technique, et des
comportements. Elle ne connait ni FastAPI, ni SQLAlchemy, ni Pydantic -- pas
plus qu'elle ne connait sa propre table. C'est ce qui la rend testable sans
Docker et reutilisable depuis une tache de fond ou une commande en ligne.

CE QUE PORTE `Account`, ET CE QU'IL NE PORTE PAS
Le compte porte le minimum permettant d'IDENTIFIER une personne -- nom, prenom,
adresse, telephone -- plus son type, son statut et l'etat de verification de son
adresse. L'adresse postale vit dans le module `profile` (BACK-32), les
preferences de notification dans `notifications` (BACK-22), et les animaux dans
`medical_records` (BACK-19).

Surtout, il ne porte AUCUN `group_id`. L'appartenance a une structure est une
relation N:M DATEE, portee par le module `organization` (BACK-16) : un
veterinaire remplacant intervient dans plusieurs groupes avec un seul compte, et
un champ immuable sur le compte l'aurait interdit des le premier jour.

CE QUE LES TICKETS SUIVANTS AJOUTERONT ICI
Le mot de passe hache, sous forme d'objet-valeur (BACK-10b) ; l'etat de la
double authentification (BACK-18). L'etat de verification est deja la : BACK-17
le fera evoluer par OTP.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Self
from uuid import UUID, uuid4

from app.modules.identity.domain.exceptions import (
    EmailAlreadyVerifiedError,
    InvalidStatusTransitionError,
)
from app.modules.identity.domain.policies import normalize_email, normalize_phone


class AccountType(StrEnum):
    """Nature du compte, et donc parcours par lequel il a ete cree.

    Ce n'est PAS un decoupage de modules : les trois applications frontend
    partagent le meme coeur d'authentification, et c'est l'audience du jeton
    (BACK-10a) qui les separe, pas trois copies du module identity.
    """

    PROFESSIONAL = "professional"
    INDIVIDUAL = "individual"
    ADMIN = "admin"


class AccountStatus(StrEnum):
    """Etat d'exploitation du compte.

    A ne pas confondre avec la verification de l'adresse e-mail, qui est un
    champ distinct : un compte non verifie reste ACTIF et peut s'authentifier --
    il est simplement retenu sur l'ecran de verification (BACK-10c, BACK-17).
    Les melanger enfermerait dehors l'utilisateur qui vient de s'inscrire, sans
    aucun moyen de demander un nouveau code.
    """

    ACTIVE = "active"
    SUSPENDED = "suspended"


# Transitions de statut admises. La table vit ICI et non dans `policies.py` :
# c'est un invariant de l'agregat, que l'agregat fait respecter lui-meme. Une
# regle dont l'entite delegue le respect a l'exterieur est le premier pas vers
# l'entite anemique que le guide DDD proscrit.
_ALLOWED_TRANSITIONS: Final[dict[AccountStatus, frozenset[AccountStatus]]] = {
    AccountStatus.ACTIVE: frozenset({AccountStatus.SUSPENDED}),
    AccountStatus.SUSPENDED: frozenset({AccountStatus.ACTIVE}),
}


@dataclass(slots=True, kw_only=True)
class Account:
    """Compte d'acces au service, quelle que soit l'application qui le sert.

    Construire l'objet directement est reserve a la RECONSTITUTION depuis la
    persistance -- c'est ce que fait le depot en relisant une ligne. Une
    creation metier passe par `Account.create()`, qui seule applique les regles
    de normalisation et fixe l'etat initial.
    """

    id: UUID
    email: str
    first_name: str
    last_name: str
    account_type: AccountType
    phone: str | None = None
    status: AccountStatus = AccountStatus.ACTIVE
    email_verified: bool = False

    @classmethod
    def create(
        cls,
        *,
        email: str,
        first_name: str,
        last_name: str,
        account_type: AccountType,
        phone: str | None = None,
    ) -> Self:
        """Cree un compte neuf, normalise et pret a etre persiste.

        L'identifiant est tire ICI, dans le domaine, et non par la base : le cas
        d'usage dispose ainsi de l'identifiant avant tout aller-retour SQL, ce
        qui lui permet d'emettre un evenement ou de composer une reponse sans
        attendre le `commit`.

        Args:
            email: l'adresse telle que saisie ; elle est normalisee.
            first_name: le prenom.
            last_name: le nom.
            account_type: la nature du compte.
            phone: le telephone, facultatif ; il est normalise.

        Returns:
            Un compte ACTIF, dont l'adresse n'est pas encore verifiee.
        """
        return cls(
            id=uuid4(),
            email=normalize_email(email),
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            account_type=account_type,
            phone=normalize_phone(phone),
            status=AccountStatus.ACTIVE,
            email_verified=False,
        )

    @property
    def full_name(self) -> str:
        """Prenom et nom, dans l'ordre d'affichage."""
        return f"{self.first_name} {self.last_name}".strip()

    def verify_email(self) -> None:
        """Marque l'adresse comme verifiee, a l'issue du parcours OTP (BACK-17).

        Raises:
            EmailAlreadyVerifiedError: si l'adresse est deja verifiee. Le refus
                est explicite plutot qu'idempotent : un second appel signale un
                code rejoue ou un double envoi, ce que l'appelant doit voir.
        """
        if self.email_verified:
            message = "L'adresse de ce compte est deja verifiee."
            raise EmailAlreadyVerifiedError(message)
        self.email_verified = True

    def suspend(self) -> None:
        """Suspend le compte : il existe toujours, il ne peut plus servir."""
        self._change_status(AccountStatus.SUSPENDED)

    def reactivate(self) -> None:
        """Rend un compte suspendu a l'exploitation."""
        self._change_status(AccountStatus.ACTIVE)

    def _change_status(self, target: AccountStatus) -> None:
        """Applique une transition de statut si la table l'autorise.

        Args:
            target: le statut demande.

        Raises:
            InvalidStatusTransitionError: si la transition n'est pas admise --
                y compris d'un statut vers lui-meme, qui trahit toujours un
                appel en trop plutot qu'une intention.
        """
        if target not in _ALLOWED_TRANSITIONS[self.status]:
            message = f"Transition de statut interdite : {self.status} -> {target}."
            raise InvalidStatusTransitionError(message)
        self.status = target
