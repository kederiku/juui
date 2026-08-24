"""Ports metier du module identity (BACK-04).

Un port est un BESOIN exprime par le domaine, jamais une technologie. Celui-ci
dit « je dois pouvoir retrouver et enregistrer un compte » ; il ne dit ni
PostgreSQL, ni SQLAlchemy, ni meme « base de donnees ». L'adaptateur qui le
remplit vit dans `infrastructure/db/repositories.py`, et un second adaptateur en
memoire lui repondra pour les tests (BACK-06c) sans qu'une ligne de metier
change.

POURQUOI CE PORT-LA EST DANS LE DOMAINE DU MODULE
`AccountRepository` parle de comptes : c'est un port METIER, il appartient a
`identity`. Les ports TECHNIQUES -- cache, stockage de fichiers, jetons -- vivent
dans `shared/domain/ports/`, sans quoi le premier module a en avoir besoin
deviendrait une dependance de tous les autres.

CE QUE BACK-06a CHANGERA ICI
Le cas d'usage recevra une unite de travail plutot que ce depot nu, et
l'implementation heritera du depot generique. Le contrat ci-dessous, lui, ne
bouge pas : c'est precisement ce qu'un port doit permettre.
"""

from abc import ABC, abstractmethod
from uuid import UUID

from app.modules.identity.domain.entities import Account


class AccountRepository(ABC):
    """Acces aux comptes, exprime en entites du domaine.

    Toutes les methodes echangent des `Account` -- jamais un modele SQLAlchemy,
    jamais un dictionnaire. C'est la frontiere ou le mapping s'applique, et
    c'est ce qui permet au cas d'usage d'ignorer jusqu'a l'existence d'un ORM.
    """

    @abstractmethod
    async def get(self, account_id: UUID) -> Account:
        """Retourne le compte portant cet identifiant.

        Args:
            account_id: l'identifiant du compte.

        Returns:
            Le compte reconstitue.

        Raises:
            AccountNotFoundError: si aucun compte ne porte cet identifiant. Une
                absence est ici une ERREUR : l'appelant tient l'identifiant d'un
                jeton ou d'une URL, il attend le compte, pas un `None` a tester.
        """

    @abstractmethod
    async def find_by_email(self, email: str) -> Account | None:
        """Cherche un compte par son adresse, sans erreur si rien ne correspond.

        `find_` et non `get_` : ici l'absence est un RESULTAT ATTENDU -- c'est ce
        qu'interroge un controle d'unicite avant creation.

        Args:
            email: l'adresse, deja normalisee par le domaine.

        Returns:
            Le compte, ou None si l'adresse est libre.
        """

    @abstractmethod
    async def add(self, account: Account) -> None:
        """Enregistre un compte qui n'existait pas.

        Args:
            account: le compte a creer.
        """

    @abstractmethod
    async def save(self, account: Account) -> None:
        """Reporte sur la persistance l'etat d'un compte deja connu.

        Args:
            account: le compte modifie.
        """
