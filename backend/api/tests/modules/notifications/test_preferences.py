"""Preferences par TYPE D'EVENEMENT, jamais un interrupteur global (BACK-22, critere 1).

Le critere premier du ticket, et celui qui decide de la forme de l'agregat :
« canal active par TYPE D'EVENEMENT, pas un interrupteur global. Rappels de
rendez-vous par SMS mais actualites par e-mail est le besoin reel ; un booleen
unique ne le couvre pas. » Ce qui se prouve ici, c'est qu'il est possible de
regler DEUX evenements differemment, et que rien ne permet de tout couper d'un
geste.

Tests PURS : aucun Docker, aucune base. L'agregat et ses regles ne dependent que
de la bibliotheque standard.
"""

from uuid import uuid4

import pytest

from app.modules.notifications.domain.entities import NotificationPreferences
from app.modules.notifications.domain.exceptions import (
    TransactionalEventNotConfigurableError,
)
from app.modules.notifications.domain.policies import (
    DEFAULT_CHANNELS,
    NotificationChannel,
    NotificationEvent,
    is_transactional,
)

pytestmark = pytest.mark.notifications


def _preferences() -> NotificationPreferences:
    """Des preferences neuves, sans aucun ecart."""
    return NotificationPreferences.create(account_id=uuid4())


def test_a_brand_new_account_follows_the_defaults_without_a_single_stored_choice() -> None:
    """Aucun ecart enregistre : chaque evenement suit son defaut."""
    preferences = _preferences()

    assert preferences.channels_by_event == {}
    for event in NotificationEvent:
        assert preferences.channels_for(event) == DEFAULT_CHANNELS[event]


def test_two_events_are_configured_independently() -> None:
    """LE critere du ticket, dans son exemple litteral.

    « Rappels de rendez-vous par SMS mais actualites par e-mail. »
    """
    preferences = _preferences()

    preferences.set_channels(NotificationEvent.APPOINTMENT_REMINDER, {NotificationChannel.SMS})
    preferences.set_channels(NotificationEvent.NEWS, {NotificationChannel.EMAIL})

    assert preferences.channels_for(NotificationEvent.APPOINTMENT_REMINDER) == frozenset(
        {NotificationChannel.SMS}
    )
    assert preferences.channels_for(NotificationEvent.NEWS) == frozenset(
        {NotificationChannel.EMAIL}
    )


def test_configuring_one_event_leaves_the_others_untouched() -> None:
    """Le contre-test de l'interrupteur global : couper un evenement n'en coupe aucun autre."""
    preferences = _preferences()

    preferences.set_channels(NotificationEvent.NEWS, [])

    assert preferences.channels_for(NotificationEvent.NEWS) == frozenset()
    assert (
        preferences.channels_for(NotificationEvent.APPOINTMENT_REMINDER)
        == DEFAULT_CHANNELS[NotificationEvent.APPOINTMENT_REMINDER]
    )


def test_several_channels_can_be_active_for_the_same_event() -> None:
    """« Ou combinaison » : le cahier des charges admet plusieurs canaux a la fois."""
    preferences = _preferences()

    preferences.set_channels(
        NotificationEvent.APPOINTMENT_REMINDER,
        {NotificationChannel.EMAIL, NotificationChannel.SMS},
    )

    assert preferences.channels_for(NotificationEvent.APPOINTMENT_REMINDER) == frozenset(
        {NotificationChannel.EMAIL, NotificationChannel.SMS}
    )


def test_an_empty_choice_is_kept_and_never_read_back_as_no_choice() -> None:
    """« Je ne veux plus rien » et « je n'ai pas d'avis » sont deux etats distincts.

    Les confondre reactiverait en silence ce qu'un utilisateur vient de couper --
    c'est la raison pour laquelle l'agregat range les ECARTS et non les valeurs
    effectives.
    """
    preferences = _preferences()

    preferences.set_channels(NotificationEvent.NEWS, [])
    assert preferences.channels_for(NotificationEvent.NEWS) == frozenset()

    preferences.reset(NotificationEvent.NEWS)
    assert (
        preferences.channels_for(NotificationEvent.NEWS) == DEFAULT_CHANNELS[NotificationEvent.NEWS]
    )


def test_resetting_an_event_that_was_never_configured_does_nothing() -> None:
    """Idempotent : un ecart absent s'efface sans erreur."""
    preferences = _preferences()

    preferences.reset(NotificationEvent.NEWS)

    assert preferences.channels_by_event == {}


@pytest.mark.parametrize("event", [event for event in NotificationEvent if is_transactional(event)])
def test_a_transactional_event_cannot_be_configured_at_all(event: NotificationEvent) -> None:
    """Le refus est EXPLICITE : accepter puis ignorer laisserait croire au contraire.

    Un utilisateur qui aurait « desactive » sa reinitialisation de mot de passe la
    recevrait quand meme -- ce qui est pire qu'un refus franc.
    """
    preferences = _preferences()

    with pytest.raises(TransactionalEventNotConfigurableError):
        preferences.set_channels(event, [])

    assert preferences.channels_by_event == {}


def test_the_aggregate_carries_the_account_it_belongs_to_and_nothing_of_identity() -> None:
    """`account_id` est un identifiant NU : aucune donnee du compte ne migre ici."""
    account_id = uuid4()

    preferences = NotificationPreferences.create(account_id=account_id)

    assert preferences.account_id == account_id
    assert not hasattr(preferences, "email")
