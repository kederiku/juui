"""Fixtures du module medical_records : ses vraies tables, sans migrations (BACK-19).

MEME PATRON QUE `_ORGANIZATION_TABLES` (BACK-16), sur les deux tables du
module. Le conftest racine (BACK-06b) ne cree que les tables stubs ; celui-ci
cree `animals` et `custodies` dans la base de test, puis les detruit. Sans
suffixe `_test`, et c'est legitime : la base `app_test` ne recoit JAMAIS de
migrations -- aucune collision possible. Le jour ou BACK-12 appliquera les
migrations a la base de test, cette fixture disparaitra ; l'emprunt est
consigne au registre des ecarts.

L'ordre de creation respecte les cles etrangeres : `create_all` et `drop_all`
trient les tables passees en cible.
"""

from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine

from app.modules.medical_records.infrastructure.db.models import AnimalModel, CustodyModel
from app.shared.infrastructure.db.base import Base

# Les deux seules tables que ces tests creent et detruisent : jamais un
# create_all/drop_all sans cible.
_MEDICAL_RECORDS_TABLES = [
    AnimalModel.__table__,
    CustodyModel.__table__,
]


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _medical_records_tables(engine: AsyncEngine) -> AsyncIterator[None]:
    """Cree les tables du module dans la base de test, puis les detruit.

    PAS `autouse` : seuls les tests d'integration la demandent (par le
    `pytest.mark.usefixtures` de `test_ports.py`), et les tests purs du
    domaine restent executables sans Docker.
    """
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=_MEDICAL_RECORDS_TABLES)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all, tables=_MEDICAL_RECORDS_TABLES)
