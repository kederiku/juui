"""Journal d'envoi : destinataire, canal, evenement, statut (BACK-22, critere 5).

« Journaliser les envois (destinataire, canal, evenement, statut) : un je n'ai
rien recu doit etre diagnosticable. » Ce qui se joue ici est exactement ca : les
quatre champs doivent permettre de distinguer, sans ouvrir le code, un message
remis d'un message refuse par le transport et d'un message que le compte avait
desactive.

LES ASSERTIONS PORTENT SUR LA LIGNE RENDUE, pas seulement sur l'enregistrement.
`caplog.records` montre ce que l'appel a pose ; le passer ensuite dans le
`JsonFormatter` de BACK-11 montre ce qui SORT en production -- masquage compris.
C'est la lecon des sondes de `tests/support/logs.py`.
"""

import json
import logging
from typing import Any
from uuid import uuid4

import pytest

from app.core.logging import JsonFormatter
from app.modules.notifications.application.use_cases.deliver_notification import (
    DeliverNotification,
)
from app.modules.notifications.domain.entities import (
    NotificationPreferences,
    NotificationRequest,
)
from app.modules.notifications.domain.policies import NotificationChannel, NotificationEvent
from app.modules.notifications.domain.ports import NotificationDeliveryError
from app.modules.notifications.infrastructure.memory.senders import FakeNotificationSender
from app.modules.notifications.infrastructure.memory.unit_of_work import (
    InMemoryNotificationsUnitOfWork,
)

pytestmark = pytest.mark.notifications

_RECIPIENT = "jean@exemple.fr"
_PAYLOAD = {
    "recipient_name": "Jean Veto",
    "appointment_date": "12 septembre a 10h30",
    "clinic_name": "Clinique des Tilleuls",
    "headline": "Les nouveautes de la rentree",
    "message": "Trois nouveautes vous attendent.",
}


def _journal(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    """Rend les lignes du journal d'envoi, telles que la production les ecrirait."""
    formatter = JsonFormatter()
    return [
        json.loads(formatter.format(record))
        for record in caplog.records
        if hasattr(record, "notification_status")
    ]


async def _deliver(
    preferences: NotificationPreferences | None,
    event: NotificationEvent,
    *,
    failing: bool = False,
) -> None:
    """Remet un evenement, avec le seul canal e-mail branche."""
    uow = InMemoryNotificationsUnitOfWork([] if preferences is None else [preferences])
    account_id = uuid4() if preferences is None else preferences.account_id
    sender = FakeNotificationSender(sender_channel=NotificationChannel.EMAIL, fails=failing)
    await DeliverNotification(uow=uow, senders=(sender,)).execute(
        NotificationRequest(
            account_id=account_id,
            event=event,
            recipient=_RECIPIENT,
            recipient_name="Jean Veto",
            payload=_PAYLOAD,
        )
    )


async def test_a_successful_delivery_carries_the_four_fields_the_ticket_names(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Destinataire, canal, evenement, statut -- les quatre, sur une seule ligne."""
    with caplog.at_level(logging.INFO):
        await _deliver(None, NotificationEvent.APPOINTMENT_REMINDER)

    (line,) = _journal(caplog)
    assert line["recipient"] == _RECIPIENT
    assert line["notification_channel"] == NotificationChannel.EMAIL.value
    assert line["notification_event"] == NotificationEvent.APPOINTMENT_REMINDER.value
    assert line["notification_status"] == "sent"


async def test_a_disabled_event_is_journalled_as_skipped_rather_than_silently_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """LE cas qui justifie le critere : « je n'ai rien recu » a une reponse.

    Sans cette ligne, un evenement desactive et une panne de transport se
    ressembleraient trait pour trait -- rien dans la boite, rien dans les
    journaux.
    """
    preferences = NotificationPreferences.create(account_id=uuid4())
    preferences.set_channels(NotificationEvent.NEWS, [])

    with caplog.at_level(logging.INFO):
        await _deliver(preferences, NotificationEvent.NEWS)

    (line,) = _journal(caplog)
    assert line["notification_status"] == "skipped"
    assert line["notification_event"] == NotificationEvent.NEWS.value
    assert line["recipient"] == _RECIPIENT
    # Aucun canal n'a ete emprunte : la cle est ABSENTE plutot que nulle.
    assert "notification_channel" not in line


async def test_a_failed_delivery_is_journalled_with_its_channel_and_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Le troisieme statut, celui qui distingue une panne d'un refus de preference."""
    with caplog.at_level(logging.INFO), pytest.raises(NotificationDeliveryError):
        await _deliver(None, NotificationEvent.APPOINTMENT_REMINDER, failing=True)

    (line,) = _journal(caplog)
    assert line["notification_status"] == "failed"
    assert line["notification_channel"] == NotificationChannel.EMAIL.value
    assert line["notification_detail"]


async def test_the_journal_never_carries_the_rendered_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Le diagnostic porte sur l'acheminement, pas sur le contenu.

    Le corps grossirait chaque ligne sans rien apprendre, et ferait entrer dans
    les journaux ce que l'utilisateur a recu -- ce qu'aucun critere ne demande.
    """
    with caplog.at_level(logging.INFO):
        await _deliver(None, NotificationEvent.APPOINTMENT_REMINDER)

    (line,) = _journal(caplog)
    assert _PAYLOAD["clinic_name"] not in json.dumps(line, ensure_ascii=False)


async def test_each_channel_gets_its_own_line(caplog: pytest.LogCaptureFixture) -> None:
    """Deux canaux, deux lignes : c'est ce qui rend un envoi partiel lisible."""
    preferences = NotificationPreferences.create(account_id=uuid4())
    preferences.set_channels(
        NotificationEvent.APPOINTMENT_REMINDER,
        {NotificationChannel.EMAIL, NotificationChannel.SMS},
    )
    uow = InMemoryNotificationsUnitOfWork([preferences])
    senders = (
        FakeNotificationSender(sender_channel=NotificationChannel.EMAIL),
        FakeNotificationSender(sender_channel=NotificationChannel.SMS, fails=True),
    )

    with caplog.at_level(logging.INFO), pytest.raises(NotificationDeliveryError):
        await DeliverNotification(uow=uow, senders=senders).execute(
            NotificationRequest(
                account_id=preferences.account_id,
                event=NotificationEvent.APPOINTMENT_REMINDER,
                recipient=_RECIPIENT,
                recipient_name="Jean Veto",
                payload=_PAYLOAD,
            )
        )

    statuses = {
        line["notification_channel"]: line["notification_status"] for line in _journal(caplog)
    }
    assert statuses == {
        NotificationChannel.EMAIL.value: "sent",
        NotificationChannel.SMS.value: "failed",
    }
