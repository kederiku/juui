"""Fixtures du module identity : sa vraie table, sans migrations (INFRA-09).

MEME PATRON QUE `_MEDICAL_RECORDS_TABLES` (BACK-19) et `_ORGANIZATION_TABLES`
(BACK-16), sur l'unique table du module. Le conftest racine (BACK-06b) ne cree
que les tables stubs ; celui-ci cree `accounts` dans la base de test, puis la
detruit. C'est ce passage par `Base.metadata.create_all` qui oblige l'index
`ix_accounts_email_lower` a vivre dans le MODELE et pas seulement dans sa
migration : une garantie que la suite ne verrait pas n'en serait pas une. Le
jour ou BACK-12 appliquera les migrations a la base de test, cette fixture
disparaitra ; l'emprunt est consigne au registre des ecarts.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from app.modules.identity.infrastructure.db.models import AccountModel
from app.shared.infrastructure.db.base import Base

# La seule table que ces tests creent et detruisent : jamais un
# create_all/drop_all sans cible.
_IDENTITY_TABLES = [
    AccountModel.__table__,
]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _identity_tables(engine: AsyncEngine) -> AsyncIterator[None]:
    """Cree la table du module dans la base de test, puis la detruit.

    PAS `autouse` : seuls les tests d'integration la demandent (par le
    `pytest.mark.usefixtures` de `test_ports.py`), et les tests purs du
    domaine restent executables sans Docker.
    """
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=_IDENTITY_TABLES)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all, tables=_IDENTITY_TABLES)
