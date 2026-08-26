"""Conformite du magasin d'OTP : Redis et la doublure (BACK-06c).

LA DOUBLURE LA PLUS DENSE DU TICKET, ET LA DERNIERE SANS CONTREPARTIE COMPAREE.
`InMemoryOtpStore` reimplemente independamment le TTL, le decrement de tentatives
et trois quotas a fenetre glissante. `RedisOtpStore` fait la meme chose contre un
vrai Redis, et `test_redis_otp_store.py` l'eprouve seul de son cote. Rien ne les
confrontait : c'est precisement la situation que le dispositif de BACK-06c existe
pour interdire -- « un comportement qui peut se comparer aux deux implementations
DOIT y etre ».

CE QUE LA SUITE COMPARE : les verdicts de `consume`, l'ecrasement absolu d'un code
reemis, et les trois controles indivisibles de `register_resend` -- delai minimal,
plafond par compte, plafond par IP -- y compris le fait qu'un refus ne consomme
RIEN. Le `retry_after_seconds` est compare a la seconde pres : il alimente un
en-tete `Retry-After`, et une doublure qui l'arrondirait autrement ferait annoncer
en test un delai que la production n'annonce pas.

CE QU'ELLE NE COMPARE PAS : l'expiration par TTL, qui demanderait d'attendre dix
minutes cote Redis. Elle est eprouvee sur horloge pilotee dans les tests du module,
et sur un TTL d'une seconde dans `test_redis_otp_store.py`.
"""

from collections.abc import AsyncIterator, Iterator
from uuid import uuid4

import pytest
import pytest_asyncio

from app.core import get_settings
from app.modules.identity.domain.ports import OtpConsumption, OtpStore
from app.modules.identity.infrastructure.clients.redis_otp_store import build_otp_store
from app.modules.identity.infrastructure.memory.otp import InMemoryOtpStore
from tests.modules.identity.helpers import a_client_ip, otp_rules

pytestmark = pytest.mark.conformance


class OtpStoreConformance:
    """La suite commune. Les sous-classes ne fournissent que la fixture `store`."""

    @pytest.fixture
    def store(self) -> OtpStore:
        """Le sujet sous test -- fourni par la sous-classe."""
        raise NotImplementedError

    async def test_the_right_code_is_accepted_once(self, store: OtpStore) -> None:
        """Usage unique : le code est detruit dans le geste qui l'accepte."""
        account_id = uuid4()
        await store.issue(account_id=account_id, code="123456", rules=otp_rules())
        assert await store.consume(account_id=account_id, code="123456") is OtpConsumption.ACCEPTED
        assert await store.consume(account_id=account_id, code="123456") is OtpConsumption.REJECTED

    async def test_a_wrong_code_is_rejected(self, store: OtpStore) -> None:
        account_id = uuid4()
        await store.issue(account_id=account_id, code="123456", rules=otp_rules())
        assert await store.consume(account_id=account_id, code="000000") is OtpConsumption.REJECTED

    async def test_no_code_at_all_is_rejected_indistinctly(self, store: OtpStore) -> None:
        """Aucun code en cours et code faux se confondent, a dessein."""
        assert await store.consume(account_id=uuid4(), code="123456") is OtpConsumption.REJECTED

    async def test_the_attempt_quota_is_exhausted_then_the_code_is_gone(
        self, store: OtpStore
    ) -> None:
        account_id = uuid4()
        rules = otp_rules(max_attempts=3)
        await store.issue(account_id=account_id, code="123456", rules=rules)
        assert await store.consume(account_id=account_id, code="000000") is OtpConsumption.REJECTED
        assert await store.consume(account_id=account_id, code="000000") is OtpConsumption.REJECTED
        assert await store.consume(account_id=account_id, code="000000") is OtpConsumption.EXHAUSTED
        # Le code est detruit : meme le BON ne vaut plus rien.
        assert await store.consume(account_id=account_id, code="123456") is OtpConsumption.REJECTED

    async def test_a_single_attempt_exhausts_on_the_first_miss(self, store: OtpStore) -> None:
        account_id = uuid4()
        await store.issue(account_id=account_id, code="123456", rules=otp_rules(max_attempts=1))
        assert await store.consume(account_id=account_id, code="000000") is OtpConsumption.EXHAUSTED

    async def test_reissuing_overwrites_the_previous_code_and_rearms_the_quota(
        self, store: OtpStore
    ) -> None:
        """ECRASEMENT ABSOLU : c'est ce qui rend la tache d'envoi rejouable."""
        account_id = uuid4()
        rules = otp_rules(max_attempts=3)
        await store.issue(account_id=account_id, code="111111", rules=rules)
        assert await store.consume(account_id=account_id, code="000000") is OtpConsumption.REJECTED
        await store.issue(account_id=account_id, code="222222", rules=rules)
        assert await store.consume(account_id=account_id, code="111111") is OtpConsumption.REJECTED
        assert await store.consume(account_id=account_id, code="222222") is OtpConsumption.ACCEPTED

    async def test_the_minimum_interval_closes_the_gate(self, store: OtpStore) -> None:
        """Le delai annonce est compare A LA SECONDE PRES : il sort en `Retry-After`."""
        account_id = uuid4()
        rules = otp_rules(resend_min_interval_seconds=30)
        first = await store.register_resend(account_id=account_id, client_ip=None, rules=rules)
        second = await store.register_resend(account_id=account_id, client_ip=None, rules=rules)
        assert first.allowed is True
        assert first.retry_after_seconds is None
        assert second.allowed is False
        assert second.retry_after_seconds == 30

    async def test_a_disabled_interval_lets_two_requests_through(self, store: OtpStore) -> None:
        account_id = uuid4()
        rules = otp_rules(resend_min_interval_seconds=0)
        assert (
            await store.register_resend(account_id=account_id, client_ip=None, rules=rules)
        ).allowed is True
        assert (
            await store.register_resend(account_id=account_id, client_ip=None, rules=rules)
        ).allowed is True

    async def test_the_per_account_cap_refuses_beyond_its_ceiling(self, store: OtpStore) -> None:
        account_id = uuid4()
        rules = otp_rules(resend_min_interval_seconds=0, resend_max_per_email=2)
        verdicts = [
            await store.register_resend(account_id=account_id, client_ip=None, rules=rules)
            for _ in range(3)
        ]
        assert [verdict.allowed for verdict in verdicts] == [True, True, False]
        assert verdicts[2].retry_after_seconds == rules.resend_window_seconds

    async def test_the_per_ip_cap_counts_across_accounts(self, store: OtpStore) -> None:
        """Le plafond par IP est ce qui empeche l'enumeration de comptes."""
        client_ip = a_client_ip()
        rules = otp_rules(
            resend_min_interval_seconds=0, resend_max_per_email=10, resend_max_per_ip=2
        )
        verdicts = [
            await store.register_resend(account_id=uuid4(), client_ip=client_ip, rules=rules)
            for _ in range(3)
        ]
        assert [verdict.allowed for verdict in verdicts] == [True, True, False]

    async def test_a_refusal_consumes_nothing(self, store: OtpStore) -> None:
        """LES TROIS CONTROLES SONT INDIVISIBLES : un refus ne depense rien.

        Eprouve SANS TOUCHER AU TEMPS -- la moitie Redis ne sait pas le remonter.
        Un refus par le plafond de COMPTE ne doit rien retirer au plafond d'IP :
        avec trois envois par IP, deux comptes refuses au passage et trois comptes
        distincts qui passent, le quatrieme seul doit tomber. Si un refus avait
        consomme une unite d'IP, le troisieme serait deja refuse.
        """
        client_ip = a_client_ip()
        rules = otp_rules(
            resend_min_interval_seconds=0, resend_max_per_email=1, resend_max_per_ip=3
        )
        first, second, third = uuid4(), uuid4(), uuid4()

        async def demande(account_id: object) -> bool:
            """Passe le tourniquet pour ce compte, sur la meme IP."""
            verdict = await store.register_resend(
                account_id=account_id,  # type: ignore[arg-type]
                client_ip=client_ip,
                rules=rules,
            )
            return verdict.allowed

        assert await demande(first) is True
        # Refuse par le plafond de COMPTE : ne doit rien retirer au plafond d'IP.
        assert await demande(first) is False
        assert await demande(second) is True
        assert await demande(second) is False
        assert await demande(third) is True
        # Trois envois consommes sur l'IP, malgre les deux refus intercales.
        assert await demande(uuid4()) is False

    async def test_the_ip_refusal_does_not_burn_the_account_quota(self, store: OtpStore) -> None:
        client_ip = a_client_ip()
        rules = otp_rules(
            resend_min_interval_seconds=0, resend_max_per_email=5, resend_max_per_ip=1
        )
        first_account = uuid4()
        assert (
            await store.register_resend(account_id=first_account, client_ip=client_ip, rules=rules)
        ).allowed is True
        second_account = uuid4()
        assert (
            await store.register_resend(account_id=second_account, client_ip=client_ip, rules=rules)
        ).allowed is False
        # Le second compte n'a rien depense : sans IP, il passe.
        assert (
            await store.register_resend(account_id=second_account, client_ip=None, rules=rules)
        ).allowed is True


class TestRedisOtpStoreConformance(OtpStoreConformance):
    """La suite, jouee contre le Redis du poste."""

    @pytest_asyncio.fixture
    async def store(self) -> AsyncIterator[OtpStore]:
        """Magasin Redis reel, ou test ignore si l'instance ne repond pas.

        Les identifiants de compte sont tires au hasard a chaque test et les
        entrees portent leur TTL : rien n'est purge, et surtout aucun `FLUSHDB` --
        l'instance est partagee avec le cache et la file de taches.
        """
        opened = build_otp_store(get_settings())
        if not await opened.ping():
            await opened.aclose()
            pytest.skip("Redis n'est pas joignable : `make up` a la racine (INFRA-02).")
        yield opened
        await opened.aclose()


class TestInMemoryOtpStoreConformance(OtpStoreConformance):
    """La MEME suite, jouee contre `InMemoryOtpStore`."""

    @pytest.fixture
    def store(self) -> Iterator[OtpStore]:
        """Doublure neuve a chaque test, sur l'horloge reelle.

        L'horloge n'est PAS pilotee ici, a dessein : la moitie Redis ne sait pas
        remonter le temps, et une suite de conformite doit poser la meme question
        aux deux cotes.
        """
        yield InMemoryOtpStore()
