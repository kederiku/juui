"""Un adaptateur par canal : l'e-mail remet, les deux autres journalisent (BACK-22).

Critere 4 du ticket -- « adaptateur e-mail reel avec auth/TLS configurables ;
autres canaux vides et journalises ». La moitie « auth/TLS » se prouve sur le
transport partage, dans `tests/shared/test_smtp_mailer.py` : c'est lui qui parle
SMTP. Ce fichier prouve l'autre moitie -- que le canal e-mail remet reellement au
transport, et que les deux canaux muets laissent une trace au lieu d'un silence.

POURQUOI LE SILENCE SERAIT LE VRAI DEFAUT
Un compte qui a choisi le SMS pour ses rappels doit laisser une trace lisible.
Sans elle, l'exploitant qui cherche pourquoi personne n'a rien recu ne peut pas
distinguer « aucun fournisseur branche » d'une panne du transport.
"""

import logging

import pytest

from app.modules.notifications.domain.policies import NotificationChannel
from app.modules.notifications.domain.ports import NotificationDeliveryError
from app.modules.notifications.infrastructure.clients.email_sender import (
    EmailNotificationSender,
)
from app.modules.notifications.infrastructure.clients.push_sender import LoggingPushSender
from app.modules.notifications.infrastructure.clients.sms_sender import LoggingSmsSender
from app.shared.infrastructure.memory.email import FakeEmailTransport

pytestmark = pytest.mark.notifications

_MESSAGE = {
    "recipient": "jean@exemple.fr",
    "recipient_name": "Jean Veto",
    "subject": "Rappel : rendez-vous le 12 septembre",
    "body": "Bonjour Jean Veto,\n\nPetit rappel.\n",
}


async def test_the_email_adapter_hands_the_message_to_the_shared_transport() -> None:
    """Le canal e-mail ne parle pas SMTP : il adapte, et delegue (ADR-0022)."""
    transport = FakeEmailTransport()
    sender = EmailNotificationSender(transport=transport)

    assert sender.channel is NotificationChannel.EMAIL

    await sender.send(**_MESSAGE)

    assert len(transport.sent) == 1
    delivered = transport.sent[0]
    assert delivered.recipient == _MESSAGE["recipient"]
    assert delivered.subject == _MESSAGE["subject"]
    assert delivered.body == _MESSAGE["body"]


async def test_a_transport_failure_is_retranslated_into_the_module_vocabulary() -> None:
    """`EmailDeliveryError` devient `NotificationDeliveryError` : c'est ce que le port annonce.

    Sans cette traduction, le cas d'usage laisserait passer une exception qu'il ne
    rattrape pas, et un canal en panne emporterait les autres.
    """
    sender = EmailNotificationSender(transport=FakeEmailTransport(fails=True))

    with pytest.raises(NotificationDeliveryError):
        await sender.send(**_MESSAGE)


@pytest.mark.parametrize(
    ("sender", "channel"),
    [
        (LoggingSmsSender(), NotificationChannel.SMS),
        (LoggingPushSender(), NotificationChannel.PUSH),
    ],
)
async def test_a_channel_without_a_provider_logs_and_sends_nothing(
    sender: LoggingSmsSender | LoggingPushSender,
    channel: NotificationChannel,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """« Implementation vide et journalisee » : la ligne existe, le message ne part pas."""
    assert sender.channel is channel

    with caplog.at_level(logging.INFO):
        await sender.send(**_MESSAGE)

    records = [record for record in caplog.records if getattr(record, "notification_channel", None)]
    assert len(records) == 1
    assert records[0].notification_channel == channel.value
    assert records[0].recipient == _MESSAGE["recipient"]


@pytest.mark.parametrize("sender", [LoggingSmsSender(), LoggingPushSender()])
async def test_a_channel_without_a_provider_never_raises(
    sender: LoggingSmsSender | LoggingPushSender,
) -> None:
    """L'absence de fournisseur n'est pas une panne de transport.

    La faire remonter declencherait la politique de reprise de BACK-15 sur une
    tache qui ne reussira jamais -- des reessais jusqu'a la file de rejets, a
    chaque notification.
    """
    await sender.send(**_MESSAGE)


@pytest.mark.parametrize("sender", [LoggingSmsSender(), LoggingPushSender()])
async def test_a_channel_without_a_provider_never_logs_the_body(
    sender: LoggingSmsSender | LoggingPushSender,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Le corps n'ajoute rien au diagnostic et grossirait chaque ligne."""
    with caplog.at_level(logging.INFO):
        await sender.send(**_MESSAGE)

    assert _MESSAGE["body"] not in caplog.text
