"""Module medical_records : « de quels animaux s'agit-il ».

`identity` prouve qui vous etes, `organization` dit ou vous travaillez ;
celui-ci porte le dossier de l'animal. LA decision du socle (ADR-0006) :
le dossier appartient a l'ANIMAL, pas au proprietaire -- il le suit lors d'un
changement de detenteur -- et la detention est une relation DATEE, plusieurs
dans le temps, une seule active. Les actes cliniques a venir referenceront la
detention en vigueur au moment des faits, jamais le proprietaire courant.

CE QUE BACK-19 A LIVRE ICI
Les entites `Animal` (la racine, SANS tenance : creee a l'inscription d'un
particulier, avant tout groupe) et `Custody` (la detention datee, « une seule
ouverte » garanti par le domaine ET par un index unique partiel), leur
persistance, et les trois lectures qui prouvent le modele : les animaux
detenus par un compte, la detention en vigueur d'un animal, l'historique
intact des detentions.

Aucun autre module n'accede a ses tables. PAS de cas d'usage, pas de routes,
pas de validation de puce : la creation et les listes appartiennent a
BACK-30, la reconciliation par numero de puce a BACK-20.

SURFACE PUBLIQUE
Les deux ports de depot et l'unite de travail, les entites et les enums qui
forment leur contrat, et la dependance FastAPI que le point de composition
consommera. Le re-export est EXPLICITE parce que Mypy tourne avec
`no_implicit_reexport` (implique par `strict`).
"""

from app.modules.medical_records.domain.entities import (
    Animal,
    AnimalSex,
    Custody,
    Species,
    SterilizationStatus,
)
from app.modules.medical_records.domain.ports import (
    AnimalRepository,
    CustodyRepository,
    MedicalRecordsUnitOfWork,
)
from app.modules.medical_records.unit_of_work import (
    MedicalRecordsUowDep,
    get_medical_records_uow,
)

__all__ = [
    "Animal",
    "AnimalRepository",
    "AnimalSex",
    "Custody",
    "CustodyRepository",
    "MedicalRecordsUnitOfWork",
    "MedicalRecordsUowDep",
    "Species",
    "SterilizationStatus",
    "get_medical_records_uow",
]
