"""Journal d'acces : une ligne par requete, et une seule (BACK-11, critere 7).

CE QUE PROUVE CE FICHIER, QU'AUCUN AUTRE NE PROUVE
Que la ligne existe pour TOUTES les issues -- y compris le 500, ou
`http.response.start` ne parvient jamais a l'intergiciel ; que la chaine de
requete y arrive masquee, la ou celle d'uvicorn journalisait `?token=...` en
clair ; et que le meme identifiant figure dans la ligne ET dans la reponse, ce
qui est le critere 7 de bout en bout.
"""

from typing import Any

import pytest
from fastapi import FastAPI

from app.core.config import AppSettings
from tests.core.logging_probes import isolated_logging
from tests.shared.api_probes import (
    API_SETTINGS,
    FRONTEND_ORIGINS,
    access_lines,
    build_app,
    client,
)

pytestmark = pytest.mark.observability

_BOOM = "/probe/back-11/boom"
_OK = "/probe/back-11/ok"


def _app_with_probe() -> FastAPI:
    """L'application reelle, plus une route qui repond et une route qui leve.

    Les deux sont necessaires : les seules routes reelles du service sont les
    sondes de sante, qui sont precisement CELLES QUE LE JOURNAL TAIT quand elles
    vont bien -- rien, sans cela, ne permettrait d'observer une ligne en INFO.
    """
    application = build_app()

    @application.get(_OK)
    async def served() -> dict[str, bool]:
        return {"ok": True}

    @application.get(_BOOM)
    async def boom() -> None:
        message = "panne de sonde"
        raise RuntimeError(message)

    return application


async def _served(
    path: str,
    *,
    application: FastAPI | None = None,
    headers: dict[str, str] | None = None,
    settings: AppSettings = API_SETTINGS,
) -> tuple[Any, list[dict[str, Any]]]:
    """Sert une requete et rend la reponse avec les lignes d'acces qu'elle a produites."""
    with isolated_logging(settings) as stream:
        async with client(application or build_app()) as opened:
            response = await opened.get(path, headers=headers)
        return response, access_lines(stream.getvalue())


# --- La ligne existe, et une seule -------------------------------------------


async def test_each_request_emits_exactly_one_access_line() -> None:
    _, lines = await _served("/api/v1/inconnu")
    assert len(lines) == 1


async def test_the_access_line_carries_the_method_the_path_and_the_status() -> None:
    _, lines = await _served("/api/v1/inconnu")
    assert lines[0]["method"] == "GET"
    assert lines[0]["path"] == "/api/v1/inconnu"
    assert lines[0]["status"] == 404


async def test_the_access_line_carries_a_duration_in_milliseconds() -> None:
    _, lines = await _served("/api/v1/inconnu")
    assert isinstance(lines[0]["duration_ms"], float | int)
    assert lines[0]["duration_ms"] >= 0


async def test_the_access_line_and_the_response_carry_the_same_identifier() -> None:
    """Le critere 7, de bout en bout : le journal et le client parlent du meme appel."""
    response, lines = await _served("/api/v1/inconnu", headers={"X-Request-ID": "trace-critere-7"})
    assert lines[0]["request_id"] == "trace-critere-7"
    assert response.headers["x-request-id"] == "trace-critere-7"


async def test_the_access_line_carries_the_client_address() -> None:
    _, lines = await _served("/api/v1/inconnu")
    assert lines[0]["client_ip"]


# --- Les issues qui echappent a l'intergiciel --------------------------------


async def test_a_failing_endpoint_still_produces_its_access_line() -> None:
    """`http.response.start` ne parvient JAMAIS a l'intergiciel sur ce chemin.

    `ServerErrorMiddleware` est au-dessus de nous et repond avec son propre
    `send` : sans le statut suppose a 500, un 500 serait la seule issue absente
    du journal d'acces -- precisement celle qu'on cherche apres coup.
    """
    _, lines = await _served(_BOOM, application=_app_with_probe())
    assert len(lines) == 1
    assert lines[0]["status"] == 500


async def test_a_refused_preflight_produces_one_access_line_naming_the_origin() -> None:
    """Le SEUL signal serveur d'une origine mal configuree.

    Sans lui, le navigateur jette la reponse et rien, de ce cote-ci, ne dit
    pourquoi.
    """
    with isolated_logging(API_SETTINGS) as stream:
        async with client(build_app()) as opened:
            await opened.options(
                "/api/v1/anything",
                headers={
                    "Origin": "https://evil.example",
                    "Access-Control-Request-Method": "POST",
                },
            )
        lines = access_lines(stream.getvalue())
    assert len(lines) == 1
    assert lines[0]["status"] == 400
    assert lines[0]["origin"] == "https://evil.example"


async def test_an_accepted_preflight_names_no_origin() -> None:
    with isolated_logging(API_SETTINGS) as stream:
        async with client(build_app()) as opened:
            await opened.options(
                "/api/v1/anything",
                headers={
                    "Origin": FRONTEND_ORIGINS[0],
                    "Access-Control-Request-Method": "POST",
                },
            )
        lines = access_lines(stream.getvalue())
    assert "origin" not in lines[0]


# --- Le niveau suit le statut ------------------------------------------------


async def test_a_served_request_is_logged_at_info() -> None:
    _, lines = await _served(_OK, application=_app_with_probe())
    assert lines[0]["status"] == 200
    assert lines[0]["level"] == "INFO"


async def test_a_client_error_is_logged_above_info() -> None:
    _, lines = await _served("/api/v1/inconnu")
    assert lines[0]["level"] == "WARNING"


async def test_a_server_error_is_logged_at_error() -> None:
    """La propriete utile : `LOG_LEVEL=WARNING` ne laisse plus que les problemes."""
    _, lines = await _served(_BOOM, application=_app_with_probe())
    assert lines[0]["level"] == "ERROR"


async def test_a_warning_level_hides_the_served_requests_and_keeps_the_failures() -> None:
    """En production, `LOG_LEVEL=WARNING` reduit le journal d'acces aux problemes.

    C'est la propriete que le niveau par statut achete : un seul reglage, deja
    existant, et le volume tombe a ce qui merite d'etre lu.
    """
    quiet = AppSettings(
        environment="production", log_level="WARNING", cors_origins=list(FRONTEND_ORIGINS)
    )
    _, served = await _served(_OK, application=_app_with_probe(), settings=quiet)
    assert served == []
    _, failed = await _served("/api/v1/inconnu", settings=quiet)
    assert failed[0]["status"] == 404


# --- La chaine de requete ----------------------------------------------------


async def test_the_query_string_is_logged_with_its_secrets_masked() -> None:
    """La ligne d'uvicorn journalisait le chemin AVEC sa chaine de requete."""
    _, lines = await _served("/api/v1/inconnu?token=en-clair&page=2")
    assert lines[0]["query"] == "token=***&page=2"
    assert "en-clair" not in str(lines[0])


async def test_the_logged_path_never_carries_the_query_string() -> None:
    _, lines = await _served("/api/v1/inconnu?page=2")
    assert lines[0]["path"] == "/api/v1/inconnu"


async def test_a_request_without_a_query_string_carries_no_query_key() -> None:
    _, lines = await _served("/api/v1/inconnu")
    assert "query" not in lines[0]


# --- Les sondes de sante -----------------------------------------------------


async def test_the_liveness_probe_does_not_flood_the_access_log() -> None:
    """Le healthcheck frappe cette route six fois par minute, pour toujours dire la meme chose."""
    _, lines = await _served("/health/live")
    assert lines == []


async def test_a_failing_health_probe_is_logged() -> None:
    """« Silencieux tant que le statut est bon » et non une exclusion seche.

    Sans `lifespan`, la sonde de disponibilite echoue -- et ce 500-la EST une
    information.
    """
    response, lines = await _served("/health/ready")
    assert response.status_code == 500
    assert len(lines) == 1
    assert lines[0]["path"] == "/health/ready"
