"""Garde de non-derive entre les deux catalogues d'especes (BACK-21).

CE FICHIER EST LE SEUL ENDROIT DU DEPOT QUI IMPORTE LES DEUX MODULES
Et il en a le droit : le contrat `module-independence` s'applique au paquet
`app` (`root_package = "app"` dans pyproject.toml), dont `tests/` ne fait pas
partie. C'est exactement la place que BACK-10a avait donnee a la meme garde pour
les types de compte recopies dans le noyau partage
(`test_the_recopied_account_types_have_not_drifted_from_identity`).

CE QUE MYPY TIENT, ET CE QU'IL NE TIENT PAS
Mypy tient l'interdit de CROISEMENT : deux `StrEnum` homonymes ne sont pas
assignables l'un a l'autre, et tout appel qui melangerait les deux echoue au
typage. Ce qu'il ne tient pas, c'est la DERIVE DE CATALOGUE -- medical_records
ajoutant une espece que scheduling ignorerait, ou l'inverse. C'est l'objet de ce
fichier.

AVERTISSEMENT HONNETE : ce filet ne tourne pas encore en integration continue.
`.github/workflows/ci-backend.yml` ne lance aujourd'hui que `lint-imports`, et
reserve nommement `pytest` a QA-01. En attendant, il tient a `make test-back` et
a la relecture.
"""

import pytest

from app.modules.medical_records.domain.entities import Species as MedicalRecordsSpecies
from app.modules.medical_records.infrastructure.db.models import AnimalModel
from app.modules.scheduling.domain.entities import Species as SchedulingSpecies
from app.modules.scheduling.infrastructure.db.models import PractitionerSpeciesModel

pytestmark = pytest.mark.scheduling

# Longueurs LUES A LA SOURCE, jamais recopiees : une garde qui repeterait « 20 »
# resterait verte le jour ou l'une des deux colonnes retrecirait, et le refus
# tomberait alors a l'INSERT, chez un utilisateur.
_SCHEDULING_COLUMN_LENGTH = PractitionerSpeciesModel.__table__.c.species.type.length
_MEDICAL_RECORDS_COLUMN_LENGTH = AnimalModel.__table__.c.species.type.length


def test_scheduling_species_have_not_drifted_from_medical_records() -> None:
    """Les deux catalogues portent exactement les memes valeurs, dans les deux sens.

    LES DEUX ENUMS SONT VOLONTAIREMENT IDENTIQUES : scheduling ne peut pas
    importer celui de medical_records (contrat `module-independence`), et le
    depot recopie plutot que de faire descendre un vocabulaire METIER dans
    `shared/`, reserve au besoin TECHNIQUE (ADR-0022).

    Si une divergence devient legitime -- une espece qu'un praticien peut
    declarer sans qu'aucun animal ne la porte, ou l'inverse --, ce test doit
    etre SUPPRIME dans la meme pull request que la divergence, avec l'ecart
    consigne au registre. Le corriger en silence rendrait l'appariement faux
    sans que personne ne l'ait decide.
    """
    assert {member.value for member in SchedulingSpecies} == {
        member.value for member in MedicalRecordsSpecies
    }
    assert {member.name for member in SchedulingSpecies} == {
        member.name for member in MedicalRecordsSpecies
    }


@pytest.mark.parametrize("member", list(MedicalRecordsSpecies))
def test_a_medical_records_species_converts_to_a_scheduling_one(
    member: MedicalRecordsSpecies,
) -> None:
    """La conversion que le point de composition ecrira, figee des aujourd'hui.

    `main.py` est le seul espace autorise a connaitre deux modules : c'est la
    que l'espece d'un animal deviendra une competence cherchee, par
    `SchedulingSpecies(animal_species.value)`.

    CE TEST FIGE L'APPEL, IL NE DIT RIEN DU SENS. `OTHER` n'a pas la meme portee
    des deux cotes -- soupape de saisie chez medical_records, competence declaree
    ici (voir la docstring de `Species`) -- et l'arbitrage revient au premier
    consommateur : convertir la valeur reste juste, decider qu'un praticien
    « OTHER » soigne un animal « OTHER » est une decision d'appariement.
    """
    assert SchedulingSpecies(member.value).value == member.value


@pytest.mark.parametrize("member", list(SchedulingSpecies))
def test_a_scheduling_species_converts_back(member: SchedulingSpecies) -> None:
    """La conversion tient aussi dans l'autre sens -- un filtre a traduire en retour."""
    assert MedicalRecordsSpecies(member.value).value == member.value


@pytest.mark.parametrize("member", list(SchedulingSpecies))
def test_every_species_value_fits_both_stored_columns(member: SchedulingSpecies) -> None:
    """Aucune valeur ne deborde l'une ou l'autre colonne de stockage, lue au mapping.

    Les deux, et pas seulement celle de scheduling : le catalogue est commun, et
    une espece ajoutee trop longue echouerait a l'INSERT du cote le plus etroit --
    a l'ecriture, c'est-a-dire chez un utilisateur, et pour une espece ajoutee en
    toute bonne foi.
    """
    assert len(member.value) <= _SCHEDULING_COLUMN_LENGTH
    assert len(member.value) <= _MEDICAL_RECORDS_COLUMN_LENGTH
