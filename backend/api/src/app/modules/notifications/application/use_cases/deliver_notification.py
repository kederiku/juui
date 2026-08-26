"""Remise d'un evenement de notification a un compte (BACK-22).

LE CAS D'USAGE QUI PORTE LES TROIS REGLES DU TICKET, ET IL TIENT EN UN GESTE
Lire les preferences du compte, en deduire les canaux, rendre le message, le
remettre, journaliser. Rien d'autre ne decide de rien : l'emetteur a emis un
EVENEMENT, et c'est ici -- une seule fois, pour tous les modules -- que le canal
se choisit (ADR-0021).

S'EXECUTE DANS LE WORKER, jamais dans le fil d'une requete : c'est le corps de la
tache `notifications.delivery.deliver`. L'appelant, lui, a mis en file par
`NotificationDispatcher` et a rendu la main aussitot.

IDEMPOTENCE, AU SENS OU BACK-15 L'EXIGE
La politique de reprise rejoue une tache en echec, et le stream represente un
message dont l'acquittement s'est perdu. Rejouee, cette remise renvoie le meme
message -- un doublon dans une boite, ce qui est le bon compromis : l'alternative
serait un registre d'envois consulte avant chaque remise, c'est-a-dire une table
et un verrou pour eviter un exemplaire en trop d'un rappel de rendez-vous. Ce qui
DOIT rester idempotent, c'est l'etat : ce cas d'usage n'en ecrit aucun.

UN CANAL EN ECHEC N'EMPORTE PAS LES AUTRES
Chaque remise est isolee. Si le SMS tombe et que le courriel passe, l'utilisateur
est prevenu -- ce qui est le but -- et la tache echoue quand meme pour que la
reprise ait lieu. Interrompre a la premiere erreur priverait l'utilisateur d'un
canal qui marchait.
"""

import logging
from collections.abc import Iterable, Mapping
from typing import Final

from app.modules.notifications.domain.entities import NotificationRequest
from app.modules.notifications.domain.policies import (
    NotificationChannel,
    RenderedMessage,
    render,
    resolve_channels,
)
from app.modules.notifications.domain.ports import (
    NotificationDeliveryError,
    NotificationSender,
    NotificationsUnitOfWork,
)

_LOGGER: Final = logging.getLogger(__name__)

# Les trois statuts que le journal d'envoi rapporte. Des constantes et non des
# litteraux recopies : ce sont elles qu'un tableau de bord filtrera, et une faute
# de frappe y creerait un quatrieme statut que personne ne chercherait.
_STATUS_SENT: Final = "sent"
_STATUS_FAILED: Final = "failed"
_STATUS_SKIPPED: Final = "skipped"


class DeliverNotification:
    """Applique les preferences d'un compte a un evenement, et remet le message.

    LES EXPEDITEURS SONT INDEXES PAR CANAL A L'ASSEMBLAGE, et c'est ce qui
    remplace la cascade de `if` que ce module existe pour eviter : ajouter un
    canal, c'est ajouter un adaptateur a la collection, sans toucher a ce fichier.
    """

    def __init__(
        self,
        *,
        uow: NotificationsUnitOfWork,
        senders: Iterable[NotificationSender],
    ) -> None:
        """Assemble le cas d'usage a partir de ses ports.

        Args:
            uow: l'unite de travail du module, pour relire les preferences.
            senders: les adaptateurs de canal disponibles, un par canal. Un canal
                sans adaptateur est traite comme un canal muet -- l'envoi est
                journalise `skipped` plutot que perdu en silence.
        """
        self._uow = uow
        self._senders: Mapping[NotificationChannel, NotificationSender] = {
            sender.channel: sender for sender in senders
        }

    async def execute(self, request: NotificationRequest) -> None:
        """Remet l'evenement demande sur les canaux que les preferences retiennent.

        Args:
            request: l'evenement, son destinataire et les variables de son
                gabarit.

        Raises:
            MissingNotificationPayloadError: si le gabarit exige une variable que
                l'emetteur n'a pas fournie -- defaut d'emetteur, la tache echoue
                franchement plutot que de remettre un message a trous.
            NotificationDeliveryError: si une remise a echoue. Levee APRES avoir
                tente tous les canaux retenus, pour qu'un canal en panne n'en
                prive pas un autre.
        """
        channels = await self._channels_for(request)

        # LE RENDU AVANT LE CONTROLE DES CANAUX, ET L'ORDRE EST DELIBERE. Un
        # gabarit auquel il manque une variable est un defaut d'EMETTEUR, pas une
        # affaire de destinataire : le rendre ici le fait echouer pour tout le
        # monde, tout de suite. Rendu apres le controle, il ne se manifesterait
        # que chez les comptes qui n'ont pas desactive l'evenement -- un defaut
        # intermittent, dependant des preferences de qui le declenche, et le pire
        # a diagnostiquer. Le prix est une tache qui echoue pour un message qui
        # ne serait de toute facon pas parti ; c'est le bon sens de l'echange.
        message = render(request.event, request.payload)

        if not channels:
            # Un ensemble vide n'est PAS une anomalie : c'est un compte qui a
            # desactive cet evenement, et le ticket demande que cela se voie.
            # Sans cette ligne, un « je n'ai rien recu » resterait indistinct
            # d'une panne de transport.
            self._log(request, channel=None, status=_STATUS_SKIPPED)
            return

        failures: list[str] = []
        for channel in sorted(channels):
            failures.extend(await self._deliver(request, channel=channel, message=message))

        if failures:
            message_text = (
                f"Remise incomplete de l'evenement « {request.event.value} » : "
                f"{', '.join(failures)}."
            )
            raise NotificationDeliveryError(message_text)

    async def _channels_for(self, request: NotificationRequest) -> frozenset[NotificationChannel]:
        """Rend les canaux retenus pour cet evenement et ce compte.

        LE COMPTE SANS PREFERENCES EST LE CAS NOMINAL, pas une erreur : personne
        ne seme de ligne a l'inscription, et `resolve_channels` sait repondre sans
        agregat -- « rien de configure » se dit `None`.

        Args:
            request: l'evenement a remettre.

        Returns:
            Les canaux retenus, eventuellement vides.
        """
        async with self._uow:
            preferences = await self._uow.preferences.find_for_account(request.account_id)

        if preferences is None:
            return resolve_channels(request.event, configured=None)
        return preferences.channels_for(request.event)

    async def _deliver(
        self,
        request: NotificationRequest,
        *,
        channel: NotificationChannel,
        message: RenderedMessage,
    ) -> list[str]:
        """Remet le message sur un canal, et journalise ce qui s'est passe.

        Args:
            request: l'evenement remis.
            channel: le canal a emprunter.
            message: le message deja rendu -- rendu UNE fois pour tous les canaux.

        Returns:
            La liste des motifs d'echec, vide si la remise a abouti.
        """
        sender = self._senders.get(channel)
        if sender is None:
            # Aucun adaptateur pour ce canal : la preference est valide, le
            # transport n'existe pas encore. Journalise plutot qu'ignore, et sans
            # lever -- rien n'est reparable par une reprise.
            self._log(request, channel=channel, status=_STATUS_SKIPPED)
            return []

        try:
            await sender.send(
                recipient=request.recipient,
                recipient_name=request.recipient_name,
                subject=message.subject,
                body=message.body,
            )
        except NotificationDeliveryError as error:
            self._log(request, channel=channel, status=_STATUS_FAILED, detail=str(error))
            return [channel.value]

        self._log(request, channel=channel, status=_STATUS_SENT)
        return []

    def _log(
        self,
        request: NotificationRequest,
        *,
        channel: NotificationChannel | None,
        status: str,
        detail: str | None = None,
    ) -> None:
        """Ecrit la ligne de journal d'envoi : destinataire, canal, evenement, statut.

        LE CRITERE 5 DU TICKET, ET LE SEUL ENDROIT OU IL S'ECRIT. « Un je n'ai
        rien recu doit etre diagnosticable » : sans ces quatre champs, la seule
        reponse possible serait de relire les journaux du serveur de messagerie,
        qui ne sait rien des preferences et donc rien de la difference entre un
        message refuse et un message que le compte avait desactive.

        LE DESTINATAIRE Y FIGURE, ET C'EST UN RENVERSEMENT ASSUME. L'adaptateur
        SMTP de BACK-17 l'excluait de ses journaux, a juste titre : sa ligne
        accompagnait un SECRET, et un journal se recopie. Ici, l'adresse EST
        l'objet du diagnostic, et le message rendu n'y figure pas. Elle n'est donc
        pas dans la liste de masquage de BACK-11 -- si une revue de confidentialite
        en decide autrement, c'est la qu'elle s'ajoutera, en un seul endroit.

        En `extra=` et non dans le texte : les champs sortent en cles du JSON de
        production (BACK-11) et se filtrent, la ou une phrase se cherche au
        `grep`.

        LES CLES NON POSEES SONT ABSENTES, jamais nulles -- la doctrine du
        `JsonFormatter`, qu'un `extra` peut enfreindre sans qu'il s'en apercoive :
        il rendrait `"notification_detail": null` sur chaque ligne d'un worker,
        c'est-a-dire du volume paye pour rien.

        Args:
            request: l'evenement remis.
            channel: le canal emprunte, ou None quand aucun ne l'a ete.
            status: `sent`, `failed` ou `skipped`.
            detail: le motif d'echec, quand il y en a un.
        """
        fields: dict[str, object] = {
            "notification_event": request.event.value,
            "notification_status": status,
            "recipient": request.recipient,
            "account_id": request.account_id,
        }
        if channel is not None:
            fields["notification_channel"] = channel.value
        if detail is not None:
            fields["notification_detail"] = detail

        _LOGGER.info(
            "Notification %s : %s vers %s.",
            status,
            request.event.value,
            request.recipient,
            extra=fields,
        )
