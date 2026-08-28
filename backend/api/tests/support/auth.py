"""Harnais des tests d'authentification et d'autorisation (BACK-10c).

CE QUE CE FICHIER EST, ET POURQUOI IL EST DANS `tests/`
Le critere 6 du ticket demande que les dependances protegent « une route de
test ». Elle est ici : le ticket ne possede aucune route publique -- `/auth/*`
appartient a BACK-28 et BACK-29 --, et livrer une route de demonstration
l'inscrirait dans l'OpenAPI exporte puis dans le client Orval. Ce que ces sondes
prouvent est exactement ce qu'une vraie route prouverait : les dependances
s'assemblent, s'executent dans l'ordre, et refusent ce qu'elles doivent refuser.

LE SERVICE QUI SIGNE EST CELUI QUI VERIFIE. Un seul `JwtTokenService`, construit
sur un `JWTSettings` compose a la main -- jamais `get_settings()`, qui est
`lru_cache`e et exigerait un fichier `.env`. Les jetons a refuser se fabriquent
donc en degradant l'emission (autre audience, autre cle, horloge reculee) plutot
qu'en forgeant des charges utiles : c'est `test_jwt_service.py` qui prouve les
refus cause par cause, et ces tests-ci prouvent qu'ils se ressemblent tous.

`ASGITransport` NE DECLENCHE PAS LE `lifespan`, donc le montage
d'authentification se pose a la main -- soit sur `app.state`, soit par
surcharge de `get_authentication`. Les deux voies servent : la seconde est
commode, la premiere est la seule qui prouve l'accesseur et sa garde.

Ce module ne commence pas par `test_` : pytest ne le collecte pas.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI

from app.core.correlation import current_account_id, current_clinic_id
from app.shared.domain.exceptions import NotFoundError
from app.shared.infrastructure.api.dependencies.auth import (
    AUTH_STATE_KEY,
    AccountRecord,
    ActiveAssignment,
    Authentication,
    CurrentAccount,
    CurrentActiveAccount,
    audience_of,
    get_authentication,
)
from app.shared.infrastructure.api.dependencies.tenant import ActiveClinic, require_role
from app.shared.infrastructure.api.error_handlers import register_error_handlers
from app.shared.infrastructure.security.jwt_service import (
    ACCOUNT_TYPE_ADMIN,
    ACCOUNT_TYPE_INDIVIDUAL,
    ACCOUNT_TYPE_PROFESSIONAL,
    JwtTokenService,
)
from app.shared.infrastructure.tenancy import current_group_id
from tests.support.tokens import (
    ACCOUNT_ID,
    AUDIENCE_PRO,
    CLINIC_ID,
    GROUP_ID,
    OTHER_CLINIC_ID,
    OTHER_GROUP_ID,
    SIGNING_KEY,
    TokenFactory,
    bearer_header,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class FakeAccount:
    """Compte de test : la forme qu'`AccountRecord` decrit, et rien de plus."""

    id: UUID = ACCOUNT_ID
    account_type: str = ACCOUNT_TYPE_PROFESSIONAL
    status: str = "active"
    email_verified: bool = True


@dataclass(frozen=True, slots=True, kw_only=True)
class FakeAssignment:
    """Affectation de test : la forme qu'`ActiveAssignment` decrit."""

    id: UUID = field(default_factory=uuid4)
    clinic_id: UUID = CLINIC_ID
    role: str = "veterinarian"
    start_at: datetime = field(default_factory=lambda: datetime.now(UTC) - timedelta(days=1))


@dataclass(slots=True)
class Calls:
    """Compteurs d'appels des resolveurs.

    Ce sont eux qui prouvent deux proprietes qu'aucune assertion sur la reponse
    ne montrerait : qu'un jeton en echec n'atteint jamais la base, et qu'une
    route declarant deux gardes de clinique ne lit les affectations qu'une fois.
    """

    accounts: int = 0
    assignments: int = 0
    clinic_groups: int = 0


def token_service(
    *,
    roles: dict[tuple[UUID, UUID], str] | None = None,
    at: datetime | None = None,
    key: str = SIGNING_KEY,
) -> JwtTokenService:
    """Le service de jetons seul, pour les tests dont le SUJET est l'emission.

    UNE VUE DE `TokenFactory`, ET NON UNE SECONDE IMPLEMENTATION (BACK-12). Les
    tests d'`auth_dependencies` et de `require_role` degradent deliberement
    l'emission -- autre cle, horloge reculee, table de roles explicite -- et
    n'ont que faire d'une table vivante : le service nu leur suffit, et le leur
    retirer aurait coute cent sites d'appel pour rien. `TokenFactory` est l'autre
    vue, celle des tests de ROUTE, qui doivent declarer un role apres que le
    service est deja pose sur `app.state`.
    """
    return TokenFactory(key=key, at=at, roles=roles).service


def an_authentication(
    *,
    tokens: JwtTokenService | None = None,
    accounts: dict[UUID, AccountRecord] | None = None,
    assignments: Sequence[ActiveAssignment] = (),
    clinic_groups: dict[UUID, UUID] | None = None,
    calls: Calls | None = None,
) -> Authentication:
    """Assemble un montage d'authentification servi par des doublures en memoire.

    Les resolveurs sont des CLOSURES et non des classes : ils tiennent en trois
    lignes, et le compteur qu'ils incrementent est deja porte par `Calls`.
    """
    # `is None` et non `or` : un dictionnaire VIDE est un cas de test a part
    # entiere -- « aucun compte connu » --, que `or` confondrait avec le defaut.
    known_accounts = {ACCOUNT_ID: FakeAccount()} if accounts is None else dict(accounts)
    default_clinics = {CLINIC_ID: GROUP_ID, OTHER_CLINIC_ID: OTHER_GROUP_ID}
    known_clinics = default_clinics if clinic_groups is None else dict(clinic_groups)
    counters = calls if calls is not None else Calls()

    async def resolve_account(account_id: UUID) -> AccountRecord:
        """Rend le compte, ou leve comme le depot d'`identity`."""
        counters.accounts += 1
        found = known_accounts.get(account_id)
        if found is None:
            message = f"Aucun compte ne porte l'identifiant {account_id}."
            raise NotFoundError(message)
        return found

    async def resolve_active_assignments(
        account_id: UUID, at: datetime
    ) -> Sequence[ActiveAssignment]:
        """Rend les affectations actives -- deja filtrees, comme le depot tenant."""
        counters.assignments += 1
        return assignments

    async def resolve_clinic_group(clinic_id: UUID) -> UUID | None:
        """Rend le groupe proprietaire d'une clinique, ou `None`."""
        counters.clinic_groups += 1
        return known_clinics.get(clinic_id)

    return Authentication(
        tokens=tokens if tokens is not None else token_service(),
        resolve_account=resolve_account,
        resolve_active_assignments=resolve_active_assignments,
        resolve_clinic_group=resolve_clinic_group,
    )


def probe_router(*, account_type: str, prefix: str) -> APIRouter:
    """Monte les routes de sonde d'une audience donnee.

    Toutes les combinaisons que le ticket doit prouver y figurent : le porteur
    seul, le porteur actif, le contexte tel que l'endpoint le voit, les deux
    perimetres de `require_role`, la clinique active, et une route qui declare a
    la fois la garde de role clinique et la clinique -- celle qui prouve que les
    affectations ne sont lues qu'une fois.
    """
    router = APIRouter(prefix=prefix, dependencies=[Depends(audience_of(account_type))])

    @router.get("/me")
    async def read_me(account: CurrentAccount) -> dict[str, str]:
        """Rend le porteur, verifie ou non."""
        return {"account_id": str(account.account_id)}

    @router.get("/active")
    async def read_active(account: CurrentActiveAccount) -> dict[str, str]:
        """Rend le porteur, adresse verifiee exigee."""
        return {"account_id": str(account.account_id)}

    @router.get("/context")
    async def read_context(account: CurrentActiveAccount) -> dict[str, str | None]:
        """Rend les trois contextvars TELLES QUE L'ENDPOINT LES VOIT.

        Aucune inspection depuis le test ne le pourrait : il tourne dans une
        autre tache, donc dans un autre contexte.
        """
        group = current_group_id.get()
        clinic = current_clinic_id.get()
        stamped = current_account_id.get()
        return {
            "account_id": None if stamped is None else str(stamped),
            "group_id": str(group) if isinstance(group, UUID) else None,
            "clinic_id": None if clinic is None else str(clinic),
        }

    @router.get("/managers", dependencies=[Depends(require_role("manager", scope="group"))])
    async def read_managers() -> dict[str, bool]:
        """Route de perimetre groupe, reservee aux gerants."""
        return {"ok": True}

    @router.get(
        "/consultations",
        dependencies=[Depends(require_role("veterinarian", scope="clinic"))],
    )
    async def read_consultations() -> dict[str, bool]:
        """Route de perimetre clinique, reservee aux veterinaires."""
        return {"ok": True}

    @router.get("/clinic")
    async def read_clinic(clinic: ActiveClinic) -> dict[str, str]:
        """Rend la clinique active et le role tenu sur elle."""
        return {"clinic_id": str(clinic.clinic_id), "role": clinic.role}

    @router.get("/clinic-context")
    async def read_clinic_context(clinic: ActiveClinic) -> dict[str, str | None]:
        """Rend `current_clinic_id` TELLE QUE L'ENDPOINT LA VOIT, clinique resolue."""
        stamped = current_clinic_id.get()
        return {
            "clinic_id": None if stamped is None else str(stamped),
            "resolved": str(clinic.clinic_id),
        }

    @router.get(
        "/clinic-and-role",
        dependencies=[Depends(require_role("veterinarian", "asv", scope="clinic"))],
    )
    async def read_clinic_and_role(clinic: ActiveClinic) -> dict[str, str]:
        """Declare la garde de role ET la clinique : une seule lecture attendue."""
        return {"clinic_id": str(clinic.clinic_id)}

    return router


def build_probe_app(
    authentication: Authentication | None = None,
    *,
    override: bool = True,
    with_public_route: bool = True,
) -> FastAPI:
    """Monte une application de sonde : handlers d'erreur, routeurs par audience.

    Application NUE plutot que `create_app()` : les intergiciels de BACK-11
    n'ont rien a prouver ici, et `create_app()` ne declencherait pas davantage
    le `lifespan`. Les handlers d'erreur, eux, sont indispensables -- sans eux
    une `DomainError` sortirait en 500 et masquerait tous les refus.

    Args:
        authentication: le montage a servir. `None` en construit un par defaut.
        override: `True` passe par `dependency_overrides` -- la voie commode ;
            `False` pose le montage sur `app.state`, seule voie qui prouve
            l'accesseur, sa garde `isinstance` et la cle d'etat.
        with_public_route: monte une route sans aucune dependance, pour prouver
            qu'aucun contexte ne fuit d'une requete authentifiee vers elle.

    Returns:
        L'application, prete a recevoir un client.
    """
    application = FastAPI()
    register_error_handlers(application)
    resolved = an_authentication() if authentication is None else authentication
    if override:
        application.dependency_overrides[get_authentication] = lambda: resolved
    else:
        setattr(application.state, AUTH_STATE_KEY, resolved)

    application.include_router(probe_router(account_type=ACCOUNT_TYPE_PROFESSIONAL, prefix="/pro"))
    application.include_router(
        probe_router(account_type=ACCOUNT_TYPE_INDIVIDUAL, prefix="/individual")
    )
    application.include_router(probe_router(account_type=ACCOUNT_TYPE_ADMIN, prefix="/admin"))

    @application.get("/unmarked")
    async def read_unmarked(account: CurrentAccount) -> dict[str, bool]:
        """Route protegee SANS marqueur d'audience : doit echouer bruyamment."""
        return {"ok": True}

    if with_public_route:

        @application.get("/public")
        async def read_public() -> dict[str, str | None]:
            """Route sans aucune dependance : elle ne doit voir aucun contexte."""
            group = current_group_id.get()
            return {
                "group_id": None if group is None else str(group),
                "account_id": (
                    None if current_account_id.get() is None else str(current_account_id.get())
                ),
            }

    return application


async def bearer(
    service: JwtTokenService,
    *,
    account_id: UUID = ACCOUNT_ID,
    account_type: str = ACCOUNT_TYPE_PROFESSIONAL,
    audience: str = AUDIENCE_PRO,
    active_group_id: UUID | None = GROUP_ID,
) -> dict[str, str]:
    """Emet un jeton d'acces sur un service DONNE et rend l'en-tete `Authorization`.

    Le pendant de `token_service` : la forme qui prend son service en argument,
    pour les tests qui en manipulent plusieurs dans un meme cas. `TokenFactory.bearer`
    est l'autre forme, celle qui n'en a qu'un.
    """
    token = await service.create_access_token(
        account_id=account_id,
        account_type=account_type,
        audience=audience,
        active_group_id=active_group_id,
    )
    return bearer_header(token)
