"""Le schema migre et les modeles ne divergent pas (BACK-12).

CE QUE LES `create_all` PAR MODULE ACHETAIENT, EN UN SEUL TEST
Jusqu'a BACK-12, chaque module creait ses tables dans la base de test depuis
`Base.metadata`. Ce detour avait un effet de bord PRECIEUX, que le conftest
d'identity nommait : il obligeait un index comme `ix_accounts_email_lower` a
vivre dans le MODELE, et pas seulement dans sa migration -- sans quoi la suite
tournait contre un schema qui ne le portait pas. Appliquer les migrations fait
perdre cette pression : un index present dans la migration mais absent du modele
passerait desormais inapercu.

Ce test la rachete, et rend davantage. Il compare le schema REELLEMENT applique
a `Base.metadata`, avec les memes options qu'`alembic/env.py` -- `compare_type`
et `compare_server_default`, la seconde n'etant pas un defaut. Il echoue donc
dans les deux sens : modele en avance sur les migrations, migration en avance
sur le modele.

IL EST AUSSI LE FILET DU `drop_all`. La fixture `engine` ne detruit que les deux
tables stubs, et son `tables=` est obligatoire : un `drop_all()` nu vaporiserait
le schema migre en laissant `alembic_version` a la tete, si bien que l'execution
suivante ferait un `upgrade head` sans rien a faire contre une base vide. Ce
test-la le dirait des le premier test de base de donnees, en nommant les tables
manquantes -- au lieu de laisser deux cents `UndefinedTable` sans cause visible.
"""

from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from app.shared.infrastructure.db.base import Base


def _differences(sync_connection: Connection) -> list[object]:
    """Compare le schema de la connexion a `Base.metadata`."""
    context = MigrationContext.configure(
        sync_connection,
        opts={"compare_type": True, "compare_server_default": True},
    )
    return list(compare_metadata(context, Base.metadata))


async def test_the_migrated_schema_matches_the_models(engine: AsyncEngine) -> None:
    """Aucune difference entre ce que les migrations posent et ce que les modeles declarent.

    Les deux tables stubs de `tenancy_stubs` ne faussent pas la comparaison : la
    fixture `engine` les cree apres les migrations, elles sont donc dans
    `Base.metadata` ET dans la base. `alembic_version` est ignoree d'office par
    le comparateur.
    """
    async with engine.connect() as connection:
        assert await connection.run_sync(_differences) == []
