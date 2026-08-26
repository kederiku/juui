"""Remise du code de verification par SMTP -- adaptateur PROVISOIRE (BACK-17).

CE FICHIER APPARTIENT A BACK-22, ET IL EST ICI QUAND MEME
La frontiere posee par INFRA-07 est nette : le service Mailpit, ses variables et
sa sonde relevent de l'infrastructure ; le code SMTP appartient a BACK-22, avec
le module `notifications` et son port d'envoi unique. BACK-17 en ecrit malgre
tout le minimum vital, et sa propre carte l'y autorise en toutes lettres --
« implementation d'`OtpSender` : via le port d'envoi de BACK-22 des qu'il
existe ; a defaut, directement l'adaptateur SMTP, a rebrancher ensuite ». La
raison est simple : un code qui ne part pas ne verifie rien, et le critere
d'acceptation du ticket exige un parcours de bout en bout jusqu'a Mailpit.

CE QUE BACK-22 DEVRA REPRENDRE, ET CE QU'IL POURRA LAISSER
A reprendre : le dialogue SMTP lui-meme, qui n'a rien a faire dans `identity`.
A laisser : le port `OtpSender` et son contrat -- une implementation qui delegue
au `NotificationSender` s'y substituera sans qu'une ligne de metier bouge. Et une
regle a ne pas perdre en chemin : un OTP est TRANSACTIONNEL, il part quelles que
soient les preferences de notification.

`smtplib` DANS UN THREAD, ET NON UN CLIENT ASYNCHRONE
La bibliotheque standard suffit et n'ajoute aucune dependance a un adaptateur
voue au remplacement. Son API est bloquante, d'ou `asyncio.to_thread` : le
worker traite d'autres taches pendant la poignee de main TLS, qui se compte en
centaines de millisecondes chez un vrai fournisseur. Appeler `smtplib`
directement dans une coroutine figerait la boucle d'evenements du processus
entier -- l'erreur classique, invisible sur Mailpit qui repond en une
milliseconde, et cuisante en production.
"""

import asyncio
import logging
import smtplib
from email.headerregistry import Address
from email.message import EmailMessage
from typing import Final

from app.core import Settings, SmtpSettings
from app.modules.identity.domain.ports import OtpDeliveryError, OtpSender

_LOGGER: Final = logging.getLogger(__name__)

# Delai d'etablissement et de dialogue. Trente secondes : un envoi de courriel
# vit dans une tache de fond, il a le droit d'etre lent -- mais pas de bloquer un
# thread pour toujours si le serveur accepte la connexion sans jamais repondre.
_TIMEOUT_SECONDS: Final = 30.0


class SmtpOtpSender(OtpSender):
    """Envoie le code par courriel, en clair et en texte brut.

    SANS ETAT ET SANS CONNEXION PERSISTANTE : une session SMTP par message, ouverte
    et refermee dans le thread. C'est le choix le plus simple, et il convient a la
    cadence attendue -- quelques messages par inscription, et des quotas de renvoi
    qui bornent le reste. Un pool de sessions serait le sujet de BACK-22, s'il se
    posait un jour.
    """

    def __init__(self, *, settings: SmtpSettings) -> None:
        """Assemble l'adaptateur autour de la section SMTP de la configuration.

        Args:
            settings: hote, port, identifiants, TLS et adresse d'expedition.
        """
        self._settings = settings

    async def send_verification_code(
        self, *, recipient: str, recipient_name: str, code: str, ttl_seconds: int
    ) -> None:
        """Compose le message et le remet au serveur. Voir le port pour le contrat."""
        message = self._compose(
            recipient=recipient,
            recipient_name=recipient_name,
            code=code,
            ttl_seconds=ttl_seconds,
        )
        try:
            await asyncio.to_thread(self._deliver, message)
        except (OSError, smtplib.SMTPException) as error:
            # Le message d'erreur ne reprend NI le code NI l'adresse : il finira
            # dans un journal, et un journal se recopie. L'identifiant de requete
            # (BACK-11) suffit a relier cette ligne a son parcours.
            _LOGGER.error(
                "Remise du code de verification impossible via %s:%s : %s",
                self._settings.host,
                self._settings.port,
                error,
            )
            message_text = "La remise du code de verification a echoue."
            raise OtpDeliveryError(message_text) from error

        _LOGGER.info(
            "Code de verification remis au serveur de messagerie.",
            extra={"smtp_host": self._settings.host},
        )

    def _compose(
        self, *, recipient: str, recipient_name: str, code: str, ttl_seconds: int
    ) -> EmailMessage:
        """Fabrique le message a expedier.

        TEXTE BRUT ET RIEN D'AUTRE. Pas de HTML : un message de verification n'a
        rien a mettre en page, il porte six chiffres. Le HTML ajouterait une
        surface (images distantes, styles, clients qui les bloquent) pour une
        lisibilite qui n'en a pas besoin, et BACK-22 tranchera pour de bon quand
        il apportera de vrais gabarits.

        LE CODE FIGURE DANS LE CORPS ET DANS L'OBJET. Dans l'objet parce que les
        applications de messagerie mobiles l'affichent en notification, ce qui
        evite d'ouvrir le message ; dans le corps parce que l'objet, lui, se perd
        des qu'on fait defiler.

        Args:
            recipient: l'adresse du destinataire.
            recipient_name: son nom affiche.
            code: les six chiffres.
            ttl_seconds: la duree de validite, annoncee dans le corps.

        Returns:
            Le message pret a expedier.
        """
        minutes = max(1, round(ttl_seconds / 60))
        message = EmailMessage()
        message["Subject"] = f"{code} est votre code de verification Juui"
        message["From"] = self._settings.mail_from
        # `Address` compose « Nom <adresse> » en encodant ce qu'il faut : un nom
        # portant une virgule casserait un en-tete assemble a la main, et
        # produirait deux destinataires dont l'un n'existe pas.
        local, _, domain = recipient.partition("@")
        message["To"] = str(Address(display_name=recipient_name, username=local, domain=domain))
        # `Auto-Submitted` : la RFC 3834 le prevoit pour qu'un repondeur
        # automatique ne reponde pas a un message automatique. Sans lui, une
        # reponse d'absence revient sur la boite d'expedition a chaque
        # inscription.
        message["Auto-Submitted"] = "auto-generated"
        message.set_content(
            f"Bonjour {recipient_name},\n\n"
            f"Votre code de verification est : {code}\n\n"
            f"Il est valable {minutes} minutes et ne peut servir qu'une fois.\n\n"
            "Si vous n'etes pas a l'origine de cette demande, ignorez ce message : "
            "votre compte reste inchange.\n\n"
            "L'equipe Juui\n"
        )
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


def build_otp_sender(settings: Settings) -> SmtpOtpSender:
    """Construit l'expediteur, sans ouvrir la moindre connexion.

    Comme `build_cache` et `build_otp_store` : construire ne connecte pas. Ici
    c'est litteral -- la session SMTP nait et meurt avec chaque message.

    Args:
        settings: la configuration du service, dont la section SMTP.

    Returns:
        L'expediteur, pret a servir la tache d'envoi.
    """
    return SmtpOtpSender(settings=settings.smtp)
