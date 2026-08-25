"""Unite de travail du module organization (BACK-16).

A la RACINE du module, comme chez identity : l'unite de travail n'appartient ni
au domaine (elle manipule une transaction) ni tout a fait a l'infrastructure
(elle expose les depots au cas d'usage) -- elle est le point d'assemblage du
module, et la seule exemption du contrat `module-layers`.

    async with uow:
        memberships = await uow.memberships.list_active_for_account(account_id, at)
        await uow.commit()

LE NOM `OrganizationUnitOfWork` EST CELUI DU PORT, PAS DE CETTE CLASSE
Le port vit dans `domain/ports.py`, et c'est lui que les consommateurs
nomment ; l'implementation d'ici s'appelle `SqlAlchemyOrganizationUnitOfWork`.
NE JAMAIS IMPORTER CE FICHIER DEPUIS `application/` -- la dependance FastAPI
ci-dessous existe pour que l'assemblage se fasse dans la route ou au point de
composition, et nulle part ailleurs.
"""

from typing import Annotated

from fastapi import Depends, Request

from app.modules.organization.domain.ports import (
    AssignmentRepository,
    MembershipRepository,
    OrganizationUnitOfWork,
)
from app.modules.organization.infrastructure.db.repositories import (
    SqlAlchemyAssignmentRepository,
    SqlAlchemyMembershipRepository,
)
from app.shared.infrastructure.db.session import get_database
from app.shared.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


class SqlAlchemyOrganizationUnitOfWork(SqlAlchemyUnitOfWork, OrganizationUnitOfWork):
    """Unite de travail d'organization adossee a PostgreSQL.

    Tout le cycle de vie -- session par bloc, rollback de sortie, gardes --
    est herite de `SqlAlchemyUnitOfWork` ; ne vit ici que ce qui appartient au
    module : ses depots.
    """

    @property
    def memberships(self) -> MembershipRepository:
        """Le depot d'appartenances, servi par le bloc `async with` en cours.

        Une propriete PARESSEUSE : le depot est une enveloppe sans etat autour
        de la session du bloc, construite a l'acces -- il ne peut jamais etre
        servi hors d'un bloc ouvert, ni survivre a sa sortie.

        Returns:
            Le depot d'appartenances du bloc en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
        return SqlAlchemyMembershipRepository(self._active_session)

    @property
    def assignments(self) -> AssignmentRepository:
        """Le depot d'affectations, servi par le bloc `async with` en cours.

        Returns:
            Le depot d'affectations du bloc en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
        return SqlAlchemyAssignmentRepository(self._active_session)


async def get_organization_uow(request: Request) -> OrganizationUnitOfWork:
    """Fournit l'unite de travail d'organization de la requete en cours.

    UNE INSTANCE PAR REQUETE, livree FERMEE : la session ne s'ouvrira qu'au
    `async with` du consommateur. `get_organization_uow` et non `get_uow` --
    une unite par module, le nom porte la frontiere, comme `get_identity_uow`
    l'avait promis.

    Args:
        request: la requete en cours, d'ou l'on remonte aux ressources de
            persistance du processus.

    Returns:
        L'unite de travail du module, typee par son port.

    Raises:
        RuntimeError: si le `lifespan` n'a pas tourne.
    """
    return SqlAlchemyOrganizationUnitOfWork(get_database(request).sessionmaker)


# Alias a annoter les parametres de route : `uow: OrganizationUowDep`. Le type
# expose est le PORT : une route ne sait pas quelle technologie la sert, et
# BACK-06c pourra y substituer sa doublure sans toucher aux signatures.
OrganizationUowDep = Annotated[OrganizationUnitOfWork, Depends(get_organization_uow)]
