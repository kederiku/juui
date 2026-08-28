"""Demande d'un code : refus, quotas, et mise en file (BACK-17).

Ce fichier eprouve le TOURNIQUET -- le critere « limites de renvoi par adresse et
par IP » --, et l'ordre dans lequel il tourne. Le reste du parcours (generation,
empreinte, envoi) vit dans `test_verify_otp.py` et dans les tests d'integration.
"""

from uuid import uuid4

import pytest

from app.modules.identity.application.use_cases.request_otp import (
    IssueEmailVerificationOtp,
    RequestEmailVerificationCommand,
    RequestEmailVerificationOtp,
)
from app.modules.identity.domain.exceptions import (
    AccountNotFoundError,
    EmailAlreadyVerifiedError,
    OtpResendThrottledError,
)
from app.modules.identity.domain.ports import OtpConsumption, OtpStoreUnavailableError
from app.modules.identity.infrastructure.memory.otp import (
    FakeOtpSender,
    InMemoryOtpStore,
    RecordingOtpDispatcher,
    UnavailableOtpStore,
)
from app.modules.identity.infrastructure.memory.unit_of_work import InMemoryIdentityUnitOfWork
from app.shared.infrastructure.memory.clock import FakeClock
from tests.modules.identity.helpers import an_account, otp_rules


async def test_a_request_reaches_the_queue() -> None:
    """Chemin nominal : le compte existe, il n'est pas verifie, la demande part."""
    account = an_account()
    uow = InMemoryIdentityUnitOfWork([account])
    dispatcher = RecordingOtpDispatcher()
    use_case = RequestEmailVerificationOtp(
        uow=uow,
        otp_store=InMemoryOtpStore(),
        dispatcher=dispatcher,
        rules=otp_rules(),
    )

    await use_case.execute(RequestEmailVerificationCommand(account_id=account.id))

    assert dispatcher.dispatched == [account.id]


async def test_an_unknown_account_is_refused() -> None:
    """Un identifiant sans compte leve, et ne met rien en file."""
    dispatcher = RecordingOtpDispatcher()
    use_case = RequestEmailVerificationOtp(
        uow=InMemoryIdentityUnitOfWork(),
        otp_store=InMemoryOtpStore(),
        dispatcher=dispatcher,
        rules=otp_rules(),
    )

    with pytest.raises(AccountNotFoundError):
        await use_case.execute(RequestEmailVerificationCommand(account_id=uuid4()))

    assert dispatcher.dispatched == []


async def test_an_already_verified_address_spends_no_quota() -> None:
    """Une demande sans objet est refusee AVANT le tourniquet.

    L'ordre compte : si le refus venait apres, un tiers epuiserait le quota d'un
    compte deja verifie par des appels sans effet.
    """
    account = an_account(verified=True)
    store = InMemoryOtpStore()
    dispatcher = RecordingOtpDispatcher()
    use_case = RequestEmailVerificationOtp(
        uow=InMemoryIdentityUnitOfWork([account]),
        otp_store=store,
        dispatcher=dispatcher,
        rules=otp_rules(),
    )

    with pytest.raises(EmailAlreadyVerifiedError):
        await use_case.execute(RequestEmailVerificationCommand(account_id=account.id))

    assert dispatcher.dispatched == []
    # Rien n'a ete consomme : une demande legitime passerait encore.
    verdict = await store.register_resend(account_id=account.id, client_ip=None, rules=otp_rules())
    assert verdict.allowed


async def test_two_requests_in_a_row_hit_the_minimum_interval() -> None:
    """Le double-clic, et le « rien recu » impatient : la seconde demande attend."""
    account = an_account()
    clock = FakeClock()
    use_case = RequestEmailVerificationOtp(
        uow=InMemoryIdentityUnitOfWork([account]),
        otp_store=InMemoryOtpStore(clock=clock),
        dispatcher=RecordingOtpDispatcher(),
        rules=otp_rules(resend_min_interval_seconds=60),
    )
    command = RequestEmailVerificationCommand(account_id=account.id)

    await use_case.execute(command)

    with pytest.raises(OtpResendThrottledError) as refusal:
        await use_case.execute(command)

    # Le delai sort, parce qu'il aide l'appelant ; le compteur restant, jamais.
    assert refusal.value.retry_after_seconds == 60
    assert "patienter" in refusal.value.message


async def test_the_interval_reopens_once_it_has_elapsed() -> None:
    """La garde est un delai, pas un verrou : elle s'ouvre toute seule."""
    account = an_account()
    clock = FakeClock()
    dispatcher = RecordingOtpDispatcher()
    use_case = RequestEmailVerificationOtp(
        uow=InMemoryIdentityUnitOfWork([account]),
        otp_store=InMemoryOtpStore(clock=clock),
        dispatcher=dispatcher,
        rules=otp_rules(resend_min_interval_seconds=60),
    )
    command = RequestEmailVerificationCommand(account_id=account.id)

    await use_case.execute(command)
    clock.advance(61)
    await use_case.execute(command)

    assert dispatcher.dispatched == [account.id, account.id]


async def test_the_account_ceiling_closes_the_window() -> None:
    """Le plafond par adresse : sans lui, le delai minimal se contourne en attendant."""
    account = an_account()
    clock = FakeClock()
    rules = otp_rules(
        resend_min_interval_seconds=0, resend_window_seconds=3600, resend_max_per_email=3
    )
    dispatcher = RecordingOtpDispatcher()
    use_case = RequestEmailVerificationOtp(
        uow=InMemoryIdentityUnitOfWork([account]),
        otp_store=InMemoryOtpStore(clock=clock),
        dispatcher=dispatcher,
        rules=rules,
    )
    command = RequestEmailVerificationCommand(account_id=account.id)

    for _ in range(3):
        await use_case.execute(command)

    with pytest.raises(OtpResendThrottledError):
        await use_case.execute(command)

    assert len(dispatcher.dispatched) == 3

    # La fenetre glisse : passe l'heure, le compteur repart.
    clock.advance(3601)
    await use_case.execute(command)
    assert len(dispatcher.dispatched) == 4


async def test_the_ip_ceiling_covers_several_accounts() -> None:
    """Le plafond par IP protege le service, pas un compte : il compte l'APPELANT.

    Un attaquant qui change de compte cible a chaque demande passerait sous tous
    les plafonds par adresse. C'est ce second compteur qui l'arrete.
    """
    accounts = [an_account(email=f"compte-{index}@exemple.fr") for index in range(4)]
    rules = otp_rules(resend_min_interval_seconds=0, resend_max_per_email=10, resend_max_per_ip=3)
    dispatcher = RecordingOtpDispatcher()
    use_case = RequestEmailVerificationOtp(
        uow=InMemoryIdentityUnitOfWork(accounts),
        otp_store=InMemoryOtpStore(),
        dispatcher=dispatcher,
        rules=rules,
    )

    for account in accounts[:3]:
        await use_case.execute(
            RequestEmailVerificationCommand(account_id=account.id, client_ip="203.0.113.7")
        )

    with pytest.raises(OtpResendThrottledError):
        await use_case.execute(
            RequestEmailVerificationCommand(account_id=accounts[3].id, client_ip="203.0.113.7")
        )

    assert len(dispatcher.dispatched) == 3


async def test_another_ip_is_not_affected_by_the_first_one() -> None:
    """Le compteur par IP est bien par IP -- sans quoi il serait global."""
    accounts = [an_account(email=f"compte-{index}@exemple.fr") for index in range(3)]
    rules = otp_rules(resend_min_interval_seconds=0, resend_max_per_ip=2)
    dispatcher = RecordingOtpDispatcher()
    use_case = RequestEmailVerificationOtp(
        uow=InMemoryIdentityUnitOfWork(accounts),
        otp_store=InMemoryOtpStore(),
        dispatcher=dispatcher,
        rules=rules,
    )

    for account in accounts[:2]:
        await use_case.execute(
            RequestEmailVerificationCommand(account_id=account.id, client_ip="203.0.113.7")
        )
    await use_case.execute(
        RequestEmailVerificationCommand(account_id=accounts[2].id, client_ip="198.51.100.2")
    )

    assert len(dispatcher.dispatched) == 3


async def test_a_request_without_ip_ignores_the_ip_ceiling() -> None:
    """Hors requete HTTP, il n'y a personne a compter -- et surtout pas un seau commun.

    Un seau partage par tous les appelants sans IP bloquerait le service entier
    des le premier d'entre eux.
    """
    accounts = [an_account(email=f"compte-{index}@exemple.fr") for index in range(3)]
    rules = otp_rules(resend_min_interval_seconds=0, resend_max_per_ip=1)
    dispatcher = RecordingOtpDispatcher()
    use_case = RequestEmailVerificationOtp(
        uow=InMemoryIdentityUnitOfWork(accounts),
        otp_store=InMemoryOtpStore(),
        dispatcher=dispatcher,
        rules=rules,
    )

    for account in accounts:
        await use_case.execute(RequestEmailVerificationCommand(account_id=account.id))

    assert len(dispatcher.dispatched) == 3


async def test_a_refusal_consumes_nothing() -> None:
    """Un refus du delai minimal ne doit pas bruler une unite du plafond horaire.

    Sans cette propriete, un utilisateur impatient qui clique cinq fois de suite
    epuiserait son quota de l'heure sans avoir recu un seul code de plus.
    """
    account = an_account()
    clock = FakeClock()
    rules = otp_rules(resend_min_interval_seconds=60, resend_max_per_email=2)
    dispatcher = RecordingOtpDispatcher()
    use_case = RequestEmailVerificationOtp(
        uow=InMemoryIdentityUnitOfWork([account]),
        otp_store=InMemoryOtpStore(clock=clock),
        dispatcher=dispatcher,
        rules=rules,
    )
    command = RequestEmailVerificationCommand(account_id=account.id)

    await use_case.execute(command)
    for _ in range(5):
        with pytest.raises(OtpResendThrottledError):
            await use_case.execute(command)

    # Une seule unite consommee malgre les six appels : la seconde reste due.
    clock.advance(61)
    await use_case.execute(command)

    assert len(dispatcher.dispatched) == 2


async def test_an_unreachable_store_blocks_the_request() -> None:
    """ECHEC FERME : un quota qu'on ne peut pas verifier ne laisse rien passer.

    C'est ce qui interdit de contourner les plafonds en faisant tomber Redis.
    """
    account = an_account()
    dispatcher = RecordingOtpDispatcher()
    use_case = RequestEmailVerificationOtp(
        uow=InMemoryIdentityUnitOfWork([account]),
        otp_store=UnavailableOtpStore(),
        dispatcher=dispatcher,
        rules=otp_rules(),
    )

    with pytest.raises(OtpStoreUnavailableError):
        await use_case.execute(RequestEmailVerificationCommand(account_id=account.id))

    assert dispatcher.dispatched == []


async def test_issuing_stores_a_code_and_sends_it() -> None:
    """Le versant worker : un code est tire, range, et remis au transport."""
    account = an_account()
    store = InMemoryOtpStore()
    sender = FakeOtpSender()
    rules = otp_rules(ttl_seconds=600)
    use_case = IssueEmailVerificationOtp(
        uow=InMemoryIdentityUnitOfWork([account]),
        otp_store=store,
        sender=sender,
        rules=rules,
    )

    await use_case.execute(account.id)

    assert len(sender.sent) == 1
    delivery = sender.sent[0]
    assert delivery.recipient == account.email
    assert delivery.recipient_name == account.full_name
    assert delivery.ttl_seconds == 600
    assert delivery.code.isdigit()
    # Le code emis est bien celui que le magasin acceptera : c'est la seule
    # facon de verifier que les deux gestes portent sur la meme valeur.
    verdict = await store.consume(account_id=account.id, code=sender.last_code)
    assert verdict is OtpConsumption.ACCEPTED


async def test_reissuing_invalidates_the_previous_code() -> None:
    """Rejouee, la tache ecrit un code NEUF : un seul est valide a la fois.

    C'est l'idempotence que BACK-15 exige de toute tache -- l'etat final est le
    meme quel que soit le nombre d'executions --, obtenue par ecrasement absolu
    plutot que par accumulation.
    """
    account = an_account()
    store = InMemoryOtpStore()
    sender = FakeOtpSender()
    use_case = IssueEmailVerificationOtp(
        uow=InMemoryIdentityUnitOfWork([account]),
        otp_store=store,
        sender=sender,
        rules=otp_rules(),
    )

    await use_case.execute(account.id)
    first_code = sender.last_code
    await use_case.execute(account.id)
    second_code = sender.last_code

    assert await store.consume(account_id=account.id, code=first_code) is OtpConsumption.REJECTED
    assert await store.consume(account_id=account.id, code=second_code) is OtpConsumption.ACCEPTED


async def test_issuing_for_a_verified_address_sends_nothing() -> None:
    """Course benigne : l'adresse a ete verifiee entre la demande et la tache."""
    account = an_account(verified=True)
    sender = FakeOtpSender()
    use_case = IssueEmailVerificationOtp(
        uow=InMemoryIdentityUnitOfWork([account]),
        otp_store=InMemoryOtpStore(),
        sender=sender,
        rules=otp_rules(),
    )

    await use_case.execute(account.id)

    assert sender.sent == []
