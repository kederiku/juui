"""Schemas d'API du module identity (BACK-04).

PREMIER des trois modeles du guide DDD : ce que le client envoie et ce qu'il
recoit, en JSON. Leur role s'arrete la -- valider, mettre en forme, documenter
le contrat OpenAPI. Aucune regle metier n'a sa place ici : une contrainte
exprimee en `Field(...)` protege la frontiere HTTP, elle ne remplace pas
l'invariant que l'entite fait respecter pour tous les appelants.

LE MAPPING EST ECRIT A LA MAIN
`CreateAccountCommand(**self.model_dump())` fonctionnerait aujourd'hui et
casserait le jour ou un champ change de nom d'un cote seulement -- en silence,
ou en remplissant la commande de valeurs inattendues. Les deux methodes
ci-dessous rendent la traduction visible, et Mypy la verifie.
"""

from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.identity.application.use_cases.create_account import CreateAccountCommand
from app.modules.identity.domain.entities import Account, AccountStatus, AccountType


class AccountCreate(BaseModel):
    """Corps de requete d'une creation de compte."""

    # `extra="forbid"` : un champ inconnu est REFUSE plutot qu'ignore. Sans lui,
    # une faute de frappe cote client (`firstname` au lieu de `first_name`)
    # produirait un compte au prenom vide, sans le moindre message d'erreur.
    model_config = ConfigDict(extra="forbid")

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)

    # `str` et non `EmailStr` : `email-validator`, dont depend `EmailStr`, n'est
    # pas une dependance declaree du projet. La validation de forme relevera de
    # BACK-28, avec le parcours d'inscription qui en a besoin.
    email: str = Field(min_length=3, max_length=320)

    phone: str | None = Field(default=None, max_length=30)
    account_type: AccountType

    def to_command(self) -> CreateAccountCommand:
        """Traduit le corps de requete en intention applicative.

        Returns:
            La commande attendue par le cas d'usage, sans aucun vocabulaire HTTP.
        """
        return CreateAccountCommand(
            email=self.email,
            first_name=self.first_name,
            last_name=self.last_name,
            account_type=self.account_type,
            phone=self.phone,
        )


class AccountRead(BaseModel):
    """Representation d'un compte telle qu'elle est renvoyee au client."""

    id: UUID
    email: str
    first_name: str
    last_name: str
    phone: str | None
    account_type: AccountType
    status: AccountStatus
    email_verified: bool

    @classmethod
    def from_entity(cls, account: Account) -> Self:
        """Met en forme une entite du domaine pour la reponse HTTP.

        Le choix des champs EXPOSES se fait ici, et c'est ce qui en fait le bon
        endroit : la minimisation des donnees (BACK-26) se decide a la sortie,
        pas dans l'entite, qui doit rester complete pour le metier.

        Args:
            account: le compte a representer.

        Returns:
            Le schema de lecture correspondant.
        """
        return cls(
            id=account.id,
            email=account.email,
            first_name=account.first_name,
            last_name=account.last_name,
            phone=account.phone,
            account_type=account.account_type,
            status=account.status,
            email_verified=account.email_verified,
        )
