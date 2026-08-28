"""Ce que la bordure d'authentification garantit (BACK-10c, criteres 1, 2, 3, 6).

`test_jwt_service.py` prouve deja, cause par cause et sur le vrai adaptateur,
qu'un jeton expire, mal signe, falsifie ou d'une autre audience est refuse. La
propriete NEUVE ici est qu'ils produisent tous la MEME reponse : c'est un test
parametre, et non vingt.
"""

import asyncio
import inspect
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import APIRouter, Depends

from app.core.correlation import current_account_id
from app.modules.identity.domain.entities import Account, AccountStatus, AccountType
from app.shared.infrastructure.api.dependencies.auth import (
    ACCOUNT_STATUS_SUSPENDED,
    ACCOUNT_STATUSES,
    AccountRecord,
    CurrentAccount,
    audience_of,
    get_current_account,
)
from app.shared.infrastructure.api.dependencies.tenant import get_active_clinic
from app.shared.infrastructure.security.jwt_service import (
    ACCOUNT_TYPE_INDIVIDUAL,
    ACCOUNT_TYPE_PROFESSIONAL,
)
from app.shared.infrastructure.tenancy import current_group_id
from tests.shared.auth_probes import (
    ACCOUNT_ID,
    AUDIENCE_INDIVIDUAL,
    AUDIENCE_PRO,
    GROUP_ID,
    OTHER_SIGNING_KEY,
    Calls,
    FakeAccount,
    an_authentication,
    bearer,
    build_probe_app,
    client,
    token_service,
)

pytestmark = pytest.mark.authorization


# ---------------------------------------------------------------------------
# Critere 1 : signature, expiration, type, audience -- et un seul 401
# ---------------------------------------------------------------------------


async def test_a_valid_bearer_token_identifies_the_account() -> None:
    """Le chemin nominal : un jeton emis par le service ouvre la route."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service))
    async with client(application) as opened:
        response = await opened.get("/pro/me", headers=await bearer(service))
    assert response.status_code == 200
    assert response.json() == {"account_id": str(ACCOUNT_ID)}


async def _refused_headers(case: str) -> dict[str, str]:
    """Compose l'en-tete `Authorization` de chaque facon d'echouer."""
    if case == "absent":
        return {}
    if case == "unknown_scheme":
        token = await bearer(token_service())
        return {"Authorization": token["Authorization"].replace("Bearer", "Basic")}
    if case == "empty_credential":
        return {"Authorization": "Bearer "}
    if case == "expired":
        old = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=2)
        return await bearer(token_service(at=old))
    if case == "another_key":
        return await bearer(token_service(key=OTHER_SIGNING_KEY))
    if case == "another_audience":
        return await bearer(
            token_service(), account_type=ACCOUNT_TYPE_INDIVIDUAL, audience=AUDIENCE_INDIVIDUAL
        )
    if case == "refresh_token":
        service = token_service()
        token = await service.create_refresh_token(
            account_id=ACCOUNT_ID,
            account_type=ACCOUNT_TYPE_PROFESSIONAL,
            audience=AUDIENCE_PRO,
            active_group_id=GROUP_ID,
        )
        return {"Authorization": f"Bearer {token}"}
    raise AssertionError(case)


@pytest.mark.parametrize(
    "case",
    [
        "absent",
        "unknown_scheme",
        "empty_credential",
        "expired",
        "another_key",
        "another_audience",
        "refresh_token",
    ],
)
async def test_every_token_failure_produces_the_same_response(case: str) -> None:
    """Sept causes distinctes, une seule reponse : aucune ne se distingue."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service))
    async with client(application) as opened:
        response = await opened.get("/pro/me", headers=await _refused_headers(case))
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "http.request.unauthorized"
    assert body["message"] == "Authentification requise."
    assert body["details"] is None


async def test_the_refusal_carries_a_bearer_challenge_naming_neither_realm_nor_error() -> None:
    """Le defi est nu : un `realm` nommerait la structure, un `error=` serait un oracle."""
    application = build_probe_app()
    async with client(application) as opened:
        response = await opened.get("/pro/me")
    assert response.headers["www-authenticate"] == "Bearer"


async def test_the_refusal_keeps_the_four_keys_of_the_error_format() -> None:
    """Un 401 est une erreur comme les autres : meme enveloppe (BACK-09)."""
    application = build_probe_app()
    async with client(application) as opened:
        response = await opened.get("/pro/me")
    assert set(response.json()) == {"code", "message", "details", "request_id"}


async def test_a_token_whose_subject_has_no_account_is_refused_as_unauthenticated() -> None:
    """Un `sub` inconnu ne sort PAS en 404 : ce serait un oracle sur la cle."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service, accounts={}))
    async with client(application) as opened:
        response = await opened.get("/pro/me", headers=await bearer(service))
    assert response.status_code == 401
    assert response.json()["code"] == "http.request.unauthorized"


async def test_two_authorization_headers_are_refused_rather_than_resolved() -> None:
    """Une valeur cliente ne se rectifie jamais -- on ne choisit pas la premiere."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service))
    valid = (await bearer(service))["Authorization"]
    async with client(application) as opened:
        response = await opened.get(
            "/pro/me",
            headers=[("authorization", valid), ("authorization", "Bearer autre")],
        )
    assert response.status_code == 401


async def test_a_token_placed_in_a_cookie_does_not_authenticate() -> None:
    """Aucun repli cookie : ce serait rendre toutes les routes vulnerables au CSRF."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service))
    token = (await bearer(service))["Authorization"].removeprefix("Bearer ")
    async with client(application) as opened:
        response = await opened.get("/pro/me", headers={"Cookie": f"access_token={token}"})
    assert response.status_code == 401


async def test_a_token_placed_in_the_query_string_does_not_authenticate() -> None:
    """Aucun repli sur l'URL : elle se journalise chez les mandataires."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service))
    token = (await bearer(service))["Authorization"].removeprefix("Bearer ")
    async with client(application) as opened:
        response = await opened.get(f"/pro/me?access_token={token}")
    assert response.status_code == 401


async def test_a_token_failure_never_reaches_the_database() -> None:
    """L'ordre des gestes est une propriete de securite, pas une optimisation."""
    calls = Calls()
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service, calls=calls))
    async with client(application) as opened:
        await opened.get("/pro/me", headers=await bearer(token_service(key=OTHER_SIGNING_KEY)))
    assert calls.accounts == 0


# ---------------------------------------------------------------------------
# Critere 1 (suite) : l'audience est une propriete de la ROUTE
# ---------------------------------------------------------------------------


async def test_an_individual_token_is_refused_by_a_professional_route() -> None:
    """L'isolation stricte du cahier des charges, en une requete."""
    service = token_service()
    application = build_probe_app(
        an_authentication(
            tokens=service,
            accounts={ACCOUNT_ID: FakeAccount(account_type=ACCOUNT_TYPE_INDIVIDUAL)},
        )
    )
    headers = await bearer(
        service,
        account_type=ACCOUNT_TYPE_INDIVIDUAL,
        audience=AUDIENCE_INDIVIDUAL,
        active_group_id=None,
    )
    async with client(application) as opened:
        response = await opened.get("/pro/me", headers=headers)
    assert response.status_code == 401


async def test_an_individual_token_is_accepted_by_the_individual_route() -> None:
    """Le pendant du test precedent : sans lui, un refus global passerait aussi."""
    service = token_service()
    application = build_probe_app(
        an_authentication(
            tokens=service,
            accounts={ACCOUNT_ID: FakeAccount(account_type=ACCOUNT_TYPE_INDIVIDUAL)},
        )
    )
    headers = await bearer(
        service,
        account_type=ACCOUNT_TYPE_INDIVIDUAL,
        audience=AUDIENCE_INDIVIDUAL,
        active_group_id=None,
    )
    async with client(application) as opened:
        response = await opened.get("/individual/me", headers=headers)
    assert response.status_code == 200


async def test_a_token_whose_audience_contradicts_its_account_type_is_refused() -> None:
    """Jeton AUTHENTIQUE mais incoherent : l'audience pro sur un compte particulier."""
    service = token_service()
    application = build_probe_app(
        an_authentication(
            tokens=service,
            accounts={ACCOUNT_ID: FakeAccount(account_type=ACCOUNT_TYPE_INDIVIDUAL)},
        )
    )
    # L'emission actuelle ne confronte pas les deux (ADR-0024 le laissait a
    # BACK-29) : on peut donc produire ce jeton, et la bordure doit le refuser.
    headers = await bearer(service, account_type=ACCOUNT_TYPE_INDIVIDUAL, audience=AUDIENCE_PRO)
    async with client(application) as opened:
        response = await opened.get("/pro/me", headers=headers)
    assert response.status_code == 401


async def test_the_expected_audience_is_not_read_from_any_request_header() -> None:
    """Un en-tete ne choisit pas la porte que l'on franchit."""
    service = token_service()
    application = build_probe_app(
        an_authentication(
            tokens=service,
            accounts={ACCOUNT_ID: FakeAccount(account_type=ACCOUNT_TYPE_INDIVIDUAL)},
        )
    )
    headers = await bearer(
        service,
        account_type=ACCOUNT_TYPE_INDIVIDUAL,
        audience=AUDIENCE_INDIVIDUAL,
        active_group_id=None,
    )
    async with client(application) as opened:
        response = await opened.get(
            "/pro/me", headers={**headers, "X-App": "individual", "X-Audience": AUDIENCE_INDIVIDUAL}
        )
    assert response.status_code == 401


async def test_a_route_declaring_an_unknown_audience_fails_loudly() -> None:
    """Un marqueur mal orthographie est un defaut de cablage, pas un refus metier.

    500 dans les deux cas, avec en-tete comme sans : laisser l'erreur du service
    de jetons s'echapper la ferait sortir en 400, c'est-a-dire deguisee en refus
    adresse a l'appelant.
    """
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service))
    router = APIRouter(prefix="/typo", dependencies=[Depends(audience_of("profesional"))])

    @router.get("/me")
    async def read_typo(account: CurrentAccount) -> dict[str, bool]:
        """Route dont le routeur declare une audience inconnue."""
        return {"ok": True}

    application.include_router(router)
    async with client(application) as opened:
        with_token = await opened.get("/typo/me", headers=await bearer(service))
        without_token = await opened.get("/typo/me")
    assert with_token.status_code == 500
    assert without_token.status_code == 500


async def test_a_route_mounted_without_its_audience_marker_fails_loudly() -> None:
    """Defaut de cablage : 500, jamais un acces accorde ni un 401 trompeur."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service))
    async with client(application) as opened:
        response = await opened.get("/unmarked", headers=await bearer(service))
    assert response.status_code == 500


# ---------------------------------------------------------------------------
# Critere 2 : suspendu, non verifie
# ---------------------------------------------------------------------------


async def test_a_suspended_account_is_refused_by_the_lower_dependency() -> None:
    """Refuse des `get_current_account` : les routes de BACK-17 en dependent."""
    service = token_service()
    application = build_probe_app(
        an_authentication(
            tokens=service, accounts={ACCOUNT_ID: FakeAccount(status=ACCOUNT_STATUS_SUSPENDED)}
        )
    )
    async with client(application) as opened:
        response = await opened.get("/pro/me", headers=await bearer(service))
    assert response.status_code == 403
    assert response.json()["code"] == "shared.account.suspended"


async def test_an_unverified_account_stays_authenticated_but_is_refused_by_the_active_one() -> None:
    """Le coeur du critere 2 : authentifie, et retenu sur l'ecran de verification."""
    service = token_service()
    application = build_probe_app(
        an_authentication(tokens=service, accounts={ACCOUNT_ID: FakeAccount(email_verified=False)})
    )
    headers = await bearer(service)
    async with client(application) as opened:
        identified = await opened.get("/pro/me", headers=headers)
        blocked = await opened.get("/pro/active", headers=headers)
    assert identified.status_code == 200
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "shared.account.email_not_verified"


async def test_a_suspended_and_unverified_account_is_answered_suspended() -> None:
    """La suspension prime : elle est refusee un etage plus bas."""
    service = token_service()
    application = build_probe_app(
        an_authentication(
            tokens=service,
            accounts={
                ACCOUNT_ID: FakeAccount(status=ACCOUNT_STATUS_SUSPENDED, email_verified=False)
            },
        )
    )
    async with client(application) as opened:
        response = await opened.get("/pro/active", headers=await bearer(service))
    assert response.json()["code"] == "shared.account.suspended"


async def test_the_identity_account_satisfies_the_account_record_protocol() -> None:
    """La forme decrite par `shared` est bien celle qu'`identity` produit."""
    account: AccountRecord = Account.create(
        email="veto@example.test",
        first_name="Alex",
        last_name="Martin",
        account_type=AccountType.PROFESSIONAL,
    )
    assert account.status == AccountStatus.ACTIVE
    assert account.email_verified is False


async def test_an_account_in_an_unknown_status_is_refused_by_default() -> None:
    """Liste blanche : ce qui n'est pas actif ne franchit pas la bordure.

    Le statut « clos » n'existe pas encore dans `identity`. C'est exactement le
    cas que ce test garde : le jour ou l'enumeration s'elargira, la bordure
    refusera par defaut au lieu de laisser passer par omission.
    """
    service = token_service()
    application = build_probe_app(
        an_authentication(tokens=service, accounts={ACCOUNT_ID: FakeAccount(status="closed")})
    )
    async with client(application) as opened:
        response = await opened.get("/pro/me", headers=await bearer(service))
    assert response.status_code == 403
    assert response.json()["code"] == "shared.account.suspended"


async def test_the_recopied_account_statuses_have_not_drifted_from_identity() -> None:
    """La recopie des statuts suit `identity`, ou le test le dit.

    Egalite d'ENSEMBLES et non d'un membre : c'est ce qui attrape aussi bien un
    statut ajoute qu'un statut retire, dans les deux sens.
    """
    assert {member.value for member in AccountStatus} == set(ACCOUNT_STATUSES)
    assert AccountStatus.SUSPENDED.value == ACCOUNT_STATUS_SUSPENDED


# ---------------------------------------------------------------------------
# Critere 3 : les contextvars, posees ET relachees
# ---------------------------------------------------------------------------


async def test_the_active_group_claim_becomes_the_tenant_context() -> None:
    """Aucun cas d'usage ne pose ce groupe a la main : il vient du claim."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service))
    async with client(application) as opened:
        response = await opened.get("/pro/context", headers=await bearer(service))
    assert response.json()["group_id"] == str(GROUP_ID)


async def test_the_account_and_the_clinic_are_stamped_in_the_logging_context() -> None:
    """Le compte est pose ; la clinique reste vide sans en-tete, et c'est normal."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service))
    async with client(application) as opened:
        response = await opened.get("/pro/context", headers=await bearer(service))
    body = response.json()
    assert body["account_id"] == str(ACCOUNT_ID)
    assert body["clinic_id"] is None


async def test_a_public_route_served_after_an_authenticated_one_sees_no_tenant_context() -> None:
    """Le contexte est relache : la requete suivante repart de zero."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service))
    async with client(application) as opened:
        await opened.get("/pro/context", headers=await bearer(service))
        response = await opened.get("/public")
    assert response.json() == {"group_id": None, "account_id": None}


async def test_a_refusal_in_a_later_dependency_still_releases_the_context() -> None:
    """Le `finally` du gestionnaire de contexte couvre aussi les chemins d'echec."""
    service = token_service()
    application = build_probe_app(
        an_authentication(tokens=service, accounts={ACCOUNT_ID: FakeAccount(email_verified=False)})
    )
    async with client(application) as opened:
        refused = await opened.get("/pro/active", headers=await bearer(service))
        public = await opened.get("/public")
    assert refused.status_code == 403
    assert public.json() == {"group_id": None, "account_id": None}
    assert current_group_id.get() is None
    assert current_account_id.get() is None


async def test_concurrent_requests_never_share_a_tenant_context() -> None:
    """Deux porteurs, deux groupes, en parallele : chacun voit le sien."""
    service = token_service()
    other_account = uuid4()
    other_group = uuid4()
    application = build_probe_app(
        an_authentication(
            tokens=service,
            accounts={ACCOUNT_ID: FakeAccount(), other_account: FakeAccount(id=other_account)},
        )
    )
    async with client(application) as opened:
        first, second = await asyncio.gather(
            opened.get("/pro/context", headers=await bearer(service)),
            opened.get(
                "/pro/context",
                headers=await bearer(
                    service, account_id=other_account, active_group_id=other_group
                ),
            ),
        )
    assert first.json()["group_id"] == str(GROUP_ID)
    assert second.json()["group_id"] == str(other_group)


async def test_the_context_setting_dependencies_are_coroutines() -> None:
    """Une dependance a `yield` SYNCHRONE poserait le contexte dans un autre `Context`.

    `contextmanager_in_threadpool` execute l'entree et la sortie dans un fil du
    pool : le `set()` n'atteindrait jamais l'endpoint. La garde est ici plutot
    qu'en revue.
    """
    assert inspect.isasyncgenfunction(get_current_account)
    assert inspect.isasyncgenfunction(get_active_clinic)


# ---------------------------------------------------------------------------
# Le montage lui-meme : `app.state`, sa garde, et l'absence de `lifespan`
# ---------------------------------------------------------------------------


async def test_the_dependencies_read_the_authentication_opened_by_the_lifespan() -> None:
    """Sans surcharge : c'est l'accesseur et la cle d'etat qui sont eprouves."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service), override=False)
    async with client(application) as opened:
        response = await opened.get("/pro/me", headers=await bearer(service))
    assert response.status_code == 200


async def test_an_application_built_without_its_lifespan_answers_500_and_never_401() -> None:
    """Echec ferme : un service incapable de juger ne dit pas « mauvais jeton »."""
    service = token_service()
    application = build_probe_app(an_authentication(tokens=service), override=False)
    delattr(application.state, "authentication")
    async with client(application) as opened:
        response = await opened.get("/pro/me", headers=await bearer(service))
    assert response.status_code == 500
