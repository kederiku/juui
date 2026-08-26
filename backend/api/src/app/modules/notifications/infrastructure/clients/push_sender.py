"""Adaptateur du canal push -- structure en place, aucune remise (BACK-22).

MEME PORTEE ET MEME MOTIF QUE `sms_sender.py` : « pas de fournisseur SMS ni push
reel a ce stade [...] les autres canaux en implementation vide et journalisee,
pour que la structure existe sans engager de cout ». Le push demande davantage
qu'un contrat -- une application mobile publiee, des cles de service chez deux
fournisseurs, et un jeton d'appareil par installation. Rien de tout cela n'existe.

IL JOURNALISE PLUTOT QUE DE SE TAIRE : un compte qui aurait choisi le push doit
laisser une trace lisible, au lieu d'un silence que l'exploitant lirait comme une
panne.

CE QU'IL MANQUERA LE JOUR OU LE PUSH REMETTRA VRAIMENT, et qui ne se decouvre pas
en lisant le port : une notification push ne s'adresse pas a une personne mais a
un APPAREIL. Il faudra donc un registre de jetons par compte -- plusieurs
appareils, des jetons qui se periment, un desabonnement quand l'application est
desinstallee --, c'est-a-dire une table et un cycle de vie que ce socle n'a pas.
`recipient` porte une adresse e-mail a ce stade ; le branchement reel demandera
que la demande porte la coordonnee du CANAL, ce qui est une extension de
`NotificationRequest` et non de ce fichier.
"""

import logging
from typing import Final

from app.modules.notifications.domain.policies import NotificationChannel
from app.modules.notifications.domain.ports import NotificationSender

_LOGGER: Final = logging.getLogger(__name__)


class LoggingPushSender(NotificationSender):
    """Journalise ce qui serait parti en notification push, et ne l'envoie pas."""

    @property
    def channel(self) -> NotificationChannel:
        """Le canal desservi : la notification push."""
        return NotificationChannel.PUSH

    async def send(self, *, recipient: str, recipient_name: str, subject: str, body: str) -> None:
        """Journalise la remise au lieu de l'effectuer.

        NE LEVE JAMAIS, pour la meme raison que le canal SMS : l'absence de
        fournisseur n'est pas une panne de transport, et la faire remonter
        declencherait la politique de reprise de BACK-15 sur une tache qui ne
        reussira jamais -- des reessais jusqu'a la file de rejets, a chaque
        notification.

        Le corps du message n'est pas journalise : l'objet suffit a reconnaitre le
        message, et c'est d'ailleurs lui qu'une notification push afficherait.
        """
        _LOGGER.info(
            "Canal push non branche : aucune notification envoyee a %s.",
            recipient,
            extra={
                "notification_channel": self.channel.value,
                "recipient": recipient,
                "notification_subject": subject,
            },
        )
