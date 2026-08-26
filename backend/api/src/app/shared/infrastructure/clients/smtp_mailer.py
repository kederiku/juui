"""Adaptateur SMTP du port `EmailTransport` (BACK-22, repris de BACK-17).

CE CODE VIENT D'`identity`, ET C'EST LE TICKET QUI LE DEMENAGE
BACK-17 l'avait ecrit dans `identity/infrastructure/clients/smtp_otp_sender.py`,
en declarant en toutes lettres qu'il appartenait a BACK-22 : « a reprendre, le
dialogue SMTP lui-meme, qui n'a rien a faire dans identity ». Il atterrit ici
plutot que dans `notifications` parce que ses DEUX consommateurs ne peuvent pas
se connaitre -- le motif est celui du port (ADR-0022).

INFRA-07 GARDE SA FRONTIERE : le service Mailpit, les six variables et la sonde
de sante lui appartiennent ; ce fichier ne fait que les lire.

`smtplib` DANS UN THREAD, ET NON UN CLIENT ASYNCHRONE
La bibliotheque standard suffit et n'ajoute aucune dependance -- ni ligne de plus
dans la liste des paquets interdits au domaine. Son API est bloquante, d'ou
`asyncio.to_thread` : le worker traite d'autres taches pendant la poignee de main
TLS, qui se compte en centaines de millisecondes chez un vrai fournisseur.
Appeler `smtplib` directement dans une coroutine figerait la boucle d'evenements
du processus entier -- l'erreur classique, invisible sur Mailpit qui repond en
une milliseconde, et cuisante en production.

AUCUN CHANGEMENT DE CODE POUR PASSER EN PRODUCTION, c'est la promesse d'INFRA-07
et le critere de BACK-22 : hote, port, identifiants et TLS viennent tous de
`SmtpSettings`. Pointer `SMTP_HOST` sur un fournisseur reel, renseigner
l'utilisateur et le mot de passe, activer `SMTP_USE_TLS` -- rien d'autre.
"""

import asyncio
import logging
import smtplib
from email.headerregistry import Address
from email.message import EmailMessage
from typing import Final

from app.core import Settings, SmtpSettings
from app.shared.domain.ports.email import EmailDeliveryError, EmailTransport

_LOGGER: Final = logging.getLogger(__name__)

# Delai d'etablissement et de dialogue. Trente secondes : un envoi de courriel
# vit dans une tache de fond, il a le droit d'etre lent -- mais pas de bloquer un
# thread pour toujours si le serveur accepte la connexion sans jamais repondre.
_TIMEOUT_SECONDS: Final = 30.0


class SmtpEmailTransport(EmailTransport):
    """Remet le message par SMTP, en texte brut.

    SANS ETAT ET SANS CONNEXION PERSISTANTE : une session SMTP par message, ouverte
    et refermee dans le thread. C'est le choix le plus simple, et il convient a la
    cadence attendue -- quelques messages par inscription, des quotas de renvoi qui
    bornent le reste, et des rappels de rendez-vous etales dans la journee. Un pool
    de sessions se poserait a une tout autre echelle, et rien ici n'y engage.

    Corollaire utile : ce transport n'a rien a ouvrir au demarrage ni a refermer a
    l'arret, contrairement au cache, au stockage objet et au magasin d'OTP. Ni le
    `lifespan` de l'API ni le demarrage du worker n'ont a le connaitre.
    """

    def __init__(self, *, settings: SmtpSettings) -> None:
        """Assemble l'adaptateur autour de la section SMTP de la configuration.

        Args:
            settings: hote, port, identifiants, TLS et adresse d'expedition.
        """
        self._settings = settings

    async def send(self, *, recipient: str, recipient_name: str, subject: str, body: str) -> None:
        """Compose le message et le remet au serveur. Voir le port pour le contrat."""
        message = self._compose(
            recipient=recipient,
            recipient_name=recipient_name,
            subject=subject,
            body=body,
        )
        try:
            await asyncio.to_thread(self._deliver, message)
        except (OSError, smtplib.SMTPException) as error:
            # Le message d'erreur ne reprend NI le corps NI l'adresse : il finira
            # dans un journal, et un journal se recopie. Ce qui relie cette ligne a
            # son parcours est l'identifiant de requete (BACK-11) ; ce qui relie un
            # envoi a son destinataire est le journal d'envoi de `notifications`,
            # qui l'ecrit une fois, a sa place.
            _LOGGER.error(
                "Remise du courriel impossible via %s:%s : %s",
                self._settings.host,
                self._settings.port,
                error,
            )
            message_text = "La remise du courriel a echoue."
            raise EmailDeliveryError(message_text) from error

        _LOGGER.info(
            "Courriel remis au serveur de messagerie.",
            extra={"smtp_host": self._settings.host},
        )

    def _compose(
        self, *, recipient: str, recipient_name: str, subject: str, body: str
    ) -> EmailMessage:
        """Fabrique le message a expedier.

        Args:
            recipient: l'adresse du destinataire.
            recipient_name: son nom affiche, eventuellement vide.
            subject: l'objet.
            body: le corps en texte brut.

        Returns:
            Le message pret a expedier.
        """
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self._settings.mail_from
        # `Address` compose « Nom <adresse> » en encodant ce qu'il faut : un nom
        # portant une virgule casserait un en-tete assemble a la main, et
        # produirait deux destinataires dont l'un n'existe pas.
        local, _, domain = recipient.partition("@")
        message["To"] = str(Address(display_name=recipient_name, username=local, domain=domain))
        # `Auto-Submitted` : la RFC 3834 le prevoit pour qu'un repondeur
        # automatique ne reponde pas a un message automatique. Sans lui, une
        # reponse d'absence revient sur la boite d'expedition a chaque envoi.
        message["Auto-Submitted"] = "auto-generated"
        message.set_content(body)
        return message

    def _deliver(self, message: EmailMessage) -> None:
        """Ouvre une session SMTP, expedie, referme.

        BLOQUANTE A DESSEIN : appelee depuis `asyncio.to_thread`, jamais depuis
        une coroutine.

        STARTTLS et non SMTPS : `SMTP_USE_TLS` fait passer la session en clair au
        chiffrement apres le `EHLO`, ce que pratiquent les fournisseurs sur le
        port 587. Mailpit ne presente aucun certificat, d'ou le `false` local --
        une negociation contre lui echouerait.

        Args:
            message: le message a expedier.

        Raises:
            OSError: si la connexion echoue.
            smtplib.SMTPException: si le dialogue echoue.
        """
        with smtplib.SMTP(
            host=self._settings.host,
            port=self._settings.port,
            timeout=_TIMEOUT_SECONDS,
        ) as client:
            if self._settings.use_tls:
                client.starttls()
                # Second `EHLO` implicite : `starttls()` s'en charge. La liste des
                # extensions annoncees change apres le chiffrement, l'authentification
                # qui suit doit donc voir la nouvelle.
            if self._settings.requires_authentication:
                password = (
                    ""
                    if self._settings.password is None
                    else self._settings.password.get_secret_value()
                )
                client.login(self._settings.user, password)
            client.send_message(message)


def build_email_transport(settings: Settings) -> SmtpEmailTransport:
    """Construit le transport, sans ouvrir la moindre connexion.

    Comme `build_cache` et `build_file_storage` : construire ne connecte pas. Ici
    c'est litteral -- la session SMTP nait et meurt avec chaque message.

    Args:
        settings: la configuration du service, dont la section SMTP.

    Returns:
        Le transport, pret a servir les adaptateurs qui composent des messages.
    """
    return SmtpEmailTransport(settings=settings.smtp)
