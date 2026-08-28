"""Creation de compte : le cas d'usage pilote, sur doublure (BACK-04, BACK-12).

CE FICHIER N'EXISTAIT PAS AVANT BACK-12, et c'est ce que la mesure de couverture
a revele : `create_account.py` etait a 0 %. Le cas d'usage etait exerce
indirectement -- par les suites de conformite, qui citent son controle
d'unicite -- mais rien ne verifiait son comportement propre.

Il tourne SANS DOCKER, sur `InMemoryIdentityUnitOfWork`, et c'est la forme que
le ticket demande d'encourager : un cas d'usage se teste sur des doublures, pas
sur une base.
"""

import pytest

from app.modules.identity.application.use_cases.create_account import (
    CreateAccount,
    CreateAccountCommand,
)
from app.modules.identity.domain.entities import AccountStatus, AccountType
from app.modules.identity.domain.exceptions import EmailAlreadyUsedError
from app.modules.identity.infrastructure.memory.unit_of_work import (
    InMemoryIdentityUnitOfWork,
)
from tests.modules.identity.helpers import an_account, stored_account


def a_command(**overrides: object) -> CreateAccountCommand:
    """Une commande de creation valide, surchargeable champ par champ."""
    fields: dict[str, object] = {
        "email": "jean@exemple.fr",
        "first_name": "Jean",
        "last_name": "Dupont",
        "account_type": AccountType.INDIVIDUAL,
    }
    fields.update(overrides)
    return CreateAccountCommand(**fields)  # type: ignore[arg-type]


async def test_a_created_account_is_committed_and_active() -> None:
    """Le compte est ecrit, VALIDE, actif et pas encore verifie."""
    uow = InMemoryIdentityUnitOfWork()

    created = await CreateAccount(uow).execute(a_command())

    assert uow.commits == 1
    persisted = stored_account(uow, created.id)
    assert persisted.email == "jean@exemple.fr"
    assert persisted.status is AccountStatus.ACTIVE
    assert persisted.email_verified is False


async def test_the_email_is_normalized_before_the_uniqueness_check() -> None:
    """« Jean@Exemple.FR » et « jean@exemple.fr » sont la MEME adresse.

    C'est l'ordre qui compte, et le cas d'usage le documente : chercher
    l'adresse telle qu'elle arrive ne trouverait pas celle deja enregistree, et
    le controle d'unicite laisserait passer le doublon qu'il est cense arreter.
    """
    uow = InMemoryIdentityUnitOfWork(accounts=[an_account(email="jean@exemple.fr")])

    with pytest.raises(EmailAlreadyUsedError):
        await CreateAccount(uow).execute(a_command(email="  Jean@Exemple.FR  "))


async def test_a_duplicate_address_is_refused_without_writing_anything() -> None:
    """Le refus d'unicite sort du bloc SANS commit : rien n'est ecrit.

    C'est l'atomicite que l'unite de travail apporte, et `commits` la rend
    observable -- une assertion sur l'absence de compte ne distinguerait pas
    « rien ecrit » de « ecrit puis annule ».
    """
    uow = InMemoryIdentityUnitOfWork(accounts=[an_account(email="jean@exemple.fr")])

    with pytest.raises(EmailAlreadyUsedError):
        await CreateAccount(uow).execute(a_command())

    assert uow.commits == 0


async def test_a_free_address_is_accepted_next_to_an_existing_account() -> None:
    """Le controle d'unicite ne refuse que l'adresse deja prise."""
    uow = InMemoryIdentityUnitOfWork(accounts=[an_account(email="jean@exemple.fr")])

    created = await CreateAccount(uow).execute(a_command(email="marie@exemple.fr"))

    assert uow.commits == 1
    assert stored_account(uow, created.id).email == "marie@exemple.fr"


async def test_the_phone_is_optional() -> None:
    """Un compte sans telephone se cree ; le champ reste nul."""
    uow = InMemoryIdentityUnitOfWork()

    created = await CreateAccount(uow).execute(a_command(phone=None))

    assert stored_account(uow, created.id).phone is None


async def test_the_account_type_travels_from_the_command_to_the_entity() -> None:
    """Le type demande est celui qui est persiste -- aucune valeur par defaut ne s'impose."""
    uow = InMemoryIdentityUnitOfWork()

    created = await CreateAccount(uow).execute(
        a_command(email="pro@exemple.fr", account_type=AccountType.PROFESSIONAL)
    )

    assert stored_account(uow, created.id).account_type is AccountType.PROFESSIONAL
