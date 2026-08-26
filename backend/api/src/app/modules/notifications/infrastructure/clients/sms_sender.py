"""Adaptateur du canal SMS -- structure en place, aucune remise (BACK-22).

CE FICHIER N'ENVOIE RIEN, ET C'EST LA PORTEE DU TICKET QUI LE VEUT : « pas de
fournisseur SMS ni push reel a ce stade [...] les autres canaux en implementation
vide et journalisee, pour que la structure existe sans engager de cout ». Un
contrat SMS se signe, se paie et se resilie ; le souscrire pour un socle serait
une depense avant tout usage.

IL JOURNALISE PLUTOT QUE DE SE TAIRE, et c'est tout ce qui le separe d'une classe
vide. Un compte qui a choisi le SMS pour ses rappels doit laisser une trace
lisible -- « voila ce qui serait parti, et par ou » -- au lieu d'un silence que
l'exploitant lirait comme une panne du transport.

CE QUE CHANGERA LE JOUR OU UN FOURNISSEUR EXISTERA : ce fichier, et rien d'autre.
Le port ne bouge pas, le cas d'usage ne bouge pas, les preferences deja
enregistrees prennent effet le jour du deploiement. C'est precisement ce que la
structure achete.

`recipient` RESTE UNE ADRESSE E-MAIL A CE STADE, et il faut le savoir avant de
brancher un fournisseur : le module ne detient aucun numero de telephone -- il
vit chez identity, et l'emetteur ne transmet aujourd'hui qu'une adresse. Le vrai
branchement demandera donc que la demande porte la coordonnee du CANAL, pas une
coordonnee unique. C'est une extension de `NotificationRequest`, notee ici pour
qu'elle ne se decouvre pas le jour de la mise en service.
"""

import logging
from typing import Final

from app.modules.notifications.domain.policies import NotificationChannel
from app.modules.notifications.domain.ports import NotificationSender

_LOGGER: Final = logging.getLogger(__name__)


class LoggingSmsSender(NotificationSender):
    """Journalise ce qui serait parti par SMS, et ne l'envoie pas."""

    @property
    def channel(self) -> NotificationChannel:
        """Le canal desservi : le SMS."""
        return NotificationChannel.SMS

    async def send(self, *, recipient: str, recipient_name: str, subject: str, body: str) -> None:
        """Journalise la remise au lieu de l'effectuer.

        NE LEVE JAMAIS : l'absence de fournisseur n'est pas une panne de
        transport, et la faire remonter declencherait la politique de reprise de
        BACK-15 sur une tache qui ne reussira jamais -- des reessais jusqu'a la
        file de rejets, a chaque notification, pour un canal dont on sait qu'il
        est muet. Le cas d'usage, lui, journalise `sent` : du point de vue du
        module, le canal a fait ce qu'il sait faire.

        Le corps du message N'EST PAS journalise : il n'ajoute rien au diagnostic
        et grossirait chaque ligne. L'objet suffit a reconnaitre le message.
        """
        _LOGGER.info(
            "Canal SMS non branche : aucun message envoye a %s.",
            recipient,
            extra={
                "notification_channel": self.channel.value,
                "recipient": recipient,
                "notification_subject": subject,
            },
        )
