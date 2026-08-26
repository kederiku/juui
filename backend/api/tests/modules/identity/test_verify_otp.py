"""Verification du code : usage unique, tentatives bornees, non-divulgation (BACK-17).

Trois criteres d'acceptation se jouent ici : « usage unique », « 3 tentatives
puis invalidation », et la regle qui ne figure pas dans la checklist mais que la
carte enonce -- code faux et code expire donnent le MEME refus.
"""

from uuid import UUID, uuid4

import pytest

from app.modules.identity.application.use_cases.request_otp import (
    IssueEmailVerificationOtp,
    RequestEmailVerificationCommand,
    RequestEmailVerificationOtp,
)
from app.modules.identity.application.use_cases.verify_otp import (
    VerifyEmailCommand,
    VerifyEmailOtp,
)
from app.modules.identity.domain.exceptions import (
    AccountNotFoundError,
    EmailAlreadyVerifiedError,
    OtpAttemptsExhaustedError,
    OtpCodeInvalidError,
)
from app.modules.identity.domain.ports import OtpConsumption, OtpStoreUnavailableError
from tests.modules.identity.otp_doubles import (
    FakeClock,
    FakeOtpSender,
    InMemoryIdentityUnitOfWork,
    InMemoryOtpStore,
    RecordingOtpDispatcher,
    UnavailableOtpStore,
    an_account,
    otp_rules,
)


class _CountingOtpStore(InMemoryOtpStore):
    """Magasin qui compte ses consommations, pour prouver ce qui n'est PAS depense."""

    def __init__(self, clock: FakeClock | None = None) -> None:
        """Ajoute le compteur au magasin en memoire."""
        super().__init__(clock=clock)
        self.consumptions = 0

    async def consume(self, *, account_id: UUID, code: str) -> OtpConsumption:
        """Compte, puis delegue."""
        self.consumptions += 1
        return await super().consume(account_id=account_id, code=code)


async def _issued(
    store: InMemoryOtpStore, uow: InMemoryIdentityUnitOfWork, account_id: UUID
) -> str:
    """Emet un code par le vrai cas d'usage, et rend sa valeur en clair.

    Passer par `IssueEmailVerificationOtp` plutot que d'appeler `store.issue` a la
    main : c'est le seul moyen d'eprouver le parcours reel, ou le code qui part
    est celui dont l'empreinte est rangee.
    """
    sender = FakeOtpSender()
    await IssueEmailVerificationOtp(
        uow=uow, otp_store=store, sender=sender, rules=otp_rules()
    ).execute(account_id)
    return sender.last_code


async def test_the_right_code_verifies_the_address() -> None:
    """Chemin nominal : l'adresse bascule, et la bascule est VALIDEE."""
    account = an_account()
    uow = InMemoryIdentityUnitOfWork([account])
    store = InMemoryOtpStore()
    code = await _issued(store, uow, account.id)
    use_case = VerifyEmailOtp(uow=uow, otp_store=store)

    verified = await use_case.execute(VerifyEmailCommand(account_id=account.id, code=code))

    assert verified.email_verified
    # L'etat VALIDE, et non celui que le bloc tenait en main : c'est la seule
    # lecture qui prouve le commit.
    assert uow.stored(account.id).email_verified
    assert uow.commits == 1


async def test_a_used_code_cannot_serve_twice() -> None:
    """Usage unique : le code est detruit au moment ou il sert."""
    account = an_account()
    uow = InMemoryIdentityUnitOfWork([account])
    store = InMemoryOtpStore()
    code = await _issued(store, uow, account.id)
    use_case = VerifyEmailOtp(uow=uow, otp_store=store)
    await use_case.execute(VerifyEmailCommand(account_id=account.id, code=code))

    # Le second passage bute d'abord sur l'etat du compte, qui est desormais
    # verifie -- et c'est le magasin qu'on veut eprouver. On repart donc d'un
    # compte neuf pour isoler la propriete.
    other = an_account(email="autre@exemple.fr")
    other_uow = InMemoryIdentityUnitOfWork([other])
    other_code = await _issued(store, other_uow, other.id)
    other_use_case = VerifyEmailOtp(uow=other_uow, otp_store=store)
    await other_use_case.execute(VerifyEmailCommand(account_id=other.id, code=other_code))

    assert await store.consume(account_id=other.id, code=other_code) is OtpConsumption.REJECTED


async def test_a_wrong_code_is_refused_without_verifying() -> None:
    """Un code faux ne verifie rien, et n'ecrit rien."""
    account = an_account()
    uow = InMemoryIdentityUnitOfWork([account])
    store = InMemoryOtpStore()
    await _issued(store, uow, account.id)
    use_case = VerifyEmailOtp(uow=uow, otp_store=store)

    with pytest.raises(OtpCodeInvalidError):
        await use_case.execute(VerifyEmailCommand(account_id=account.id, code="000000"))

    assert not uow.stored(account.id).email_verified
    assert uow.commits == 0


async def test_an_expired_code_says_exactly_what_a_wrong_one_says() -> None:
    """LA regle de non-divulgation : meme classe d'erreur, meme message.

    Distinguer « expire » de « faux » dirait a un attaquant qu'il a trouve le bon
    moment, sinon le bon code.
    """
    clock = FakeClock()
    store = InMemoryOtpStore(clock=clock)

    expired_account = an_account()
    expired_uow = InMemoryIdentityUnitOfWork([expired_account])
    expired_code = await _issued(store, expired_uow, expired_account.id)
    clock.advance(otp_rules().ttl_seconds + 1)

    wrong_account = an_account(email="autre@exemple.fr")
    wrong_uow = InMemoryIdentityUnitOfWork([wrong_account])
    await _issued(store, wrong_uow, wrong_account.id)

    with pytest.raises(OtpCodeInvalidError) as expired:
        await VerifyEmailOtp(uow=expired_uow, otp_store=store).execute(
            VerifyEmailCommand(account_id=expired_account.id, code=expired_code)
        )
    with pytest.raises(OtpCodeInvalidError) as wrong:
        await VerifyEmailOtp(uow=wrong_uow, otp_store=store).execute(
            VerifyEmailCommand(account_id=wrong_account.id, code="000000")
        )

    assert expired.value.message == wrong.value.message
    assert expired.value.code == wrong.value.code


async def test_no_pending_code_says_the_same_thing_again() -> None:
    """Troisieme situation, meme refus : aucune demande en cours ne se devine pas."""
    account = an_account()
    uow = InMemoryIdentityUnitOfWork([account])
    use_case = VerifyEmailOtp(uow=uow, otp_store=InMemoryOtpStore())

    with pytest.raises(OtpCodeInvalidError) as refusal:
        await use_case.execute(VerifyEmailCommand(account_id=account.id, code="000000"))

    assert refusal.value.code == "identity.otp.invalid_code"


async def test_three_wrong_attempts_destroy_the_code() -> None:
    """Le critere du ticket : trois tentatives, puis invalidation.

    La troisieme erreur ne dit pas « faux » mais « bloque » -- ce que
    l'utilisateur doit savoir, c'est qu'insister ne sert plus a rien. Le compteur
    restant, lui, ne sort jamais.
    """
    account = an_account()
    uow = InMemoryIdentityUnitOfWork([account])
    store = InMemoryOtpStore()
    good_code = await _issued(store, uow, account.id)
    use_case = VerifyEmailOtp(uow=uow, otp_store=store)
    wrong = VerifyEmailCommand(account_id=account.id, code="000000")

    for _ in range(2):
        with pytest.raises(OtpCodeInvalidError):
            await use_case.execute(wrong)

    with pytest.raises(OtpAttemptsExhaustedError) as blocked:
        await use_case.execute(wrong)

    assert "nouveau" in blocked.value.message

    # Et le BON code ne vaut plus rien : le document est detruit, pas seulement
    # bloque -- sinon il suffirait d'attendre.
    with pytest.raises(OtpCodeInvalidError):
        await use_case.execute(VerifyEmailCommand(account_id=account.id, code=good_code))
    assert not uow.stored(account.id).email_verified


async def test_a_wrong_attempt_does_not_burn_the_others() -> None:
    """Deux erreurs laissent une chance : le compteur decremente, il ne s'effondre pas."""
    account = an_account()
    uow = InMemoryIdentityUnitOfWork([account])
    store = InMemoryOtpStore()
    code = await _issued(store, uow, account.id)
    use_case = VerifyEmailOtp(uow=uow, otp_store=store)

    for _ in range(2):
        with pytest.raises(OtpCodeInvalidError):
            await use_case.execute(VerifyEmailCommand(account_id=account.id, code="000000"))

    verified = await use_case.execute(VerifyEmailCommand(account_id=account.id, code=code))

    assert verified.email_verified


async def test_an_already_verified_address_spends_no_attempt() -> None:
    """Une adresse deja verifiee est refusee AVANT que la tentative ne soit depensee.

    Sans cet ordre, un tiers qui connait l'identifiant d'un compte epuiserait le
    quota de tentatives de son voisin par des appels sans objet.
    """
    account = an_account(verified=True)
    uow = InMemoryIdentityUnitOfWork([account])
    store = _CountingOtpStore()
    use_case = VerifyEmailOtp(uow=uow, otp_store=store)

    with pytest.raises(EmailAlreadyVerifiedError):
        await use_case.execute(VerifyEmailCommand(account_id=account.id, code="000000"))

    assert store.consumptions == 0


async def test_an_unknown_account_spends_no_attempt() -> None:
    """Meme raisonnement pour un identifiant sans compte."""
    store = _CountingOtpStore()
    use_case = VerifyEmailOtp(uow=InMemoryIdentityUnitOfWork(), otp_store=store)

    with pytest.raises(AccountNotFoundError):
        await use_case.execute(VerifyEmailCommand(account_id=uuid4(), code="000000"))

    assert store.consumptions == 0


async def test_an_unreachable_store_verifies_nothing() -> None:
    """ECHEC FERME : sur un magasin muet, aucune verification n'est prononcee."""
    account = an_account()
    uow = InMemoryIdentityUnitOfWork([account])
    use_case = VerifyEmailOtp(uow=uow, otp_store=UnavailableOtpStore())

    with pytest.raises(OtpStoreUnavailableError):
        await use_case.execute(VerifyEmailCommand(account_id=account.id, code="000000"))

    assert not uow.stored(account.id).email_verified
    assert uow.commits == 0


async def test_the_full_journey_from_request_to_verification() -> None:
    """Le parcours entier, sans Docker : demande, emission, saisie, bascule.

    C'est le pendant en memoire du test de bout en bout par Mailpit : celui-ci
    prouve l'enchainement des trois cas d'usage, celui-la prouve que le message
    part vraiment.
    """
    account = an_account()
    uow = InMemoryIdentityUnitOfWork([account])
    store = InMemoryOtpStore()
    sender = FakeOtpSender()
    dispatcher = RecordingOtpDispatcher()

    await RequestEmailVerificationOtp(
        uow=uow, otp_store=store, dispatcher=dispatcher, rules=otp_rules()
    ).execute(RequestEmailVerificationCommand(account_id=account.id, client_ip="203.0.113.7"))

    # Ce que le worker fera de la demande mise en file.
    assert dispatcher.dispatched == [account.id]
    await IssueEmailVerificationOtp(
        uow=uow, otp_store=store, sender=sender, rules=otp_rules()
    ).execute(dispatcher.dispatched[0])

    verified = await VerifyEmailOtp(uow=uow, otp_store=store).execute(
        VerifyEmailCommand(account_id=account.id, code=sender.last_code)
    )

    assert verified.email_verified
    assert uow.stored(account.id).email_verified
