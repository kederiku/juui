"""Le test d'acceptation de BACK-16 : affectation hors appartenance active -> refus.

La regle est pure -- elle se prouve sans Docker : `ensure_assignment_allowed`
recoit les appartenances d'un compte, le groupe de la clinique visee et
l'instant de la decision, et refuse tout ce qui n'est pas couvert par une
appartenance ACTIVE a ce groupe. La moitie structurelle (clinique et
affectation dans le meme groupe) est prouvee cote base par
`test_ports.py::test_assignment_with_clinic_outside_its_group_is_refused_by_the_database`.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.modules.organization.domain.entities import (
    GroupRole,
    Membership,
    ensure_assignment_allowed,
)
from app.modules.organization.domain.exceptions import (
    AssignmentOutsideMembershipError,
    InvalidWindowError,
)

_AT = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


def _membership(group_id: UUID, *, start_at: datetime, end_at: datetime | None) -> Membership:
    """Fabrique une appartenance du compte teste, sur la fenetre donnee."""
    return Membership.create(
        account_id=uuid4(),
        group_id=group_id,
        role=GroupRole.MANAGER,
        start_at=start_at,
        end_at=end_at,
    )


def test_active_membership_in_the_clinic_group_allows_the_assignment() -> None:
    """Cas nominal : une appartenance active au groupe de la clinique suffit."""
    group_id = uuid4()
    memberships = [_membership(group_id, start_at=_AT - timedelta(days=30), end_at=None)]
    ensure_assignment_allowed(memberships, group_id, _AT)


def test_no_membership_at_all_refuses_the_assignment() -> None:
    """Aucune appartenance : rien ne couvre la clinique visee."""
    with pytest.raises(AssignmentOutsideMembershipError):
        ensure_assignment_allowed([], uuid4(), _AT)


def test_expired_membership_refuses_the_assignment() -> None:
    """Une appartenance terminee avant l'instant de la decision ne compte plus."""
    group_id = uuid4()
    memberships = [
        _membership(group_id, start_at=_AT - timedelta(days=60), end_at=_AT - timedelta(days=1))
    ]
    with pytest.raises(AssignmentOutsideMembershipError):
        ensure_assignment_allowed(memberships, group_id, _AT)


def test_future_membership_refuses_the_assignment() -> None:
    """Une appartenance qui ne commence que demain ne couvre pas aujourd'hui."""
    group_id = uuid4()
    memberships = [_membership(group_id, start_at=_AT + timedelta(days=1), end_at=None)]
    with pytest.raises(AssignmentOutsideMembershipError):
        ensure_assignment_allowed(memberships, group_id, _AT)


def test_membership_in_another_group_refuses_the_assignment() -> None:
    """Cas du remplacant : etre actif AILLEURS n'ouvre pas ce groupe-ci."""
    memberships = [_membership(uuid4(), start_at=_AT - timedelta(days=30), end_at=None)]
    with pytest.raises(AssignmentOutsideMembershipError):
        ensure_assignment_allowed(memberships, uuid4(), _AT)


def test_naive_decision_instant_is_refused() -> None:
    """Un instant de decision naif est refuse avant toute evaluation de la regle."""
    group_id = uuid4()
    memberships = [_membership(group_id, start_at=_AT - timedelta(days=30), end_at=None)]
    with pytest.raises(InvalidWindowError):
        ensure_assignment_allowed(memberships, group_id, datetime(2026, 8, 25, 12, 0))


def test_membership_ending_exactly_now_refuses_the_assignment() -> None:
    """La borne de fin est EXCLUE : une appartenance qui finit a l'instant meme."""
    group_id = uuid4()
    memberships = [_membership(group_id, start_at=_AT - timedelta(days=30), end_at=_AT)]
    with pytest.raises(AssignmentOutsideMembershipError):
        ensure_assignment_allowed(memberships, group_id, _AT)
