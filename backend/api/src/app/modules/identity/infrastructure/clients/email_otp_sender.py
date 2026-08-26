"""Remise du code de verification par courriel (BACK-17, transport repris par BACK-22).

CE QUI A CHANGE ICI, ET CE QUI N'A PAS BOUGE
BACK-17 avait ecrit ce fichier avec son propre dialogue SMTP, en declarant qu'il
appartenait a BACK-22. Le dialogue est parti : il vit desormais dans
`shared/infrastructure/clients/smtp_mailer.py`, derriere le port `EmailTransport`
(ADR-0022). Ce qui reste ici est ce qui appartient VRAIMENT a identity -- la
composition du message de verification --, et le port `OtpSender` n'a pas bouge
d'une ligne, comme BACK-17 l'avait promis.

POURQUOI L'OTP NE PASSE PAS PAR LE MODULE `notifications`
La carte de BACK-17 annoncait « via le port d'envoi de BACK-22 des qu'il
existe » ; le rebranchement s'arrete au transport, et ce n'est pas un
renoncement. Le module `notifications` recoit un evenement PAR LA FILE, ou tout
argument voyage en clair dans un stream sans TTL : y faire passer un code de
verification deposerait le secret a cote de son propre condense (ADR-0020).
Le code est donc engendre dans le worker et remis depuis le worker, sans
traverser quoi que ce soit.

Deux consequences a garder en tete : un OTP est TRANSACTIONNEL -- il part quelles
que soient les preferences de notification, et ce fichier n'en consulte aucune --,
et le journal d'envoi de `notifications` ne le voit pas passer.
"""

import logging
from typing import Final

from app.core import Settings
from app.modules.identity.domain.ports import OtpDeliveryError, OtpSender
from app.shared.domain.ports.email import EmailDeliveryError, EmailTransport
from app.shared.infrastructure.clients.smtp_mailer import build_email_transport

_LOGGER: Final = logging.getLogger(__name__)


class EmailOtpSender(OtpSender):
    """Compose le message de verification et le confie au transport.

    SANS ETAT : le transport n'en a pas davantage, et le message se fabrique a
    chaque appel. Rien a ouvrir, rien a refermer.
    """

    def __init__(self, *, transport: EmailTransport) -> None:
        """Assemble l'expediteur autour du transport de courriel.

        Args:
            transport: le port de remise, injecte -- jamais construit ici. C'est
                ce qui permet a un test de retenir le message au lieu de
                l'expedier, sans serveur SMTP.
        """
        self._transport = transport

    async def send_verification_code(
        self, *, recipient: str, recipient_name: str, code: str, ttl_seconds: int
    ) -> None:
        """Compose le message et le remet. Voir le port pour le contrat."""
        minutes = max(1, round(ttl_seconds / 60))
        try:
            await self._transport.send(
                recipient=recipient,
                recipient_name=recipient_name,
                # LE CODE FIGURE DANS L'OBJET ET DANS LE CORPS. Dans l'objet
                # parce que les applications de messagerie mobiles l'affichent en
                # notification, ce qui evite d'ouvrir le message ; dans le corps
                # parce que l'objet, lui, se perd des qu'on fait defiler.
                subject=f"{code} est votre code de verification Juui",
                body=(
                    f"Bonjour {recipient_name},\n\n"
                    f"Votre code de verification est : {code}\n\n"
                    f"Il est valable {minutes} minutes et ne peut servir qu'une fois.\n\n"
                    "Si vous n'etes pas a l'origine de cette demande, ignorez ce message : "
                    "votre compte reste inchange.\n\n"
                    "L'equipe Juui\n"
                ),
            )
        except EmailDeliveryError as error:
            # Retraduit dans le vocabulaire du module : c'est `OtpDeliveryError`
            # que le port annonce, et c'est elle que la politique de reprise de
            # BACK-15 attend. Ni le code ni l'adresse ne rentrent dans le message.
            _LOGGER.error("Remise du code de verification impossible : %s", error)
            message = "La remise du code de verification a echoue."
            raise OtpDeliveryError(message) from error


def build_otp_sender(settings: Settings) -> EmailOtpSender:
    """Construit l'expediteur, sans ouvrir la moindre connexion.

    Le NOM ET LA SIGNATURE N'ONT PAS CHANGE malgre le demenagement du transport :
    c'est le seul point d'entree que connaissent la tache d'envoi et ses tests, et
    un rebranchement interne n'a pas a se voir de l'exterieur.

    Args:
        settings: la configuration du service, dont la section SMTP.

    Returns:
        L'expediteur, pret a servir la tache d'envoi.
    """
    return EmailOtpSender(transport=build_email_transport(settings))
