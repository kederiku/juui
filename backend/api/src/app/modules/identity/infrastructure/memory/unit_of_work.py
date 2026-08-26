"""Unite de travail d'identity en memoire (BACK-06c).

Le pendant de `SqlAlchemyIdentityUnitOfWork`, adosse a des dictionnaires. Tout le
cycle de vie -- gardes de bloc, commit qui replie les magasins, rollback qui les
jette -- est herite d'`InMemoryUnitOfWork` ; ne vit ici que ce qui appartient au
module : son depot.

ELLE VIT SOUS `infrastructure/memory/` ET NON A LA RACINE DU MODULE
`unit_of_work.py` a la racine est le point d'ASSEMBLAGE du module -- il choisit
l'implementation de production et publie la dependance FastAPI. Celle-ci est une
implementation parmi d'autres, au meme titre que l'adaptateur SQLAlchemy sous
`infrastructure/db/` : elle se range avec les autres adaptateurs. Le contrat
`module-layers` l'exige d'ailleurs -- `unit_of_work` est sa SEULE exemption de
couche, et une seconde exemption serait une couche clandestine.

CE QUE LE PORT PUBLIE RESTE `IdentityUnitOfWork`, ici comme la-bas : un cas
d'usage recoit le port, et substituer cette doublure ne touche aucune signature.
C'est ce que les commentaires d'`IdentityUowDep` annoncaient depuis BACK-06a.
"""

from collections.abc import Iterable

from app.modules.identity.domain.entities import Account
from app.modules.identity.domain.ports import AccountRepository, IdentityUnitOfWork
from app.modules.identity.infrastructure.memory.repositories import InMemoryAccountRepository
from app.shared.infrastructure.memory.repository import InMemoryStore
from app.shared.infrastructure.memory.unit_of_work import InMemoryUnitOfWork


class InMemoryIdentityUnitOfWork(InMemoryUnitOfWork, IdentityUnitOfWork):
    """Unite de travail d'identity adossee a la memoire du processus."""

    def __init__(self, accounts: Iterable[Account] = ()) -> None:
        """Declare le magasin du module et y seme l'etat valide initial.

        Args:
            accounts: les comptes a poser comme deja persistes. Ils sont copies :
                ce que l'appelant garde en main ne peut pas toucher l'etat range.
        """
        super().__init__()
        self._accounts: InMemoryStore[Account] = self._new_store()
        for account in accounts:
            self._accounts.seed(account)

    @property
    def accounts(self) -> AccountRepository:
        """Le depot de comptes, servi par le bloc `async with` en cours.

        Une propriete PARESSEUSE : le depot est une enveloppe sans etat autour du
        magasin, construite a l'acces. Elle repasse ainsi par la garde a chaque
        lecture -- un depot ne peut jamais etre servi hors d'un bloc ouvert, ni
        survivre a sa sortie. Meme forme, meme garantie que cote SQLAlchemy.

        Returns:
            Le depot de comptes du bloc en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
        self._require_open()
        return InMemoryAccountRepository(self._accounts)

    @property
    def accounts_store(self) -> InMemoryStore[Account]:
        """Le magasin des comptes, pour relire l'etat VALIDE hors de tout bloc.

        C'est ce qu'un test interroge apres la sortie du bloc :
        `uow.accounts_store.committed_entity(account_id)` rend ce qui a
        reellement ete commite, la ou `uow.accounts` refuserait de repondre hors
        bloc -- et c'est bien ce qu'on veut lui faire dire.

        Returns:
            Le magasin des comptes.
        """
        return self._accounts
