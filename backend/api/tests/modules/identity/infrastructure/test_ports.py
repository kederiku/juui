"""Tests d'integration de l'unicite d'e-mail insensible a la casse (INFRA-09).

Le semis passe par la session BRUTE, et c'est le coeur de la preuve : passer
par le domaine normaliserait l'adresse, et les tests ne prouveraient plus que
la normalisation -- pas la contrainte. C'est l'index
`ix_accounts_email_lower`, seul acteur a voir TOUTES les ecritures, qui doit
refuser le doublon de casse. Les tests ne committent jamais ; le rollback du
teardown annule tout.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.domain.entities import Account, AccountStatus, AccountType
from app.modules.identity.infrastructure.db.models import AccountModel
from app.modules.identity.infrastructure.db.repositories import SqlAlchemyAccountRepository

# La table du module nait avec la fixture de session du conftest local --
# demandee ici, et seulement ici : les tests purs n'exigent pas Docker.


async def _seed_account(session: AsyncSession, email: str) -> AccountModel:
    """Seme un compte par la session brute, l'adresse ecrite TELLE QUELLE."""
    model = AccountModel(
        id=uuid4(),
        email=email,
        first_name="Jean",
        last_name="Veto",
        account_type=AccountType.PROFESSIONAL.value,
        status=AccountStatus.ACTIVE.value,
    )
    session.add(model)
    await session.flush()
    return model


async def test_same_email_with_a_different_case_is_refused_by_the_database(
    session: AsyncSession,
) -> None:
    """LE critere du ticket, mot pour mot : `Veto@x.fr` apres `veto@x.fr` echoue."""
    await _seed_account(session, "veto@x.fr")

    with pytest.raises(IntegrityError):
        await _seed_account(session, "Veto@x.fr")


async def test_exact_duplicate_email_is_refused_by_the_database(session: AsyncSession) -> None:
    """L'index fonctionnel subsume l'unicite exacte que portait `ix_accounts_email`."""
    await _seed_account(session, "veto@x.fr")

    with pytest.raises(IntegrityError):
        await _seed_account(session, "veto@x.fr")


async def test_distinct_emails_coexist(session: AsyncSession) -> None:
    """Deux adresses reellement differentes ne se genent pas."""
    await _seed_account(session, "veto@x.fr")
    await _seed_account(session, "assistant@x.fr")


async def test_find_by_email_matches_a_row_stored_with_capitals(session: AsyncSession) -> None:
    """La recherche compare sur `lower(email)` : une ligne ecrite hors domaine reste trouvable."""
    seeded = await _seed_account(session, "Veto@x.fr")
    repository = SqlAlchemyAccountRepository(session)

    found = await repository.find_by_email("veto@x.fr")

    assert found is not None
    assert found.id == seeded.id


async def test_find_by_email_returns_none_when_the_address_is_free(
    session: AsyncSession,
) -> None:
    """Une adresse libre repond None, pas une erreur."""
    repository = SqlAlchemyAccountRepository(session)

    assert await repository.find_by_email("libre@x.fr") is None


async def test_account_round_trips_through_the_repository(session: AsyncSession) -> None:
    """Chemin nominal : le domaine normalise, le depot persiste, la relecture est canonique."""
    account = Account.create(
        email="  Veto@X.fr  ",
        first_name="Jean",
        last_name="Veto",
        account_type=AccountType.PROFESSIONAL,
    )
    repository = SqlAlchemyAccountRepository(session)
    await repository.add(account)

    found = await repository.find_by_email("veto@x.fr")

    assert found is not None
    assert isinstance(found.id, UUID)
    assert found.email == "veto@x.fr"
