"""Ports metier du module identity (BACK-04, unite de travail en BACK-06a).

Un port est un BESOIN exprime par le domaine, jamais une technologie. Celui-ci
dit « je dois pouvoir retrouver et enregistrer un compte » ; il ne dit ni
PostgreSQL, ni SQLAlchemy, ni meme « base de donnees ». L'adaptateur qui le
remplit vit dans `infrastructure/db/repositories.py`, et un second adaptateur en
memoire lui repondra pour les tests (BACK-06c) sans qu'une ligne de metier
change.

POURQUOI CES PORTS-LA SONT DANS LE DOMAINE DU MODULE
`AccountRepository` et `IdentityUnitOfWork` parlent de comptes : ce sont des
ports METIER, ils appartiennent a `identity`. Les ports TECHNIQUES -- cache,
stockage de fichiers, jetons -- vivent dans `shared/domain/ports/`, sans quoi le
premier module a en avoir besoin deviendrait une dependance de tous les autres.

CE QUE BACK-06A A CHANGE ICI
Le cas d'usage recoit desormais `IdentityUnitOfWork` -- le port d'unite de
travail du module -- plutot qu'un depot nu, et l'implementation du depot herite
du depot generique de `shared/`. Le contrat d'`AccountRepository`, lui, n'a pas
bouge : c'est precisement ce qu'un port doit permettre. Seule retouche de
forme : les arguments de `get`, `add` et `save` sont devenus positionnels
(`/`), pour que le vocabulaire du port (`account_id`) et celui du generique
(`entity_id`) ne puissent jamais diverger dans un appel par mot-cle que Mypy
ne verifie pas. `find_by_email`, propre au module, garde sa forme.
"""

from abc import ABC, abstractmethod
from uuid import UUID

from app.modules.identity.domain.entities import Account
from app.shared.domain.ports.unit_of_work import AbstractUnitOfWork


class AccountRepository(ABC):
    """Acces aux comptes, exprime en entites du domaine.

    Toutes les methodes echangent des `Account` -- jamais un modele SQLAlchemy,
    jamais un dictionnaire. C'est la frontiere ou le mapping s'applique, et
    c'est ce qui permet au cas d'usage d'ignorer jusqu'a l'existence d'un ORM.

    Le port n'expose QUE ce que les cas d'usage du module ont le droit de
    faire. L'implementation, qui herite du depot generique de `shared/`, sait
    aussi lister et supprimer : le port ne s'elargit pas parce que la classe
    sait faire plus.
    """

    @abstractmethod
    async def get(self, account_id: UUID, /) -> Account:
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
    async def add(self, account: Account, /) -> None:
        """Enregistre un compte qui n'existait pas.

        Args:
            account: le compte a creer.
        """

    @abstractmethod
    async def save(self, account: Account, /) -> None:
        """Reporte sur la persistance l'etat d'un compte deja connu.

        Args:
            account: le compte modifie.
        """


class IdentityUnitOfWork(AbstractUnitOfWork):
    """Unite de travail du module : sa transaction, ses depots, rien d'autre.

    UNE UNITE DE TRAVAIL PAR MODULE, et jamais une unite globale. Ce qu'on ne
    peut pas placer dans une seule transaction devient alors une frontiere
    VISIBLE -- `identity` et `organization` ne partagent pas leur atomicite --
    plutot qu'une dette invisible que le premier incident revelera.

    C'est CE type que recoivent les cas d'usage, et la raison est mecanique
    autant qu'architecturale : l'implementation vit a la racine du module et
    importe l'infrastructure ; un cas d'usage qui la nommerait creerait la
    chaine `application -> infrastructure` que le contrat `module-layers` de
    BACK-04b refuse. Le port, lui, ne connait que le domaine.

    LES DEPOTS SONT DES PROPRIETES, PAS DES ATTRIBUTS. Un attribut pose a
    l'entree du bloc survivrait a sa sortie, depot mort en main ; une propriete
    repasse par la garde de l'unite a chaque acces, et lever hors bloc reste
    ainsi la regle 3 du port, partout.
    """

    @property
    @abstractmethod
    def accounts(self) -> AccountRepository:
        """Le depot de comptes, servi par le bloc `async with` en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
