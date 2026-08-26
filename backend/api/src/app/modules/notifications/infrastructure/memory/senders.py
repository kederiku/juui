"""Doublure du port d'envoi de notifications (BACK-06c, reprise de BACK-22).

`FakeNotificationSender` est nomme par la carte du ticket, et il n'est pas
decoratif : sans lui, verifier « le module appelant emet un evenement,
notifications choisit le canal » demanderait un serveur SMTP pour un test qui ne
parle pas de SMTP.

CE N'EST PAS LA DOUBLURE DU TRANSPORT. `NotificationSender` porte un CANAL et un
message deja rendu ; `EmailTransport` porte un courriel. Le second est un port
technique de `shared/` (ADR-0022) et sa doublure vit la-bas. Les confondre
reviendrait a faire croire qu'un canal SMS passe par SMTP.

PAS DE DOUBLURE DE `NotificationDispatcher` ICI, et c'est le meme arbitrage que
pour `organization` et `medical_records` : aucun consommateur ne l'emploie
encore. Le jour ou BACK-23 emettra un evenement, elle s'ecrira en vingt lignes
sur le modele de `RecordingOtpDispatcher` -- avec une precaution a ne pas
oublier : COPIER le `payload`, qui voyagerait sur la file, donc fige a
l'emission.
"""

from dataclasses import dataclass, field

from app.modules.notifications.domain.policies import NotificationChannel
from app.modules.notifications.domain.ports import (
    NotificationDeliveryError,
    NotificationSender,
)


@dataclass(slots=True)
class SentNotification:
    """Un envoi observe par une doublure d'expedition.

    Attributes:
        channel: le canal emprunte.
        recipient: la coordonnee du destinataire sur ce canal.
        recipient_name: le nom affiche.
        subject: l'objet du message.
        body: le corps, en texte brut.
    """

    channel: NotificationChannel
    recipient: str
    recipient_name: str
    subject: str
    body: str


@dataclass(slots=True)
class FakeNotificationSender(NotificationSender):
    """Expediteur qui retient ce qu'on lui confie, sur le canal qu'on lui donne.

    Deux usages : verifier qu'un message est parti par le bon canal, et -- avec
    `fails=True` -- verifier qu'un canal en panne n'empeche pas les autres de
    remettre.

    Attributes:
        sender_channel: le canal que cette doublure dessert.
        fails: si vrai, la remise leve apres avoir ete enregistree.
        sent: les remises tentees, dans l'ordre.
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

        L'ECHEC EST ENREGISTRE AVANT D'ETRE LEVE, a rebours de
        `FakeEmailTransport` qui ne retient rien : un test doit pouvoir verifier
        que la TENTATIVE a bien eu lieu sur ce canal-la, et pas seulement qu'elle
        a echoue -- c'est ce qui prouve que le cas d'usage a bien essaye tous les
        canaux retenus par les preferences.

        Args:
            recipient: la coordonnee du destinataire sur ce canal.
            recipient_name: le nom affiche.
            subject: l'objet du message.
            body: le corps, en texte brut.

        Raises:
            NotificationDeliveryError: si l'echec est simule.
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

        Returns:
            La derniere remise tentee.

        Raises:
            AssertionError: si rien n'est parti -- le test se trompe de cible.
        """
        if not self.sent:
            message = f"Aucun message n'est parti par le canal {self.sender_channel.value}."
            raise AssertionError(message)
        return self.sent[-1]
