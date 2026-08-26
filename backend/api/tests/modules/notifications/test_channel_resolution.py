"""Le module choisit le canal, et le transactionnel ignore les preferences.

BACK-22, criteres 2 et 3 -- les deux regles que le ticket met en gras :

- « Le module appelant emet un evenement, notifications choisit le canal » ;
- « Transactionnel part toujours, optionnel respecte les preferences ».

CE QUE PROUVE CE FICHIER, ET COMMENT
Chaque test passe par `DeliverNotification`, c'est-a-dire par le CHEMIN REEL de
la remise -- lecture des preferences comprise --, avec des `FakeNotificationSender`
a la place des trois canaux. Aucun appel ne nomme de canal : c'est bien le module
qui decide, et non le test.
"""

from uuid import UUID, uuid4

import pytest

from app.modules.notifications.application.use_cases.deliver_notification import (
    DeliverNotification,
)
from app.modules.notifications.domain.entities import (
    NotificationPreferences,
    NotificationRequest,
)
from app.modules.notifications.domain.policies import NotificationChannel, NotificationEvent
from app.modules.notifications.domain.ports import NotificationDeliveryError
from tests.modules.notifications.notification_doubles import (
    FakeNotificationSender,
    InMemoryNotificationsUnitOfWork,
)

pytestmark = pytest.mark.notifications

# Variables des gabarits employes ici. Un seul dictionnaire pour tous les
# evenements du fichier : les cles en trop sont ignorees par le rendu, et un
# payload par test dirait qui l'emet plutot que ce qui se joue.
_PAYLOAD = {
    "recipient_name": "Jean Veto",
    "reset_url": "https://juui.test/reinitialiser/jeton",
    "appointment_date": "12 septembre a 10h30",
    "clinic_name": "Clinique des Tilleuls",
    "headline": "Les nouveautes de la rentree",
    "message": "Trois nouveautes vous attendent.",
}


class _Channels:
    """Les trois doublures de canal, et l'unite de travail qui va avec."""

    def __init__(self, uow: InMemoryNotificationsUnitOfWork) -> None:
        """Monte un jeu complet de canaux sur cette unite de travail."""
        self.email = FakeNotificationSender(sender_channel=NotificationChannel.EMAIL)
        self.sms = FakeNotificationSender(sender_channel=NotificationChannel.SMS)
        self.push = FakeNotificationSender(sender_channel=NotificationChannel.PUSH)
        self.use_case = DeliverNotification(uow=uow, senders=(self.email, self.sms, self.push))

    async def deliver(self, account_id: UUID, event: NotificationEvent) -> None:
        """Emet l'evenement -- SANS nommer le moindre canal."""
        await self.use_case.execute(
            NotificationRequest(
                account_id=account_id,
                event=event,
                recipient="jean@exemple.fr",
                recipient_name="Jean Veto",
                payload=_PAYLOAD,
            )
        )


async def test_the_emitter_names_no_channel_and_the_module_picks_the_default() -> None:
    """Critere 2 : un compte sans preferences recoit sur le canal par defaut."""
    account_id = uuid4()
    channels = _Channels(InMemoryNotificationsUnitOfWork())

    await channels.deliver(account_id, NotificationEvent.APPOINTMENT_REMINDER)

    assert len(channels.email.sent) == 1
    assert channels.sms.sent == []
    assert channels.push.sent == []


async def test_the_module_follows_the_account_choice_of_channel() -> None:
    """Critere 2 : le meme evenement, le meme appel, un autre canal.

    C'est LA preuve que le canal n'est pas dans l'evenement : rien n'a change du
    cote de l'emetteur, seules les preferences ont bouge.
    """
    preferences = NotificationPreferences.create(account_id=uuid4())
    preferences.set_channels(NotificationEvent.APPOINTMENT_REMINDER, {NotificationChannel.SMS})
    channels = _Channels(InMemoryNotificationsUnitOfWork([preferences]))

    await channels.deliver(preferences.account_id, NotificationEvent.APPOINTMENT_REMINDER)

    assert len(channels.sms.sent) == 1
    assert channels.email.sent == []


async def test_the_module_delivers_on_every_chosen_channel() -> None:
    """« Ou combinaison » : deux canaux choisis, deux remises."""
    preferences = NotificationPreferences.create(account_id=uuid4())
    preferences.set_channels(
        NotificationEvent.APPOINTMENT_REMINDER,
        {NotificationChannel.EMAIL, NotificationChannel.SMS},
    )
    channels = _Channels(InMemoryNotificationsUnitOfWork([preferences]))

    await channels.deliver(preferences.account_id, NotificationEvent.APPOINTMENT_REMINDER)

    assert len(channels.email.sent) == 1
    assert len(channels.sms.sent) == 1
    assert channels.push.sent == []


async def test_an_optional_event_that_was_switched_off_is_not_delivered() -> None:
    """Critere 3, premier cas : l'optionnel respecte les preferences."""
    preferences = NotificationPreferences.create(account_id=uuid4())
    preferences.set_channels(NotificationEvent.NEWS, [])
    channels = _Channels(InMemoryNotificationsUnitOfWork([preferences]))

    await channels.deliver(preferences.account_id, NotificationEvent.NEWS)

    assert channels.email.sent == []
    assert channels.sms.sent == []
    assert channels.push.sent == []


async def test_a_transactional_event_leaves_even_with_every_optional_channel_switched_off() -> None:
    """Critere 3, second cas : le transactionnel part toujours.

    Le compte a coupe TOUT ce qu'il avait le droit de couper -- l'agregat refusant
    de configurer un transactionnel, c'est le maximum qu'un utilisateur puisse
    faire. La reinitialisation part quand meme.
    """
    preferences = NotificationPreferences.create(account_id=uuid4())
    for event in NotificationEvent:
        if event not in (
            NotificationEvent.PASSWORD_RESET,
            NotificationEvent.APPOINTMENT_CANCELLED,
        ):
            preferences.set_channels(event, [])
    channels = _Channels(InMemoryNotificationsUnitOfWork([preferences]))

    await channels.deliver(preferences.account_id, NotificationEvent.PASSWORD_RESET)

    assert len(channels.email.sent) == 1


async def test_a_transactional_event_ignores_a_preference_that_would_reroute_it() -> None:
    """Meme si un document forge en base disait le contraire, le canal impose gagne.

    L'agregat refuse d'ecrire un tel ecart ; ce test le pose DE FORCE, comme le
    ferait une ligne heritee d'un catalogue plus ancien, pour prouver que la regle
    tient a la LECTURE et pas seulement a l'ecriture.
    """
    preferences = NotificationPreferences.create(account_id=uuid4())
    preferences.channels_by_event[NotificationEvent.PASSWORD_RESET] = frozenset()
    channels = _Channels(InMemoryNotificationsUnitOfWork([preferences]))

    await channels.deliver(preferences.account_id, NotificationEvent.PASSWORD_RESET)

    assert len(channels.email.sent) == 1


async def test_the_rendered_message_belongs_to_the_event_that_was_emitted() -> None:
    """L'emetteur n'ecrit pas le message non plus : le gabarit vit dans le module."""
    account_id = uuid4()
    channels = _Channels(InMemoryNotificationsUnitOfWork())

    await channels.deliver(account_id, NotificationEvent.PASSWORD_RESET)

    sent = channels.email.last
    assert "mot de passe" in sent.subject
    assert _PAYLOAD["reset_url"] in sent.body


async def test_one_failing_channel_does_not_deprive_the_others() -> None:
    """Un canal en panne n'interrompt pas la boucle, et la tache echoue quand meme.

    Interrompre a la premiere erreur priverait l'utilisateur d'un canal qui
    marchait ; ne pas lever priverait la reprise de BACK-15 de son declencheur.
    """
    preferences = NotificationPreferences.create(account_id=uuid4())
    preferences.set_channels(
        NotificationEvent.APPOINTMENT_REMINDER,
        {NotificationChannel.EMAIL, NotificationChannel.SMS},
    )
    uow = InMemoryNotificationsUnitOfWork([preferences])
    email = FakeNotificationSender(sender_channel=NotificationChannel.EMAIL, fails=True)
    sms = FakeNotificationSender(sender_channel=NotificationChannel.SMS)
    use_case = DeliverNotification(uow=uow, senders=(email, sms))

    with pytest.raises(NotificationDeliveryError):
        await use_case.execute(
            NotificationRequest(
                account_id=preferences.account_id,
                event=NotificationEvent.APPOINTMENT_REMINDER,
                recipient="jean@exemple.fr",
                recipient_name="Jean Veto",
                payload=_PAYLOAD,
            )
        )

    assert len(sms.sent) == 1


async def test_a_channel_without_adapter_is_skipped_rather_than_failing() -> None:
    """Une preference valide sur un canal sans adaptateur ne casse pas la remise."""
    preferences = NotificationPreferences.create(account_id=uuid4())
    preferences.set_channels(NotificationEvent.NEWS, {NotificationChannel.PUSH})
    uow = InMemoryNotificationsUnitOfWork([preferences])
    email = FakeNotificationSender(sender_channel=NotificationChannel.EMAIL)
    use_case = DeliverNotification(uow=uow, senders=(email,))

    await use_case.execute(
        NotificationRequest(
            account_id=preferences.account_id,
            event=NotificationEvent.NEWS,
            recipient="jean@exemple.fr",
            recipient_name="Jean Veto",
            payload=_PAYLOAD,
        )
    )

    assert email.sent == []
