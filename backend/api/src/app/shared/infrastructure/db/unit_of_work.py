"""Adaptateur SQLAlchemy de l'unite de travail (BACK-06a).

C'est ICI que la promesse du port devient du code : une session par bloc
`async with`, un rollback a chaque sortie, et une couche application qui ne
voit jamais passer une `AsyncSession`.

LA FABRIQUE, JAMAIS UNE SESSION
Le constructeur recoit l'`async_sessionmaker` livre par BACK-05 -- l'unite de
travail en est le premier consommateur reel, comme `session.py` l'annoncait.
Recevoir une session deja ouverte remettrait a l'appelant la decision que ce
module existe pour porter : quand elle s'ouvre, quand elle se ferme.

UNE SESSION PAR BLOC, MECANIQUEMENT
`session.py` documente le piege : une session reutilisee d'un bloc a l'autre
ressert son identity map sans relire la base. Ici, chaque `__aenter__` fabrique
une session NEUVE et chaque sortie de bloc la ferme definitivement
(`close_resets_only=False`) : un depot capture dans un bloc et rejoue apres la
sortie leve une erreur SQLAlchemy au lieu de rouvrir une connexion en douce.

CE QUE LES SOUS-CLASSES RECOIVENT
Une seule chose : la propriete `_active_session`, qui rend la session du bloc
courant ou leve hors bloc. Les unites de travail de module (une par module,
`SqlAlchemyIdentityUnitOfWork` la premiere) y adossent leurs depots en
PROPRIETES paresseuses -- jamais en attributs poses a l'entree du bloc, qui
survivraient a la sortie avec une session morte entre les mains.

Piege BACK-05, toujours vrai ici : `rollback()` perime les instances suivies.
Ce qui doit etre journalise apres une annulation se capture AVANT.
"""

from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.shared.domain.ports.unit_of_work import AbstractUnitOfWork


class SqlAlchemyUnitOfWork(AbstractUnitOfWork):
    """Unite de travail adossee a une session SQLAlchemy, une par bloc.

    La classe est complete mais ne sert a rien telle quelle : elle n'expose
    aucun depot. Chaque module la derive avec son port d'unite de travail et
    n'y ajoute que ses propres depots.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """Memorise la fabrique de sessions, sans rien ouvrir.

        Construire l'unite ne coute rien et n'engage rien : la session n'existe
        qu'entre `__aenter__` et la sortie du bloc. C'est ce qui permet a la
        dependance FastAPI d'en livrer une par requete sans finaliseur.

        Args:
            session_factory: la fabrique livree par `build_sessionmaker`
                (BACK-05), partagee pour toute la duree du processus.
        """
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> Self:
        """Ouvre le bloc transactionnel sur une session neuve.

        Returns:
            L'unite elle-meme, depots accessibles.

        Raises:
            RuntimeError: si un bloc est deja ouvert sur cette unite.
        """
        if self._session is not None:
            message = "Cette unite de travail est deja ouverte : un seul bloc a la fois."
            raise RuntimeError(message)
        self._session = self._session_factory(close_resets_only=False)
        return self

    async def commit(self) -> None:
        """Valide la transaction du bloc courant.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
        await self._active_session.commit()

    async def rollback(self) -> None:
        """Annule ce que le bloc courant a ecrit depuis le dernier commit.

        Apres un commit, la session n'a pas rouvert de transaction tant que
        rien n'a ete relu ou reecrit : ce rollback est alors un geste vide,
        sans SQL emis. C'est ce qui rend le rollback de sortie inconditionnel
        -- et un drapeau « deja commite » non seulement inutile mais faux, un
        bloc pouvant commiter PUIS continuer a travailler.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
        await self._active_session.rollback()

    async def _release(self) -> None:
        """Referme la session du bloc et remet l'unite en etat d'etre rouverte.

        `_session` est remis a `None` AVANT le `close()` : si la fermeture
        leve, l'unite reste saine et reouvrable, plutot que coincee sur une
        session moribonde.
        """
        session = self._active_session
        self._session = None
        await session.close()

    @property
    def _active_session(self) -> AsyncSession:
        """Rend la session du bloc courant, ou leve hors bloc.

        C'est la garde de la regle 3 du port -- la transaction vit dans le
        bloc -- et le SEUL acces que les sous-classes ont a la session : leurs
        depots la traversent a chaque lecture, donc un depot ne peut jamais
        etre servi hors d'un bloc ouvert.

        Returns:
            La session du bloc en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
        if self._session is None:
            message = (
                "Aucune transaction en cours : l'unite de travail ne sert "
                "que dans son bloc async with."
            )
            raise RuntimeError(message)
        return self._session
