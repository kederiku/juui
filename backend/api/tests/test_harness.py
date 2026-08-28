"""Le harnais de BACK-12, eprouve par lui-meme : client, jetons, transaction.

Ces tests ne portent sur aucun module metier. Ils prouvent que les trois pieces
que le ticket avait a livrer FONCTIONNENT, et surtout qu'elles fonctionnent
ENSEMBLE -- ce qu'aucun test de module ne montrerait, chacun n'en touchant qu'une.

Ils vivent a la racine de `tests/`, comme `test_context_guards.py`, et pour la
meme raison : les ranger sous un module mentirait sur leur portee.
"""

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.identity.domain.entities import Account, AccountType
from app.modules.identity.unit_of_work import SqlAlchemyIdentityUnitOfWork
from app.shared.domain.ports.token_service import InactiveMembershipError
from app.shared.infrastructure.api.dependencies.auth import Authentication
from app.shared.infrastructure.security.jwt_service import ACCOUNT_TYPE_INDIVIDUAL
from tests.support.tokens import ACCOUNT_ID, AUDIENCE_INDIVIDUAL, GROUP_ID, TokenFactory


async def test_the_api_client_serves_the_real_application(api_client: AsyncClient) -> None:
    """Le client d'integration parle bien a l'application de `create_app()`.

    `/health/live` est la route la plus modeste du service, et c'est ce qui en
    fait le bon temoin : elle ne prouve rien du metier, seulement que les
    intergiciels sont montes, que le routeur repond, et que le montage manuel
    d'`app.state` a suffi la ou le `lifespan` ne tourne pas.
    """
    response = await api_client.get("/health/live")
    assert response.status_code == 200


async def test_a_route_reached_through_the_client_sees_the_uncommitted_seed(
    api_client: AsyncClient,
    authentication: Authentication,
    bound_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """CE QUE LE PATRON DE TRANSACTION ACHETE, ET QUI VAUT TOUT LE RESTE.

    Le test seme un compte dans SA transaction, puis appelle le resolveur de
    PRODUCTION -- celui que `build_authentication` monte, le meme qu'en
    production, qui ouvre sa PROPRE unite de travail -- et il le trouve.

    Avant BACK-12 c'etait impossible : `test_auth_integration.py` cablait ses
    resolveurs a la main sur la session du test, en expliquant qu'« une autre
    connexion ne verrait rien du semis ». La fabrique de sessions LIEE supprime
    le contournement -- les deux unites de travail partagent la connexion du test
    --, et le point de composition teste redevient celui qui tourne. Rien n'en
    sort : le teardown annule la transaction externe, savepoints compris.
    """
    account = Account.create(
        email=f"harness-{uuid4().hex}@example.test",
        first_name="Harnais",
        last_name="Juui",
        account_type=AccountType.PROFESSIONAL,
    )
    async with SqlAlchemyIdentityUnitOfWork(bound_sessionmaker) as uow:
        await uow.accounts.add(account)
        # Commit EXPLICITE : sans lui, `__aexit__` annule, c'est le contrat de
        # l'unite de travail (BACK-06a). Sous `create_savepoint` ce commit
        # relache un savepoint -- la ligne devient visible de tout le test, et de
        # rien d'autre. Le teardown de `connection` l'emportera.
        await uow.commit()

    found = await authentication.resolve_account(account.id)

    assert found.id == account.id


async def test_the_token_factory_signs_what_the_montage_verifies(
    probe_client: AsyncClient, tokens: TokenFactory
) -> None:
    """Un jeton emis par la fabrique ouvre une route protegee de son audience."""
    response = await probe_client.get("/pro/me", headers=await tokens.bearer())
    assert response.status_code == 200
    assert response.json() == {"account_id": str(ACCOUNT_ID)}


async def test_the_group_role_travels_from_the_factory_to_the_guard(
    probe_client: AsyncClient, tokens: TokenFactory
) -> None:
    """`group_role=` traverse l'emission et arrive dans la garde de perimetre groupe.

    C'est la parametrabilite que le ticket reclame, prouvee de bout en bout : le
    role n'est pas un argument d'emission, il passe par la table du resolveur --
    et un role qui n'ouvre pas la route est refuse en 403, pas en 401.
    """
    granted = await probe_client.get("/pro/managers", headers=await tokens.bearer())
    assert granted.status_code == 200

    refused = await probe_client.get(
        "/pro/managers", headers=await tokens.bearer(group_role="admin")
    )
    assert refused.status_code == 403


async def test_an_audience_of_another_application_is_refused(
    probe_client: AsyncClient, tokens: TokenFactory
) -> None:
    """Un jeton AUTHENTIQUE d'une autre application ne passe pas.

    C'est le cas que l'isolation du cahier des charges vise, et la fabrique le
    produit sans forger la moindre charge utile : meme cle, meme signature,
    seule l'audience differe.
    """
    header = await tokens.bearer(account_type=ACCOUNT_TYPE_INDIVIDUAL, audience=AUDIENCE_INDIVIDUAL)
    response = await probe_client.get("/pro/me", headers=header)
    assert response.status_code == 401


async def test_an_expired_token_is_refused(probe_client: AsyncClient, tokens: TokenFactory) -> None:
    """`expired=True` emet DANS LE PASSE, seule facon d'obtenir un jeton perime.

    L'horloge injectable ne pilote que l'emission : PyJWT verifie sur l'horloge
    murale, et aucun argument ne la deplace.
    """
    response = await probe_client.get("/pro/me", headers=await tokens.bearer(expired=True))
    assert response.status_code == 401


async def test_an_inactive_membership_is_refused_at_issuance(tokens: TokenFactory) -> None:
    """`group_role=None` produit le refus REEL, et il tombe A L'EMISSION.

    Un test qui chercherait un 401 se tromperait d'endroit : BACK-10a refuse
    d'emettre un jeton dont le groupe actif ne correspond a aucune appartenance
    active. Le jeton n'existe jamais.
    """
    with pytest.raises(InactiveMembershipError):
        await tokens.token(group_role=None, active_group_id=GROUP_ID)
