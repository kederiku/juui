"""Politique CORS de l'API (BACK-11, criteres 1 et 6).

CE QUI NE SE PROUVE PAS EN OBSERVANT UNE REPONSE
Sous `allow_credentials=True`, Starlette echoise l'origine du client MEME
configure avec `allow_origins=["*"]` : deux configurations opposees rendent la
meme reponse. Le critere « jamais de joker » ne peut donc etre tenu que par une
garde au demarrage -- c'est `test_a_wildcard_is_refused_at_startup` qui le
prouve, et lui seul.
"""

import pytest
from starlette.middleware.cors import CORSMiddleware

from app.core.config import AppSettings, ConfigurationError
from app.shared.infrastructure.api.middlewares import (
    AccessLogMiddleware,
    RequestIdMiddleware,
    register_middlewares,
)
from tests.shared.api_probes import FRONTEND_ORIGINS, build_app, client

pytestmark = pytest.mark.observability

_FOREIGN_ORIGIN = "https://evil.example"
_PREFLIGHT = {"Access-Control-Request-Method": "POST"}


# --- Le preflight ------------------------------------------------------------


@pytest.mark.parametrize("origin", FRONTEND_ORIGINS)
async def test_the_three_frontend_origins_are_accepted(origin: str) -> None:
    """Le critere 6 en assertion : les trois frontends de `.env.example`."""
    async with client(build_app()) as opened:
        response = await opened.options(
            "/api/v1/anything", headers={"Origin": origin, **_PREFLIGHT}
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


async def test_a_preflight_advertises_the_headers_the_frontends_send() -> None:
    """`X-Clinic-Id` vient de l'ADR-0012, `Authorization` de BACK-10."""
    async with client(build_app()) as opened:
        response = await opened.options(
            "/api/v1/anything",
            headers={
                "Origin": FRONTEND_ORIGINS[0],
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,x-clinic-id,x-request-id",
            },
        )
    allowed = response.headers["access-control-allow-headers"].lower()
    assert "authorization" in allowed
    assert "x-clinic-id" in allowed
    assert "x-request-id" in allowed


@pytest.mark.parametrize("method", ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
async def test_a_preflight_advertises_the_methods_the_api_serves(method: str) -> None:
    """HEAD y figure parce que Starlette l'ajoute d'office a toute route GET."""
    async with client(build_app()) as opened:
        response = await opened.options(
            "/api/v1/anything",
            headers={"Origin": FRONTEND_ORIGINS[0], "Access-Control-Request-Method": method},
        )
    assert response.status_code == 200
    assert method in response.headers["access-control-allow-methods"]


async def test_a_preflight_never_reaches_the_router() -> None:
    """Un chemin inconnu rend 200 et non 404 : le CORS repond avant le routage."""
    async with client(build_app()) as opened:
        response = await opened.options(
            "/chemin/qui/n/existe/pas", headers={"Origin": FRONTEND_ORIGINS[0], **_PREFLIGHT}
        )
    assert response.status_code == 200


async def test_a_preflight_from_an_unlisted_origin_omits_the_allow_origin_header() -> None:
    """Et NON « aucun en-tete CORS » : Starlette en rend une partie malgre le refus."""
    async with client(build_app()) as opened:
        response = await opened.options(
            "/api/v1/anything", headers={"Origin": _FOREIGN_ORIGIN, **_PREFLIGHT}
        )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


async def test_a_refused_preflight_answers_in_plain_text() -> None:
    """ECART ASSUME au format d'erreur unique de BACK-09.

    Un preflight ne remonte jamais au code applicatif : le CORS le fabrique
    lui-meme, et sa reponse ne passe donc par aucun handler d'erreur. Rien a
    corriger, tout a savoir -- d'ou ce test.
    """
    async with client(build_app()) as opened:
        response = await opened.options(
            "/api/v1/anything", headers={"Origin": _FOREIGN_ORIGIN, **_PREFLIGHT}
        )
    assert response.text.strip() == "Disallowed CORS origin"


async def test_a_refused_preflight_still_carries_a_request_id() -> None:
    """La preuve de l'ordre de montage : l'identifiant est POSE AU-DESSUS du CORS.

    Sans cet ordre, le seul symptome exploitable d'une origine mal configuree
    serait invisible cote serveur -- le navigateur, lui, jette la reponse en
    silence.
    """
    async with client(build_app()) as opened:
        response = await opened.options(
            "/api/v1/anything", headers={"Origin": _FOREIGN_ORIGIN, **_PREFLIGHT}
        )
    assert response.headers["x-request-id"]


# --- Les requetes ordinaires -------------------------------------------------


async def test_a_simple_request_echoes_the_exact_origin_never_a_star() -> None:
    async with client(build_app()) as opened:
        response = await opened.get("/health/live", headers={"Origin": FRONTEND_ORIGINS[0]})
    assert response.headers["access-control-allow-origin"] == FRONTEND_ORIGINS[0]


async def test_credentials_are_allowed_on_a_listed_origin() -> None:
    async with client(build_app()) as opened:
        response = await opened.get("/health/live", headers={"Origin": FRONTEND_ORIGINS[0]})
    assert response.headers["access-control-allow-credentials"] == "true"


async def test_the_request_id_header_is_exposed_to_the_browser() -> None:
    """Sans cette liste, `response.headers.get('X-Request-ID')` rend `null` cote client."""
    async with client(build_app()) as opened:
        response = await opened.get("/health/live", headers={"Origin": FRONTEND_ORIGINS[0]})
    assert "X-Request-ID" in response.headers["access-control-expose-headers"]


async def test_a_simple_request_from_an_unlisted_origin_carries_no_allow_origin() -> None:
    async with client(build_app()) as opened:
        response = await opened.get("/health/live", headers={"Origin": _FOREIGN_ORIGIN})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


async def test_a_request_without_an_origin_header_gets_no_cors_headers() -> None:
    async with client(build_app()) as opened:
        response = await opened.get("/health/live")
    assert "access-control-allow-origin" not in response.headers


async def test_an_empty_whitelist_grants_no_origin_at_all() -> None:
    """Le CORS reste monte : un `400` qui nomme la cause vaut mieux qu'un `405` de routage."""
    application = build_app(AppSettings(environment="development", cors_origins=[]))
    async with client(application) as opened:
        response = await opened.options(
            "/api/v1/anything", headers={"Origin": FRONTEND_ORIGINS[0], **_PREFLIGHT}
        )
    assert response.status_code == 400


# --- La garde de demarrage ---------------------------------------------------


def test_a_wildcard_is_refused_at_startup() -> None:
    """LE test du critere « jamais de joker » -- voir la docstring du module."""
    with pytest.raises(ConfigurationError, match="joker"):
        build_app(AppSettings(environment="production", cors_origins=["*"]))


def test_a_wildcard_is_refused_even_alongside_legitimate_origins() -> None:
    settings = AppSettings(environment="production", cors_origins=[*FRONTEND_ORIGINS, "*"])
    with pytest.raises(ConfigurationError):
        build_app(settings)


def test_an_empty_whitelist_is_not_a_refusal(caplog: pytest.LogCaptureFixture) -> None:
    """Sans origine, l'API repond toujours -- aux clients qui ne sont pas des navigateurs.

    Meme asymetrie que le cache dans le `lifespan` : un service d'integration
    legitime n'a pas a etre arrete parce qu'aucun navigateur n'est declare.
    """
    with caplog.at_level("WARNING"):
        build_app(AppSettings(environment="production", cors_origins=[]))
    assert any("CORS_ORIGINS est vide" in record.message for record in caplog.records)


# --- L'ordre de montage ------------------------------------------------------


def test_the_middlewares_are_mounted_from_the_outermost_to_the_innermost() -> None:
    """`add_middleware` insere en position 0 : l'index 0 est le plus EXTERIEUR.

    L'identifiant d'abord, pour que meme un refus de preflight le porte ; le
    journal d'acces ensuite, au-dessus du CORS, pour qu'il voie ce refus.
    """
    mounted = [entry.cls for entry in build_app().user_middleware]
    assert mounted == [RequestIdMiddleware, AccessLogMiddleware, CORSMiddleware]


def test_registering_twice_would_mount_twice() -> None:
    """Garde-fou de lecture : `register_middlewares` n'est PAS idempotente.

    Elle est appelee une fois, par `create_app()`. Ce test fige le fait pour que
    personne ne l'appelle « au cas ou » depuis un autre endroit.
    """
    application = build_app()
    before = len(application.user_middleware)
    register_middlewares(application, settings=AppSettings(cors_origins=list(FRONTEND_ORIGINS)))
    assert len(application.user_middleware) == before + 3
