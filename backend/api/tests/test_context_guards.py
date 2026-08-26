"""Tests des garde-fous de contexte du harnais lui-meme.

UNE GARDE QUI N'EST PAS TESTEE N'EST PAS UNE GARDE, et celle-ci en est la preuve
par l'absurde : les fixtures `_ensure_clean_tenant_context` et
`_ensure_clean_request_context` existaient depuis BACK-06b et BACK-11, elles
rassuraient dans leur docstring, et elles ne voyaient RIEN de ce qui se passait
dans un test asynchrone -- c'est-a-dire dans la quasi-totalite de la suite.
Personne ne l'a vu pendant deux tickets, parce qu'aucun test ne leur demandait
jamais d'attraper quoi que ce soit.

CE QUE CES TESTS EPINGLENT
Que l'enveloppe posee par `pytest_runtest_setup` s'execute bien DANS la tache du
test -- donc qu'elle voit ce que les fixtures ne voient pas --, et qu'elle laisse
passer un test propre. Le cas reel est joue jusqu'au bout : une application ASGI
coiffee d'un intergiciel qui oublie son `reset(token)`, sondee par
`httpx.ASGITransport`.

POURQUOI PAS UN SOUS-PROCESSUS PYTEST
Un test qui fuit vraiment serait attrape par la garde qu'il eprouve. On appelle
donc l'enveloppe A LA MAIN, sur une coroutine fabriquee pour l'occasion : c'est
le meme objet que pytest-asyncio recevra, awaite depuis la tache du test courant.
Ce que ce montage ne prouve pas -- que `item.obj` est encore une coroutine a
`pytest_runtest_setup`, et ne l'est plus a `pytest_pyfunc_call` -- est un fait de
pytest-asyncio, mesure et consigne dans la docstring du hook.
"""

from collections.abc import Awaitable, Callable
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.correlation import current_request_id
from app.shared.infrastructure.tenancy import current_group_id, use_group
from tests.conftest import pytest_runtest_setup


class _FakeItem:
    """Le strict minimum que le hook lit d'un test : sa fonction.

    Un vrai `pytest.Function` demanderait une session, un module collecte et un
    jeu de fixtures resolu -- rien de tout cela n'entre dans ce que le hook fait.
    """

    def __init__(self, obj: Callable[[], Awaitable[object]]) -> None:
        """Porte la fonction de test."""
        self.obj = obj


def _guard(coroutine_function: Callable[[], Awaitable[object]]) -> Callable[[], Awaitable[object]]:
    """Passe une coroutine par le hook et rend ce que pytest-asyncio recevrait.

    Args:
        coroutine_function: la fonction de test a envelopper.

    Returns:
        L'enveloppe posee par le hook, ou la fonction telle quelle s'il l'ignore.
    """
    item = _FakeItem(coroutine_function)
    pytest_runtest_setup(item)  # type: ignore[arg-type]
    return item.obj


async def test_a_clean_async_test_passes_through() -> None:
    """Le cas nominal : une coroutine qui ne laisse rien derriere elle."""

    async def sujet() -> str:
        with use_group(uuid4()):
            pass
        return "termine"

    assert await _guard(sujet)() == "termine"


async def test_a_leaked_tenant_context_is_caught_inside_the_task() -> None:
    """Ce que les fixtures ne voyaient pas : un `set()` sans `reset` dans la tache."""

    async def sujet() -> None:
        current_group_id.set(uuid4())

    with pytest.raises(AssertionError, match="current_group_id"):
        await _guard(sujet)()

    # La fuite appartient a la tache de CE test : on la nettoie a la main, sinon
    # c'est la garde du test courant qui la trouverait en sortie.
    current_group_id.set(None)


async def test_a_leaked_request_context_is_caught_inside_the_task() -> None:
    """Les contextvars de requete sont gardees par le meme geste."""

    async def sujet() -> None:
        current_request_id.set("fuite-de-requete")

    with pytest.raises(AssertionError, match="current_request_id"):
        await _guard(sujet)()

    current_request_id.set(None)


async def test_a_synchronous_test_is_left_alone() -> None:
    """Le hook ne touche pas aux tests synchrones : leurs fixtures les gardent deja."""

    def sujet() -> str:
        return "synchrone"

    assert _guard(sujet) is sujet  # type: ignore[arg-type]


async def test_a_middleware_that_forgets_its_reset_is_caught() -> None:
    """LE cas que la docstring de BACK-11 revendiquait, joue jusqu'au bout.

    Sous `httpx.ASGITransport`, l'application tourne dans le contexte de
    l'APPELANT -- la ou uvicorn lui donnerait une tache. Un intergiciel qui
    oublie son `reset(token)` depose donc sa contextvar dans le contexte du
    TEST, ou tout ce qui suit la lit : une seconde requete du meme test verrait
    l'identifiant de la premiere.
    """

    class LeakingMiddleware:
        """Intergiciel ASGI pur qui pose une contextvar et ne la remet jamais."""

        def __init__(self, app: ASGIApp) -> None:
            """Coiffe l'application a sonder."""
            self._app = app

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            """Pose l'identifiant de requete, sans jamais le remettre."""
            if scope["type"] == "http":
                current_request_id.set("jamais-remis")
            await self._app(scope, receive, send)

    application = FastAPI()
    application.add_middleware(LeakingMiddleware)

    @application.get("/sonde")
    async def sonde() -> dict[str, str]:
        """Rend l'identifiant tel que la route le voit."""
        return {"request_id": str(current_request_id.get())}

    async def sujet() -> None:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/sonde")
        assert response.json()["request_id"] == "jamais-remis"

    with pytest.raises(AssertionError, match="current_request_id"):
        await _guard(sujet)()

    current_request_id.set(None)
