"""Tests de l'adaptateur PyJWT du port `TokenService` (BACK-10a).

Purement en memoire : ni base de donnees, ni HTTP. Le resolveur d'appartenance
est une fonction de test, et l'horloge d'emission est injectee -- prouver qu'un
jeton expire ne demande donc pas d'attendre quinze minutes.

L'HORLOGE INJECTEE NE PILOTE QUE L'EMISSION
PyJWT date la VERIFICATION sur l'horloge murale reelle, qu'aucun argument ne
remplace. Un test qui voudrait faire expirer un jeton avance donc l'horloge de
l'EMETTEUR vers le passe, jamais celle du verificateur -- c'est le seul levier
qui existe, et confondre les deux ferait ecrire un test qui ne verifie rien.

CE QUE CES TESTS VERROUILLENT EN PLUS DU TICKET
Cinq comportements par defaut de PyJWT ont ete mesures et juges dangereux. Trois
se prouvent par le COMPORTEMENT -- une audience en liste, une derive d'horloge,
un algorithme hors liste : retirer la correction fait echouer le test.

LES DEUX AUTRES NE SE PROUVENT PAS AINSI, et le savoir evite d'ecrire un test
qui ment. `require` fait double emploi avec la reconstruction des claims, et
`enforce_minimum_key_length` avec la borne de configuration : les retirer ne
change RIEN au comportement observable, parce qu'une seconde barriere les
couvre. Elles restent utiles le jour ou cette seconde barriere cede -- ce qui
est arrive une fois, la borne de cle ayant d'abord compte des caracteres la ou
le RFC compte des octets. Elles sont donc verrouillees sur l'OPTION elle-meme,
par `test_the_decode_options_close_the_permissivities_of_pyjwt`, et non sur un
effet de bord qu'elles ne produisent pas.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from pydantic import SecretStr

from app.core.config import JWTSettings
from app.modules.identity.domain.entities import AccountType
from app.shared.domain.ports.token_service import (
    ExpiredTokenError,
    InactiveMembershipError,
    InvalidAudienceError,
    InvalidSignatureError,
    MalformedTokenError,
    MembershipLookupFailedError,
    NaiveInstantError,
    TokenError,
    TokenIssuanceError,
    TokenNotYetValidError,
    TokenType,
    UnknownAccountTypeError,
    UnknownAudienceError,
    WrongTokenTypeError,
)
from app.shared.infrastructure.security.jwt_service import (
    _DECODE_OPTIONS,
    ACCOUNT_TYPES,
    CLOCK_SKEW_LEEWAY_SECONDS,
    JwtTokenService,
)

pytestmark = pytest.mark.tokens

# Quarante-deux caracteres : au-dela du minimum de trente-deux que la
# configuration impose et que PyJWT verifie a la signature.
_SIGNING_KEY = "cle-de-test-assez-longue-pour-hs256-0123456"
_OTHER_SIGNING_KEY = "autre-cle-de-test-assez-longue-pour-hs256-9"

_AUDIENCE_PRO = "test-pro"
_AUDIENCE_INDIVIDUAL = "test-particulier"
_AUDIENCE_ADMIN = "test-admin"

_ACCOUNT_ID = UUID("0198c0de-0000-7000-8000-00000000a001")
_GROUP_ID = UUID("0198c0de-0000-7000-8000-00000000b001")
_OTHER_GROUP_ID = UUID("0198c0de-0000-7000-8000-00000000b002")
_KNOWN_GROUP_ID = UUID("0198c0de-0000-7000-8000-00000000b003")


class _Resolver:
    """Resolveur d'appartenance de test, qui note ce qu'on lui a demande.

    Repond comme le depot de BACK-16 : le role si une appartenance active
    existe, `None` sinon -- l'absence est un resultat, pas une erreur.
    """

    def __init__(
        self,
        roles: Mapping[tuple[UUID, UUID], str] | None = None,
        *,
        failure: Exception | None = None,
    ) -> None:
        self._roles = dict(roles or {})
        self._failure = failure
        self.calls: list[tuple[UUID, UUID, datetime]] = []

    async def __call__(self, account_id: UUID, group_id: UUID, at: datetime) -> str | None:
        self.calls.append((account_id, group_id, at))
        if self._failure is not None:
            raise self._failure
        return self._roles.get((account_id, group_id))


def _settings(
    *,
    key: str = _SIGNING_KEY,
    access_minutes: int = 15,
    refresh_days: int = 7,
) -> JWTSettings:
    """Compose une configuration de jetons complete, sans lire l'environnement."""
    return JWTSettings(
        secret_key=key,
        access_token_expire_minutes=access_minutes,
        refresh_token_expire_days=refresh_days,
        audience_professional=_AUDIENCE_PRO,
        audience_individual=_AUDIENCE_INDIVIDUAL,
        audience_admin=_AUDIENCE_ADMIN,
    )


def _instant(offset: timedelta = timedelta()) -> datetime:
    """Rend un instant reel decale, sans microsecondes.

    Sans microsecondes parce qu'un JWT date en secondes entieres : les garder
    ferait echouer la comparaison entre l'instant d'emission et le `iat` relu.
    """
    return datetime.now(UTC).replace(microsecond=0) + offset


def _service(
    *,
    resolver: _Resolver | None = None,
    at: datetime | None = None,
    key: str = _SIGNING_KEY,
    access_minutes: int = 15,
    refresh_days: int = 7,
) -> JwtTokenService:
    """Construit le service avec une horloge figee sur `at`."""
    frozen = _instant() if at is None else at
    return JwtTokenService(
        settings=_settings(key=key, access_minutes=access_minutes, refresh_days=refresh_days),
        resolve_group_role=resolver or _Resolver(),
        now=lambda: frozen,
    )


def _payload(**overrides: object) -> dict[str, Any]:
    """Charge utile complete et valide, que chaque test degrade a sa facon."""
    issued_at = _instant()
    claims: dict[str, Any] = {
        "sub": str(_ACCOUNT_ID),
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=15),
        "jti": str(uuid4()),
        "aud": _AUDIENCE_PRO,
        "type": TokenType.ACCESS.value,
        "account_type": AccountType.PROFESSIONAL.value,
        "active_group_id": None,
        "group_role": None,
    }
    claims.update(overrides)
    return claims


def _forge(claims: dict[str, Any], *, key: str = _SIGNING_KEY, algorithm: str = "HS256") -> str:
    """Signe une charge utile arbitraire, pour fabriquer les jetons a refuser."""
    return jwt.encode(claims, key, algorithm=algorithm)


# ---------------------------------------------------------------------------
# Aller-retour : ce que le ticket demande de savoir faire
# ---------------------------------------------------------------------------


async def test_access_token_carries_every_claim() -> None:
    """Les neuf claims du ticket sont presents et exacts, `group_role` compris."""
    at = _instant()
    resolver = _Resolver({(_ACCOUNT_ID, _GROUP_ID): "manager"})
    service = _service(resolver=resolver, at=at)

    token = await service.create_access_token(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.PROFESSIONAL.value,
        audience=_AUDIENCE_PRO,
        active_group_id=_GROUP_ID,
    )
    claims = await service.decode_token(
        token, expected_audience=_AUDIENCE_PRO, expected_type=TokenType.ACCESS
    )

    assert claims.subject == _ACCOUNT_ID
    assert claims.token_type is TokenType.ACCESS
    assert claims.audience == _AUDIENCE_PRO
    assert claims.account_type == AccountType.PROFESSIONAL.value
    assert claims.active_group_id == _GROUP_ID
    assert claims.group_role == "manager"
    assert claims.issued_at == at
    assert claims.expires_at == at + timedelta(minutes=15)
    assert isinstance(claims.token_id, UUID)


async def test_refresh_token_carries_every_claim() -> None:
    """Le rafraichissement porte les memes claims, sur sa propre duree."""
    at = _instant()
    resolver = _Resolver({(_ACCOUNT_ID, _GROUP_ID): "manager"})
    service = _service(resolver=resolver, at=at)

    token = await service.create_refresh_token(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.PROFESSIONAL.value,
        audience=_AUDIENCE_PRO,
        active_group_id=_GROUP_ID,
    )
    claims = await service.decode_token(
        token, expected_audience=_AUDIENCE_PRO, expected_type=TokenType.REFRESH
    )

    assert claims.token_type is TokenType.REFRESH
    assert claims.group_role == "manager"
    assert claims.expires_at == at + timedelta(days=7)


async def test_lifetimes_come_from_settings_and_not_from_the_code() -> None:
    """Des durees NON par defaut : un adaptateur qui coderait 15 et 7 en dur echoue ici."""
    at = _instant()
    service = _service(at=at, access_minutes=7, refresh_days=3)

    access = await service.create_access_token(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.INDIVIDUAL.value,
        audience=_AUDIENCE_INDIVIDUAL,
    )
    refresh = await service.create_refresh_token(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.INDIVIDUAL.value,
        audience=_AUDIENCE_INDIVIDUAL,
    )

    access_claims = await service.decode_token(
        access, expected_audience=_AUDIENCE_INDIVIDUAL, expected_type=TokenType.ACCESS
    )
    refresh_claims = await service.decode_token(
        refresh, expected_audience=_AUDIENCE_INDIVIDUAL, expected_type=TokenType.REFRESH
    )

    assert access_claims.expires_at - access_claims.issued_at == timedelta(minutes=7)
    assert refresh_claims.expires_at - refresh_claims.issued_at == timedelta(days=3)


async def test_each_token_carries_its_own_identifier() -> None:
    """Deux emissions, deux `jti` : BACK-10d revoquera l'un sans toucher l'autre."""
    service = _service()

    first = await service.create_access_token(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.ADMIN.value,
        audience=_AUDIENCE_ADMIN,
    )
    second = await service.create_access_token(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.ADMIN.value,
        audience=_AUDIENCE_ADMIN,
    )

    first_claims = await service.decode_token(
        first, expected_audience=_AUDIENCE_ADMIN, expected_type=TokenType.ACCESS
    )
    second_claims = await service.decode_token(
        second, expected_audience=_AUDIENCE_ADMIN, expected_type=TokenType.ACCESS
    )
    assert first_claims.token_id != second_claims.token_id


# ---------------------------------------------------------------------------
# Emission : l'appartenance n'est pas declarative
# ---------------------------------------------------------------------------


async def test_group_role_comes_from_the_repository_not_from_the_caller() -> None:
    """Aucun parametre ne permet de se declarer gerant : le role vient du depot."""
    resolver = _Resolver({(_ACCOUNT_ID, _GROUP_ID): "admin"})
    service = _service(resolver=resolver)

    token = await service.create_access_token(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.PROFESSIONAL.value,
        audience=_AUDIENCE_PRO,
        active_group_id=_GROUP_ID,
    )

    claims = await service.decode_token(
        token, expected_audience=_AUDIENCE_PRO, expected_type=TokenType.ACCESS
    )
    assert claims.group_role == "admin"


async def test_the_issuance_instant_is_the_one_the_membership_is_judged_on() -> None:
    """Un seul instant fige : le `iat` du jeton EST le `at` de la verification."""
    at = _instant()
    resolver = _Resolver({(_ACCOUNT_ID, _GROUP_ID): "manager"})
    service = _service(resolver=resolver, at=at)

    token = await service.create_access_token(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.PROFESSIONAL.value,
        audience=_AUDIENCE_PRO,
        active_group_id=_GROUP_ID,
    )

    claims = await service.decode_token(
        token, expected_audience=_AUDIENCE_PRO, expected_type=TokenType.ACCESS
    )
    assert resolver.calls == [(_ACCOUNT_ID, _GROUP_ID, at)]
    assert claims.issued_at == at


async def test_the_membership_instant_carries_a_timezone() -> None:
    """Le depot de BACK-16 refuse un instant naif : il n'en recevra jamais."""
    resolver = _Resolver({(_ACCOUNT_ID, _GROUP_ID): "manager"})
    service = _service(resolver=resolver)

    await service.create_access_token(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.PROFESSIONAL.value,
        audience=_AUDIENCE_PRO,
        active_group_id=_GROUP_ID,
    )

    (_, _, at) = resolver.calls[0]
    assert at.tzinfo is not None
    assert at.tzinfo.utcoffset(at) is not None


@pytest.mark.parametrize("group_id", [_GROUP_ID, _OTHER_GROUP_ID])
async def test_no_active_membership_emits_nothing(group_id: UUID) -> None:
    """Appartenance expiree ou groupe inconnu : meme refus, meme message.

    Le resolveur connait un TROISIEME groupe, et seulement lui : les deux
    paramètres empruntent donc bien deux situations distinctes -- un groupe
    dont l'appartenance a pris fin, un groupe jamais rejoint -- et non deux fois
    la même branche vide.
    """
    resolver = _Resolver({(_ACCOUNT_ID, _KNOWN_GROUP_ID): "manager"})
    service = _service(resolver=resolver)

    with pytest.raises(InactiveMembershipError) as refus:
        await service.create_access_token(
            account_id=_ACCOUNT_ID,
            account_type=AccountType.PROFESSIONAL.value,
            audience=_AUDIENCE_PRO,
            active_group_id=group_id,
        )

    assert refus.value.message == "Aucune appartenance active a ce groupe."


async def test_inactive_membership_is_catchable_as_a_token_error() -> None:
    """Un `except TokenError` autour de l'emission ne rate pas ce refus."""
    service = _service(resolver=_Resolver())

    with pytest.raises(TokenError):
        await service.create_access_token(
            account_id=_ACCOUNT_ID,
            account_type=AccountType.PROFESSIONAL.value,
            audience=_AUDIENCE_PRO,
            active_group_id=_GROUP_ID,
        )


async def test_an_account_without_group_never_asks_the_repository() -> None:
    """Cas nominal du particulier : claims nuls, et aucune requete."""
    resolver = _Resolver()
    service = _service(resolver=resolver)

    token = await service.create_access_token(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.INDIVIDUAL.value,
        audience=_AUDIENCE_INDIVIDUAL,
    )

    claims = await service.decode_token(
        token, expected_audience=_AUDIENCE_INDIVIDUAL, expected_type=TokenType.ACCESS
    )
    assert resolver.calls == []
    assert claims.active_group_id is None
    assert claims.group_role is None


async def test_a_failing_resolver_emits_nothing() -> None:
    """Panne de lecture : erreur TECHNIQUE, hors DomainError, et aucun jeton."""
    resolver = _Resolver(failure=ConnectionError("base injoignable"))
    service = _service(resolver=resolver)

    with pytest.raises(MembershipLookupFailedError):
        await service.create_access_token(
            account_id=_ACCOUNT_ID,
            account_type=AccountType.PROFESSIONAL.value,
            audience=_AUDIENCE_PRO,
            active_group_id=_GROUP_ID,
        )


async def test_a_naive_clock_is_refused_before_anything_is_asked() -> None:
    """Une horloge sans fuseau echoue ici, pas en 422 au fond du depot."""
    resolver = _Resolver({(_ACCOUNT_ID, _GROUP_ID): "manager"})
    service = JwtTokenService(
        settings=_settings(),
        resolve_group_role=resolver,
        now=lambda: datetime(2026, 8, 27, 12, 0),
    )

    with pytest.raises(NaiveInstantError):
        await service.create_access_token(
            account_id=_ACCOUNT_ID,
            account_type=AccountType.PROFESSIONAL.value,
            audience=_AUDIENCE_PRO,
            active_group_id=_GROUP_ID,
        )
    assert resolver.calls == []


# ---------------------------------------------------------------------------
# Audiences
# ---------------------------------------------------------------------------


async def test_an_undeclared_audience_is_refused_before_any_lookup() -> None:
    """Une audience inconnue est un bug d'appelant : refuse avant de toucher la base."""
    resolver = _Resolver({(_ACCOUNT_ID, _GROUP_ID): "manager"})
    service = _service(resolver=resolver)

    with pytest.raises(UnknownAudienceError):
        await service.create_access_token(
            account_id=_ACCOUNT_ID,
            account_type=AccountType.PROFESSIONAL.value,
            audience="audience-qui-n-existe-pas",
            active_group_id=_GROUP_ID,
        )
    assert resolver.calls == []


def test_the_audience_table_answers_for_the_three_account_types() -> None:
    """La table est exposee : BACK-29 la lit au lieu de la recopier."""
    service = _service()

    assert service.audience_for(AccountType.PROFESSIONAL.value) == _AUDIENCE_PRO
    assert service.audience_for(AccountType.INDIVIDUAL.value) == _AUDIENCE_INDIVIDUAL
    assert service.audience_for(AccountType.ADMIN.value) == _AUDIENCE_ADMIN


def test_the_audience_table_refuses_an_unknown_account_type() -> None:
    service = _service()

    with pytest.raises(UnknownAccountTypeError):
        service.audience_for("veterinaire-remplacant")


def test_the_recopied_account_types_have_not_drifted_from_identity() -> None:
    """Le noyau partage recopie les trois types faute de pouvoir les importer.

    Ce test, lui, a le droit d'importer les deux cotes -- il est la seule garde
    contre une derive silencieuse entre `AccountType` et la table d'audiences.
    """
    assert set(ACCOUNT_TYPES) == {member.value for member in AccountType}


async def test_a_token_of_another_audience_is_refused() -> None:
    """Le critere du ticket : un jeton particulier refuse par une verification pro."""
    service = _service()

    token = await service.create_access_token(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.INDIVIDUAL.value,
        audience=_AUDIENCE_INDIVIDUAL,
    )

    with pytest.raises(InvalidAudienceError):
        await service.decode_token(
            token, expected_audience=_AUDIENCE_PRO, expected_type=TokenType.ACCESS
        )


async def test_a_token_without_audience_is_an_audience_error() -> None:
    """Sans `aud`, un jeton serait recevable PARTOUT : c'est le pire des cas."""
    service = _service()
    claims = _payload()
    del claims["aud"]

    with pytest.raises(InvalidAudienceError):
        await service.decode_token(
            _forge(claims), expected_audience=_AUDIENCE_PRO, expected_type=TokenType.ACCESS
        )


async def test_an_audience_list_does_not_pass() -> None:
    """Sans `strict_aud`, PyJWT accepterait un jeton vise sur deux applications."""
    service = _service()
    token = _forge(_payload(aud=[_AUDIENCE_PRO, _AUDIENCE_INDIVIDUAL]))

    with pytest.raises(InvalidAudienceError):
        await service.decode_token(
            token, expected_audience=_AUDIENCE_PRO, expected_type=TokenType.ACCESS
        )


# ---------------------------------------------------------------------------
# Decodage : les refus
# ---------------------------------------------------------------------------


async def test_an_expired_token_is_refused() -> None:
    """Emis il y a une heure pour quinze minutes : l'horloge de l'emetteur suffit."""
    service = _service(at=_instant(-timedelta(hours=1)))

    token = await service.create_access_token(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.ADMIN.value,
        audience=_AUDIENCE_ADMIN,
    )

    with pytest.raises(ExpiredTokenError):
        await service.decode_token(
            token, expected_audience=_AUDIENCE_ADMIN, expected_type=TokenType.ACCESS
        )


async def test_a_token_dated_in_the_future_names_the_clock_drift() -> None:
    """Une derive d'horloge se dit, elle ne se range pas dans « illisible »."""
    service = _service(at=_instant(timedelta(hours=1)))

    token = await service.create_access_token(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.ADMIN.value,
        audience=_AUDIENCE_ADMIN,
    )

    with pytest.raises(TokenNotYetValidError):
        await service.decode_token(
            token, expected_audience=_AUDIENCE_ADMIN, expected_type=TokenType.ACCESS
        )


async def test_a_short_clock_drift_is_tolerated() -> None:
    """Quelques secondes d'avance entre deux instances ne cassent pas la session."""
    service = _service(at=_instant(timedelta(seconds=5)))

    token = await service.create_access_token(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.ADMIN.value,
        audience=_AUDIENCE_ADMIN,
    )

    claims = await service.decode_token(
        token, expected_audience=_AUDIENCE_ADMIN, expected_type=TokenType.ACCESS
    )
    assert claims.subject == _ACCOUNT_ID


async def test_a_token_signed_with_another_key_is_refused() -> None:
    service = _service()
    token = _forge(_payload(), key=_OTHER_SIGNING_KEY)

    with pytest.raises(InvalidSignatureError):
        await service.decode_token(
            token, expected_audience=_AUDIENCE_PRO, expected_type=TokenType.ACCESS
        )


async def test_a_tampered_payload_is_refused() -> None:
    """La charge utile reecrite, la signature conservee : l'integrite mord."""
    service = _service()
    header, payload, signature = _forge(_payload()).split(".")
    falsified = jwt.utils.base64url_encode(
        jwt.utils.base64url_decode(payload).replace(
            AccountType.PROFESSIONAL.value.encode(), AccountType.ADMIN.value.encode()
        )
    ).decode()

    with pytest.raises(InvalidSignatureError):
        await service.decode_token(
            f"{header}.{falsified}.{signature}",
            expected_audience=_AUDIENCE_PRO,
            expected_type=TokenType.ACCESS,
        )


async def test_an_unsigned_token_is_refused() -> None:
    """`alg: none` : la liste fermee d'algorithmes est ce qui l'arrete."""
    service = _service()
    token = jwt.encode(_payload(), None, algorithm="none")

    with pytest.raises(MalformedTokenError):
        await service.decode_token(
            token, expected_audience=_AUDIENCE_PRO, expected_type=TokenType.ACCESS
        )


# L'avertissement vient de CE test, qui forge un jeton HS512 avec la cle courte
# des tests : PyJWT attend 64 octets pour SHA512. Le forgeage passe par
# `jwt.encode` nu, jamais par l'adaptateur -- lequel exige au contraire la
# longueur minimale, ce que verifient les tests de configuration.
@pytest.mark.filterwarnings("ignore::jwt.warnings.InsecureKeyLengthWarning")
async def test_a_token_signed_with_another_algorithm_is_refused() -> None:
    service = _service()
    token = _forge(_payload(), algorithm="HS512")

    with pytest.raises(MalformedTokenError):
        await service.decode_token(
            token, expected_audience=_AUDIENCE_PRO, expected_type=TokenType.ACCESS
        )


async def test_a_token_without_expiry_is_refused() -> None:
    """Sans la clause `require`, PyJWT accepterait ce jeton -- pour toujours."""
    service = _service()
    claims = _payload()
    del claims["exp"]

    with pytest.raises(MalformedTokenError):
        await service.decode_token(
            _forge(claims), expected_audience=_AUDIENCE_PRO, expected_type=TokenType.ACCESS
        )


@pytest.mark.parametrize("missing", ["iat", "jti", "sub", "type", "account_type"])
async def test_a_token_missing_a_required_claim_is_refused(missing: str) -> None:
    service = _service()
    claims = _payload()
    del claims[missing]

    with pytest.raises(MalformedTokenError):
        await service.decode_token(
            _forge(claims), expected_audience=_AUDIENCE_PRO, expected_type=TokenType.ACCESS
        )


@pytest.mark.parametrize("missing", ["active_group_id", "group_role"])
async def test_a_token_missing_a_nullable_claim_is_refused(missing: str) -> None:
    """Nuls, ils sont admis ; ABSENTS, non -- la reconstruction n'a pas de repli."""
    service = _service()
    claims = _payload()
    del claims[missing]

    with pytest.raises(MalformedTokenError):
        await service.decode_token(
            _forge(claims), expected_audience=_AUDIENCE_PRO, expected_type=TokenType.ACCESS
        )


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": "pas-un-identifiant"},
        {"jti": "pas-un-identifiant"},
        {"active_group_id": "pas-un-identifiant"},
    ],
    ids=["sub", "jti", "active_group_id"],
)
async def test_an_unusable_claim_is_refused_without_a_500(claims: dict[str, Any]) -> None:
    """Ces trois cas levent ValueError : hors du bloc, ils sortiraient en 500."""
    service = _service()

    with pytest.raises(MalformedTokenError):
        await service.decode_token(
            _forge(_payload(**claims)),
            expected_audience=_AUDIENCE_PRO,
            expected_type=TokenType.ACCESS,
        )


async def test_an_unknown_token_type_is_a_wrong_type_and_not_a_malformed_token() -> None:
    """Un `type` que le service ne connait pas n'est simplement pas celui attendu.

    Refuse par le controle de type, avant la reconstruction : dire « illisible »
    d'un jeton parfaitement lisible qui annonce un troisieme type ferait chercher
    un defaut de serialisation la ou il y a un jeton d'un autre parcours.
    """
    service = _service()

    with pytest.raises(WrongTokenTypeError):
        await service.decode_token(
            _forge(_payload(type="session")),
            expected_audience=_AUDIENCE_PRO,
            expected_type=TokenType.ACCESS,
        )


async def test_an_unreadable_token_is_refused() -> None:
    service = _service()

    with pytest.raises(MalformedTokenError):
        await service.decode_token(
            "ceci-n-est-pas-un-jeton",
            expected_audience=_AUDIENCE_PRO,
            expected_type=TokenType.ACCESS,
        )


async def test_a_refresh_token_does_not_open_a_business_route() -> None:
    """Le cas dangereux : sept jours la ou quinze minutes etaient prevues."""
    service = _service()

    token = await service.create_refresh_token(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.INDIVIDUAL.value,
        audience=_AUDIENCE_INDIVIDUAL,
    )

    with pytest.raises(WrongTokenTypeError):
        await service.decode_token(
            token, expected_audience=_AUDIENCE_INDIVIDUAL, expected_type=TokenType.ACCESS
        )


async def test_an_access_token_does_not_refresh_a_session() -> None:
    """L'autre sens compte aussi : c'est lui qui casserait la rotation de BACK-29."""
    service = _service()

    token = await service.create_access_token(
        account_id=_ACCOUNT_ID,
        account_type=AccountType.INDIVIDUAL.value,
        audience=_AUDIENCE_INDIVIDUAL,
    )

    with pytest.raises(WrongTokenTypeError):
        await service.decode_token(
            token, expected_audience=_AUDIENCE_INDIVIDUAL, expected_type=TokenType.REFRESH
        )


async def test_no_token_error_carries_the_token_in_its_details() -> None:
    """`details` sort au client sans redaction : rien du jeton n'y entre."""
    service = _service()
    token = _forge(_payload(), key=_OTHER_SIGNING_KEY)

    with pytest.raises(TokenError) as refus:
        await service.decode_token(
            token, expected_audience=_AUDIENCE_PRO, expected_type=TokenType.ACCESS
        )

    assert refus.value.details is None
    assert token not in refus.value.message


# ---------------------------------------------------------------------------
# Ce que la revue contradictoire du code a fait ajouter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("account_type", ["root", "", None])
async def test_an_unknown_account_type_emits_nothing(account_type: str | None) -> None:
    """Un type de compte inconnu produirait un jeton illisible par ce service.

    Il decide en outre, chez BACK-29, de l'application autorisee a servir ce
    compte : le laisser passer reviendrait a signer un jeton dont personne ne
    sait a qui il donne droit.
    """
    resolver = _Resolver({(_ACCOUNT_ID, _GROUP_ID): "manager"})
    service = _service(resolver=resolver)

    with pytest.raises(UnknownAccountTypeError):
        await service.create_access_token(
            account_id=_ACCOUNT_ID,
            account_type=account_type,  # type: ignore[arg-type]
            audience=_AUDIENCE_PRO,
            active_group_id=_GROUP_ID,
        )
    assert resolver.calls == []


async def test_a_resolver_that_refuses_keeps_its_own_refusal() -> None:
    """Un refus du resolveur reste un refus : il ne devient pas une panne 500.

    Le dépôt de BACK-16 rend `None` aujourd'hui, mais une implementation future
    pourrait lever. L'envelopper transformerait un 404 non divulguant en 500.
    """
    refus = InactiveMembershipError("Aucune appartenance active a ce groupe.")
    service = _service(resolver=_Resolver(failure=refus))

    with pytest.raises(InactiveMembershipError):
        await service.create_access_token(
            account_id=_ACCOUNT_ID,
            account_type=AccountType.PROFESSIONAL.value,
            audience=_AUDIENCE_PRO,
            active_group_id=_GROUP_ID,
        )


@pytest.mark.parametrize("role", ["", 42])
async def test_a_resolver_returning_an_unusable_role_emits_nothing(role: object) -> None:
    """Un role vide passerait toutes les gardes `if group_role` sans en etre un."""
    resolver = _Resolver({(_ACCOUNT_ID, _GROUP_ID): role})  # type: ignore[dict-item]
    service = _service(resolver=resolver)

    with pytest.raises(MembershipLookupFailedError):
        await service.create_access_token(
            account_id=_ACCOUNT_ID,
            account_type=AccountType.PROFESSIONAL.value,
            audience=_AUDIENCE_PRO,
            active_group_id=_GROUP_ID,
        )


@pytest.mark.parametrize("claims", [{"exp": 2**62}, {"iat": -(2**63)}], ids=["exp", "iat"])
async def test_an_out_of_range_instant_is_refused_without_a_500(claims: dict[str, Any]) -> None:
    """`datetime.fromtimestamp` leve `OverflowError` ou `OSError`, pas `ValueError`.

    Ni l'une ni l'autre ne descend des trois familles evidentes : hors du bloc,
    un jeton signe de la bonne cle rendrait 500 avec une trace complete.
    """
    service = _service()

    with pytest.raises(MalformedTokenError):
        await service.decode_token(
            _forge(_payload(**claims)),
            expected_audience=_AUDIENCE_PRO,
            expected_type=TokenType.ACCESS,
        )


async def test_an_untypable_issued_at_is_malformed_and_not_a_clock_drift() -> None:
    """PyJWT distingue `iat` FUTUR et `iat` INTYPABLE ; l'adaptateur aussi.

    Les confondre enverrait chercher un NTP en retard la ou il n'y a qu'un
    defaut de serialisation -- l'inverse exact de ce que `TokenNotYetValidError`
    existe pour dire.
    """
    service = _service()

    with pytest.raises(MalformedTokenError):
        await service.decode_token(
            _forge(_payload(iat="pas-un-nombre")),
            expected_audience=_AUDIENCE_PRO,
            expected_type=TokenType.ACCESS,
        )


@pytest.mark.parametrize(
    "claims",
    [{"group_role": "manager"}, {"active_group_id": str(_GROUP_ID)}],
    ids=["role sans groupe", "groupe sans role"],
)
async def test_a_role_and_its_group_travel_together_or_not_at_all(
    claims: dict[str, Any],
) -> None:
    """L'invariant que l'emission tient est verifie a la relecture.

    Un role sans perimetre est precisement la combinaison qu'une garde de role
    mal ecrite accepterait, alors qu'aucun groupe ne s'y applique.
    """
    service = _service()

    with pytest.raises(MalformedTokenError):
        await service.decode_token(
            _forge(_payload(**claims)),
            expected_audience=_AUDIENCE_PRO,
            expected_type=TokenType.ACCESS,
        )


def test_the_decode_options_close_the_permissivities_of_pyjwt() -> None:
    """Verrouille les trois options dont l'effet est INVISIBLE au comportement.

    `require` fait double emploi avec la reconstruction, et
    `enforce_minimum_key_length` avec la configuration : les retirer ne ferait
    echouer aucun autre test de ce fichier. Elles resteraient pourtant les
    dernieres barrieres si l'une des deux autres cedait — d'ou ce test, qui
    porte sur l'option et non sur son effet de bord.
    """
    assert _DECODE_OPTIONS["strict_aud"] is True
    assert _DECODE_OPTIONS["enforce_minimum_key_length"] is True
    assert set(_DECODE_OPTIONS["require"]) == {
        "exp",
        "iat",
        "jti",
        "sub",
        "aud",
        "type",
        "account_type",
    }
    assert CLOCK_SKEW_LEEWAY_SECONDS > 0


async def test_a_key_too_short_is_refused_at_signature_too() -> None:
    """La seconde barriere, celle qui tient si la configuration est contournee.

    `model_construct` saute la validation de pydantic — c'est le seul chemin qui
    atteigne cette garde, et c'est bien le but : elle existe pour le jour ou un
    service serait assemble sans passer par `JWTSettings`.
    """
    service = JwtTokenService(
        settings=JWTSettings.model_construct(
            secret_key=SecretStr("trop-courte"),
            algorithm="HS256",
            access_token_expire_minutes=15,
            refresh_token_expire_days=7,
            audience_professional=_AUDIENCE_PRO,
            audience_individual=_AUDIENCE_INDIVIDUAL,
            audience_admin=_AUDIENCE_ADMIN,
        ),
        resolve_group_role=_Resolver(),
    )

    with pytest.raises(TokenIssuanceError):
        await service.create_access_token(
            account_id=_ACCOUNT_ID,
            account_type=AccountType.PROFESSIONAL.value,
            audience=_AUDIENCE_PRO,
        )
