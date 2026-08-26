"""Doublures en memoire du module notifications (BACK-22, en avance sur BACK-06c).

CE QUE CES DOUBLURES SONT, ET CE QU'ELLES NE SONT PAS
Des implementations completes des ports, pas des simulacres :
`InMemoryNotificationPreferencesRepository` rend des COPIES, comme le vrai depot,
et `FakeNotificationSender` respecte le contrat du port jusqu'a la maniere
d'echouer. C'est ce qui rend les tests de cas d'usage significatifs : ils
eprouvent la regle, pas la doublure.

POURQUOI ELLES VIVENT ICI ET NON DANS `shared/`
BACK-06c livrera le jeu complet de doublures du projet. Il n'est pas livre ;
ecrire ces quatre classes ici est l'emprunt minimal qui permet de tester BACK-22
sans Docker, et l'ecart est consigne au registre. Le jour ou BACK-06c arrive, ce
fichier disparait au profit du sien -- meme trajectoire que `otp_doubles.py`.

`FakeNotificationSender` EST NOMME PAR LA CARTE DU TICKET, et il n'est pas
decoratif : sans lui, verifier « le module appelant emet un evenement,
notifications choisit le canal » demanderait un serveur SMTP pour un test qui ne
parle pas de SMTP.
"""

from dataclasses import dataclass, field, replace
from typing import Self
from uuid import UUID

from app.modules.notifications.domain.entities import NotificationPreferences
from app.modules.notifications.domain.policies import NotificationChannel
from app.modules.notifications.domain.ports import (
    NotificationDeliveryError,
    NotificationPreferencesRepository,
    NotificationSender,
    NotificationsUnitOfWork,
)
from app.shared.domain.ports.email import EmailDeliveryError, EmailTransport


def _copy(preferences: NotificationPreferences) -> NotificationPreferences:
    """Rend une copie INDEPENDANTE de preferences, dictionnaire compris.

    `dataclasses.replace` copie les champs, mais le `dict` des ecarts resterait
    PARTAGE : un `set_channels` sur l'objet rendu modifierait l'etat « persiste »,
    et le test « rien n'est ecrit sans commit » passerait sans rien prouver.
    """
    return replace(preferences, channels_by_event=dict(preferences.channels_by_event))


class InMemoryNotificationPreferencesRepository(NotificationPreferencesRepository):
    """Depot de preferences en memoire, avec ecritures en attente de validation."""

    def __init__(
        self,
        committed: dict[UUID, NotificationPreferences],
        pending: dict[UUID, NotificationPreferences],
    ) -> None:
        """Branche le depot sur les deux etats de l'unite de travail."""
        self._committed = committed
        self._pending = pending

    async def find_for_account(self, account_id: UUID) -> NotificationPreferences | None:
        """Cherche par compte, sans erreur si rien n'est enregistre."""
        for stored in (*self._pending.values(), *self._committed.values()):
            if stored.account_id == account_id:
                return _copy(stored)
        return None

    async def add(self, preferences: NotificationPreferences, /) -> None:
        """Range des preferences neuves, en attente de validation."""
        self._pending[preferences.id] = _copy(preferences)

    async def save(self, preferences: NotificationPreferences, /) -> None:
        """Reporte l'etat de preferences connues, en attente de validation."""
        self._pending[preferences.id] = _copy(preferences)


class InMemoryNotificationsUnitOfWork(NotificationsUnitOfWork):
    """Unite de travail de notifications en memoire, commit et rollback compris."""

    def __init__(self, preferences: list[NotificationPreferences] | None = None) -> None:
        """Seme l'etat valide initial."""
        self._committed: dict[UUID, NotificationPreferences] = {
            item.id: _copy(item) for item in preferences or []
        }
        self._pending: dict[UUID, NotificationPreferences] = {}
        self._open = False
        self.commits = 0

    @property
    def preferences(self) -> NotificationPreferencesRepository:
        """Le depot du bloc en cours."""
        if not self._open:
            message = "Aucun bloc n'est ouvert sur cette unite de travail."
            raise RuntimeError(message)
        return InMemoryNotificationPreferencesRepository(self._committed, self._pending)

    def stored(self, preferences_id: UUID) -> NotificationPreferences:
        """Relit l'etat VALIDE, hors de tout bloc -- ce que le test veut assurer."""
        return _copy(self._committed[preferences_id])

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
class SentNotification:
    """Un envoi observe par une doublure d'expedition."""

    channel: NotificationChannel
    recipient: str
    recipient_name: str
    subject: str
    body: str


@dataclass(slots=True)
class FakeNotificationSender(NotificationSender):
    """Expediteur qui retient ce qu'on lui confie, sur le canal qu'on lui donne.

    LA DOUBLURE QUE LA CARTE NOMME. Deux usages : verifier qu'un message est parti
    par le bon canal, et -- avec `fails=True` -- verifier qu'un canal en panne
    n'empeche pas les autres de remettre.
    """

    sender_channel: NotificationChannel = NotificationChannel.EMAIL
    fails: bool = False
    sent: list[SentNotification] = field(default_factory=list)

    @property
    def channel(self) -> NotificationChannel:
        """Le canal desservi par cette doublure."""
        return self.sender_channel

    async def send(self, *, recipient: str, recipient_name: str, subject: str, body: str) -> None:
        """Retient l'envoi au lieu de le faire -- ou echoue, si on le lui a demande.

        L'ECHEC EST ENREGISTRE AVANT D'ETRE LEVE : un test doit pouvoir verifier
        que la tentative a bien eu lieu sur ce canal-la, et pas seulement qu'elle
        a echoue.
        """
        self.sent.append(
            SentNotification(
                channel=self.sender_channel,
                recipient=recipient,
                recipient_name=recipient_name,
                subject=subject,
                body=body,
            )
        )
        if self.fails:
            raise NotificationDeliveryError(f"Panne simulee du canal {self.sender_channel.value}.")

    @property
    def last(self) -> SentNotification:
        """Le dernier message confie.

        Raises:
            AssertionError: si rien n'est parti -- le test se trompe de cible.
        """
        assert self.sent, f"Aucun message n'est parti par le canal {self.sender_channel.value}."
        return self.sent[-1]


@dataclass(slots=True)
class SentEmail:
    """Un courriel observe par la doublure de transport."""

    recipient: str
    recipient_name: str
    subject: str
    body: str


@dataclass(slots=True)
class FakeEmailTransport(EmailTransport):
    """Transport de courriel qui retient les messages au lieu de les expedier.

    Doublure du port TECHNIQUE de `shared/` -- celui que partagent l'adaptateur de
    canal de notifications et l'expediteur d'OTP d'identity (ADR-0022). Elle sert
    a eprouver l'adaptateur de canal sans serveur SMTP.
    """

    fails: bool = False
    sent: list[SentEmail] = field(default_factory=list)

    async def send(self, *, recipient: str, recipient_name: str, subject: str, body: str) -> None:
        """Retient le message au lieu de l'expedier -- ou echoue, sur demande."""
        if self.fails:
            raise EmailDeliveryError("Panne simulee du transport de courriel.")
        self.sent.append(
            SentEmail(
                recipient=recipient,
                recipient_name=recipient_name,
                subject=subject,
                body=body,
            )
        )
