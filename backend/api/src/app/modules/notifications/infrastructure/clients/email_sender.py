"""Adaptateur du canal courriel (BACK-22).

LE SEUL CANAL QUI REMET VRAIMENT A CE STADE, et il ne parle pourtant pas SMTP :
le dialogue vit dans `shared/infrastructure/clients/smtp_mailer.py`, derriere le
port technique `EmailTransport`. Ce fichier fait la seule chose qui appartienne
au module -- adapter le vocabulaire des notifications a celui d'un transport.

POURQUOI LE DIALOGUE N'EST PAS ICI, ALORS QUE LA CARTE L'Y PLACE
Parce qu'`identity` en a besoin pour son code de verification (BACK-17) et n'a
pas le droit d'importer ce module (contrat `module-independence`). Laisser le
SMTP ici imposerait d'en ecrire une seconde copie la-bas, ou de percer le
contrat. L'argumentaire complet est l'ADR-0022 ; ce qui compte pour ce fichier,
c'est qu'auth et TLS restent pilotes par `SmtpSettings`, sans changement de code
entre Mailpit et un fournisseur reel.
"""

from app.core import Settings
from app.modules.notifications.domain.policies import NotificationChannel
from app.modules.notifications.domain.ports import NotificationDeliveryError, NotificationSender
from app.shared.domain.ports.email import EmailDeliveryError, EmailTransport
from app.shared.infrastructure.clients.smtp_mailer import build_email_transport


class EmailNotificationSender(NotificationSender):
    """Remet la notification par courriel.

    SANS ETAT, comme le transport qu'il enveloppe : une session SMTP nait et meurt
    avec chaque message. Rien a ouvrir au demarrage du worker, rien a refermer a
    son arret.
    """

    def __init__(self, *, transport: EmailTransport) -> None:
        """Assemble l'adaptateur autour du transport de courriel.

        Args:
            transport: le port de remise, injecte -- jamais construit ici. C'est
                ce qui permet a un test de retenir le message au lieu de
                l'expedier, sans serveur SMTP.
        """
        self._transport = transport

    @property
    def channel(self) -> NotificationChannel:
        """Le canal desservi : le courriel."""
        return NotificationChannel.EMAIL

    async def send(self, *, recipient: str, recipient_name: str, subject: str, body: str) -> None:
        """Remet le message. Voir le port pour le contrat."""
        try:
            await self._transport.send(
                recipient=recipient,
                recipient_name=recipient_name,
                subject=subject,
                body=body,
            )
        except EmailDeliveryError as error:
            # Retraduit dans le vocabulaire du module : c'est
            # `NotificationDeliveryError` que le port annonce, et c'est elle que
            # le cas d'usage attrape pour journaliser l'echec de CE canal sans
            # priver les autres. Le message ne reprend ni l'adresse ni le corps --
            # le journal d'envoi les porte deja, une seule fois, a sa place.
            message = "La remise de la notification par courriel a echoue."
            raise NotificationDeliveryError(message) from error


def build_email_notification_sender(settings: Settings) -> EmailNotificationSender:
    """Construit l'adaptateur courriel, sans ouvrir la moindre connexion.

    Args:
        settings: la configuration du service, dont la section SMTP.

    Returns:
        L'adaptateur, pret a servir la tache de remise.
    """
    return EmailNotificationSender(transport=build_email_transport(settings))
