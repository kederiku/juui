"""Les dependances branchees sur les VRAIS depots (BACK-10c, critere 5).

CE QUE CE FICHIER PROUVE, ET QUE LES DOUBLURES NE PEUVENT PAS PROUVER
Que les entites livrees par BACK-16 satisfont les protocoles de la bordure
telles quelles, que le filtre de tenance et la lecture non tenante de la
clinique disent bien la meme chose sur les memes lignes, et que la contrainte de
schema sur laquelle la premiere s'appuie existe REELLEMENT.

Le test tient lieu de POINT DE COMPOSITION, comme `test_jwt_service_integration`
avant lui : les resolveurs se branchent sur LA SESSION DU TEST et non sur une
unite de travail ouverte sur le `sessionmaker`. La fixture `session` ne commite
jamais -- une autre connexion ne verrait rien du semis, et le refus observe
serait une invisibilite transactionnelle deguisee en propriete de securite.

Les tests ne committent jamais ; le rollback du teardown annule le semis.
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import inspect as sqlalchemy_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.domain.entities import AccountType
from app.modules.organization.domain.entities import ClinicRole, GroupRole
from app.modules.organization.infrastructure.db.models import (
    AssignmentModel,
    ClinicModel,
    GroupModel,
    MembershipModel,
)
from app.modules.organization.infrastructure.db.repositories import (
    SqlAlchemyAssignmentRepository,
    SqlAlchemyClinicRepository,
    SqlAlchemyMembershipRepository,
)
from app.shared.domain.ports.token_service import InactiveMembershipError
from app.shared.infrastructure.api.dependencies.auth import (
    AccountRecord,
    ActiveAssignment,
    Authentication,
)
from app.shared.infrastructure.api.dependencies.tenant import CLINIC_HEADER
from app.shared.infrastructure.security.jwt_service import JwtTokenService
from tests.support.auth import (
    AUDIENCE_PRO,
    FakeAccount,
    bearer,
    build_probe_app,
    client,
    jwt_settings,
)

pytestmark = pytest.mark.authorization

# Instant REEL et non date en dur : PyJWT verifie le `iat` contre son horloge
# murale, qu'aucun argument ne remplace.
_AT = datetime.now(UTC).replace(microsecond=0)
_STARTED = _AT - timedelta(days=30)
_ENDED = _AT - timedelta(days=1)


async def _seed_group(session: AsyncSession, account_id: UUID, group_id: UUID) -> None:
    """Seme un groupe et l'appartenance active du compte."""
    session.add(GroupModel(id=group_id, name=f"groupe {group_id.hex[:8]}"))
    session.add(
        MembershipModel(
            id=uuid4(),
            account_id=account_id,
            group_id=group_id,
            role=GroupRole.MANAGER.value,
            start_at=_STARTED,
            end_at=None,
        )
    )
    await session.flush()


async def _seed_clinic(
    session: AsyncSession,
    group_id: UUID,
    clinic_id: UUID,
    *,
    account_id: UUID | None = None,
    role: ClinicRole = ClinicRole.VETERINARIAN,
    start_at: datetime = _STARTED,
    end_at: datetime | None = None,
) -> None:
    """Seme une clinique du groupe, et l'affectation du compte si demande."""
    session.add(ClinicModel(id=clinic_id, group_id=group_id, name=f"clinique {clinic_id.hex[:8]}"))
    # Vidage AVANT l'affectation : la cle etrangere composite exige que la ligne
    # de clinique existe deja, et l'ordonnancement de SQLAlchemy ne le garantit
    # pas pour une contrainte declaree en `__table_args__`.
    await session.flush()
    if account_id is not None:
        session.add(
            AssignmentModel(
                id=uuid4(),
                group_id=group_id,
                account_id=account_id,
                clinic_id=clinic_id,
                role=role.value,
                start_at=start_at,
                end_at=end_at,
            )
        )
    await session.flush()


def _authentication(session: AsyncSession, account: AccountRecord) -> Authentication:
    """Branche les quatre resolveurs sur la session du test.

    Seul le compte est une doublure : `identity` a deja ses propres tests de
    depot, et lui creer une table ici n'ajouterait rien a ce que ce fichier
    cherche a prouver.
    """
    memberships = SqlAlchemyMembershipRepository(session)
    assignments = SqlAlchemyAssignmentRepository(session)
    clinics = SqlAlchemyClinicRepository(session)

    async def resolve_account(account_id: UUID) -> AccountRecord:
        """Rend le compte porteur."""
        return account

    async def resolve_active_assignments(
        account_id: UUID, at: datetime
    ) -> Sequence[ActiveAssignment]:
        """Rend les affectations actives, filtrees par le contexte de tenance."""
        return await assignments.list_active_for_account(account_id, at)

    return Authentication(
        tokens=JwtTokenService(
            settings=jwt_settings(),
            resolve_group_role=memberships.find_active_role,
            now=lambda: _AT,
        ),
        resolve_account=resolve_account,
        resolve_active_assignments=resolve_active_assignments,
        resolve_clinic_group=clinics.find_group_id,
    )


async def _authorization(
    authentication: Authentication, account_id: UUID, group_id: UUID
) -> dict[str, str]:
    """Emet un vrai jeton, role de groupe lu dans la vraie table."""
    assert isinstance(authentication.tokens, JwtTokenService)
    return await bearer(
        authentication.tokens,
        account_id=account_id,
        account_type=AccountType.PROFESSIONAL.value,
        audience=AUDIENCE_PRO,
        active_group_id=group_id,
    )


async def test_a_real_token_opens_a_protected_route_end_to_end(session: AsyncSession) -> None:
    """De la ligne en base a la route protegee, sans rien simuler entre les deux."""
    account_id, group_id, clinic_id = uuid4(), uuid4(), uuid4()
    await _seed_group(session, account_id, group_id)
    await _seed_clinic(session, group_id, clinic_id, account_id=account_id)
    authentication = _authentication(session, FakeAccount(id=account_id))
    headers = await _authorization(authentication, account_id, group_id)

    async with client(build_probe_app(authentication)) as opened:
        response = await opened.get(
            "/pro/clinic", headers={**headers, CLINIC_HEADER: str(clinic_id)}
        )

    assert response.status_code == 200
    assert response.json() == {"clinic_id": str(clinic_id), "role": ClinicRole.VETERINARIAN.value}


async def test_a_clinic_role_comes_from_the_assignment_row(session: AsyncSession) -> None:
    """Le role de clinique n'est jamais dans le jeton : il vient de la ligne."""
    account_id, group_id, clinic_id = uuid4(), uuid4(), uuid4()
    await _seed_group(session, account_id, group_id)
    await _seed_clinic(session, group_id, clinic_id, account_id=account_id, role=ClinicRole.ASV)
    authentication = _authentication(session, FakeAccount(id=account_id))
    headers = await _authorization(authentication, account_id, group_id)

    async with client(build_probe_app(authentication)) as opened:
        allowed = await opened.get(
            "/pro/clinic", headers={**headers, CLINIC_HEADER: str(clinic_id)}
        )
        refused = await opened.get(
            "/pro/consultations", headers={**headers, CLINIC_HEADER: str(clinic_id)}
        )

    assert allowed.json()["role"] == ClinicRole.ASV.value
    assert refused.status_code == 403


async def test_a_clinic_of_another_group_is_refused_even_when_the_account_is_assigned(
    session: AsyncSession,
) -> None:
    """LE CAS DU REMPLACANT : deux appartenances legitimes, un jeton pour le groupe A.

    La clinique du groupe B est refusee bien que le compte y soit reellement
    affecte -- c'est la seconde verification qui l'arrete, et elle ne dit pas
    davantage que si la clinique n'existait pas.
    """
    account_id = uuid4()
    group_a, group_b = uuid4(), uuid4()
    clinic_a, clinic_b = uuid4(), uuid4()
    await _seed_group(session, account_id, group_a)
    await _seed_group(session, account_id, group_b)
    await _seed_clinic(session, group_a, clinic_a, account_id=account_id)
    await _seed_clinic(session, group_b, clinic_b, account_id=account_id)
    authentication = _authentication(session, FakeAccount(id=account_id))
    headers = await _authorization(authentication, account_id, group_a)

    async with client(build_probe_app(authentication)) as opened:
        own = await opened.get("/pro/clinic", headers={**headers, CLINIC_HEADER: str(clinic_a)})
        other = await opened.get("/pro/clinic", headers={**headers, CLINIC_HEADER: str(clinic_b)})
        unknown = await opened.get("/pro/clinic", headers={**headers, CLINIC_HEADER: str(uuid4())})

    assert own.status_code == 200
    assert other.status_code == 404
    assert other.json() == unknown.json()


async def test_an_expired_assignment_no_longer_grants_a_clinic_role(
    session: AsyncSession,
) -> None:
    """Une affectation close ne donne plus rien -- la fenetre est demi-ouverte."""
    account_id, group_id, clinic_id = uuid4(), uuid4(), uuid4()
    await _seed_group(session, account_id, group_id)
    await _seed_clinic(
        session, group_id, clinic_id, account_id=account_id, start_at=_STARTED, end_at=_ENDED
    )
    authentication = _authentication(session, FakeAccount(id=account_id))
    headers = await _authorization(authentication, account_id, group_id)

    async with client(build_probe_app(authentication)) as opened:
        response = await opened.get(
            "/pro/clinic", headers={**headers, CLINIC_HEADER: str(clinic_id)}
        )

    assert response.status_code == 404


async def test_a_clinic_without_any_assignment_is_refused_like_an_unknown_one(
    session: AsyncSession,
) -> None:
    """La clinique est bien du groupe actif, mais le compte n'y est pas affecte."""
    account_id, group_id, clinic_id = uuid4(), uuid4(), uuid4()
    await _seed_group(session, account_id, group_id)
    await _seed_clinic(session, group_id, clinic_id)
    authentication = _authentication(session, FakeAccount(id=account_id))
    headers = await _authorization(authentication, account_id, group_id)

    async with client(build_probe_app(authentication)) as opened:
        response = await opened.get(
            "/pro/clinic", headers={**headers, CLINIC_HEADER: str(clinic_id)}
        )

    assert response.status_code == 404
    assert response.json()["code"] == "shared.clinic.not_active"


async def test_a_closed_membership_still_grants_its_group_role_until_the_token_expires(
    session: AsyncSession,
) -> None:
    """LIMITE EPINGLEE, et non defaut : la bordure ne rejoue pas l'appartenance.

    Le role de groupe est fige a l'emission et vaut jusqu'a l'expiration du
    jeton -- le budget de quinze minutes assume par l'ADR-0024, dont BACK-10d
    couvrira l'urgence par la revocation. Ce test existe pour que la journee ou
    quelqu'un voudra changer ce comportement, il trouve la decision ecrite ici
    plutot qu'un silence.
    """
    account_id, group_id = uuid4(), uuid4()
    await _seed_group(session, account_id, group_id)
    authentication = _authentication(session, FakeAccount(id=account_id))
    headers = await _authorization(authentication, account_id, group_id)

    # L'appartenance se ferme APRES l'emission du jeton.
    membership = (
        (
            await session.execute(
                select(MembershipModel).where(MembershipModel.account_id == account_id)
            )
        )
        .scalars()
        .one()
    )
    membership.end_at = _AT - timedelta(minutes=1)
    await session.flush()

    async with client(build_probe_app(authentication)) as opened:
        response = await opened.get("/pro/managers", headers=headers)

    assert response.status_code == 200


async def test_a_closed_membership_forbids_issuing_a_new_token_for_that_group(
    session: AsyncSession,
) -> None:
    """Le pendant du test precedent : la porte se ferme a la PROCHAINE emission.

    C'est ce qui borne la latence a la duree de vie du jeton d'acces, et c'est
    pourquoi le test ci-dessus decrit une limite et non une fuite.
    """
    account_id, group_id = uuid4(), uuid4()
    await _seed_group(session, account_id, group_id)
    authentication = _authentication(session, FakeAccount(id=account_id))
    membership = (
        (
            await session.execute(
                select(MembershipModel).where(MembershipModel.account_id == account_id)
            )
        )
        .scalars()
        .one()
    )
    membership.end_at = _AT - timedelta(minutes=1)
    await session.flush()

    with pytest.raises(InactiveMembershipError):
        await _authorization(authentication, account_id, group_id)


def test_the_assignments_table_keeps_the_composite_foreign_key() -> None:
    """La contrainte que rien d'autre n'observe, et sur laquelle le filtre s'appuie.

    Les migrations sont ecrites A LA MAIN : une migration qui recreerait
    `assignments` en omettant cette cle etrangere ouvrirait la lecture
    inter-tenant sans un mot. La verification explicite de `get_active_clinic`
    ne depend pas d'elle -- c'est bien pour cela qu'elle existe --, mais le
    filtre tenant, lui, y adosse sa promesse.
    """
    constraints = sqlalchemy_inspect(AssignmentModel).local_table.foreign_key_constraints
    composite = {
        (tuple(sorted(element.parent.name for element in constraint.elements)))
        for constraint in constraints
    }
    assert ("clinic_id", "group_id") in composite
