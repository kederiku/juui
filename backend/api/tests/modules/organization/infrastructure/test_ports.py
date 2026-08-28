"""Tests d'integration des trois requetes publiques du module organization (BACK-16).

Le semis passe par la session BRUTE -- la verite terrain a laquelle chaque
test compare le comportement des depots -- et pose explicitement `group_id`
sur chaque ligne, y compris tenant : le filtre vit dans le depot, pas dans la
session. Les tests ne committent jamais ; le rollback du teardown annule tout.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.organization.domain.entities import ClinicRole, GroupRole
from app.modules.organization.domain.exceptions import InvalidWindowError
from app.modules.organization.infrastructure.db.models import (
    AssignmentModel,
    ClinicModel,
    GroupModel,
    MembershipModel,
)
from app.modules.organization.infrastructure.db.repositories import (
    SqlAlchemyAssignmentRepository,
    SqlAlchemyMembershipRepository,
)
from app.shared.infrastructure.tenancy import MissingTenantContextError, use_group

# Les quatre tables du module naissent avec la fixture de session du conftest
# local -- demandee ici, et seulement ici : les tests purs n'exigent pas Docker.

_AT = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
_RECENT_START = _AT - timedelta(days=30)
_OLD_START = _AT - timedelta(days=90)
_EXPIRED_END = _AT - timedelta(days=1)


async def _seed_group(session: AsyncSession, group_id: UUID) -> None:
    """Seme un groupe par la session brute et le rend visible au bloc."""
    session.add(GroupModel(id=group_id, name=f"groupe {group_id.hex[:8]}"))
    await session.flush()


async def _seed_clinic(session: AsyncSession, clinic_id: UUID, group_id: UUID) -> None:
    """Seme une clinique du groupe donne, `group_id` pose a la main."""
    session.add(ClinicModel(id=clinic_id, group_id=group_id, name=f"clinique {clinic_id.hex[:8]}"))
    await session.flush()


async def _seed_membership(
    session: AsyncSession,
    account_id: UUID,
    group_id: UUID,
    *,
    role: GroupRole = GroupRole.MANAGER,
    start_at: datetime = _RECENT_START,
    end_at: datetime | None = None,
) -> None:
    """Seme une appartenance sur la fenetre donnee."""
    session.add(
        MembershipModel(
            id=uuid4(),
            account_id=account_id,
            group_id=group_id,
            role=role.value,
            start_at=start_at,
            end_at=end_at,
        )
    )
    await session.flush()


async def _seed_assignment(
    session: AsyncSession,
    account_id: UUID,
    clinic_id: UUID,
    group_id: UUID,
    *,
    role: ClinicRole = ClinicRole.VETERINARIAN,
    start_at: datetime = _RECENT_START,
    end_at: datetime | None = None,
) -> None:
    """Seme une affectation, `group_id` pose a la main comme le ferait le socle."""
    session.add(
        AssignmentModel(
            id=uuid4(),
            account_id=account_id,
            clinic_id=clinic_id,
            group_id=group_id,
            role=role.value,
            start_at=start_at,
            end_at=end_at,
        )
    )
    await session.flush()


async def test_active_memberships_are_listed_without_tenant_context(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    """La requete de l'emission de jeton tourne HORS de tout contexte de groupe."""
    await _seed_group(session, group_a)
    await _seed_group(session, group_b)
    account_id = uuid4()
    await _seed_membership(session, account_id, group_a, start_at=_RECENT_START)
    await _seed_membership(session, account_id, group_a, start_at=_OLD_START, end_at=_EXPIRED_END)
    await _seed_membership(session, account_id, group_b, start_at=_OLD_START)
    await _seed_membership(session, uuid4(), group_a)

    memberships = await SqlAlchemyMembershipRepository(session).list_active_for_account(
        account_id, _AT
    )

    # Deux actives sur trois, du debut le plus ancien au plus recent, et
    # jamais celles d'un autre compte.
    assert [membership.group_id for membership in memberships] == [group_b, group_a]
    assert all(membership.account_id == account_id for membership in memberships)


async def test_membership_activity_respects_the_half_open_window(
    session: AsyncSession, group_a: UUID
) -> None:
    """`[start_at, end_at)` en SQL comme dans le domaine : debut inclus, fin exclue."""
    await _seed_group(session, group_a)
    account_id = uuid4()
    end_at = _AT + timedelta(days=1)
    await _seed_membership(session, account_id, group_a, start_at=_RECENT_START, end_at=end_at)
    repository = SqlAlchemyMembershipRepository(session)

    assert await repository.list_active_for_account(account_id, _RECENT_START)
    assert not await repository.list_active_for_account(account_id, end_at)


async def test_find_active_role_returns_the_group_role(
    session: AsyncSession, group_a: UUID
) -> None:
    """Le role rendu est celui de l'appartenance active, dans le type du domaine."""
    await _seed_group(session, group_a)
    account_id = uuid4()
    await _seed_membership(session, account_id, group_a, role=GroupRole.MANAGER)

    role = await SqlAlchemyMembershipRepository(session).find_active_role(account_id, group_a, _AT)

    assert role is GroupRole.MANAGER


async def test_find_active_role_without_active_membership_returns_none(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    """L'absence de role est un RESULTAT : appartenance expiree ou groupe etranger."""
    await _seed_group(session, group_a)
    await _seed_group(session, group_b)
    account_id = uuid4()
    await _seed_membership(session, account_id, group_a, start_at=_OLD_START, end_at=_EXPIRED_END)
    repository = SqlAlchemyMembershipRepository(session)

    assert await repository.find_active_role(account_id, group_a, _AT) is None
    assert await repository.find_active_role(account_id, group_b, _AT) is None


async def test_find_active_role_prefers_the_most_recent_start(
    session: AsyncSession, group_a: UUID
) -> None:
    """Deux appartenances chevauchantes au meme groupe : la decision recente gagne."""
    await _seed_group(session, group_a)
    account_id = uuid4()
    await _seed_membership(
        session, account_id, group_a, role=GroupRole.MANAGER, start_at=_OLD_START
    )
    await _seed_membership(
        session, account_id, group_a, role=GroupRole.ADMIN, start_at=_RECENT_START
    )

    role = await SqlAlchemyMembershipRepository(session).find_active_role(account_id, group_a, _AT)

    assert role is GroupRole.ADMIN


async def test_active_assignments_are_scoped_to_account_and_activity(
    session: AsyncSession, group_a: UUID
) -> None:
    """La requete de BACK-10c rend les affectations actives du compte, et elles seules."""
    await _seed_group(session, group_a)
    clinic_id = uuid4()
    await _seed_clinic(session, clinic_id, group_a)
    account_id = uuid4()
    await _seed_assignment(session, account_id, clinic_id, group_a, role=ClinicRole.ASV)
    await _seed_assignment(
        session, account_id, clinic_id, group_a, start_at=_OLD_START, end_at=_EXPIRED_END
    )
    await _seed_assignment(session, uuid4(), clinic_id, group_a)

    with use_group(group_a):
        assignments = await SqlAlchemyAssignmentRepository(session).list_active_for_account(
            account_id, _AT
        )

    assert len(assignments) == 1
    assert assignments[0].clinic_id == clinic_id
    assert assignments[0].role is ClinicRole.ASV


async def test_assignments_without_context_raise_instead_of_returning_everything(
    session: AsyncSession, group_a: UUID
) -> None:
    """Hors de tout perimetre, la lecture d'affectations leve -- jamais de repli."""
    await _seed_group(session, group_a)
    repository = SqlAlchemyAssignmentRepository(session)

    with pytest.raises(MissingTenantContextError):
        await repository.list_active_for_account(uuid4(), _AT)


@pytest.mark.tenant_isolation
async def test_locum_assignments_stay_in_the_active_group(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    """Le remplacant REEL de BACK-16 : deux appartenances, un seul groupe visible.

    BACK-06b avait reduit le cas a « contexte A, donnee B » faute de modele ;
    l'appartenance N:M datee existe desormais, et le test le rejoue en entier :
    un compte membre des deux groupes, affecte dans chacun, ne voit sous le
    contexte du groupe A que ses affectations du groupe A.
    """
    await _seed_group(session, group_a)
    await _seed_group(session, group_b)
    clinic_a, clinic_b = uuid4(), uuid4()
    await _seed_clinic(session, clinic_a, group_a)
    await _seed_clinic(session, clinic_b, group_b)
    account_id = uuid4()
    await _seed_membership(session, account_id, group_a)
    await _seed_membership(session, account_id, group_b)
    await _seed_assignment(session, account_id, clinic_a, group_a)
    await _seed_assignment(session, account_id, clinic_b, group_b)

    with use_group(group_a):
        assignments = await SqlAlchemyAssignmentRepository(session).list_active_for_account(
            account_id, _AT
        )

    assert [assignment.clinic_id for assignment in assignments] == [clinic_a]


async def test_naive_reference_instant_is_refused_before_any_query(
    session: AsyncSession, group_a: UUID
) -> None:
    """Un `at` naif leve en erreur metier AVANT le SQL -- jamais interprete en silence.

    Sans la garde, PostgreSQL lierait le naif a un `timestamptz` en
    l'interpretant dans le fuseau de la session : une appartenance expiree
    redeviendrait active a deux heures pres, sans aucun signal.
    """
    naive_at = datetime(2026, 8, 25, 12, 0)

    with pytest.raises(InvalidWindowError):
        await SqlAlchemyMembershipRepository(session).list_active_for_account(uuid4(), naive_at)
    with pytest.raises(InvalidWindowError):
        await SqlAlchemyMembershipRepository(session).find_active_role(uuid4(), group_a, naive_at)
    with use_group(group_a), pytest.raises(InvalidWindowError):
        await SqlAlchemyAssignmentRepository(session).list_active_for_account(uuid4(), naive_at)


async def test_assignment_with_clinic_outside_its_group_is_refused_by_the_database(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    """La cle composite rend physiquement impossible une clinique hors groupe."""
    await _seed_group(session, group_a)
    await _seed_group(session, group_b)
    clinic_a = uuid4()
    await _seed_clinic(session, clinic_a, group_a)

    with pytest.raises(IntegrityError):
        await _seed_assignment(session, uuid4(), clinic_a, group_b)


async def test_membership_with_unknown_group_is_refused_by_the_database(
    session: AsyncSession,
) -> None:
    """`memberships.group_id` reference `groups` : un groupe inconnu ne s'insere pas."""
    with pytest.raises(IntegrityError):
        await _seed_membership(session, uuid4(), uuid4())
