"""Tests de la traduction des erreurs en HTTP (BACK-09).

Sans base de donnees : la matrice statut/format se prouve sur une application
minimale -- `FastAPI()` nue, `register_error_handlers`, routes jetables qui
levent chaque exception -- et le cablage reel se prouve sur `create_app()`
(jamais l'instance module `app`, regle du depot). `ASGITransport` ne declenche
pas le lifespan : l'application reelle se teste donc sans PostgreSQL, Redis ni
S3.

`raise_app_exceptions=False` sur le transport est OBLIGATOIRE pour les tests
du 500 : `ServerErrorMiddleware` envoie la reponse du handler PUIS re-leve
l'exception, et sans ce drapeau elle traverserait le client de test.

DEPUIS BACK-11, LES DEUX ANGLES NE PROUVENT PLUS LA MEME CHOSE
`create_app()` monte desormais trois intergiciels ; `_build_app()` n'en monte
aucun. Les tests batis sur la seconde eprouvent le TRADUCTEUR seul -- dont le
comportement hors de toute requete HTTP, qui est le cas reel d'une `DomainError`
levee depuis une tache de fond ou un script. Ceux batis sur la premiere eprouvent
le traducteur ET la chaine. NE PAS convertir les premiers aux seconds : les deux
angles sont distincts, et le second ne couvre pas le premier.
"""

import logging

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.core.correlation import use_request_id
from app.main import create_app
from app.shared.domain.exceptions import (
    AlreadyExistsError,
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    TooManyRequestsError,
    ValidationError,
)
from app.shared.domain.ports.file_storage import FileStorageUnavailableError
from app.shared.domain.ports.token_service import InactiveMembershipError
from app.shared.infrastructure.api.error_handlers import register_error_handlers
from app.shared.infrastructure.tenancy import MissingTenantContextError
from tests.support.api import asgi_client

_INTERNAL_DETAIL = "detail-interne-10.0.0.5"

_DELIBERATE_BODY = {"status": "unready", "components": {"postgres": "unreachable", "redis": "ok"}}


class _ProbeNotFoundError(NotFoundError):
    """Absence de sonde, reparentee comme le ferait un module."""

    code = "probe.note.not_found"


class _ProbeAlreadyExistsError(AlreadyExistsError):
    """Doublon de sonde."""

    code = "probe.note.already_exists"


class _ProbeConflictError(ConflictError):
    """Conflit d'etat de sonde."""

    code = "probe.note.conflict"


class _ProbeValidationError(ValidationError):
    """Valeur refusee par une regle de sonde."""

    code = "probe.note.invalid"


class _ProbePermissionDeniedError(PermissionDeniedError):
    """Refus de droit de sonde."""

    code = "probe.note.forbidden"


class _ProbeTooManyRequestsError(TooManyRequestsError):
    """Cadence de sonde depassee (categorie ajoutee par BACK-17)."""

    code = "probe.note.too_many"


class _ProbePayload(BaseModel):
    """Corps de sonde : un champ contraint et aucun champ inconnu tolere."""

    model_config = ConfigDict(extra="forbid")

    count: int = Field(gt=0)


def _build_app() -> FastAPI:
    """Construit l'application minimale : handlers enregistres, routes jetables."""
    application = FastAPI()
    register_error_handlers(application)

    @application.get("/raise/not-found")
    async def raise_not_found() -> None:
        raise _ProbeNotFoundError("Aucune note de sonde ne porte cet identifiant.")

    @application.get("/raise/already-exists")
    async def raise_already_exists() -> None:
        raise _ProbeAlreadyExistsError("Une note de sonde identique existe deja.")

    @application.get("/raise/conflict")
    async def raise_conflict() -> None:
        raise _ProbeConflictError("La note de sonde n'est pas dans le bon etat.")

    @application.get("/raise/validation")
    async def raise_validation() -> None:
        raise _ProbeValidationError("La valeur de sonde est refusee.")

    @application.get("/raise/permission")
    async def raise_permission() -> None:
        raise _ProbePermissionDeniedError("La sonde n'a pas ce droit.")

    @application.get("/raise/too-many")
    async def raise_too_many() -> None:
        raise _ProbeTooManyRequestsError("Trop de sondes, trop vite.", retry_after_seconds=42)

    @application.get("/raise/too-many-without-delay")
    async def raise_too_many_without_delay() -> None:
        raise _ProbeTooManyRequestsError("Trop de sondes, trop vite.")

    @application.get("/raise/untyped")
    async def raise_untyped() -> None:
        raise DomainError("Refus metier sans categorie.")

    @application.get("/raise/unexpected")
    async def raise_unexpected() -> None:
        raise MissingTenantContextError(_INTERNAL_DETAIL)

    @application.get("/raise/storage-unavailable")
    async def raise_storage_unavailable() -> None:
        raise FileStorageUnavailableError("Le stockage objet ne repond pas.")

    @application.get("/raise/inactive-membership")
    async def raise_inactive_membership() -> None:
        raise InactiveMembershipError("Aucune appartenance active a ce groupe.")

    @application.post("/probe/payload")
    async def echo_payload(payload: _ProbePayload) -> dict[str, int]:
        return {"count": payload.count}

    @application.get("/probe/int/{item_id}")
    async def probe_int(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    @application.get("/deliberate-503")
    async def deliberate_503() -> JSONResponse:
        return JSONResponse(status_code=503, content=_DELIBERATE_BODY)

    return application


@pytest.mark.parametrize(
    ("path", "expected_status", "expected_code"),
    [
        ("/raise/not-found", 404, "probe.note.not_found"),
        ("/raise/already-exists", 409, "probe.note.already_exists"),
        ("/raise/conflict", 409, "probe.note.conflict"),
        ("/raise/validation", 422, "probe.note.invalid"),
        ("/raise/permission", 403, "probe.note.forbidden"),
        ("/raise/too-many", 429, "probe.note.too_many"),
        ("/raise/untyped", 400, "shared.domain.error"),
    ],
)
async def test_each_typed_error_maps_to_its_status(
    path: str, expected_status: int, expected_code: str
) -> None:
    async with asgi_client(_build_app()) as client:
        response = await client.get(path)
    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["code"] == expected_code
    assert body["message"]
    assert body["details"] is None


async def test_a_rate_limit_refusal_carries_retry_after() -> None:
    """Le delai sort en EN-TETE standard, pas enfoui dans `details` (BACK-17).

    `Retry-After` (RFC 9110) se lit par les clients HTTP et par les navigateurs :
    c'est la seule information qu'un 429 doit donner, et la seule qui aide
    l'appelant sans renseigner un attaquant sur le compteur restant.
    """
    async with asgi_client(_build_app()) as client:
        response = await client.get("/raise/too-many")

    assert response.status_code == 429
    assert response.headers["retry-after"] == "42"


async def test_a_rate_limit_refusal_without_a_known_delay_omits_the_header() -> None:
    """Un quota sur fenetre glissante ne sait pas toujours quand il rouvrira.

    Mieux vaut pas d'en-tete qu'un `Retry-After: 0`, qui inviterait a reessayer
    immediatement -- et donc a se faire refuser de nouveau.
    """
    async with asgi_client(_build_app()) as client:
        response = await client.get("/raise/too-many-without-delay")

    assert response.status_code == 429
    assert "retry-after" not in response.headers


async def test_all_error_responses_share_the_same_shape() -> None:
    """Le critere « toutes les erreurs partagent le meme format », en un test."""
    async with asgi_client(_build_app()) as client:
        responses = [
            await client.get("/raise/not-found"),
            await client.get("/raise/untyped"),
            await client.post("/probe/payload", json={"count": 0}),
            await client.get("/raise/unexpected"),
            await client.get("/route/inconnue"),
            await client.post("/raise/not-found"),
        ]
    for response in responses:
        assert response.status_code >= 400
        body = response.json()
        assert set(body) == {"code", "message", "details", "request_id"}, body


async def test_request_id_field_is_null_outside_any_request_context() -> None:
    """Le champ tolere l'absence de contexte, et cette absence est un etat NORMAL.

    Depuis BACK-11, une requete HTTP porte toujours un identifiant. Ce test
    couvre l'autre moitie : une `DomainError` levee hors de toute requete --
    tache de fond, script, CLI -- doit se traduire sans que rien ne leve.
    """
    async with asgi_client(_build_app()) as client:
        response = await client.get("/raise/not-found")
    assert response.json()["request_id"] is None


async def test_request_id_reflects_the_correlation_context_when_it_is_set_by_hand() -> None:
    """Le REPLI de `_error_response`, et non le chemin nominal.

    En production l'identifiant vient de la cle de `scope` posee par
    l'intergiciel de BACK-11 ; ce test couvre la lecture de la contextvar, qui
    reste le chemin de tout ce qui traduit une erreur hors d'une requete servie.
    """
    async with asgi_client(_build_app()) as client:
        with use_request_id("req-test-0001"):
            response = await client.get("/raise/not-found")
    assert response.json()["request_id"] == "req-test-0001"


async def test_pydantic_extra_field_is_reformatted() -> None:
    async with asgi_client(_build_app()) as client:
        response = await client.post("/probe/payload", json={"count": 1, "intrus": True})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "http.request.validation_error"
    assert "detail" not in body
    errors = body["details"]["errors"]
    assert any(error["type"] == "extra_forbidden" for error in errors)
    assert all(set(error) == {"loc", "msg", "type"} for error in errors)


async def test_pydantic_constraint_error_is_reformatted() -> None:
    """Le `ctx` non serialisable des erreurs de contrainte ne fait pas exploser le handler."""
    async with asgi_client(_build_app()) as client:
        response = await client.post("/probe/payload", json={"count": 0})
    assert response.status_code == 422
    errors = response.json()["details"]["errors"]
    assert any(error["type"] == "greater_than" for error in errors)


async def test_malformed_json_body_is_reformatted() -> None:
    async with asgi_client(_build_app()) as client:
        response = await client.post(
            "/probe/payload",
            content=b"pas du json",
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 422
    assert response.json()["code"] == "http.request.validation_error"


async def test_path_param_type_error_is_reformatted() -> None:
    async with asgi_client(_build_app()) as client:
        response = await client.get("/probe/int/abc")
    assert response.status_code == 422
    assert response.json()["code"] == "http.request.validation_error"


async def test_unexpected_exception_returns_a_generic_500() -> None:
    """L'assertion centrale du 500 : aucune information interne ne sort."""
    async with asgi_client(_build_app()) as client:
        response = await client.get("/raise/unexpected")
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "http.server.internal_error"
    assert body["message"] == "Une erreur interne est survenue."
    assert body["details"] is None
    assert _INTERNAL_DETAIL not in response.text
    assert "MissingTenantContextError" not in response.text


async def test_unexpected_exception_is_logged_with_stack(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """La double face du 500 : le detail part au journal, jamais dans le corps."""
    logger_name = "app.shared.infrastructure.api.error_handlers"
    with caplog.at_level(logging.ERROR, logger=logger_name):
        async with asgi_client(_build_app()) as client:
            response = await client.get("/raise/unexpected")
    assert response.status_code == 500
    record = next(r for r in caplog.records if r.exc_info is not None)
    assert isinstance(record.exc_info[1], MissingTenantContextError)
    assert _INTERNAL_DETAIL in str(record.exc_info[1])


async def test_storage_unavailability_follows_the_generic_500_path() -> None:
    """Une panne du stockage est technique : re-levee vers le 500, jamais un 4xx."""
    async with asgi_client(_build_app()) as client:
        response = await client.get("/raise/storage-unavailable")
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "http.server.internal_error"
    assert "stockage" not in response.text


async def test_a_membership_refusal_does_not_confirm_the_group_exists() -> None:
    """Heritage multiple et TUPLE ORDONNE : le 404 doit gagner sur la famille.

    `InactiveMembershipError` descend de `TokenError` -- pour qu'un
    `except TokenError` autour de l'emission ne la rate pas -- et de
    `NotFoundError`, pour la regle de non-divulgation de BACK-09. Le traducteur
    resout par `isinstance` sur un tuple parcouru dans l'ordre : c'est
    `(NotFoundError, 404)`, en tete, qui doit repondre. Un refus de DROIT
    confirmerait au demandeur que le groupe existe.
    """
    async with asgi_client(_build_app()) as client:
        response = await client.get("/raise/inactive-membership")

    assert response.status_code == 404
    assert response.json()["code"] == "shared.token.membership_not_active"


async def test_http_exceptions_share_the_format() -> None:
    """404 de routage et 405 sortent au format unique, plus jamais en `{"detail"}`."""
    async with asgi_client(_build_app()) as client:
        not_found = await client.get("/route/inconnue")
        method_not_allowed = await client.post("/raise/not-found")
    assert not_found.status_code == 404
    assert not_found.json()["code"] == "http.request.not_found"
    assert "detail" not in not_found.json()
    assert method_not_allowed.status_code == 405
    assert method_not_allowed.json()["code"] == "http.request.method_not_allowed"


async def test_deliberate_error_status_body_is_untouched() -> None:
    """Un corps pose avec un statut d'erreur (le modele de /health/ready) ne bouge pas.

    Les handlers s'enregistrent par CLASSE d'exception, jamais par code de
    statut : une reponse construite sans exception traverse intacte.
    """
    async with asgi_client(_build_app()) as client:
        response = await client.get("/deliberate-503")
    assert response.status_code == 503
    assert response.json() == _DELIBERATE_BODY


async def test_create_app_registers_the_handlers() -> None:
    """LE test qui prouve la prod : `create_app()` sait traduire un refus metier."""
    application = create_app()

    @application.get("/probe/back-09")
    async def raise_probe() -> None:
        raise _ProbeNotFoundError("Aucune note de sonde ne porte cet identifiant.")

    async with asgi_client(application) as client:
        response = await client.get("/probe/back-09")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "probe.note.not_found"
    assert set(body) == {"code", "message", "details", "request_id"}
    # Depuis BACK-11 ce test prouve aussi le critere 3 de bout en bout : le
    # meme identifiant dans l'en-tete et dans le corps, sur le cablage reel.
    assert body["request_id"] == response.headers["x-request-id"]
    assert body["request_id"] is not None


async def test_create_app_unknown_route_shares_the_format() -> None:
    async with asgi_client(create_app()) as client:
        response = await client.get("/api/v1/inexistant")
    assert response.status_code == 404
    assert response.json()["code"] == "http.request.not_found"
    assert response.json()["request_id"] is not None


async def test_create_app_health_live_is_untouched() -> None:
    """Temoin du nominal : les handlers ne touchent pas aux reponses saines."""
    async with asgi_client(create_app()) as client:
        response = await client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}
    # Le temoin du nominal prouve aussi que l'identifiant sort sur une reponse
    # SAINE, et pas seulement sur les erreurs.
    assert response.headers["x-request-id"]


async def test_create_app_ready_without_lifespan_does_not_leak() -> None:
    """Une erreur levee en resolution de dependance passe aussi par le filet."""
    async with asgi_client(create_app()) as client:
        response = await client.get("/health/ready")
    assert response.status_code == 500
    body = response.json()
    assert body["code"] == "http.server.internal_error"
    assert body["message"] == "Une erreur interne est survenue."
    assert "lifespan" not in response.text
    # LE test qui rencontre en premier les deux pieges de `ServerErrorMiddleware`
    # (BACK-11) : il repond avec le `send` d'origine, hors de toute enveloppe de
    # sortie, et apres que la contextvar a ete remise. Sans la cle de `scope`,
    # cette assertion echoue sur un `KeyError` ou sur un `None`.
    assert body["request_id"] == response.headers["x-request-id"]


async def test_openapi_schema_still_serves() -> None:
    async with asgi_client(create_app()) as client:
        response = await client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Juui API"


async def test_openapi_publishes_the_error_format() -> None:
    """Le format d'erreur est ANNONCE dans le contrat, et pas seulement respecte.

    FRONT-10 derive son type TypeScript de ce composant plutot que de le
    reecrire a la main : sans cette declaration, Orval ne genere rien et le
    client d'API recopie un contrat qu'il ne controle pas. `/health/ready`
    declare le 500 -- elle le produit reellement, le test ci-dessus le prouve --,
    ce qui suffit a faire entrer le schema dans `components`.

    `details` et `request_id` portent un defaut Pydantic, donc sortent
    FACULTATIVES : le type genere est plus permissif que la promesse « quatre
    cles toujours presentes ». C'est le contrat publie qui fait foi cote client,
    d'ou l'assertion sur `required` plutot qu'un commentaire.
    """
    async with asgi_client(create_app()) as client:
        response = await client.get("/openapi.json")
    document = response.json()

    assert "ErrorResponse" in document["components"]["schemas"]
    schema = document["components"]["schemas"]["ErrorResponse"]
    assert set(schema["properties"]) == {"code", "message", "details", "request_id"}
    assert schema["required"] == ["code", "message"]

    responses = document["paths"]["/health/ready"]["get"]["responses"]
    reference = responses["500"]["content"]["application/json"]["schema"]["$ref"]
    assert reference == "#/components/schemas/ErrorResponse"
