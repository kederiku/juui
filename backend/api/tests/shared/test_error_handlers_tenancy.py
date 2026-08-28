"""La non-divulgation au niveau HTTP : 404, jamais 403 (BACK-06b + BACK-09).

Miroir HTTP de `test_cross_group_get_is_indistinguishable_from_absence` : la
chaine COMPLETE -- filtre du depot, erreur d'absence typee `NotFoundError`,
traduction par les handlers -- repond a une ressource d'un autre groupe
exactement comme a une ressource inexistante. Un 403 confirmerait l'existence
de la ressource chez un concurrent.

PostgreSQL requis (fixtures `session`/`group_*` du conftest) : la preuve porte
sur le depot reel de BACK-06b, pas sur une erreur levee a la main -- ce cas-la
est deja couvert par la matrice de `test_error_handlers.py`.
"""

from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.infrastructure.api.error_handlers import register_error_handlers
from app.shared.infrastructure.tenancy import use_group
from tests.support.api import asgi_client
from tests.support.tenancy_stubs import TenantNoteRepository, make_tenant_row

pytestmark = pytest.mark.tenant_isolation


def _build_app(session: AsyncSession, viewer_group: UUID) -> FastAPI:
    """Application minimale : une route de lecture, le groupe lecteur en closure."""
    application = FastAPI()
    register_error_handlers(application)

    @application.get("/tenant-notes/{note_id}")
    async def read_note(note_id: UUID) -> dict[str, str]:
        with use_group(viewer_group):
            note = await TenantNoteRepository(session).get(note_id)
        return {"id": str(note.id), "label": note.label}

    return application


async def test_cross_group_read_answers_404_never_403(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    note_id = uuid4()
    session.add(make_tenant_row(note_id, group_a, "note du groupe A"))
    await session.flush()
    async with asgi_client(_build_app(session, group_b)) as client:
        response = await client.get(f"/tenant-notes/{note_id}")
    assert response.status_code == 404
    assert response.status_code != 403
    body = response.json()
    assert body["code"] == "tests.tenant_note.not_found"
    assert set(body) == {"code", "message", "details", "request_id"}


async def test_cross_group_response_is_indistinguishable_from_absence(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    """Meme identifiant, deux realites, un seul corps de reponse possible."""
    note_id = uuid4()
    async with asgi_client(_build_app(session, group_b)) as client:
        absent = await client.get(f"/tenant-notes/{note_id}")
        session.add(make_tenant_row(note_id, group_a, "note du groupe A"))
        await session.flush()
        cross = await client.get(f"/tenant-notes/{note_id}")
    assert absent.status_code == 404
    assert cross.status_code == 404
    absent_body, cross_body = absent.json(), cross.json()
    # BACK-11 genere un identifiant par requete : des que ce fichier passera sur
    # `create_app()`, les deux corps differeront par construction. On compare
    # tout le reste, qui doit rester indistinguable -- c'est le critere de
    # NON-DIVULGATION qui se joue ici, pas celui de correlation.
    absent_body.pop("request_id")
    cross_body.pop("request_id")
    assert absent_body == cross_body
