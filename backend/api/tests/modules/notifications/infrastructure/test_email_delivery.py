"""Test de bout en bout : la notification arrive vraiment dans la boite (BACK-22).

Le pendant, pour ce module, de `test_otp_email_delivery.py` : ce qui se joue ici
ne se joue nulle part ailleurs -- le message relu est celui que l'UTILISATEUR
aurait recu, extrait de ce que le serveur a reellement accepte, et non celui que
le service croit avoir ecrit.

C'est aussi le seul test qui traverse la chaine entiere du module : preferences,
choix du canal, rendu du gabarit, adaptateur de canal, transport partage, SMTP.
Le broker seul reste dehors -- le corps de la tache est appele directement, ce qui
prouve son cablage sans exiger un worker.

PREALABLE : la pile doit tourner (`make dev` a la racine). Sans Mailpit, le test
est IGNORE plutot qu'en echec : la suite doit rester passante sur un poste sans
Docker.
"""

import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.core import get_settings
from app.modules.notifications.application.use_cases.deliver_notification import (
    DeliverNotification,
)
from app.modules.notifications.domain.entities import (
    NotificationPreferences,
    NotificationRequest,
)
from app.modules.notifications.domain.policies import NotificationChannel, NotificationEvent
from app.modules.notifications.infrastructure.clients.email_sender import (
    build_email_notification_sender,
)
from app.modules.notifications.infrastructure.clients.push_sender import LoggingPushSender
from app.modules.notifications.infrastructure.clients.sms_sender import LoggingSmsSender
from app.modules.notifications.infrastructure.memory.unit_of_work import (
    InMemoryNotificationsUnitOfWork,
)
from tests.support.services import MAILPIT, MAILPIT_REMEDY, require_service

pytestmark = pytest.mark.notifications

# Boite web de Mailpit, telle qu'INFRA-07 la publie sur la boucle locale. Lue de
# l'environnement comme `POSTGRES_TEST_DB` l'est dans le conftest racine : ce
# n'est pas un reglage de l'API, l'API ne parle qu'au port SMTP.
_MAILPIT_WEB_PORT = os.environ.get("MAILPIT_WEB_HOST_PORT", "8025")
_MAILPIT_URL = f"http://localhost:{_MAILPIT_WEB_PORT}"

_PAYLOAD = {
    "recipient_name": "Jean Veto",
    "appointment_date": "12 septembre a 10h30",
    "clinic_name": "Clinique des Tilleuls",
    "reset_url": "https://juui.test/reinitialiser/jeton-de-sonde",
}


@pytest.fixture
async def mailpit(pytestconfig: pytest.Config) -> AsyncIterator[httpx.AsyncClient]:
    """Client de l'API de Mailpit, ou test ignore si la boite ne repond pas."""
    async with httpx.AsyncClient(base_url=_MAILPIT_URL, timeout=5.0) as client:
        try:
            await client.get("/api/v1/messages", params={"limit": 1})
        except httpx.HTTPError:
            require_service(pytestconfig, name=MAILPIT, remedy=MAILPIT_REMEDY)
        yield client


async def _messages(client: httpx.AsyncClient, recipient: str) -> list[dict[str, Any]]:
    """Rend les messages adresses a cette boite, corps compris."""
    listing = await client.get("/api/v1/search", params={"query": f"to:{recipient}"})
    listing.raise_for_status()
    detailed: list[dict[str, Any]] = []
    for summary in listing.json()["messages"]:
        detail = await client.get(f"/api/v1/message/{summary['ID']}")
        detail.raise_for_status()
        detailed.append(dict(detail.json()))
    return detailed


async def _delete(client: httpx.AsyncClient, messages: list[dict[str, Any]]) -> None:
    """Retire du courrier de la boite partagee, par identifiant SEULEMENT.

    Un `DELETE /api/v1/messages` sans corps efface toute la boite, y compris ce
    qu'un developpeur etait en train de regarder.
    """
    identifiers = [str(message["ID"]) for message in messages]
    if identifiers:
        await client.request("DELETE", "/api/v1/messages", json={"IDs": identifiers})


def _use_case(preferences: NotificationPreferences) -> DeliverNotification:
    """Le cas d'usage cable comme le worker le cable : trois canaux, vrais adaptateurs."""
    return DeliverNotification(
        uow=InMemoryNotificationsUnitOfWork([preferences]),
        senders=(
            build_email_notification_sender(get_settings()),
            LoggingSmsSender(),
            LoggingPushSender(),
        ),
    )


async def test_an_optional_notification_reaches_the_mailbox(
    mailpit: httpx.AsyncClient,
) -> None:
    """Le parcours nominal, de l'evenement emis jusqu'au message recu."""
    recipient = f"notif-{uuid4().hex[:12]}@exemple.test"
    preferences = NotificationPreferences.create(account_id=uuid4())

    await _use_case(preferences).execute(
        NotificationRequest(
            account_id=preferences.account_id,
            event=NotificationEvent.APPOINTMENT_REMINDER,
            recipient=recipient,
            recipient_name="Jean Veto",
            payload=_PAYLOAD,
        )
    )

    messages = await _messages(mailpit, recipient)
    try:
        assert len(messages) == 1
        assert _PAYLOAD["appointment_date"] in str(messages[0]["Subject"])
        assert _PAYLOAD["clinic_name"] in str(messages[0]["Text"])
    finally:
        await _delete(mailpit, messages)


async def test_a_transactional_notification_reaches_the_mailbox_despite_the_preferences(
    mailpit: httpx.AsyncClient,
) -> None:
    """Critere 3, jusqu'a la boite : le compte a coupe tout ce qu'il pouvait couper."""
    recipient = f"notif-{uuid4().hex[:12]}@exemple.test"
    preferences = NotificationPreferences.create(account_id=uuid4())
    preferences.set_channels(NotificationEvent.NEWS, [])
    preferences.set_channels(NotificationEvent.APPOINTMENT_REMINDER, [])

    await _use_case(preferences).execute(
        NotificationRequest(
            account_id=preferences.account_id,
            event=NotificationEvent.PASSWORD_RESET,
            recipient=recipient,
            recipient_name="Jean Veto",
            payload=_PAYLOAD,
        )
    )

    messages = await _messages(mailpit, recipient)
    try:
        assert len(messages) == 1
        assert _PAYLOAD["reset_url"] in str(messages[0]["Text"])
    finally:
        await _delete(mailpit, messages)


async def test_an_event_switched_off_never_reaches_the_mailbox(
    mailpit: httpx.AsyncClient,
) -> None:
    """Critere 3, l'autre moitie : l'optionnel desactive ne part pas.

    Le contre-test des deux precedents. Sans lui, un module qui enverrait TOUT
    passerait les deux autres sans broncher.
    """
    recipient = f"notif-{uuid4().hex[:12]}@exemple.test"
    preferences = NotificationPreferences.create(account_id=uuid4())
    preferences.set_channels(NotificationEvent.NEWS, [])

    await _use_case(preferences).execute(
        NotificationRequest(
            account_id=preferences.account_id,
            event=NotificationEvent.NEWS,
            recipient=recipient,
            recipient_name="Jean Veto",
            payload={**_PAYLOAD, "headline": "Sonde", "message": "Sonde."},
        )
    )

    messages = await _messages(mailpit, recipient)
    try:
        assert messages == []
    finally:
        await _delete(mailpit, messages)


async def test_a_notification_routed_to_sms_does_not_leave_by_email(
    mailpit: httpx.AsyncClient,
) -> None:
    """Le canal choisi est le SEUL emprunte : l'e-mail ne double pas le SMS.

    C'est ici que « le module choisit le canal » se verifie a l'exterieur du
    service -- une boite qui reste vide vaut mieux qu'une doublure qui n'a rien
    recu.
    """
    recipient = f"notif-{uuid4().hex[:12]}@exemple.test"
    preferences = NotificationPreferences.create(account_id=uuid4())
    preferences.set_channels(NotificationEvent.APPOINTMENT_REMINDER, {NotificationChannel.SMS})

    await _use_case(preferences).execute(
        NotificationRequest(
            account_id=preferences.account_id,
            event=NotificationEvent.APPOINTMENT_REMINDER,
            recipient=recipient,
            recipient_name="Jean Veto",
            payload=_PAYLOAD,
        )
    )

    messages = await _messages(mailpit, recipient)
    try:
        assert messages == []
    finally:
        await _delete(mailpit, messages)
