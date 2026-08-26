"""Unite de travail du module identity -- livree par BACK-06a.

Le fichier est cree par BACK-04 pour fixer sa place : a la RACINE du module, et
non dans une couche. L'unite de travail n'appartient ni au domaine (elle
manipule une transaction) ni tout a fait a l'infrastructure (elle expose les
depots au cas d'usage) : elle est le point d'assemblage du module.

    async with uow:
        account = await uow.accounts.get(account_id)
        account.verify_email()
        await uow.accounts.save(account)
        await uow.commit()

LE NOM `IdentityUnitOfWork` EST CELUI DU PORT, PAS DE CETTE CLASSE
Le port vit dans `domain/ports.py`, et c'est lui que les cas d'usage nomment ;
l'implementation d'ici s'appelle `SqlAlchemyIdentityUnitOfWork`, comme
`SqlAlchemyAccountRepository` repond a `AccountRepository`. La raison est
mecanique : ce fichier importe l'infrastructure, et un cas d'usage qui
l'importerait creerait la chaine `application -> infrastructure` que le
contrat `module-layers` de BACK-04b refuse. NE JAMAIS IMPORTER CE FICHIER
DEPUIS `application/` -- la dependance FastAPI ci-dessous existe pour que
l'assemblage se fasse dans la route, et nulle part ailleurs.

UNE UNITE DE TRAVAIL PAR MODULE, et jamais une unite globale : le paragraphe
fondateur est passe sur le port, ou il engage desormais tous les adaptateurs.
"""

from typing import Annotated

from fastapi import Depends, Request

from app.modules.identity.domain.ports import AccountRepository, IdentityUnitOfWork
from app.modules.identity.infrastructure.db.repositories import SqlAlchemyAccountRepository
from app.shared.infrastructure.db.session import get_database
from app.shared.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


class SqlAlchemyIdentityUnitOfWork(SqlAlchemyUnitOfWork, IdentityUnitOfWork):
    """Unite de travail d'identity adossee a PostgreSQL.

    Tout le cycle de vie -- session par bloc, rollback de sortie, gardes --
    est herite de `SqlAlchemyUnitOfWork` ; ne vit ici que ce qui appartient au
    module : ses depots.
    """

    @property
    def accounts(self) -> AccountRepository:
        """Le depot de comptes, servi par le bloc `async with` en cours.

        Une propriete PARESSEUSE : le depot est une enveloppe sans etat autour
        de la session du bloc, construite a l'acces. Elle repasse ainsi par la
        garde a chaque lecture -- un depot ne peut jamais etre servi hors d'un
        bloc ouvert, ni survivre a sa sortie.

        Returns:
            Le depot de comptes du bloc en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
        return SqlAlchemyAccountRepository(self._active_session)


async def get_identity_uow(request: Request) -> IdentityUnitOfWork:
    """Fournit l'unite de travail d'identity de la requete en cours.

    UNE INSTANCE PAR REQUETE : FastAPI memorise le resultat d'une dependance le
    temps d'une requete, jamais au-dela. L'unite livree est FERMEE -- la
    session ne s'ouvrira qu'au `async with` du cas d'usage -- ce qui dispense
    de tout finaliseur : une requete abandonnee avant le bloc n'a rien a
    nettoyer, et une requete annulee en plein bloc voit `__aexit__` derouler
    rollback et fermeture au depilement.

    `get_identity_uow` et non `get_uow` : une unite par module, le nom porte la
    frontiere. `organization` publie la sienne, `get_organization_uow` (BACK-16).

    Args:
        request: la requete en cours, d'ou l'on remonte aux ressources de
            persistance du processus.

    Returns:
        L'unite de travail du module, typee par son port.

    Raises:
        RuntimeError: si le `lifespan` n'a pas tourne.
    """
    return SqlAlchemyIdentityUnitOfWork(get_database(request).sessionmaker)


# Alias a annoter les parametres de route : `uow: IdentityUowDep`, sur le
# modele de `SettingsDep` (BACK-08). Le type expose est le PORT : une route ne
# sait pas quelle technologie la sert, et `InMemoryIdentityUnitOfWork` (BACK-06c)
# s'y substitue sans toucher aux signatures.
IdentityUowDep = Annotated[IdentityUnitOfWork, Depends(get_identity_uow)]
