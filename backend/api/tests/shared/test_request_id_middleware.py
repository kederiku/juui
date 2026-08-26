"""Identifiant de requete : generation, reprise, echo, propagation (BACK-11, criteres 3 et 7).

DEUX TESTS DE CE FICHIER PROTEGENT UNE DECISION, ET EUX SEULS
`test_the_identifier_reaches_the_endpoint_through_the_contextvar` echoue si
l'intergiciel est un jour reecrit en `BaseHTTPMiddleware` -- Starlette en execute
l'aval dans une TACHE distincte, dont la copie de contexte part avant le `set()`.
Et les deux tests du 500 echouent si l'on cesse de passer par la cle de `scope` :
`ServerErrorMiddleware` repond avec le `send` d'origine, hors de toute enveloppe
de sortie, et apres que la contextvar a ete remise.
"""

from typing import Any
from uuid import UUID

import pytest
from fastapi import FastAPI

from app.core.correlation import REQUEST_ID_SCOPE_KEY, current_request_id
from app.shared.infrastructure.api.middlewares import RequestIdMiddleware
from tests.shared.api_probes import build_app, client

pytestmark = pytest.mark.observability

_BOOM = "/probe/back-11/boom"
_SEEN = "/probe/back-11/seen-by-the-endpoint"


def _app_with_probes() -> FastAPI:
    """L'application reelle, plus deux routes de sonde."""
    application = build_app()

    @application.get(_BOOM)
    async def boom() -> None:
        message = "panne de sonde"
        raise RuntimeError(message)

    @application.get(_SEEN)
    async def seen() -> dict[str, str | None]:
        return {"seen": current_request_id.get()}

    return application


# --- Generation et reprise ---------------------------------------------------


async def test_a_request_without_the_header_receives_a_generated_identifier() -> None:
    async with client(build_app()) as opened:
        response = await opened.get("/health/live")
    assert UUID(hex=response.headers["x-request-id"])


async def test_two_requests_receive_two_distinct_identifiers() -> None:
    async with client(build_app()) as opened:
        first = await opened.get("/health/live")
        second = await opened.get("/health/live")
    assert first.headers["x-request-id"] != second.headers["x-request-id"]


async def test_a_client_supplied_identifier_is_reused() -> None:
    """Un identifiant de tracage venu d'une passerelle ou d'un frontend survit."""
    async with client(build_app()) as opened:
        response = await opened.get("/health/live", headers={"X-Request-ID": "trace-amont-42"})
    assert response.headers["x-request-id"] == "trace-amont-42"


@pytest.mark.parametrize(
    "hostile",
    [
        "a\r\nX-Injecte: 1",
        "a\nligne-de-journal-fabriquee",
        "x" * 200,
        "",
        "   ",
        "<script>alert(1)</script>",
        "a b c",
        "\x00nul",
    ],
)
async def test_a_hostile_client_identifier_is_replaced_and_never_rectified(hostile: str) -> None:
    """JETE, PAS ASSAINI : une valeur tronquee serait un jeton menteur.

    Les trois dangers sont reels -- une scission de reponse HTTP, une ligne de
    journal fabriquee, et dix kilo-octets recopies sur chaque ligne de la requete.
    """
    async with client(build_app()) as opened:
        response = await opened.get("/health/live", headers={"X-Request-ID": hostile})
    rendered = response.headers["x-request-id"]
    assert rendered != hostile
    assert UUID(hex=rendered)


async def test_a_non_ascii_client_identifier_is_replaced() -> None:
    """Cas qu'aucun client HTTP ne sait emettre, et qu'un serveur reel presente quand meme.

    `httpx` refuse d'encoder un en-tete non-ASCII : le cas ne peut donc pas
    passer par le client de test. Uvicorn, lui, rend les en-tetes decodes en
    latin-1 -- c'est cette forme-la qui atteint l'intergiciel, et c'est donc
    celle qu'on eprouve, sur le vrai chemin ASGI.
    """
    seen: list[str] = []

    async def downstream(scope: dict[str, Any], receive: object, send: object) -> None:
        seen.append(scope[REQUEST_ID_SCOPE_KEY])

    async def never_called() -> dict[str, str]:
        return {"type": "http.disconnect"}

    scope: dict[str, Any] = {
        "type": "http",
        "headers": [(b"x-request-id", "accentue\u00e9".encode("latin-1"))],
    }
    await RequestIdMiddleware(downstream)(scope, never_called, never_called)  # type: ignore[arg-type]
    assert UUID(hex=seen[0])


async def test_a_sanitised_identifier_never_reaches_the_response_header() -> None:
    async with client(build_app()) as opened:
        response = await opened.get("/health/live", headers={"X-Request-ID": "a\r\nX-Injecte: 1"})
    assert "\r" not in response.headers["x-request-id"]
    assert "\n" not in response.headers["x-request-id"]
    assert "x-injecte" not in response.headers


# --- Propagation -------------------------------------------------------------


async def test_the_identifier_reaches_the_endpoint_through_the_contextvar() -> None:
    """LA preuve que l'intergiciel est ASGI PUR -- voir la docstring du module."""
    async with client(_app_with_probes()) as opened:
        response = await opened.get(_SEEN, headers={"X-Request-ID": "trace-endpoint"})
    assert response.json()["seen"] == "trace-endpoint"
    assert response.headers["x-request-id"] == "trace-endpoint"


async def test_the_contextvar_is_reset_once_the_response_is_sent() -> None:
    async with client(build_app()) as opened:
        await opened.get("/health/live")
    assert current_request_id.get() is None


async def test_a_non_http_scope_passes_through_untouched() -> None:
    """Le piege classique de l'intergiciel ASGI pur : `lifespan` n'est pas une requete."""
    seen: list[str] = []

    async def downstream(scope: dict[str, Any], receive: object, send: object) -> None:
        seen.append(scope["type"])

    async def never_called() -> dict[str, str]:
        return {"type": "lifespan.startup"}

    await RequestIdMiddleware(downstream)(  # type: ignore[arg-type]
        {"type": "lifespan"}, never_called, never_called
    )
    assert seen == ["lifespan"]
    assert current_request_id.get() is None


# --- Presence dans les reponses ----------------------------------------------


async def test_a_successful_response_carries_the_identifier() -> None:
    async with client(build_app()) as opened:
        response = await opened.get("/health/live")
    assert response.headers["x-request-id"]


async def test_a_404_carries_the_identifier_in_its_header_and_in_its_body() -> None:
    async with client(build_app()) as opened:
        response = await opened.get("/chemin/inconnu")
    assert response.status_code == 404
    assert response.json()["request_id"] == response.headers["x-request-id"]


async def test_the_identifier_header_is_never_duplicated() -> None:
    async with client(build_app()) as opened:
        response = await opened.get("/chemin/inconnu", headers={"X-Request-ID": "trace-unique"})
    assert response.headers.get_list("x-request-id") == ["trace-unique"]


async def test_a_500_carries_the_identifier_in_its_body() -> None:
    """LE piege du `reset(token)` : sans la cle de `scope`, ce corps dirait `null`."""
    async with client(_app_with_probes()) as opened:
        response = await opened.get(_BOOM)
    assert response.status_code == 500
    assert response.json()["request_id"] is not None


async def test_a_500_carries_the_identifier_in_its_header() -> None:
    """LE piege du `send` court-circuite : aucune enveloppe de sortie ne voit cette reponse."""
    async with client(_app_with_probes()) as opened:
        response = await opened.get(_BOOM)
    assert response.headers["x-request-id"]


async def test_the_header_and_the_body_of_a_500_agree() -> None:
    async with client(_app_with_probes()) as opened:
        response = await opened.get(_BOOM)
    assert response.json()["request_id"] == response.headers["x-request-id"]


async def test_a_500_reuses_the_identifier_the_client_supplied() -> None:
    async with client(_app_with_probes()) as opened:
        response = await opened.get(_BOOM, headers={"X-Request-ID": "trace-de-l-incident"})
    assert response.json()["request_id"] == "trace-de-l-incident"
    assert response.headers["x-request-id"] == "trace-de-l-incident"


async def test_a_500_body_still_says_nothing_of_the_failure() -> None:
    """L'identifiant s'ajoute au corps fige de BACK-09, il ne l'ouvre pas."""
    async with client(_app_with_probes()) as opened:
        response = await opened.get(_BOOM)
    body = response.json()
    assert body["code"] == "http.server.internal_error"
    assert body["details"] is None
    assert "panne de sonde" not in response.text
