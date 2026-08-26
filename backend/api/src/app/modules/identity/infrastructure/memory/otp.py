"""Doublures en memoire du parcours OTP (BACK-06c, reprises de BACK-17).

CE QUE CES DOUBLURES SONT, ET CE QU'ELLES NE SONT PAS
Des implementations COMPLETES des ports, pas des simulacres : `InMemoryOtpStore`
tient reellement le TTL, le compteur de tentatives et les trois quotas, et appelle
les MEMES fonctions du domaine que l'adaptateur Redis -- meme empreinte, meme
comparaison en temps constant. C'est ce qui rend les tests de cas d'usage
significatifs : ils eprouvent la regle, pas la doublure.

CES CLASSES VIENNENT DE `tests/modules/identity/otp_doubles.py`
Ecrites en avance sur ce ticket par BACK-17, dont la docstring annoncait leur
deplacement ici. Le code est repris tel quel, a trois changements pres : le
poivre devient un argument plutot qu'une constante de test, l'horloge vient de
`shared/infrastructure/memory/clock.py` plutot que d'une copie locale, et le
depot et l'unite de travail sont partis dans leurs propres fichiers, sur le socle
generique.

LE TEMPS EST INJECTE, ET IL LE FAUT. Sans horloge pilotable, tester l'expiration
d'un code ou la fermeture d'une fenetre de renvoi demanderait de dormir dix
minutes.
"""

import math
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

from app.modules.identity.domain.policies import (
    OtpRules,
    codes_match,
    fingerprint_otp_code,
)
from app.modules.identity.domain.ports import (
    OtpConsumption,
    OtpDispatcher,
    OtpSender,
    OtpStore,
    OtpStoreUnavailableError,
    ResendVerdict,
)
from app.shared.infrastructure.memory.clock import DEFAULT_CLOCK, Clock

# Poivre par defaut de la doublure.
#
# UNE VALEUR QUELCONQUE, ET SURTOUT PAS CELLE DE PRODUCTION. Ce qui compte est
# qu'elle existe -- une empreinte non poivree se retrouve par force brute sur six
# chiffres -- et qu'elle soit VISIBLEMENT differente de ce que `derive_otp_pepper`
# fabrique a partir de la cle de signature des jetons. Un test qui a besoin d'un
# poivre precis le passe en argument.
MEMORY_OTP_PEPPER: Final = b"juui/otp/in-memory-double"


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

    def __init__(self, clock: Clock = DEFAULT_CLOCK, *, pepper: bytes = MEMORY_OTP_PEPPER) -> None:
        """Construit un magasin vide.

        Args:
            clock: l'horloge des expirations et des fenetres de renvoi.
                `FakeClock` pour piloter le temps.
            pepper: le poivre des empreintes. Jamais celui de production.
        """
        self._clock = clock
        self._pepper = pepper
        self._codes: dict[UUID, _StoredOtp] = {}
        self._gates: dict[UUID, float] = {}
        self._per_account: dict[UUID, _ResendCounter] = {}
        self._per_ip: dict[str, _ResendCounter] = {}

    async def issue(self, *, account_id: UUID, code: str, rules: OtpRules) -> None:
        """Range l'empreinte du code, en ecrasement absolu. Voir le port."""
        self._codes[account_id] = _StoredOtp(
            fingerprint=fingerprint_otp_code(code, account_id=account_id, pepper=self._pepper),
            attempts_left=rules.max_attempts,
            expires_at=self._clock() + rules.ttl_seconds,
        )

    async def consume(self, *, account_id: UUID, code: str) -> OtpConsumption:
        """Depense une tentative et juge le code. Voir le port."""
        candidate = fingerprint_otp_code(code, account_id=account_id, pepper=self._pepper)
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
            return ResendVerdict(
                allowed=False, retry_after_seconds=self._remaining(gate_until, now)
            )

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
        """Rend le compteur de la fenetre en cours, en ouvrant une neuve si besoin.

        Args:
            counters: la table des compteurs -- par compte ou par IP.
            key: la cle du compteur cherche.
            now: l'instant courant.
            rules: les bornes, dont la duree de la fenetre.

        Returns:
            Le compteur de la fenetre en cours.
        """
        counter = counters.get(key)
        if counter is None or counter.window_ends_at <= now:
            counter = _ResendCounter(used=0, window_ends_at=now + rules.resend_window_seconds)
            counters[key] = counter
        return counter

    @staticmethod
    def _remaining(deadline: float, now: float) -> int:
        """Rend le delai avant nouvelle tentative, arrondi comme le fait Redis.

        AU SUPERIEUR, ET NON PAR TRONCATURE. Le `TTL` de Redis rend le nombre de
        secondes ENTIERES restantes arrondi vers le haut : une echeance a 59,4
        secondes rend 60. Un `int()` rendait 59 ici, et la doublure sous-evaluait
        donc systematiquement d'une seconde le `Retry-After` que la production
        annoncera -- un client discipline serait refuse une seconde fois.

        Args:
            deadline: l'instant ou le tourniquet rouvre.
            now: l'instant courant.

        Returns:
            Le delai en secondes, jamais nul.
        """
        return max(1, math.ceil(deadline - now))

    def _refuse(self, counter: _ResendCounter, now: float) -> ResendVerdict:
        """Compose le refus d'un plafond atteint.

        Args:
            counter: le compteur qui a atteint son plafond.
            now: l'instant courant.

        Returns:
            Le verdict de refus, avec le delai avant nouvelle tentative.
        """
        return ResendVerdict(
            allowed=False, retry_after_seconds=self._remaining(counter.window_ends_at, now)
        )


class UnavailableOtpStore(OtpStore):
    """Magasin toujours en panne : la doublure de l'echec ferme.

    Elle existe pour une regle precise du port, et une seule : tout echec est
    FERME. Un magasin qui ne repond pas ne rend jamais un verdict par defaut --
    « cet OTP a-t-il ete consomme ? » repondu « non » ouvrirait la porte au lieu
    de la fermer. C'est l'exact contraire du port `Cache`, dont la doublure
    degrade.
    """

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
    """Un envoi observe par la doublure d'expedition.

    Attributes:
        recipient: l'adresse visee.
        recipient_name: le nom affiche du destinataire.
        code: les six chiffres emis.
        ttl_seconds: la duree de validite annoncee.
    """

    recipient: str
    recipient_name: str
    code: str
    ttl_seconds: int


@dataclass(slots=True)
class FakeOtpSender(OtpSender):
    """Expediteur qui retient ce qu'on lui a confie -- le dernier code compris.

    C'est la doublure que la carte du ticket nomme : « `FakeOtpSender` exposant le
    dernier code emis, pour les tests ». Sans elle, un test de bout en bout devrait
    relire l'empreinte, qui ne dit rien du code.

    Attributes:
        sent: les envois observes, dans l'ordre.
    """

    sent: list[SentOtp] = field(default_factory=list)

    async def send_verification_code(
        self, *, recipient: str, recipient_name: str, code: str, ttl_seconds: int
    ) -> None:
        """Retient l'envoi au lieu de le faire.

        Args:
            recipient: l'adresse e-mail, deja normalisee.
            recipient_name: le nom affiche du destinataire.
            code: les six chiffres.
            ttl_seconds: la duree de validite a annoncer.
        """
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

        Returns:
            Les six chiffres du dernier envoi.

        Raises:
            AssertionError: si rien n'est parti -- le test se trompe de cible.
        """
        if not self.sent:
            message = "Aucun code n'a ete emis."
            raise AssertionError(message)
        return self.sent[-1].code


@dataclass(slots=True)
class RecordingOtpDispatcher(OtpDispatcher):
    """Declencheur qui note les demandes au lieu de les mettre en file.

    Attributes:
        dispatched: les comptes pour lesquels un envoi a ete demande, dans l'ordre.
    """

    dispatched: list[UUID] = field(default_factory=list)

    async def dispatch_verification(self, *, account_id: UUID) -> None:
        """Note la demande.

        Args:
            account_id: le compte dont l'adresse est a verifier.
        """
        self.dispatched.append(account_id)
