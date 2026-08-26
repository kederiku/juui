"""Test de bout en bout : le code part vraiment, et il verifie vraiment (BACK-17).

LE CRITERE D'ACCEPTATION LE PLUS EXIGEANT DU TICKET -- « test de bout en bout qui
recupere le code via Mailpit ». Ce qui se joue ici ne se joue nulle part
ailleurs : le code relu est celui que l'UTILISATEUR aurait recu, extrait du
message reellement remis au serveur, et non celui que le service croit avoir
ecrit. Relire Redis testerait le code a la sortie de la generation ; relire
Mailpit le teste a l'arrivee.

C'est aussi le seul test qui traverse la tache elle-meme : le corps de
`send_email_verification_otp` est appele avec des adaptateurs explicites, ce qui
prouve son cablage -- unite de travail, magasin, expediteur, regles -- sans
exiger un worker et un broker.

PREALABLE : la pile doit tourner (`make up`). Sans Mailpit, le test est IGNORE
plutot qu'en echec : la suite doit rester passante sur un poste sans Docker.
"""

import os
import re
from typing import Any
from uuid import uuid4

import httpx
import pytest

from app.core import get_settings
from app.modules.identity.application.use_cases.verify_otp import (
    VerifyEmailCommand,
    VerifyEmailOtp,
)
from app.modules.identity.infrastructure.clients.smtp_otp_sender import build_otp_sender
from app.modules.identity.infrastructure.tasks.otp import send_email_verification_otp
from tests.modules.identity.otp_doubles import (
    InMemoryIdentityUnitOfWork,
    InMemoryOtpStore,
    an_account,
)

pytestmark = pytest.mark.otp

# Boite web de Mailpit, telle qu'INFRA-07 la publie sur la boucle locale. Lue de
# l'environnement comme `POSTGRES_TEST_DB` l'est dans le conftest racine : ce
# n'est pas un reglage de l'API, l'API ne parle qu'au port SMTP.
_MAILPIT_WEB_PORT = os.environ.get("MAILPIT_WEB_HOST_PORT", "8025")
_MAILPIT_URL = f"http://localhost:{_MAILPIT_WEB_PORT}"

# Le code dans le corps du message. Six chiffres precedes de leur libelle : un
# `\d{6}` nu attraperait le premier nombre venu le jour ou le message en
# porterait un autre.
_CODE_IN_BODY = re.compile(r"Votre code de verification est : (\d{6})")


@pytest.fixture
async def mailpit() -> httpx.AsyncClient:
    """Client de l'API de Mailpit, ou test ignore si la boite ne repond pas."""
    async with httpx.AsyncClient(base_url=_MAILPIT_URL, timeout=5.0) as client:
        try:
            await client.get("/api/v1/messages", params={"limit": 1})
        except httpx.HTTPError:
            pytest.skip(f"Mailpit ne repond pas sur {_MAILPIT_URL} : `make up` a la racine.")
        yield client


async def _find_message(client: httpx.AsyncClient, recipient: str) -> dict[str, Any]:
    """Retrouve le message adresse a cette boite, et rend son contenu complet.

    Args:
        client: le client de l'API de Mailpit.
        recipient: l'adresse visee, unique a ce test.

    Returns:
        Le message complet, corps compris.
    """
    listing = await client.get("/api/v1/search", params={"query": f"to:{recipient}"})
    listing.raise_for_status()
    messages = listing.json()["messages"]
    assert len(messages) == 1, f"Attendu un message pour {recipient}, recu {len(messages)}."
    detail = await client.get(f"/api/v1/message/{messages[0]['ID']}")
    detail.raise_for_status()
    return dict(detail.json())


async def _delete_message(client: httpx.AsyncClient, message_id: str) -> None:
    """Retire le message du test de la boite partagee, sans jamais la vider.

    Par identifiant, et par identifiant SEULEMENT : un `DELETE /api/v1/messages`
    sans corps efface toute la boite, y compris ce qu'un developpeur etait en
    train de regarder.
    """
    await client.request("DELETE", "/api/v1/messages", json={"IDs": [message_id]})


async def test_the_code_travels_to_the_mailbox_and_verifies_the_account(
    mailpit: httpx.AsyncClient,
) -> None:
    """Emission par la tache, lecture dans Mailpit, verification par le code recu."""
    recipient = f"otp-{uuid4().hex[:12]}@exemple.test"
    account = an_account(email=recipient)
    uow = InMemoryIdentityUnitOfWork([account])
    store = InMemoryOtpStore()

    # Le corps de la tache, avec des adaptateurs explicites : c'est ce que le
    # worker executera, l'injection en moins.
    await send_email_verification_otp(
        account.id,
        uow=uow,
        otp_store=store,
        sender=build_otp_sender(get_settings()),
    )

    message = await _find_message(mailpit, recipient)
    try:
        body = str(message["Text"])
        found = _CODE_IN_BODY.search(body)
        assert found is not None, f"Aucun code dans le corps du message : {body!r}"
        code = found.group(1)

        # Le code figure aussi dans l'objet : c'est lui que la notification d'un
        # telephone affiche, et c'est ce qui evite d'ouvrir le message.
        assert code in str(message["Subject"])
        # Et le message dit sa peremption, sans quoi il se recopie une heure plus tard.
        assert "valable" in body

        verified = await VerifyEmailOtp(uow=uow, otp_store=store).execute(
            VerifyEmailCommand(account_id=account.id, code=code)
        )

        assert verified.email_verified
        assert uow.stored(account.id).email_verified
    finally:
        await _delete_message(mailpit, str(message["ID"]))
