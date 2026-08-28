"""Tests d'integration du magasin d'OTP Redis (BACK-17).

CE QUE SEUL UN VRAI REDIS PROUVE
Les tests de cas d'usage tournent contre la doublure en memoire : ils eprouvent
les regles. Ceux-ci eprouvent l'ADAPTATEUR, et trois de ses proprietes ne se
verifient nulle part ailleurs -- le TTL est reellement pose, le decrement de
tentative est indivisible, et ce qui est ecrit dans Redis n'est PAS le code. La
quatrieme, l'echec ferme, se verifie contre un port ou personne n'ecoute.

Les cles portent des identifiants tires au hasard a chaque test et expirent
d'elles-memes : rien n'est purge, et surtout aucun `FLUSHDB` -- l'instance est
partagee avec le cache et avec la file de taches.
"""

import asyncio
from uuid import UUID, uuid4

import pytest
from redis.asyncio import ConnectionPool, Redis

from app.core import get_settings
from app.modules.identity.domain.policies import fingerprint_otp_code
from app.modules.identity.domain.ports import OtpConsumption, OtpStoreUnavailableError
from app.modules.identity.infrastructure.clients.redis_otp_store import (
    RedisOtpStore,
    build_otp_store,
    derive_otp_pepper,
)
from app.shared.infrastructure.clients.cache_keys import environment_slug
from tests.conftest import require_service
from tests.modules.identity.helpers import a_client_ip, otp_rules

# AU NIVEAU DU MODULE, contrairement aux suites de conformite : il n'y a pas
# de moitie en memoire ici, les douze tests attaquent le Redis du poste. La
# deduction automatique ne le voit pas -- la fixture s'appelle `store` des
# deux cotes du depot, et c'est la doublure qui porte le meme nom ailleurs.
pytestmark = [pytest.mark.otp, pytest.mark.integration]


def _code_key(account_id: UUID) -> str:
    """Recompose la cle attendue, sans rien lire de l'objet sous test.

    Recalculer la convention plutot que de la demander a l'adaptateur : un test
    qui relirait sa cle passerait meme si la convention changeait des deux cotes
    a la fois -- or c'est justement le contrat de nommage qu'on veut figer.
    """
    return f"{environment_slug(get_settings().app.environment)}:otp:verify:{account_id}"


def _account_quota_key(account_id: UUID) -> str:
    """Recompose la cle du plafond de renvois par compte, meme raison."""
    return f"{environment_slug(get_settings().app.environment)}:otp:resend:account:{account_id}"


@pytest.fixture
async def store(pytestconfig: pytest.Config) -> RedisOtpStore:
    """Magasin adosse au Redis du poste, ou test ignore s'il ne repond pas."""
    opened = build_otp_store(get_settings())
    if not await opened.ping():
        await opened.aclose()
        require_service(
            pytestconfig, name="redis", remedy="`make up` a la racine demarre la pile (INFRA-02)."
        )
    yield opened
    await opened.aclose()


@pytest.fixture
async def raw_client() -> Redis:
    """Client brut, pour inspecter ce que l'adaptateur a REELLEMENT ecrit."""
    settings = get_settings()
    client = Redis.from_url(settings.redis.cache_url, decode_responses=True)
    yield client
    await client.aclose()


async def test_a_code_verifies_once_and_only_once(store: RedisOtpStore) -> None:
    """Usage unique, contre le vrai magasin."""
    account_id = uuid4()
    await store.issue(account_id=account_id, code="123456", rules=otp_rules())

    first = await store.consume(account_id=account_id, code="123456")
    second = await store.consume(account_id=account_id, code="123456")

    assert first is OtpConsumption.ACCEPTED
    assert second is OtpConsumption.REJECTED


async def test_what_redis_holds_is_never_the_code(store: RedisOtpStore, raw_client: Redis) -> None:
    """LE critere « stocke hache », verifie la ou il se joue : dans la base.

    On relit le document par un client BRUT -- passer par l'adaptateur ne
    prouverait que sa propre coherence.
    """
    account_id = uuid4()
    settings = get_settings()
    await store.issue(account_id=account_id, code="123456", rules=otp_rules())

    key = _code_key(account_id)
    document = await raw_client.hgetall(key)

    assert "123456" not in str(document)
    assert document["fingerprint"] == fingerprint_otp_code(
        "123456", account_id=account_id, pepper=derive_otp_pepper(settings)
    )
    assert document["attempts_left"] == "3"


async def test_the_ttl_is_really_posed(store: RedisOtpStore, raw_client: Redis) -> None:
    """Chaque document expire, et l'expiration est celle des regles.

    La verifier par le TTL de la cle plutot qu'en dormant dix minutes -- et le
    test suivant, lui, dort une seconde pour prouver que l'expiration mord.
    """
    account_id = uuid4()
    await store.issue(account_id=account_id, code="123456", rules=otp_rules(ttl_seconds=600))

    key = _code_key(account_id)
    ttl = await raw_client.ttl(key)

    assert 0 < ttl <= 600


# Attend qu'un TTL d'une seconde s'ecoule cote Redis : le test le plus lent de
# la suite (mesure a l'ouverture de BACK-12).
@pytest.mark.slow
async def test_an_expired_code_is_refused(store: RedisOtpStore) -> None:
    """Passe le TTL, le code n'existe plus -- et le refus est celui d'un code faux."""
    account_id = uuid4()
    await store.issue(account_id=account_id, code="123456", rules=otp_rules(ttl_seconds=1))

    await asyncio.sleep(1.5)

    assert await store.consume(account_id=account_id, code="123456") is OtpConsumption.REJECTED


async def test_three_wrong_attempts_destroy_the_document(
    store: RedisOtpStore, raw_client: Redis
) -> None:
    """Le quota epuise detruit le document, il ne se contente pas de le bloquer."""
    account_id = uuid4()
    await store.issue(account_id=account_id, code="123456", rules=otp_rules(max_attempts=3))

    verdicts = [await store.consume(account_id=account_id, code="000000") for _ in range(3)]

    assert verdicts == [
        OtpConsumption.REJECTED,
        OtpConsumption.REJECTED,
        OtpConsumption.EXHAUSTED,
    ]
    key = _code_key(account_id)
    assert await raw_client.exists(key) == 0
    # Le bon code ne vaut plus rien : il a disparu avec le document.
    assert await store.consume(account_id=account_id, code="123456") is OtpConsumption.REJECTED


async def test_verifying_a_missing_code_leaves_no_key_behind(
    store: RedisOtpStore, raw_client: Redis
) -> None:
    """LE piege de `HINCRBY` : sur une cle absente, il la CREE, et sans TTL.

    Sans la garde d'existence du script, verifier un code inexistant laisserait
    derriere lui un document eternel, dans une instance ou toute cle doit expirer.
    """
    account_id = uuid4()

    verdict = await store.consume(account_id=account_id, code="000000")

    assert verdict is OtpConsumption.REJECTED
    key = _code_key(account_id)
    assert await raw_client.exists(key) == 0


async def test_reissuing_replaces_the_previous_code(store: RedisOtpStore) -> None:
    """Ecrasement absolu : le code precedent meurt avec l'emission du suivant."""
    account_id = uuid4()
    rules = otp_rules()
    await store.issue(account_id=account_id, code="111111", rules=rules)
    await store.issue(account_id=account_id, code="222222", rules=rules)

    assert await store.consume(account_id=account_id, code="111111") is OtpConsumption.REJECTED
    assert await store.consume(account_id=account_id, code="222222") is OtpConsumption.ACCEPTED


async def test_the_minimum_interval_holds_the_second_request(store: RedisOtpStore) -> None:
    """Le tourniquet, contre le vrai magasin : la seconde demande attend son tour."""
    account_id = uuid4()
    rules = otp_rules(resend_min_interval_seconds=60)

    first = await store.register_resend(account_id=account_id, client_ip=None, rules=rules)
    second = await store.register_resend(account_id=account_id, client_ip=None, rules=rules)

    assert first.allowed
    assert not second.allowed
    assert second.retry_after_seconds is not None
    assert 0 < second.retry_after_seconds <= 60


async def test_the_account_ceiling_closes_after_its_quota(store: RedisOtpStore) -> None:
    """Le plafond par compte, delai minimal desactive pour ne mesurer que lui."""
    account_id = uuid4()
    rules = otp_rules(resend_min_interval_seconds=0, resend_max_per_email=3)

    verdicts = [
        await store.register_resend(account_id=account_id, client_ip=None, rules=rules)
        for _ in range(4)
    ]

    assert [verdict.allowed for verdict in verdicts] == [True, True, True, False]


async def test_the_ip_ceiling_counts_across_accounts(store: RedisOtpStore) -> None:
    """Le plafond par IP compte l'APPELANT, quel que soit le compte vise."""
    client_ip = a_client_ip()
    rules = otp_rules(resend_min_interval_seconds=0, resend_max_per_email=10, resend_max_per_ip=2)

    verdicts = [
        await store.register_resend(account_id=uuid4(), client_ip=client_ip, rules=rules)
        for _ in range(3)
    ]

    assert [verdict.allowed for verdict in verdicts] == [True, True, False]


async def test_a_refusal_consumes_no_quota(store: RedisOtpStore, raw_client: Redis) -> None:
    """Les trois controles sont indivisibles : ce qui refuse ne depense rien.

    Sans cette propriete, un utilisateur qui clique cinq fois de suite epuiserait
    son quota horaire sans avoir recu un code de plus.

    Le compteur se relit par un client BRUT, et il le faut : rejouer un
    `register_resend` avec un delai minimal desactive ne prouverait rien, la
    garde de delai vivant dans une CLE deja posee -- avec son propre TTL -- et
    non dans les regles passees a l'appel.
    """
    account_id = uuid4()
    rules = otp_rules(resend_min_interval_seconds=60, resend_max_per_email=5)

    await store.register_resend(account_id=account_id, client_ip=None, rules=rules)
    for _ in range(5):
        refused = await store.register_resend(account_id=account_id, client_ip=None, rules=rules)
        assert not refused.allowed

    assert await raw_client.get(_account_quota_key(account_id)) == "1"


async def test_an_unreachable_redis_fails_closed() -> None:
    """ECHEC FERME, la propriete qui distingue ce magasin du cache.

    Le port `Cache` degrade en silence : `get` rend MISSING, `exists` rend False.
    Applique ici, ce contrat repondrait « ce code n'a pas ete consomme » et
    « ce quota n'est pas atteint » des que Redis tombe -- c'est-a-dire qu'il
    suffirait de faire tomber Redis pour ouvrir la porte.
    """
    # Port 1 : reserve, et personne n'y ecoute. Le refus de connexion est
    # immediat, le test ne paie aucun delai d'attente.
    pool = ConnectionPool.from_url(
        "redis://127.0.0.1:1/0", decode_responses=True, socket_connect_timeout=0.5
    )
    dead = RedisOtpStore(
        client=Redis(connection_pool=pool),
        pool=pool,
        environment="test",
        pepper=b"poivre-de-test",
        target="127.0.0.1:1 (base 0)",
    )
    account_id = uuid4()
    rules = otp_rules()

    try:
        with pytest.raises(OtpStoreUnavailableError):
            await dead.issue(account_id=account_id, code="123456", rules=rules)
        with pytest.raises(OtpStoreUnavailableError):
            await dead.consume(account_id=account_id, code="123456")
        with pytest.raises(OtpStoreUnavailableError):
            await dead.register_resend(account_id=account_id, client_ip=None, rules=rules)
        # La sonde, elle, ne leve jamais : c'est ce qui laisse le service demarrer
        # sans Redis.
        assert await dead.ping() is False
    finally:
        await dead.aclose()
