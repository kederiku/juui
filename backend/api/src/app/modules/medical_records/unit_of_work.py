"""Unite de travail du module medical_records (BACK-19).

A la RACINE du module, comme chez identity et organization : l'unite de
travail n'appartient ni au domaine (elle manipule une transaction) ni tout a
fait a l'infrastructure (elle expose les depots au cas d'usage) -- elle est le
point d'assemblage du module, et la seule exemption du contrat
`module-layers`.

    async with uow:
        custodies = await uow.custodies.list_for_animal(animal_id)
        await uow.commit()

Les deux depots partagent la session du bloc : la creation de BACK-30 --
l'animal ET sa detention initiale, jamais l'un sans l'autre -- tiendra dans UN
SEUL bloc `async with` de cette unite.

LE NOM `MedicalRecordsUnitOfWork` EST CELUI DU PORT, PAS DE CETTE CLASSE
Le port vit dans `domain/ports.py`, et c'est lui que les consommateurs
nomment ; l'implementation d'ici s'appelle
`SqlAlchemyMedicalRecordsUnitOfWork`. NE JAMAIS IMPORTER CE FICHIER DEPUIS
`application/` -- la dependance FastAPI ci-dessous existe pour que
l'assemblage se fasse dans la route ou au point de composition, et nulle part
ailleurs.
"""

from typing import Annotated

from fastapi import Depends, Request

from app.modules.medical_records.domain.ports import (
    AnimalRepository,
    CustodyRepository,
    MedicalRecordsUnitOfWork,
)
from app.modules.medical_records.infrastructure.db.repositories import (
    SqlAlchemyAnimalRepository,
    SqlAlchemyCustodyRepository,
)
from app.shared.infrastructure.db.session import get_database
from app.shared.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


class SqlAlchemyMedicalRecordsUnitOfWork(SqlAlchemyUnitOfWork, MedicalRecordsUnitOfWork):
    """Unite de travail de medical_records adossee a PostgreSQL.

    Tout le cycle de vie -- session par bloc, rollback de sortie, gardes --
    est herite de `SqlAlchemyUnitOfWork` ; ne vit ici que ce qui appartient au
    module : ses depots.
    """

    @property
    def animals(self) -> AnimalRepository:
        """Le depot des fiches animal, servi par le bloc `async with` en cours.

        Une propriete PARESSEUSE : le depot est une enveloppe sans etat autour
        de la session du bloc, construite a l'acces -- il ne peut jamais etre
        servi hors d'un bloc ouvert, ni survivre a sa sortie.

        Returns:
            Le depot des fiches animal du bloc en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
        return SqlAlchemyAnimalRepository(self._active_session)

    @property
    def custodies(self) -> CustodyRepository:
        """Le depot des detentions, servi par le bloc `async with` en cours.

        Returns:
            Le depot des detentions du bloc en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
        return SqlAlchemyCustodyRepository(self._active_session)


async def get_medical_records_uow(request: Request) -> MedicalRecordsUnitOfWork:
    """Fournit l'unite de travail de medical_records de la requete en cours.

    UNE INSTANCE PAR REQUETE, livree FERMEE : la session ne s'ouvrira qu'au
    `async with` du consommateur. `get_medical_records_uow` et non `get_uow`
    -- une unite par module, le nom porte la frontiere, comme
    `get_identity_uow` et `get_organization_uow` l'ont promis.

    Args:
        request: la requete en cours, d'ou l'on remonte aux ressources de
            persistance du processus.

    Returns:
        L'unite de travail du module, typee par son port.

    Raises:
        RuntimeError: si le `lifespan` n'a pas tourne.
    """
    return SqlAlchemyMedicalRecordsUnitOfWork(get_database(request).sessionmaker)


# Alias a annoter les parametres de route : `uow: MedicalRecordsUowDep`. Le
# type expose est le PORT : une route ne sait pas quelle technologie la sert,
# et BACK-06c pourra y substituer sa doublure sans toucher aux signatures.
MedicalRecordsUowDep = Annotated[MedicalRecordsUnitOfWork, Depends(get_medical_records_uow)]
