"""Autorisation scopee et clinique active (BACK-10c, criteres 4 et 5 hors base).

Le critere 5 est prouve deux fois : ici sur des doublures, pour la logique de
refus et l'absence d'oracle ; et sur PostgreSQL dans
`tests/shared/security/test_auth_integration.py`, pour la garantie de schema.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.correlation import current_clinic_id
from app.modules.organization.domain.entities import ClinicRole, GroupRole
from app.shared.infrastructure.api.dependencies.tenant import (
    CLINIC_HEADER,
    CLINIC_ROLE_NAMES,
    GROUP_ROLE_NAMES,
)
from tests.support.api import asgi_client
from tests.support.auth import (
    Calls,
    FakeAccount,
    FakeAssignment,
    an_authentication,
    bearer,
    build_probe_app,
    token_service,
)
from tests.support.tokens import (
    ACCOUNT_ID,
    CLINIC_ID,
    GROUP_ID,
    OTHER_CLINIC_ID,
)

pytestmark = pytest.mark.authorization

_CLINIC_HEADERS = {CLINIC_HEADER: str(CLINIC_ID)}


# ---------------------------------------------------------------------------
# Critere 4 : le perimetre groupe se lit dans le claim, sans requete
# ---------------------------------------------------------------------------


async def test_a_group_scoped_role_is_read_from_the_claim_without_any_query() -> None:
    """Aucune lecture d'affectation : c'est tout l'interet du role porte par le jeton."""
    calls = Calls()
    service = token_service(roles={(ACCOUNT_ID, GROUP_ID): "manager"})
    application = build_probe_app(an_authentication(tokens=service, calls=calls))
    async with asgi_client(application) as opened:
        response = await opened.get("/pro/managers", headers=await bearer(service))
    assert response.status_code == 200
    assert calls.assignments == 0


async def test_a_group_role_outside_the_allowed_set_is_refused() -> None:
    """Un administrateur n'est pas un gerant : le refus est un 403, pas un 404."""
    service = token_service(roles={(ACCOUNT_ID, GROUP_ID): "admin"})
    application = build_probe_app(an_authentication(tokens=service))
    async with asgi_client(application) as opened:
        response = await opened.get("/pro/managers", headers=await bearer(service))
    assert response.status_code == 403
    assert response.json()["code"] == "shared.resource.forbidden"


async def test_a_token_without_group_role_cannot_satisfy_a_group_scope() -> None:
    """Un jeton sans groupe actif ne porte aucun role de groupe."""
    service = token_service()
    application = build_probe_app(
        an_authentication(tokens=service, accounts={ACCOUNT_ID: FakeAccount()})
    )
    headers = await bearer(service, active_group_id=None)
    async with asgi_client(application) as opened:
        response = await opened.get("/pro/managers", headers=headers)
    assert response.status_code == 403


async def test_a_group_role_guard_alone_still_refuses_a_suspended_account() -> None:
    """La garde depend du compte ACTIF : sans cela, aucun SELECT ne serait fait."""
    service = token_service(roles={(ACCOUNT_ID, GROUP_ID): "manager"})
    application = build_probe_app(
        an_authentication(tokens=service, accounts={ACCOUNT_ID: FakeAccount(status="suspended")})
    )
    async with asgi_client(application) as opened:
        response = await opened.get("/pro/managers", headers=await bearer(service))
    assert response.status_code == 403
    assert response.json()["code"] == "shared.account.suspended"


# ---------------------------------------------------------------------------
# Critere 4 (suite) : le perimetre clinique se resout a la requete
# ---------------------------------------------------------------------------


async def test_a_clinic_scoped_role_is_resolved_per_request() -> None:
    """Le chemin nominal : une affectation active de veterinaire ouvre la route."""
    service = token_service()
    application = build_probe_app(
        an_authentication(tokens=service, assignments=[FakeAssignment(role="veterinarian")])
    )
    async with asgi_client(application) as opened:
        response = await opened.get(
            "/pro/consultations", headers={**await bearer(service), **_CLINIC_HEADERS}
        )
    assert response.status_code == 200


async def test_a_clinic_role_forged_in_the_token_grants_nothing() -> None:
    """Le role de groupe du jeton n'ouvre aucune route de perimetre clinique."""
    service = token_service(roles={(ACCOUNT_ID, GROUP_ID): "manager"})
    application = build_probe_app(
        an_authentication(tokens=service, assignments=[FakeAssignment(role="asv")])
    )
    async with asgi_client(application) as opened:
        response = await opened.get(
            "/pro/consultations", headers={**await bearer(service), **_CLINIC_HEADERS}
        )
    assert response.status_code == 403


async def test_a_role_held_in_another_clinic_grants_nothing_in_the_active_one() -> None:
    """ASV ici, veterinaire ailleurs : c'est la LIGNE de la clinique active qui compte."""
    service = token_service()
    application = build_probe_app(
        an_authentication(
            tokens=service,
            assignments=[
                FakeAssignment(clinic_id=CLINIC_ID, role="asv"),
                FakeAssignment(clinic_id=OTHER_CLINIC_ID, role="veterinarian"),
            ],
        )
    )
    async with asgi_client(application) as opened:
        response = await opened.get(
            "/pro/consultations", headers={**await bearer(service), **_CLINIC_HEADERS}
        )
    assert response.status_code == 403


async def test_two_overlapping_assignments_to_one_clinic_grant_the_most_recent_role() -> None:
    """Une retrogradation faite sans fermer la precedente doit prendre effet."""
    now = datetime.now(UTC)
    service = token_service()
    application = build_probe_app(
        an_authentication(
            tokens=service,
            assignments=[
                FakeAssignment(role="veterinarian", start_at=now - timedelta(days=30)),
                FakeAssignment(role="asv", start_at=now - timedelta(days=1)),
            ],
        )
    )
    async with asgi_client(application) as opened:
        response = await opened.get(
            "/pro/clinic", headers={**await bearer(service), **_CLINIC_HEADERS}
        )
    assert response.json()["role"] == "asv"


async def test_a_group_role_alone_does_not_activate_a_clinic() -> None:
    """La gerante non affectee n'obtient pas de perimetre clinique : 404, pas 403."""
    service = token_service(roles={(ACCOUNT_ID, GROUP_ID): "manager"})
    application = build_probe_app(an_authentication(tokens=service, assignments=[]))
    async with asgi_client(application) as opened:
        response = await opened.get(
            "/pro/clinic", headers={**await bearer(service), **_CLINIC_HEADERS}
        )
    assert response.status_code == 404
    assert response.json()["code"] == "shared.clinic.not_active"


async def test_the_assignments_are_read_once_for_a_route_that_declares_both_guards() -> None:
    """Le cache de dependances tient : une seule lecture, donc une seule verite."""
    calls = Calls()
    service = token_service()
    application = build_probe_app(
        an_authentication(
            tokens=service, assignments=[FakeAssignment(role="veterinarian")], calls=calls
        )
    )
    async with asgi_client(application) as opened:
        response = await opened.get(
            "/pro/clinic-and-role", headers={**await bearer(service), **_CLINIC_HEADERS}
        )
    assert response.status_code == 200
    assert calls.assignments == 1
    assert calls.clinic_groups == 1


# ---------------------------------------------------------------------------
# Critere 5 : l'en-tete de clinique, et l'absence d'oracle
# ---------------------------------------------------------------------------


async def test_a_missing_clinic_header_is_a_validation_error_not_an_absence() -> None:
    """La route l'EXIGE : c'est la requete qui est mal formee, pas la clinique absente."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service, assignments=[FakeAssignment()]))
    async with asgi_client(application) as opened:
        response = await opened.get("/pro/clinic", headers=await bearer(service))
    assert response.status_code == 422


async def test_a_malformed_or_empty_clinic_header_is_a_validation_error() -> None:
    """Un identifiant illisible n'est pas une clinique inconnue."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service, assignments=[FakeAssignment()]))
    async with asgi_client(application) as opened:
        malformed = await opened.get(
            "/pro/clinic", headers={**await bearer(service), CLINIC_HEADER: "pas-un-uuid"}
        )
        empty = await opened.get(
            "/pro/clinic", headers={**await bearer(service), CLINIC_HEADER: ""}
        )
    assert malformed.status_code == 422
    assert empty.status_code == 422


async def test_two_clinic_headers_are_refused_rather_than_resolved() -> None:
    """Meme doctrine que pour `Authorization` : on ne choisit pas la premiere."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service, assignments=[FakeAssignment()]))
    authorization = (await bearer(service))["Authorization"]
    async with asgi_client(application) as opened:
        response = await opened.get(
            "/pro/clinic",
            headers=[
                ("authorization", authorization),
                (CLINIC_HEADER.lower(), str(CLINIC_ID)),
                (CLINIC_HEADER.lower(), str(OTHER_CLINIC_ID)),
            ],
        )
    assert response.status_code == 422
    assert response.json()["code"] == "shared.resource.invalid"


async def test_a_clinic_header_is_ignored_by_a_route_that_does_not_ask_for_it() -> None:
    """L'en-tete ne pose rien tout seul : il faut que la route le demande."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service))
    async with asgi_client(application) as opened:
        response = await opened.get(
            "/pro/context", headers={**await bearer(service), **_CLINIC_HEADERS}
        )
    assert response.status_code == 200
    assert response.json()["clinic_id"] is None


async def test_a_token_without_an_active_group_cannot_activate_a_clinic() -> None:
    """Un particulier n'a pas de groupe : 404, et surtout pas un 500 de tenance."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service, assignments=[FakeAssignment()]))
    headers = await bearer(service, active_group_id=None)
    async with asgi_client(application) as opened:
        response = await opened.get("/pro/clinic", headers={**headers, **_CLINIC_HEADERS})
    assert response.status_code == 404


async def test_a_clinic_of_another_group_is_refused() -> None:
    """La seconde verification, isolee : la clinique n'appartient pas au groupe actif."""
    service = token_service()
    application = build_probe_app(
        an_authentication(
            tokens=service,
            assignments=[FakeAssignment(clinic_id=OTHER_CLINIC_ID)],
        )
    )
    async with asgi_client(application) as opened:
        response = await opened.get(
            "/pro/clinic",
            headers={**await bearer(service), CLINIC_HEADER: str(OTHER_CLINIC_ID)},
        )
    assert response.status_code == 404


async def test_the_absent_clinic_causes_share_one_response() -> None:
    """Inconnue, d'un autre groupe, ou non affectee : aucune ne se distingue."""
    service = token_service()
    unknown = uuid4()
    application = build_probe_app(
        an_authentication(tokens=service, assignments=[FakeAssignment(clinic_id=OTHER_CLINIC_ID)])
    )
    async with asgi_client(application) as opened:
        headers = await bearer(service)
        answers = [
            await opened.get("/pro/clinic", headers={**headers, CLINIC_HEADER: str(unknown)}),
            await opened.get(
                "/pro/clinic", headers={**headers, CLINIC_HEADER: str(OTHER_CLINIC_ID)}
            ),
            await opened.get("/pro/clinic", headers={**headers, CLINIC_HEADER: str(CLINIC_ID)}),
        ]
    bodies = {
        (answer.status_code, answer.json()["code"], answer.json()["message"]) for answer in answers
    }
    assert len(bodies) == 1
    assert next(iter(bodies))[0] == 404


async def test_a_resolved_clinic_is_stamped_in_the_logging_context() -> None:
    """`current_clinic_id` est posee une fois la clinique verifiee, pas avant."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service, assignments=[FakeAssignment()]))
    async with asgi_client(application) as opened:
        response = await opened.get(
            "/pro/clinic-context", headers={**await bearer(service), **_CLINIC_HEADERS}
        )
    assert response.json() == {"clinic_id": str(CLINIC_ID), "resolved": str(CLINIC_ID)}


async def test_a_refused_clinic_leaves_no_context_behind() -> None:
    """Une clinique refusee ne pose rien -- et ne laisse rien derriere elle.

    Les gardes autouse de `conftest.py` verifient les contextvars DANS la tache
    du test ; les deux assertions ci-dessous les redisent a l'endroit ou le
    lecteur se pose la question.
    """
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service, assignments=[FakeAssignment()]))
    async with asgi_client(application) as opened:
        refused = await opened.get(
            "/pro/clinic-context",
            headers={**await bearer(service), CLINIC_HEADER: str(OTHER_CLINIC_ID)},
        )
        public = await opened.get("/public")
    assert refused.status_code == 404
    assert public.json() == {"group_id": None, "account_id": None}
    assert current_clinic_id.get() is None


# ---------------------------------------------------------------------------
# La recopie du vocabulaire
# ---------------------------------------------------------------------------


async def test_the_recopied_role_names_have_not_drifted_from_organization() -> None:
    """Les deux vocabulaires suivent `organization`, ou le test le dit."""
    assert {member.value for member in GroupRole} == set(GROUP_ROLE_NAMES)
    assert {member.value for member in ClinicRole} == set(CLINIC_ROLE_NAMES)
