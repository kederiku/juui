"""Tests purs des entites du module medical_records (BACK-19) : sans Docker."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from app.modules.medical_records.domain.entities import (
    Animal,
    AnimalSex,
    Custody,
    Species,
    SterilizationStatus,
)
from app.modules.medical_records.domain.exceptions import InvalidWindowError

_START = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
_END = datetime(2026, 8, 31, 18, 0, tzinfo=UTC)


def _custody(end_at: datetime | None = _END) -> Custody:
    """Fabrique une detention de reference, fenetre `[_START, end_at)`."""
    return Custody.create(
        animal_id=uuid4(),
        account_id=uuid4(),
        start_at=_START,
        end_at=end_at,
    )


def test_create_strips_fields_and_mints_ids() -> None:
    """Les fabriques identifient dans le domaine et normalisent les textes."""
    animal = Animal.create(
        name="  Caramel  ",
        species=Species.DOG,
        breed="  border collie  ",
        microchip_number="  250269604213456  ",
    )
    other = Animal.create(name="Plume", species=Species.CAT)
    assert animal.name == "Caramel"
    assert animal.breed == "border collie"
    assert animal.microchip_number == "250269604213456"
    assert animal.id != other.id


def test_blank_optional_fields_become_none() -> None:
    """Une puce ou une race saisie vide n'est pas une valeur : elle devient None."""
    animal = Animal.create(name="Caramel", species=Species.DOG, breed="   ", microchip_number="")
    assert animal.breed is None
    assert animal.microchip_number is None


def test_animal_defaults_say_unknown() -> None:
    """La fiche MINIMALE de l'etape 3 : nom et espece, l'inconnu partout ailleurs."""
    animal = Animal.create(name="Caramel", species=Species.OTHER)
    assert animal.sex is AnimalSex.UNKNOWN
    assert animal.sterilization is SterilizationStatus.UNKNOWN
    assert animal.breed is None
    assert animal.birth_date is None
    assert animal.microchip_number is None


def test_birth_date_is_kept_to_the_day() -> None:
    """La naissance est une date au jour pres, jamais un instant."""
    animal = Animal.create(name="Caramel", species=Species.DOG, birth_date=date(2024, 3, 15))
    assert animal.birth_date == date(2024, 3, 15)


def test_custody_window_is_half_open() -> None:
    """`[start_at, end_at)` : debut inclus, fin exclue."""
    custody = _custody()
    assert custody.is_active(_START)
    assert custody.is_active(_END - timedelta(seconds=1))
    assert not custody.is_active(_END)
    assert not custody.is_active(_START - timedelta(seconds=1))


def test_open_ended_custody_stays_active_and_open() -> None:
    """Une detention sans fin couvre tout instant posterieur -- et elle est OUVERTE."""
    custody = _custody(end_at=None)
    assert custody.is_open()
    assert custody.is_active(_START + timedelta(days=3650))


def test_closed_custody_is_not_open() -> None:
    """OUVERTE et ACTIVE sont deux questions : une fenetre close n'est jamais ouverte."""
    custody = _custody()
    assert not custody.is_open()
    assert custody.is_active(_START)


def test_naive_bounds_are_refused() -> None:
    """Une borne sans fuseau ne construit jamais une fenetre."""
    with pytest.raises(InvalidWindowError):
        _custody(end_at=datetime(2026, 8, 31, 18, 0))
    with pytest.raises(InvalidWindowError):
        Custody.create(
            animal_id=uuid4(),
            account_id=uuid4(),
            start_at=datetime(2026, 8, 1, 9, 0),
            end_at=None,
        )


def test_naive_reference_instant_is_refused() -> None:
    """`is_active` refuse un instant naif en erreur METIER, pas en TypeError."""
    custody = _custody()
    with pytest.raises(InvalidWindowError):
        custody.is_active(datetime(2026, 8, 25, 12, 0))


def test_inverted_or_empty_window_is_refused() -> None:
    """La fin suit STRICTEMENT le debut : fenetre vide ou inversee refusee."""
    with pytest.raises(InvalidWindowError):
        _custody(end_at=_START)
    with pytest.raises(InvalidWindowError):
        _custody(end_at=_START - timedelta(days=1))


def test_enums_expose_the_expected_states() -> None:
    """Les trois enums portent leurs membres exacts, l'inconnu compris."""
    assert set(AnimalSex) == {AnimalSex.MALE, AnimalSex.FEMALE, AnimalSex.UNKNOWN}
    assert set(SterilizationStatus) == {
        SterilizationStatus.STERILIZED,
        SterilizationStatus.INTACT,
        SterilizationStatus.UNKNOWN,
    }
    assert Species.OTHER in set(Species)
    assert {Species.DOG, Species.CAT, Species.FERRET} <= set(Species)
