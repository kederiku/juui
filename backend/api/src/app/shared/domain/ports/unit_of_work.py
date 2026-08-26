"""Port de l'unite de travail -- la transaction sans la session (BACK-06a).

Le contrat, jamais son adaptateur : ce module ne connait ni SQLAlchemy, ni la
session, ni la configuration. C'est le but declare de BACK-06a -- la couche
application ouvre, valide ou annule une transaction sans jamais voir une
`AsyncSession` -- et le contrat `domain-purity` de BACK-04b le rend mecanique.

CE QUE L'UNITE DE TRAVAIL EST, ET CE QU'ELLE N'EST PAS
Un gestionnaire de contexte asynchrone qui delimite UNE transaction : ce que le
bloc `async with` ecrit tient ou tombe d'un seul tenant. Elle n'est PAS un
registre universel de depots : ce port ne declare aucun depot, parce qu'il y a
UNE UNITE DE TRAVAIL PAR MODULE, jamais une unite globale. Chaque module derive
son propre port -- `IdentityUnitOfWork` est le premier -- qui n'expose que les
depots de ce module. Ce qu'on ne peut pas placer dans une seule transaction
devient alors une frontiere VISIBLE plutot qu'une dette invisible que le
premier incident revelera.

LA TROISIEME REPONSE A LA PANNE
`Cache` DEGRADE, `FileStorage` LEVE ; l'unite de travail LEVE ET ANNULE. Un
`commit()` en echec remonte a l'appelant, et toute sortie de bloc sans commit
explicite -- exception comprise -- n'ecrit RIEN. Ce rollback automatique n'est
pas une consigne : il est code une fois pour toutes dans `__aexit__`, la seule
methode concrete du port, et chaque adaptateur en herite.

Usage cible, tel que BACK-04 le fixait deja :

    async with uow:
        account = await uow.accounts.get(account_id)
        account.verify_email()
        await uow.accounts.save(account)
        await uow.commit()
"""

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self


class AbstractUnitOfWork(ABC):
    """Delimite une transaction atomique, sans en exposer le mecanisme.

    TROIS REGLES QUI ENGAGENT L'APPELANT

    1. LE COMMIT EST EXPLICITE. Sortir du bloc sans `commit()` annule tout,
       exception ou pas : oublier de valider ne publie jamais un etat partiel.

    2. UN SEUL BLOC A LA FOIS. Entrer dans une unite deja ouverte est un defaut
       de programmation et leve `RuntimeError`. Rouvrir la MEME unite apres la
       sortie du bloc est en revanche permis : chaque entree recoit des
       ressources neuves.

    3. LA TRANSACTION VIT DANS LE BLOC. Hors du bloc, `commit()`, `rollback()`
       et les depots levent `RuntimeError` plutot que de laisser croire a une
       ecriture -- ou a une annulation -- qui n'a rien touche.
    """

    @abstractmethod
    async def __aenter__(self) -> Self:
        """Ouvre le bloc transactionnel et rend l'unite prete a l'usage.

        Returns:
            L'unite elle-meme, depots accessibles.

        Raises:
            RuntimeError: si un bloc est deja ouvert sur cette unite.
        """

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Annule ce qui n'a pas ete valide, puis libere les ressources du bloc.

        CONCRETE DANS LE PORT, A DESSEIN. Le rollback automatique est LA
        promesse de l'unite de travail ; une methode-gabarit l'impose a tous
        les adaptateurs -- celui de SQLAlchemy comme `InMemoryUnitOfWork`
        (BACK-06c) -- plutot que de la confier a leur discipline. Apres un
        `commit()` reussi, ce rollback ne trouve rien a annuler et reste sans
        effet.

        Rien n'est retourne : l'exception sortante, s'il y en a une, se propage
        toujours a l'appelant.

        Args:
            exc_type: le type de l'exception qui fait sortir du bloc, le cas
                echeant.
            exc: l'exception elle-meme.
            traceback: sa pile d'appels.
        """
        try:
            await self.rollback()
        finally:
            await self._release()

    @abstractmethod
    async def commit(self) -> None:
        """Valide la transaction : tout ce que le bloc a ecrit devient durable.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """

    @abstractmethod
    async def rollback(self) -> None:
        """Annule ce que le bloc a ecrit depuis le dernier commit.

        Rarement appele a la main : la sortie de bloc s'en charge deja. Il
        reste au contrat pour le cas d'usage qui veut annuler PUIS continuer
        dans le meme bloc.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """

    @abstractmethod
    async def _release(self) -> None:
        """Libere les ressources du bloc, apres le rollback de la sortie.

        Reserve a `__aexit__`, qui l'appelle toujours, meme quand le rollback
        leve. Les adaptateurs y referment ce qu'ils ont ouvert en `__aenter__`
        -- la session pour SQLAlchemy, rien pour une doublure en memoire -- et
        y remettent l'unite en etat d'etre rouverte.
        """
