"""Le service de jetons branche sur le VRAI depot d'appartenances (BACK-10a).

CE QUE CE FICHIER PROUVE, ET QUE LES TESTS EN MEMOIRE NE PEUVENT PAS PROUVER
Que la requete livree par BACK-16 satisfait l'alias `ActiveGroupRoleResolver`
tel quel. C'est la seule verification de cet emboitement, et c'est ce qui a
permis de ne PAS ecrire un port intermediaire, son adaptateur et sa doublure :
`MembershipRepository.find_active_role` a deja la bonne signature, `GroupRole`
etant un `StrEnum` -- donc une chaine.

Le montage definitif, lui, appartient a BACK-10c : une dependance FastAPI qui
assemble le service et l'unite de travail ne peut vivre ni dans `shared`, qui
n'a pas le droit d'importer un module, ni dans un module, qui n'a pas le droit
d'en connaitre un autre. Ici, le test tient lieu de point de composition.

Les tests ne committent jamais ; le rollback du teardown annule le semis.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import JWTSettings, get_settings
from app.modules.identity.domain.entities import AccountType
from app.modules.organization.domain.entities import GroupRole
from app.modules.organization.infrastructure.db.models import GroupModel, MembershipModel
from app.modules.organization.infrastructure.db.repositories import SqlAlchemyMembershipRepository
from app.shared.domain.ports.token_service import InactiveMembershipError, TokenType
from app.shared.infrastructure.security.jwt_service import (
    JwtTokenService,
    build_token_service,
)

pytestmark = pytest.mark.tokens

_AUDIENCE_PRO = "test-pro"
_SIGNING_KEY = "cle-de-test-assez-longue-pour-hs256-0123456"

# L'instant de reference est REEL, et non une date en dur : PyJWT verifie le
# `iat` contre son horloge murale, qu'aucun argument ne remplace. Une date figee
# ferait passer ou echouer ce fichier selon l'heure a laquelle il tourne.
_AT = datetime.now(UTC).replace(microsecond=0)
_STARTED = _AT - timedelta(days=30)
_ENDED = _AT - timedelta(days=1)
_NOT_STARTED = _AT + timedelta(days=1)

# Le message de refus, ecrit une fois : les trois situations doivent rendre le
# MEME, faute de quoi la difference dirait au demandeur si le groupe existe.
_REFUSAL = "Aucune appartenance active a ce groupe."


async def _seed_membership(
    session: AsyncSession,
    account_id: UUID,
    group_id: UUID,
    *,
    start_at: datetime = _STARTED,
    end_at: datetime | None = None,
) -> None:
    """Seme un groupe et une appartenance par la session brute."""
    session.add(GroupModel(id=group_id, name=f"groupe {group_id.hex[:8]}"))
    session.add(
        MembershipModel(
            id=uuid4(),
            account_id=account_id,
            group_id=group_id,
            role=GroupRole.MANAGER.value,
            start_at=start_at,
            end_at=end_at,
        )
    )
    await session.flush()


def _service(session: AsyncSession) -> JwtTokenService:
    """Branche le service sur la requete du depot, sans enveloppe intermediaire."""
    return JwtTokenService(
        settings=JWTSettings(
            secret_key=_SIGNING_KEY,
            audience_professional=_AUDIENCE_PRO,
            audience_individual="test-particulier",
            audience_admin="test-admin",
        ),
        resolve_group_role=SqlAlchemyMembershipRepository(session).find_active_role,
        now=lambda: _AT,
    )


async def test_an_active_membership_puts_a_real_role_in_a_real_token(
    session: AsyncSession,
) -> None:
    """De la ligne en base au claim signe, sans rien simuler entre les deux."""
    account_id, group_id = uuid4(), uuid4()
    await _seed_membership(session, account_id, group_id)
    service = _service(session)

    token = await service.create_access_token(
        account_id=account_id,
        account_type=AccountType.PROFESSIONAL.value,
        audience=_AUDIENCE_PRO,
        active_group_id=group_id,
    )

    claims = await service.decode_token(
        token, expected_audience=_AUDIENCE_PRO, expected_type=TokenType.ACCESS
    )
    assert claims.active_group_id == group_id
    assert claims.group_role == GroupRole.MANAGER.value


@pytest.mark.parametrize(
    "situation",
    ["fenetre close", "fenetre a venir", "groupe jamais rejoint"],
)
async def test_the_three_refusals_are_indistinguishable(
    session: AsyncSession, situation: str
) -> None:
    """Trois situations, un seul message : c'est la regle de non-divulgation.

    Les distinguer -- meme par la nuance d'un message -- dirait au demandeur si
    le groupe existe et s'il y a deja appartenu. Le test porte sur le MESSAGE et
    pas seulement sur le type d'exception : c'est le message qui sort au client.
    """
    account_id, group_id = uuid4(), uuid4()
    if situation == "fenetre close":
        await _seed_membership(session, account_id, group_id, end_at=_ENDED)
        demande = group_id
    elif situation == "fenetre a venir":
        await _seed_membership(session, account_id, group_id, start_at=_NOT_STARTED)
        demande = group_id
    else:
        await _seed_membership(session, account_id, group_id)
        demande = uuid4()
    service = _service(session)

    with pytest.raises(InactiveMembershipError) as refus:
        await service.create_access_token(
            account_id=account_id,
            account_type=AccountType.PROFESSIONAL.value,
            audience=_AUDIENCE_PRO,
            active_group_id=demande,
        )

    assert refus.value.message == _REFUSAL


async def test_the_factory_assembles_a_working_service(session: AsyncSession) -> None:
    """`build_token_service` est le point d'entree que BACK-10c cablera.

    Il lit la configuration REELLE du service -- c'est ce qui distingue ce test
    des autres, qui composent leurs reglages a la main : il prouve que les trois
    audiences declarees dans l'environnement suffisent a emettre.
    """
    account_id, group_id = uuid4(), uuid4()
    await _seed_membership(session, account_id, group_id)
    settings = get_settings()
    service = build_token_service(
        settings,
        SqlAlchemyMembershipRepository(session).find_active_role,
        now=lambda: _AT,
    )

    token = await service.create_access_token(
        account_id=account_id,
        account_type=AccountType.PROFESSIONAL.value,
        audience=settings.jwt.audience_professional,
        active_group_id=group_id,
    )

    claims = await service.decode_token(
        token,
        expected_audience=settings.jwt.audience_professional,
        expected_type=TokenType.ACCESS,
    )
    assert claims.group_role == GroupRole.MANAGER.value
    assert claims.audience == service.audience_for(AccountType.PROFESSIONAL.value)
