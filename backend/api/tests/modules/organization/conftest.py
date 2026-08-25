"""Fixtures du module organization : ses vraies tables, sans migrations (BACK-16).

MEME PATRON QUE `_STUB_TABLES`, SUR LES VRAIES TABLES
Le conftest racine (BACK-06b) ne cree que les tables stubs ; celui-ci cree les
quatre tables du module dans la base de test, puis les detruit. Sans suffixe
`_test`, et c'est legitime : la base `app_test` ne recoit JAMAIS de
migrations -- aucune collision possible. Le jour ou BACK-12 appliquera les
migrations a la base de test, cette fixture disparaitra ; l'emprunt est
consigne au registre des ecarts.

L'ordre de creation respecte les cles etrangeres : `create_all` et `drop_all`
trient les tables passees en cible.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from app.modules.organization.infrastructure.db.models import (
    AssignmentModel,
    ClinicModel,
    GroupModel,
    MembershipModel,
)
from app.shared.infrastructure.db.base import Base

# Les quatre seules tables que ces tests creent et detruisent : jamais un
# create_all/drop_all sans cible.
_ORGANIZATION_TABLES = [
    GroupModel.__table__,
    ClinicModel.__table__,
    MembershipModel.__table__,
    AssignmentModel.__table__,
]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _organization_tables(engine: AsyncEngine) -> AsyncIterator[None]:
    """Cree les tables du module dans la base de test, puis les detruit.

    PAS `autouse` : seuls les tests d'integration la demandent (par le
    `pytest.mark.usefixtures` de `test_ports.py`), et les tests purs du
    domaine restent executables sans Docker.
    """
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=_ORGANIZATION_TABLES)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all, tables=_ORGANIZATION_TABLES)
