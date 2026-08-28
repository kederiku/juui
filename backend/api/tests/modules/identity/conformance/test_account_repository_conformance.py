"""Conformite du depot de comptes : PostgreSQL et la doublure (BACK-06c).

LE SOCLE EST DEJA COUVERT AILLEURS -- `tests/shared/conformance/` eprouve les
cinq operations, la pagination et la tenance sur la paire de stubs. Ce qui reste
a comparer est ce que le socle ne porte pas : le FINDER MAISON du module.

`find_by_email` n'est pas un detail de vocabulaire. Son seul appelant est le
controle d'unicite de `CreateAccount` : si la doublure declare libre une adresse
que la production refuse, une creation de compte passe au vert en test et echoue
en production. C'est exactement la divergence que ce fichier existe pour fermer.
"""

from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.identity.domain.entities import Account, AccountStatus, AccountType
from app.modules.identity.domain.exceptions import AccountNotFoundError
from app.modules.identity.domain.ports import IdentityUnitOfWork
from app.modules.identity.infrastructure.memory.unit_of_work import InMemoryIdentityUnitOfWork
from app.modules.identity.unit_of_work import SqlAlchemyIdentityUnitOfWork
from tests.modules.identity.helpers import an_account

pytestmark = pytest.mark.conformance


def an_account_stored_as(email: str) -> Account:
    """Un compte dont l'adresse est ecrite TELLE QUELLE, sans passer par le domaine.

    `Account.create()` normalise ; cette fabrique-ci construit la dataclass
    directement, pour poser en base ce qu'une version anterieure du service, un
    import ou une correction manuelle aurait pu y laisser. C'est le seul moyen de
    comparer ce que les deux depots font d'une casse qu'ils n'ont pas choisie.
    """
    return Account(
        id=uuid4(),
        email=email,
        first_name="Jean",
        last_name="Veto",
        account_type=AccountType.INDIVIDUAL,
        phone=None,
        status=AccountStatus.ACTIVE,
        email_verified=False,
    )


class AccountRepositoryConformance:
    """La suite commune. Les sous-classes ne fournissent que la fixture `uow`."""

    @pytest.fixture
    def uow(self) -> IdentityUnitOfWork:
        """Le sujet sous test -- fourni par la sous-classe."""
        raise NotImplementedError

    async def test_an_unknown_identifier_raises_the_module_error(
        self, uow: IdentityUnitOfWork
    ) -> None:
        async with uow:
            with pytest.raises(AccountNotFoundError):
                await uow.accounts.get(uuid4())

    async def test_an_addition_is_visible_inside_its_own_block(
        self, uow: IdentityUnitOfWork
    ) -> None:
        account = an_account()
        async with uow:
            await uow.accounts.add(account)
            assert (await uow.accounts.get(account.id)).email == account.email

    async def test_commit_makes_the_account_durable(self, uow: IdentityUnitOfWork) -> None:
        account = an_account()
        async with uow:
            await uow.accounts.add(account)
            await uow.commit()
        async with uow:
            assert (await uow.accounts.get(account.id)).id == account.id

    async def test_leaving_the_block_without_commit_writes_nothing(
        self, uow: IdentityUnitOfWork
    ) -> None:
        account = an_account()
        async with uow:
            await uow.accounts.add(account)
        async with uow:
            with pytest.raises(AccountNotFoundError):
                await uow.accounts.get(account.id)

    async def test_save_reports_the_verification(self, uow: IdentityUnitOfWork) -> None:
        """Le geste que le port existe pour porter : verifier une adresse."""
        account = an_account()
        async with uow:
            await uow.accounts.add(account)
            await uow.commit()
            account.verify_email()
            await uow.accounts.save(account)
            await uow.commit()
        async with uow:
            assert (await uow.accounts.get(account.id)).email_verified is True

    async def test_save_of_an_unknown_account_raises(self, uow: IdentityUnitOfWork) -> None:
        async with uow:
            with pytest.raises(AccountNotFoundError):
                await uow.accounts.save(an_account())

    async def test_find_by_email_reports_a_free_address(self, uow: IdentityUnitOfWork) -> None:
        """L'absence est un RESULTAT ATTENDU ici, pas une erreur."""
        async with uow:
            assert await uow.accounts.find_by_email(f"libre-{uuid4().hex}@exemple.fr") is None

    async def test_find_by_email_finds_what_was_written(self, uow: IdentityUnitOfWork) -> None:
        account = an_account(email=f"jean-{uuid4().hex[:8]}@exemple.fr")
        async with uow:
            await uow.accounts.add(account)
            await uow.commit()
            found = await uow.accounts.find_by_email(account.email)
        assert found is not None
        assert found.id == account.id

    async def test_find_by_email_ignores_the_case_of_what_is_stored(
        self, uow: IdentityUnitOfWork
    ) -> None:
        """LE CAS QUI COMPTE : une ligne ecrite hors du domaine reste trouvable.

        La base compare en minuscules (`ix_accounts_email_lower`, INFRA-09), donc
        une adresse rangee `Veto@…` repond a une recherche `veto@…`. Une doublure
        qui comparerait la chaine exacte declarerait l'adresse LIBRE -- et le
        controle d'unicite de `CreateAccount` laisserait creer un compte que la
        production refuse.
        """
        marker = uuid4().hex[:8]
        account = an_account_stored_as(f"Veto-{marker}@Exemple.FR".upper())
        async with uow:
            await uow.accounts.add(account)
            await uow.commit()
            found = await uow.accounts.find_by_email(f"veto-{marker}@exemple.fr")
        assert found is not None
        assert found.id == account.id


class TestSqlAlchemyAccountRepositoryConformance(AccountRepositoryConformance):
    """La suite, jouee contre PostgreSQL par la base de test."""

    @pytest.fixture
    def uow(self, bound_sessionmaker: async_sessionmaker[AsyncSession]) -> IdentityUnitOfWork:
        """Unite de travail reelle, inscrite dans la transaction du test.

        PLUS DE PURGE, meme motif que la conformite du socle (BACK-12) : cette
        moitie commite toujours pour de bon, mais la transaction externe de
        `connection` l'annule -- y compris apres un test interrompu, ce que la
        purge « avant » ne faisait que reparer.
        """
        return SqlAlchemyIdentityUnitOfWork(bound_sessionmaker)


class TestInMemoryAccountRepositoryConformance(AccountRepositoryConformance):
    """La MEME suite, jouee contre la doublure du module."""

    @pytest.fixture
    def uow(self) -> Iterator[IdentityUnitOfWork]:
        """Unite de travail en memoire, neuve a chaque test."""
        yield InMemoryIdentityUnitOfWork()
