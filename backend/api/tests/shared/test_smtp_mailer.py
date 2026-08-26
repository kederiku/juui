"""Le transport SMTP partage : auth et TLS pilotes par la configuration (BACK-22).

CRITERE 4 DU TICKET, SA MOITIE « CONFIGURABLES ». La promesse d'INFRA-07 est
qu'aucun changement de code ne separe Mailpit d'un fournisseur reel : pointer
`SMTP_HOST` ailleurs, renseigner l'utilisateur et le mot de passe, activer
`SMTP_USE_TLS`. Ce qui se prouve ici, c'est que les trois reglages COMMANDENT
reellement le dialogue -- et non qu'ils existent dans un fichier de configuration.

`smtplib.SMTP` EST REMPLACE PAR UNE DOUBLURE, et le test n'ouvre aucune socket :
ce qu'on eprouve est la sequence d'appels, pas la pile TCP. Le parcours reel
jusqu'a une boite est le sujet de `tests/modules/notifications/test_email_delivery.py`,
qui passe par Mailpit.

CE FICHIER VIT DANS `tests/shared/` PARCE QUE LE TRANSPORT Y VIT (ADR-0022) : il
sert le module notifications ET l'expediteur d'OTP d'identity.
"""

import smtplib
from email.message import EmailMessage
from typing import ClassVar, Self

import pytest
from pydantic import SecretStr

from app.core.config import SmtpSettings
from app.shared.domain.ports.email import EmailDeliveryError
from app.shared.infrastructure.clients.smtp_mailer import SmtpEmailTransport

pytestmark = pytest.mark.notifications

_MESSAGE = {
    "recipient": "jean@exemple.fr",
    "recipient_name": "Jean Veto",
    "subject": "Objet de sonde",
    "body": "Corps de sonde.\n",
}


class _RecordingSmtp:
    """Doublure de `smtplib.SMTP` : note la sequence au lieu de la jouer.

    Instanciee par le code teste, elle range ses observations dans la liste de
    classe ci-dessous -- c'est le seul moyen de les relire, l'instance etant creee
    a l'interieur du `with`.
    """

    calls: ClassVar[list[tuple[str, tuple[str, str] | None]]] = []
    kwargs: ClassVar[dict[str, object]] = {}
    sent: ClassVar[list[EmailMessage]] = []
    failure: ClassVar[type[Exception] | None] = None

    def __init__(self, **kwargs: object) -> None:
        """Note les parametres de connexion."""
        type(self).kwargs = kwargs
        if type(self).failure is not None:
            raise type(self).failure("connexion refusee")

    def __enter__(self) -> Self:
        """Ouvre la session."""
        return self

    def __exit__(self, *_: object) -> None:
        """Referme la session."""

    def starttls(self) -> None:
        """Note la negociation TLS."""
        type(self).calls.append(("starttls", None))

    def login(self, user: str, password: str) -> None:
        """Note l'authentification."""
        type(self).calls.append(("login", (user, password)))

    def send_message(self, message: EmailMessage) -> None:
        """Note le message remis."""
        type(self).calls.append(("send_message", None))
        type(self).sent.append(message)


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[_RecordingSmtp]:
    """Remplace `smtplib.SMTP` par la doublure, remise a zero a chaque test."""
    _RecordingSmtp.calls = []
    _RecordingSmtp.kwargs = {}
    _RecordingSmtp.sent = []
    _RecordingSmtp.failure = None
    monkeypatch.setattr(smtplib, "SMTP", _RecordingSmtp)
    return _RecordingSmtp


def _settings(
    *, user: str = "", password: SecretStr | None = None, use_tls: bool = False
) -> SmtpSettings:
    """Les reglages du gabarit local, surchargeables sur les trois champs eprouves ici.

    Les valeurs par defaut sont celles de Mailpit : ni authentification, ni TLS.
    """
    return SmtpSettings(
        host="localhost",
        port=1025,
        user=user,
        password=password,
        use_tls=use_tls,
        MAIL_FROM="no-reply@juui.test",
    )


async def test_the_local_mailbox_needs_neither_tls_nor_authentication(
    smtp: type[_RecordingSmtp],
) -> None:
    """Mailpit ne presente aucun certificat : negocier contre lui echouerait."""
    await SmtpEmailTransport(settings=_settings()).send(**_MESSAGE)

    assert [name for name, _ in smtp.calls] == ["send_message"]
    assert smtp.kwargs["host"] == "localhost"
    assert smtp.kwargs["port"] == 1025


async def test_tls_is_negotiated_before_anything_else_when_the_setting_asks_for_it(
    smtp: type[_RecordingSmtp],
) -> None:
    """STARTTLS et non SMTPS : la session passe au chiffrement apres le EHLO."""
    await SmtpEmailTransport(settings=_settings(use_tls=True)).send(**_MESSAGE)

    assert [name for name, _ in smtp.calls] == ["starttls", "send_message"]


async def test_the_adapter_authenticates_when_a_user_is_declared(
    smtp: type[_RecordingSmtp],
) -> None:
    """La configuration d'un fournisseur reel, sans une ligne de code changee."""
    settings = _settings(user="juui", password=SecretStr("secret"), use_tls=True)

    await SmtpEmailTransport(settings=settings).send(**_MESSAGE)

    assert [name for name, _ in smtp.calls] == ["starttls", "login", "send_message"]
    assert smtp.calls[1][1] == ("juui", "secret")


async def test_a_password_without_a_user_authenticates_nobody(
    smtp: type[_RecordingSmtp],
) -> None:
    """Le test porte sur l'UTILISATEUR seul.

    Tenter un `login` contre Mailpit ferait echouer un envoi qui serait autrement
    passe -- d'ou la propriete `requires_authentication`, et ce test qui la garde.
    """
    settings = _settings(password=SecretStr("secret"))

    await SmtpEmailTransport(settings=settings).send(**_MESSAGE)

    assert [name for name, _ in smtp.calls] == ["send_message"]


async def test_the_composed_message_carries_the_headers_a_robot_message_needs(
    smtp: type[_RecordingSmtp],
) -> None:
    """`To` encode par `Address`, et `Auto-Submitted` de la RFC 3834.

    Sans le second, une reponse d'absence revient sur la boite d'expedition a
    chaque envoi.
    """
    await SmtpEmailTransport(settings=_settings()).send(**_MESSAGE)

    (message,) = smtp.sent
    assert message["Subject"] == _MESSAGE["subject"]
    assert message["From"] == "no-reply@juui.test"
    assert message["To"] == "Jean Veto <jean@exemple.fr>"
    assert message["Auto-Submitted"] == "auto-generated"
    assert message.get_content() == _MESSAGE["body"]


async def test_a_recipient_name_carrying_a_comma_does_not_split_the_header(
    smtp: type[_RecordingSmtp],
) -> None:
    """Un en-tete assemble a la main produirait deux destinataires dont l'un n'existe pas."""
    await SmtpEmailTransport(settings=_settings()).send(
        **{**_MESSAGE, "recipient_name": "Veto, Jean"}
    )

    (message,) = smtp.sent
    assert message["To"] == '"Veto, Jean" <jean@exemple.fr>'


@pytest.mark.parametrize("failure", [OSError, smtplib.SMTPException])
async def test_a_transport_failure_becomes_the_error_the_port_announces(
    smtp: type[_RecordingSmtp], failure: type[Exception]
) -> None:
    """Le port LEVE, toujours.

    Un message perdu en silence est un message dont personne n'apprendra jamais
    l'absence.
    """
    smtp.failure = failure

    with pytest.raises(EmailDeliveryError):
        await SmtpEmailTransport(settings=_settings()).send(**_MESSAGE)


async def test_the_failure_message_carries_neither_the_recipient_nor_the_body(
    smtp: type[_RecordingSmtp],
) -> None:
    """Une erreur finit dans un journal, et un journal se recopie.

    Ce qui relie un envoi a son destinataire est le journal d'envoi du module
    notifications, qui l'ecrit une fois, a sa place.
    """
    smtp.failure = OSError

    with pytest.raises(EmailDeliveryError) as raised:
        await SmtpEmailTransport(settings=_settings()).send(**_MESSAGE)

    assert _MESSAGE["recipient"] not in str(raised.value)
    assert _MESSAGE["body"] not in str(raised.value)
