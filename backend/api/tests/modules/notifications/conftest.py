"""Fixtures du module notifications : sa vraie table, sans migrations (BACK-22).

MEME PATRON QUE `_IDENTITY_TABLES` (INFRA-09), `_ORGANIZATION_TABLES` (BACK-16)
et `_MEDICAL_RECORDS_TABLES` (BACK-19). Le conftest racine (BACK-06b) ne cree que
les tables stubs ; celui-ci cree `notification_preferences` dans la base de test,
puis la detruit. Le jour ou BACK-12 appliquera les migrations a la base de test,
cette fixture disparaitra ; l'emprunt est consigne au registre des ecarts.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from app.modules.notifications.infrastructure.db.models import NotificationPreferencesModel
from app.shared.infrastructure.db.base import Base

# La seule table que ces tests creent et detruisent : jamais un
# create_all/drop_all sans cible.
_NOTIFICATIONS_TABLES = [
    NotificationPreferencesModel.__table__,
]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _notifications_tables(engine: AsyncEngine) -> AsyncIterator[None]:
    """Cree la table du module dans la base de test, puis la detruit.

    PAS `autouse` : seuls les tests d'integration la demandent (par le
    `pytest.mark.usefixtures` de `test_ports.py`), et les tests purs du domaine
    restent executables sans Docker.
    """
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=_NOTIFICATIONS_TABLES)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all, tables=_NOTIFICATIONS_TABLES)
