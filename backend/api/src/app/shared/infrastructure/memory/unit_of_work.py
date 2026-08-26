"""Unite de travail en memoire -- la transaction, sans la base (BACK-06c).

C'est ICI que la promesse du port devient observable sans PostgreSQL : des
magasins par agregat, un commit qui les replie tous, un rollback qui jette tout,
et les memes gardes que l'adaptateur SQLAlchemy.

COMMIT ET ROLLBACK ONT UN EFFET REEL, ET C'EST LE PREMIER CRITERE DU TICKET
Une doublure dont le `rollback()` ne fait rien valide une semantique que la vraie
implementation ne tient pas -- c'est pire que pas de test. Le port l'a d'ailleurs
anticipe : son `__aexit__` est CONCRET, donc le rollback de sortie s'applique ici
sans qu'aucune ligne le redise, et une doublure ne peut pas naitre en l'oubliant.
Ce qui restait a ecrire est ce que le port ne pouvait pas ecrire a sa place :
que `commit()` et `rollback()` agissent VRAIMENT sur l'etat range.

UNE UNITE PAR MODULE, ICI AUSSI (ADR-0009)
Cette classe est complete mais ne sert a rien telle quelle : elle n'expose aucun
depot. Chaque module la derive avec son port d'unite de travail et n'y ajoute que
ses propres depots -- `InMemoryIdentityUnitOfWork` la premiere. La doublure ne
reunit pas ce que la production separe : une unite globale en memoire laisserait
ecrire dans une seule transaction ce que la production ne sait pas ecrire ainsi,
et les tests valideraient une atomicite qui n'existe pas.

CE QUE LES SOUS-CLASSES RECOIVENT
Deux choses. `_new_store()`, a appeler dans leur `__init__` pour declarer un
magasin par agregat -- c'est ce qui les fait entrer dans le commit atomique.
Et `_require_open()`, la garde a poser en tete de chaque propriete de depot :
elle joue le role de `_active_session` cote SQLAlchemy, et repasse a chaque acces
pour qu'un depot ne puisse jamais etre servi hors d'un bloc ouvert ni survivre a
sa sortie.
"""

from collections.abc import Callable
from copy import deepcopy
from typing import Any, Self

from app.shared.domain.ports.repository import Identified
from app.shared.domain.ports.unit_of_work import AbstractUnitOfWork
from app.shared.infrastructure.memory.repository import InMemoryStore


class InMemoryUnitOfWork(AbstractUnitOfWork):
    """Unite de travail adossee a des dictionnaires, une transaction par bloc.

    Les trois regles du port sont tenues a l'identique de l'adaptateur reel : le
    commit est explicite, un seul bloc a la fois, et la transaction vit dans le
    bloc.
    """

    def __init__(self) -> None:
        """Construit l'unite, magasins vides, aucun bloc ouvert.

        Construire ne coute rien et n'engage rien, exactement comme cote
        SQLAlchemy ou la session n'existe qu'entre `__aenter__` et la sortie du
        bloc. Les MAGASINS, eux, survivent aux blocs : ils tiennent lieu de base
        de donnees, et une base ne disparait pas a la fermeture d'une session.
        """
        self._stores: list[InMemoryStore[Any]] = []
        self._open = False
        self.commits = 0
        """Nombre de commits reussis depuis la construction.

        Un compteur et non un booleen : « le cas d'usage a-t-il valide UNE fois ? »
        est une assertion courante, et « deux fois » est un defaut qu'un booleen
        laisserait passer.
        """

    def _new_store[EntityT: Identified](
        self, *, copy: Callable[[EntityT], EntityT] = deepcopy
    ) -> InMemoryStore[EntityT]:
        """Declare un magasin d'agregat et l'inscrit au commit atomique.

        A appeler depuis le `__init__` de la sous-classe, une fois par agregat.
        Un magasin construit sans passer par ici ne serait ni commite ni annule
        avec les autres -- c'est-a-dire une transaction qui ne couvre qu'une
        partie de ce que le bloc a ecrit.

        Args:
            copy: la fonction qui duplique une entite de cet agregat. `deepcopy`
                par defaut ; a ne remplacer que pour une raison ecrite.

        Returns:
            Le magasin, vide, deja rattache a l'unite.
        """
        store: InMemoryStore[EntityT] = InMemoryStore(copy=copy)
        self._stores.append(store)
        return store

    def _require_open(self) -> None:
        """Refuse tout acces a un depot hors d'un bloc ouvert.

        La garde de la regle 3 du port -- la transaction vit dans le bloc -- et le
        pendant exact de la propriete `_active_session`. A poser en tete de chaque
        propriete de depot des sous-classes.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
        if not self._open:
            message = (
                "Aucune transaction en cours : l'unite de travail ne sert "
                "que dans son bloc async with."
            )
            raise RuntimeError(message)

    async def __aenter__(self) -> Self:
        """Ouvre le bloc transactionnel.

        Returns:
            L'unite elle-meme, depots accessibles.

        Raises:
            RuntimeError: si un bloc est deja ouvert sur cette unite.
        """
        if self._open:
            message = "Cette unite de travail est deja ouverte : un seul bloc a la fois."
            raise RuntimeError(message)
        self._open = True
        return self

    async def commit(self) -> None:
        """Valide la transaction : ce que le bloc a ecrit devient l'etat range.

        TOUS LES MAGASINS OU AUCUN. La boucle ne peut pas echouer a mi-chemin --
        replier un dictionnaire ne leve pas --, ce qui donne ici l'atomicite que
        la transaction donne la-bas.

        Un bloc peut commiter PUIS continuer a travailler : ce qui suit forme une
        nouvelle transaction, que la sortie de bloc annulera si elle n'est pas
        validee a son tour. Meme comportement que la session SQLAlchemy, et c'est
        pourquoi aucun drapeau « deja commite » n'existe ici.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
        self._require_open()
        for store in self._stores:
            store.commit()
        self.commits += 1

    async def rollback(self) -> None:
        """Annule ce que le bloc a ecrit depuis le dernier commit.

        Rarement appele a la main : la sortie de bloc s'en charge deja. Apres un
        commit, il ne trouve rien a annuler et reste sans effet -- c'est ce qui
        rend le rollback de sortie inconditionnel.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
        self._require_open()
        for store in self._stores:
            store.rollback()

    async def _release(self) -> None:
        """Referme le bloc et remet l'unite en etat d'etre rouverte.

        Appele par `__aexit__` APRES le rollback, toujours, meme quand celui-ci
        leve. Les magasins, eux, ne sont pas vides : ils portent l'etat VALIDE,
        qui doit survivre au bloc comme une base survit a une session -- c'est
        exactement ce qu'un test relit apres la sortie pour prouver qu'un commit
        a eu lieu.
        """
        self._open = False
