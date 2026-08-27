"""Unite de travail du module scheduling (BACK-21).

A la RACINE du module, comme chez identity, organization, medical_records et
notifications : l'unite de travail n'appartient ni au domaine (elle manipule une
transaction) ni tout a fait a l'infrastructure (elle expose le depot au cas
d'usage) -- elle est le point d'assemblage du module, et la seule exemption du
contrat `module-layers`.

    async with uow:
        profiles = await uow.practitioner_profiles.list_available(clinic_id, slot, species)

UN SEUL DEPOT, ET C'EST DEJA UNE UNITE DE TRAVAIL COMPLETE
La forme ne change pas parce que le module n'a qu'un agregat : ce qui la
justifie est la GARDE -- lever hors bloc, annuler en sortie sans commit -- et non
le nombre de depots.

LE NOM `SchedulingUnitOfWork` EST CELUI DU PORT, PAS DE CETTE CLASSE
Le port vit dans `domain/ports.py`, et c'est lui que les consommateurs nomment ;
l'implementation d'ici s'appelle `SqlAlchemySchedulingUnitOfWork`. NE JAMAIS
IMPORTER CE FICHIER DEPUIS `application/` -- la dependance FastAPI ci-dessous
existe pour que l'assemblage se fasse dans la route ou au point de composition,
et nulle part ailleurs.

LA DEPENDANCE FASTAPI N'A ENCORE AUCUN APPELANT, ET ELLE EST LA QUAND MEME
Le module n'expose aucune route -- l'ecran « mon compte » et son ticket les
apporteront --, mais la livrer coute trois lignes et evite qu'un ticket futur
invente sa propre facon d'ouvrir la session, ce que les quatre modules
precedents ont deja evite ainsi.
"""

from typing import Annotated

from fastapi import Depends, Request

from app.modules.scheduling.domain.ports import (
    PractitionerProfileRepository,
    SchedulingUnitOfWork,
)
from app.modules.scheduling.infrastructure.db.repositories import (
    SqlAlchemyPractitionerProfileRepository,
)
from app.shared.infrastructure.db.session import get_database
from app.shared.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


class SqlAlchemySchedulingUnitOfWork(SqlAlchemyUnitOfWork, SchedulingUnitOfWork):
    """Unite de travail de scheduling adossee a PostgreSQL.

    Tout le cycle de vie -- session par bloc, rollback de sortie, gardes -- est
    herite de `SqlAlchemyUnitOfWork` ; ne vit ici que ce qui appartient au
    module : son depot.
    """

    @property
    def practitioner_profiles(self) -> PractitionerProfileRepository:
        """Le depot de fiches techniques, servi par le bloc `async with` en cours.

        Une propriete PARESSEUSE : le depot est une enveloppe sans etat autour
        de la session du bloc, construite a l'acces -- il ne peut jamais etre
        servi hors d'un bloc ouvert, ni survivre a sa sortie.

        Returns:
            Le depot de fiches techniques du bloc en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
        return SqlAlchemyPractitionerProfileRepository(self._active_session)


async def get_scheduling_uow(request: Request) -> SchedulingUnitOfWork:
    """Fournit l'unite de travail de scheduling de la requete en cours.

    UNE INSTANCE PAR REQUETE, livree FERMEE : la session ne s'ouvrira qu'au
    `async with` du consommateur. `get_scheduling_uow` et non `get_uow` -- une
    unite par module, le nom porte la frontiere.

    Args:
        request: la requete en cours, d'ou l'on remonte aux ressources de
            persistance du processus.

    Returns:
        L'unite de travail du module, typee par son port.

    Raises:
        RuntimeError: si le `lifespan` n'a pas tourne.
    """
    return SqlAlchemySchedulingUnitOfWork(get_database(request).sessionmaker)


# Alias a annoter les parametres de route : `uow: SchedulingUowDep`. Le type
# expose est le PORT : une route ne sait pas quelle technologie la sert, et une
# doublure en memoire s'y substitue sans toucher aux signatures. Celle de ce
# module reste a ecrire -- ADR-0023 : seuls les modules ayant un consommateur
# reel en ont une, et le socle rend la suivante mecanique.
SchedulingUowDep = Annotated[SchedulingUnitOfWork, Depends(get_scheduling_uow)]
