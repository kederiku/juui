"""Tests purs des entites du module organization (BACK-16) : sans Docker."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.modules.organization.domain.entities import (
    Clinic,
    ClinicRole,
    Group,
    GroupRole,
    Membership,
)
from app.modules.organization.domain.exceptions import InvalidWindowError

_START = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
_END = datetime(2026, 8, 31, 18, 0, tzinfo=UTC)


def _membership(end_at: datetime | None = _END) -> Membership:
    """Fabrique une appartenance de reference, fenetre `[_START, end_at)`."""
    return Membership.create(
        account_id=uuid4(),
        group_id=uuid4(),
        role=GroupRole.MANAGER,
        start_at=_START,
        end_at=end_at,
    )


def test_create_strips_names_and_mints_ids() -> None:
    """Les fabriques identifient dans le domaine et normalisent les noms."""
    group = Group.create(name="  Clinique des Lilas  ")
    clinic = Clinic.create(name="  Site de Vincennes  ")
    assert group.name == "Clinique des Lilas"
    assert clinic.name == "Site de Vincennes"
    assert group.id != clinic.id


def test_membership_window_is_half_open() -> None:
    """`[start_at, end_at)` : debut inclus, fin exclue."""
    membership = _membership()
    assert membership.is_active(_START)
    assert membership.is_active(_END - timedelta(seconds=1))
    assert not membership.is_active(_END)
    assert not membership.is_active(_START - timedelta(seconds=1))


def test_open_ended_membership_stays_active() -> None:
    """Une fenetre sans fin couvre tout instant posterieur au debut."""
    membership = _membership(end_at=None)
    assert membership.is_active(_START + timedelta(days=3650))


def test_naive_bounds_are_refused() -> None:
    """Une borne sans fuseau ne construit jamais une fenetre."""
    with pytest.raises(InvalidWindowError):
        _membership(end_at=datetime(2026, 8, 31, 18, 0))
    with pytest.raises(InvalidWindowError):
        Membership.create(
            account_id=uuid4(),
            group_id=uuid4(),
            role=GroupRole.ADMIN,
            start_at=datetime(2026, 8, 1, 9, 0),
            end_at=None,
        )


def test_naive_reference_instant_is_refused() -> None:
    """`is_active` refuse un instant naif en erreur METIER, pas en TypeError."""
    membership = _membership()
    with pytest.raises(InvalidWindowError):
        membership.is_active(datetime(2026, 8, 25, 12, 0))


def test_inverted_or_empty_window_is_refused() -> None:
    """La fin suit STRICTEMENT le debut : fenetre vide ou inversee refusee."""
    with pytest.raises(InvalidWindowError):
        _membership(end_at=_START)
    with pytest.raises(InvalidWindowError):
        _membership(end_at=_START - timedelta(days=1))


def test_role_enums_are_distinct_types() -> None:
    """Les deux perimetres de role ne partagent aucun membre."""
    assert set(GroupRole) == {GroupRole.MANAGER, GroupRole.ADMIN, GroupRole.SUPERADMIN}
    assert set(ClinicRole) == {ClinicRole.VETERINARIAN, ClinicRole.ASV}
    assert not {member.value for member in GroupRole} & {member.value for member in ClinicRole}
