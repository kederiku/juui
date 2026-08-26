"""Doublures en memoire du parcours OTP (BACK-17, en avance sur BACK-06c).

CE QUE CES DOUBLURES SONT, ET CE QU'ELLES NE SONT PAS
Des implementations completes des ports, pas des simulacres : `InMemoryOtpStore`
tient reellement le TTL, le compteur de tentatives et les trois quotas, et
appelle les MEMES fonctions du domaine que l'adaptateur Redis -- meme empreinte,
meme comparaison en temps constant. C'est ce qui rend les tests de cas d'usage
significatifs : ils eprouvent la regle, pas la doublure.

POURQUOI ELLES VIVENT ICI ET NON DANS `shared/`
BACK-06c livrera le jeu complet de doublures du projet -- `InMemoryCache`,
`FakeOtpSender`, unites de travail en memoire. Il n'est pas livre ; ecrire ces
quatre classes ici est l'emprunt minimal qui permet de tester BACK-17 sans
Docker, et l'ecart est consigne au registre. Le jour ou BACK-06c arrive, ce
fichier disparait au profit du sien.

LE TEMPS EST INJECTE, ET IL LE FAUT
`InMemoryOtpStore` recoit son horloge. Sans cela, tester l'expiration d'un code
ou la fermeture d'une fenetre de renvoi demanderait de dormir dix minutes.
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Self
from uuid import UUID

from app.modules.identity.domain.entities import Account, AccountType
from app.modules.identity.domain.exceptions import AccountNotFoundError
from app.modules.identity.domain.policies import (
    OtpRules,
    codes_match,
    fingerprint_otp_code,
)
from app.modules.identity.domain.ports import (
    AccountRepository,
    IdentityUnitOfWork,
    OtpConsumption,
    OtpDispatcher,
    OtpSender,
    OtpStore,
    OtpStoreUnavailableError,
    ResendVerdict,
)

# Poivre des tests. Une valeur quelconque : ce qui compte est qu'elle existe et
# qu'elle ne soit pas celle de production.
TEST_PEPPER = b"poivre-de-test"

# Bornes par defaut des tests -- celles du gabarit .env.example. Chaque test
# surcharge ce dont il a besoin, et rien d'autre : un test qui ecrit ses six
# valeurs ne dit plus laquelle il eprouve.
_DEFAULT_RULES = {
    "ttl_seconds": 600,
    "max_attempts": 3,
    "resend_min_interval_seconds": 60,
    "resend_window_seconds": 3600,
    "resend_max_per_email": 5,
    "resend_max_per_ip": 20,
}


def otp_rules(**overrides: int) -> OtpRules:
    """Un jeu de bornes complet, surchargeable champ par champ."""
    return OtpRules(**{**_DEFAULT_RULES, **overrides})


def an_account(*, email: str = "jean@exemple.fr", verified: bool = False) -> Account:
    """Un compte particulier, verifie ou non.

    Passe par `Account.create()` puis bascule l'etat par le COMPORTEMENT de
    l'entite : construire directement une dataclass avec `email_verified=True`
    contournerait l'invariant, et un test qui contourne l'invariant ne teste plus
    le meme objet que la production.
    """
    account = Account.create(
        email=email,
        first_name="Jean",
        last_name="Veto",
        account_type=AccountType.INDIVIDUAL,
    )
    if verified:
        account.verify_email()
    return account


class FakeClock:
    """Horloge que le test avance a la main."""

    def __init__(self, start: float = 1_000.0) -> None:
        """Pose l'instant initial."""
        self._now = start

    def __call__(self) -> float:
        """Rend l'instant courant, en secondes."""
        return self._now

    def advance(self, seconds: float) -> None:
        """Avance l'horloge."""
        self._now += seconds


class InMemoryAccountRepository(AccountRepository):
    """Depot de comptes en memoire, avec ecritures en attente de validation.

    LES ENTITES SORTENT EN COPIE, et c'est la ligne qui rend ce depot utile : un
    depot qui rendrait l'objet range laisserait un `account.verify_email()` non
    valide modifier l'etat « persiste ». Le test « une exception avant le commit
    n'ecrit rien » passerait alors sans rien prouver.
    """

    def __init__(self, committed: dict[UUID, Account], pending: dict[UUID, Account]) -> None:
        """Branche le depot sur les deux etats de l'unite de travail."""
        self._committed = committed
        self._pending = pending

    async def get(self, account_id: UUID, /) -> Account:
        """Retourne le compte, ou leve comme le vrai depot."""
        stored = self._pending.get(account_id) or self._committed.get(account_id)
        if stored is None:
            message = "Aucun compte ne porte cet identifiant."
            raise AccountNotFoundError(message)
        return replace(stored)

    async def find_by_email(self, email: str) -> Account | None:
        """Cherche par adresse, sans erreur si rien ne correspond."""
        for stored in (*self._pending.values(), *self._committed.values()):
            if stored.email == email:
                return replace(stored)
        return None

    async def add(self, account: Account, /) -> None:
        """Range un compte neuf, en attente de validation."""
        self._pending[account.id] = replace(account)

    async def save(self, account: Account, /) -> None:
        """Reporte l'etat d'un compte connu, en attente de validation."""
        self._pending[account.id] = replace(account)


class InMemoryIdentityUnitOfWork(IdentityUnitOfWork):
    """Unite de travail d'identity en memoire, commit et rollback compris."""

    def __init__(self, accounts: list[Account] | None = None) -> None:
        """Seme l'etat valide initial."""
        self._committed: dict[UUID, Account] = {
            account.id: replace(account) for account in accounts or []
        }
        self._pending: dict[UUID, Account] = {}
        self._open = False
        self.commits = 0

    @property
    def accounts(self) -> AccountRepository:
        """Le depot du bloc en cours."""
        if not self._open:
            message = "Aucun bloc n'est ouvert sur cette unite de travail."
            raise RuntimeError(message)
        return InMemoryAccountRepository(self._committed, self._pending)

    def stored(self, account_id: UUID) -> Account:
        """Relit l'etat VALIDE, hors de tout bloc -- ce que le test veut assurer."""
        return replace(self._committed[account_id])

    async def __aenter__(self) -> Self:
        """Ouvre le bloc."""
        if self._open:
            message = "Un bloc est deja ouvert sur cette unite de travail."
            raise RuntimeError(message)
        self._open = True
        return self

    async def commit(self) -> None:
        """Valide les ecritures en attente."""
        self._require_open()
        self._committed.update(self._pending)
        self._pending.clear()
        self.commits += 1

    async def rollback(self) -> None:
        """Jette les ecritures en attente."""
        self._require_open()
        self._pending.clear()

    async def _release(self) -> None:
        """Referme le bloc."""
        self._pending.clear()
        self._open = False

    def _require_open(self) -> None:
        """Refuse toute operation hors bloc, comme le vrai adaptateur."""
        if not self._open:
            message = "Aucun bloc n'est ouvert sur cette unite de travail."
            raise RuntimeError(message)


@dataclass(slots=True)
class _StoredOtp:
    """Ce que la doublure conserve d'un code : son empreinte, et rien d'autre."""

    fingerprint: str
    attempts_left: int
    expires_at: float


@dataclass(slots=True)
class _ResendCounter:
    """Compteur de fenetre glissante, remis a zero quand la fenetre se ferme."""

    used: int = 0
    window_ends_at: float = 0.0


class InMemoryOtpStore(OtpStore):
    """Magasin d'OTP en memoire : meme contrat, meme empreinte, meme comparaison."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        """Construit un magasin vide, avec l'horloge fournie."""
        self._clock: Callable[[], float] = clock or FakeClock()
        self._codes: dict[UUID, _StoredOtp] = {}
        self._gates: dict[UUID, float] = {}
        self._per_account: dict[UUID, _ResendCounter] = {}
        self._per_ip: dict[str, _ResendCounter] = {}

    async def issue(self, *, account_id: UUID, code: str, rules: OtpRules) -> None:
        """Range l'empreinte du code, en ecrasement absolu."""
        self._codes[account_id] = _StoredOtp(
            fingerprint=fingerprint_otp_code(code, account_id=account_id, pepper=TEST_PEPPER),
            attempts_left=rules.max_attempts,
            expires_at=self._clock() + rules.ttl_seconds,
        )

    async def consume(self, *, account_id: UUID, code: str) -> OtpConsumption:
        """Depense une tentative et juge le code."""
        candidate = fingerprint_otp_code(code, account_id=account_id, pepper=TEST_PEPPER)
        stored = self._codes.get(account_id)
        if stored is None:
            return OtpConsumption.REJECTED
        if stored.expires_at <= self._clock():
            # Expire : indistinct d'un code faux, exactement comme cote Redis, ou
            # c'est le TTL qui a fait disparaitre la cle.
            del self._codes[account_id]
            return OtpConsumption.REJECTED

        stored.attempts_left -= 1
        accepted = codes_match(candidate, stored.fingerprint)
        if accepted or stored.attempts_left <= 0:
            del self._codes[account_id]
        if accepted:
            return OtpConsumption.ACCEPTED
        return OtpConsumption.EXHAUSTED if stored.attempts_left <= 0 else OtpConsumption.REJECTED

    async def register_resend(
        self, *, account_id: UUID, client_ip: str | None, rules: OtpRules
    ) -> ResendVerdict:
        """Passe le tourniquet : delai minimal, plafond par compte, plafond par IP."""
        now = self._clock()

        gate_until = self._gates.get(account_id, 0.0)
        if gate_until > now:
            return ResendVerdict(allowed=False, retry_after_seconds=int(gate_until - now) or 1)

        account_counter = self._counter(self._per_account, account_id, now, rules)
        if account_counter.used >= rules.resend_max_per_email:
            return self._refuse(account_counter, now)

        ip_counter = None
        if client_ip:
            ip_counter = self._counter(self._per_ip, client_ip, now, rules)
            if ip_counter.used >= rules.resend_max_per_ip:
                return self._refuse(ip_counter, now)

        # AUCUNE CONSOMMATION AVANT CE POINT : un refus ne doit rien depenser.
        if rules.resend_min_interval_seconds > 0:
            self._gates[account_id] = now + rules.resend_min_interval_seconds
        account_counter.used += 1
        if ip_counter is not None:
            ip_counter.used += 1
        return ResendVerdict(allowed=True)

    def _counter[K](
        self, counters: dict[K, _ResendCounter], key: K, now: float, rules: OtpRules
    ) -> _ResendCounter:
        """Rend le compteur de la fenetre en cours, en ouvrant une neuve si besoin."""
        counter = counters.get(key)
        if counter is None or counter.window_ends_at <= now:
            counter = _ResendCounter(used=0, window_ends_at=now + rules.resend_window_seconds)
            counters[key] = counter
        return counter

    def _refuse(self, counter: _ResendCounter, now: float) -> ResendVerdict:
        """Compose le refus d'un plafond atteint."""
        return ResendVerdict(
            allowed=False, retry_after_seconds=int(counter.window_ends_at - now) or 1
        )


class UnavailableOtpStore(OtpStore):
    """Magasin toujours en panne : la doublure de l'echec ferme."""

    async def issue(self, *, account_id: UUID, code: str, rules: OtpRules) -> None:
        """Leve, comme le fait l'adaptateur Redis quand rien ne repond."""
        raise OtpStoreUnavailableError("Magasin indisponible.")

    async def consume(self, *, account_id: UUID, code: str) -> OtpConsumption:
        """Leve, plutot que de rendre un verdict par defaut."""
        raise OtpStoreUnavailableError("Magasin indisponible.")

    async def register_resend(
        self, *, account_id: UUID, client_ip: str | None, rules: OtpRules
    ) -> ResendVerdict:
        """Leve : un quota qu'on ne peut pas verifier bloque l'envoi."""
        raise OtpStoreUnavailableError("Magasin indisponible.")


@dataclass(slots=True)
class SentOtp:
    """Un envoi observe par la doublure d'expedition."""

    recipient: str
    recipient_name: str
    code: str
    ttl_seconds: int


@dataclass(slots=True)
class FakeOtpSender(OtpSender):
    """Expediteur qui retient ce qu'on lui a confie -- le dernier code compris.

    C'est la doublure que le ticket nomme : « `FakeOtpSender` exposant le dernier
    code emis, pour les tests ». Sans elle, un test de bout en bout devrait relire
    l'empreinte, qui ne dit rien du code.
    """

    sent: list[SentOtp] = field(default_factory=list)

    async def send_verification_code(
        self, *, recipient: str, recipient_name: str, code: str, ttl_seconds: int
    ) -> None:
        """Retient l'envoi au lieu de le faire."""
        self.sent.append(
            SentOtp(
                recipient=recipient,
                recipient_name=recipient_name,
                code=code,
                ttl_seconds=ttl_seconds,
            )
        )

    @property
    def last_code(self) -> str:
        """Le dernier code emis.

        Raises:
            AssertionError: si rien n'est parti -- le test se trompe de cible.
        """
        assert self.sent, "Aucun code n'a ete emis."
        return self.sent[-1].code


@dataclass(slots=True)
class RecordingOtpDispatcher(OtpDispatcher):
    """Declencheur qui note les demandes au lieu de les mettre en file."""

    dispatched: list[UUID] = field(default_factory=list)

    async def dispatch_verification(self, *, account_id: UUID) -> None:
        """Note la demande."""
        self.dispatched.append(account_id)
