"""Le depot ecrit et relit les preferences, sans rien perdre en chemin (BACK-22).

TESTS D'INTEGRATION : ils tournent contre PostgreSQL, sur la table du module
creee par le conftest voisin. Ce qu'ils prouvent ne se prouve pas en memoire --
la traversee du document JSONB, dans les deux sens, et l'unicite par compte.

PREALABLE : `make dev` a la racine. Sans PostgreSQL, ils echouent au lieu d'etre
ignores : c'est le contrat du harnais de BACK-06b, dont le `pytest.exit` nomme la
commande manquante.
"""

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.domain.entities import NotificationPreferences
from app.modules.notifications.domain.exceptions import (
    UnknownNotificationChannelError,
    UnknownNotificationEventError,
)
from app.modules.notifications.domain.policies import NotificationChannel, NotificationEvent
from app.modules.notifications.infrastructure.db.models import NotificationPreferencesModel
from app.modules.notifications.infrastructure.db.repositories import (
    SqlAlchemyNotificationPreferencesRepository,
)

pytestmark = [pytest.mark.notifications, pytest.mark.usefixtures("_notifications_tables")]


async def test_the_choices_survive_a_round_trip_through_the_document(
    session: AsyncSession,
) -> None:
    """Deux evenements regles differemment se relisent a l'identique.

    Le critere 1 du ticket, eprouve la ou il pourrait se perdre : la traduction
    entre les enums du domaine et le texte du document.
    """
    repository = SqlAlchemyNotificationPreferencesRepository(session)
    preferences = NotificationPreferences.create(account_id=uuid4())
    preferences.set_channels(NotificationEvent.APPOINTMENT_REMINDER, {NotificationChannel.SMS})
    preferences.set_channels(NotificationEvent.NEWS, [])

    await repository.add(preferences)
    session.expunge_all()

    relu = await repository.find_for_account(preferences.account_id)

    assert relu is not None
    assert relu.channels_for(NotificationEvent.APPOINTMENT_REMINDER) == frozenset(
        {NotificationChannel.SMS}
    )
    assert relu.channels_for(NotificationEvent.NEWS) == frozenset()


async def test_the_document_holds_enum_values_and_the_entity_holds_enum_members(
    session: AsyncSession,
) -> None:
    """Le mapping TRADUIT, il ne recopie pas.

    Une entite peuplee de `str` passerait une egalite sur `StrEnum` et casserait
    au premier `frozenset` -- exactement le genre de defaut qu'un
    `Model(**model.__dict__)` introduit sans bruit.
    """
    repository = SqlAlchemyNotificationPreferencesRepository(session)
    preferences = NotificationPreferences.create(account_id=uuid4())
    preferences.set_channels(
        NotificationEvent.APPOINTMENT_REMINDER,
        {NotificationChannel.SMS, NotificationChannel.EMAIL},
    )

    await repository.add(preferences)
    stored = await session.get(NotificationPreferencesModel, preferences.id)

    assert stored is not None
    # Trie a l'ecriture : deux enregistrements du meme etat produisent le meme
    # document, sinon SQLAlchemy verrait une modification a chaque `save`.
    assert stored.channels_by_event == {"appointment_reminder": ["email", "sms"]}

    session.expunge_all()
    relu = await repository.find_for_account(preferences.account_id)
    assert relu is not None
    assert all(
        isinstance(channel, NotificationChannel)
        for channel in relu.channels_for(NotificationEvent.APPOINTMENT_REMINDER)
    )


async def test_a_second_choice_replaces_the_first(session: AsyncSession) -> None:
    """`save` reecrit le document : un JSONB mute en place ne serait pas detecte."""
    repository = SqlAlchemyNotificationPreferencesRepository(session)
    preferences = NotificationPreferences.create(account_id=uuid4())
    preferences.set_channels(NotificationEvent.NEWS, {NotificationChannel.EMAIL})
    await repository.add(preferences)

    preferences.set_channels(NotificationEvent.NEWS, {NotificationChannel.PUSH})
    await repository.save(preferences)
    await session.flush()
    session.expunge_all()

    relu = await repository.find_for_account(preferences.account_id)
    assert relu is not None
    assert relu.channels_for(NotificationEvent.NEWS) == frozenset({NotificationChannel.PUSH})


async def test_an_account_without_any_stored_choice_is_a_nominal_answer(
    session: AsyncSession,
) -> None:
    """`find_` et non `get_` : l'absence est le cas le plus frequent, pas une erreur."""
    repository = SqlAlchemyNotificationPreferencesRepository(session)

    assert await repository.find_for_account(uuid4()) is None


async def test_two_preference_rows_for_one_account_are_impossible(
    session: AsyncSession,
) -> None:
    """L'unicite est PHYSIQUE : deux jeux feraient dependre le resultat de l'ordre de lecture.

    La violation remonte depuis l'`add` lui-meme, et non d'une lecture ulterieure :
    le depot generique flushe a l'inscription, precisement pour que la contrainte
    parle depuis l'ecriture qui l'enfreint.
    """
    repository = SqlAlchemyNotificationPreferencesRepository(session)
    account_id = uuid4()
    await repository.add(NotificationPreferences.create(account_id=account_id))

    with pytest.raises(IntegrityError):
        await repository.add(NotificationPreferences.create(account_id=account_id))


async def test_an_event_the_catalogue_no_longer_knows_is_refused(
    session: AsyncSession,
) -> None:
    """Une valeur perimee LEVE plutot que d'etre ignoree.

    L'avaler en silence rendrait au compte le DEFAUT de l'evenement disparu --
    c'est-a-dire lui enverrait des messages qu'il avait coupes.
    """
    repository = SqlAlchemyNotificationPreferencesRepository(session)
    account_id = uuid4()
    session.add(
        NotificationPreferencesModel(
            id=uuid4(),
            account_id=account_id,
            channels_by_event={"evenement_retire_du_catalogue": ["email"]},
        )
    )
    await session.flush()
    session.expunge_all()

    with pytest.raises(UnknownNotificationEventError):
        await repository.find_for_account(account_id)


async def test_a_channel_the_module_no_longer_knows_is_refused(session: AsyncSession) -> None:
    """Meme regle, meme motif, sur l'autre moitie du document."""
    repository = SqlAlchemyNotificationPreferencesRepository(session)
    account_id = uuid4()
    session.add(
        NotificationPreferencesModel(
            id=uuid4(),
            account_id=account_id,
            channels_by_event={"news": ["pigeon_voyageur"]},
        )
    )
    await session.flush()
    session.expunge_all()

    with pytest.raises(UnknownNotificationChannelError):
        await repository.find_for_account(account_id)
