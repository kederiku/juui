"""Tests d'integration des lectures publiques du module medical_records (BACK-19).

Le semis passe par la session BRUTE -- la verite terrain a laquelle chaque
test compare le comportement des depots. Aucune tenance ici : ni `animals` ni
`custodies` n'est tenant, et aucun test ne pose de contexte de groupe -- c'est
la preuve en creux du ticket. Les tests ne committent jamais ; le rollback du
teardown annule tout.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.medical_records.domain.entities import (
    Animal,
    AnimalSex,
    Custody,
    Species,
    SterilizationStatus,
)
from app.modules.medical_records.domain.exceptions import InvalidWindowError
from app.modules.medical_records.infrastructure.db.models import AnimalModel, CustodyModel
from app.modules.medical_records.infrastructure.db.repositories import (
    SqlAlchemyAnimalRepository,
    SqlAlchemyCustodyRepository,
)

# Les deux tables du module naissent avec la fixture de session du conftest
# local -- demandee ici, et seulement ici : les tests purs n'exigent pas Docker.
pytestmark = pytest.mark.usefixtures("_medical_records_tables")

_AT = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
_FIRST_START = _AT - timedelta(days=90)
_HANDOVER_AT = _AT - timedelta(days=30)


async def _seed_animal(session: AsyncSession, animal_id: UUID) -> AnimalModel:
    """Seme une fiche animal minimale par la session brute."""
    model = AnimalModel(
        id=animal_id,
        name=f"animal {animal_id.hex[:8]}",
        species=Species.DOG.value,
        sex=AnimalSex.UNKNOWN.value,
        sterilization=SterilizationStatus.UNKNOWN.value,
    )
    session.add(model)
    await session.flush()
    return model


async def _seed_custody(
    session: AsyncSession,
    animal_id: UUID,
    account_id: UUID,
    *,
    start_at: datetime = _FIRST_START,
    end_at: datetime | None = None,
) -> CustodyModel:
    """Seme une detention sur la fenetre donnee, rendue pour les mutations du test."""
    model = CustodyModel(
        id=uuid4(),
        animal_id=animal_id,
        account_id=account_id,
        start_at=start_at,
        end_at=end_at,
    )
    session.add(model)
    await session.flush()
    return model


async def test_two_successive_custodies_keep_history_intact(session: AsyncSession) -> None:
    """LE test du critere 4 : deux detentions successives, l'historique intact.

    L'animal change de detenteur : la premiere fenetre est close, la seconde
    ouverte au meme instant. Aucune ligne n'est reecrite -- la question
    d'audit « qui detenait l'animal a J-60 » repond toujours le premier
    compte, et la detention en vigueur aujourd'hui est la seconde.
    """
    animal_id = uuid4()
    await _seed_animal(session, animal_id)
    first_account, second_account = uuid4(), uuid4()
    await _seed_custody(
        session, animal_id, first_account, start_at=_FIRST_START, end_at=_HANDOVER_AT
    )
    await _seed_custody(session, animal_id, second_account, start_at=_HANDOVER_AT)
    repository = SqlAlchemyCustodyRepository(session)

    history = await repository.list_for_animal(animal_id)
    past = await repository.find_active_for_animal(animal_id, _AT - timedelta(days=60))
    current = await repository.find_active_for_animal(animal_id, _AT)

    assert [custody.account_id for custody in history] == [first_account, second_account]
    assert (history[0].start_at, history[0].end_at) == (_FIRST_START, _HANDOVER_AT)
    assert (history[1].start_at, history[1].end_at) == (_HANDOVER_AT, None)
    assert past is not None and past.account_id == first_account
    assert current is not None and current.account_id == second_account


async def test_find_active_custody_without_cover_returns_none(session: AsyncSession) -> None:
    """L'absence est un RESULTAT : un animal cede n'a pas de detention en vigueur."""
    animal_id = uuid4()
    await _seed_animal(session, animal_id)
    await _seed_custody(session, animal_id, uuid4(), start_at=_FIRST_START, end_at=_HANDOVER_AT)
    repository = SqlAlchemyCustodyRepository(session)

    assert await repository.find_active_for_animal(animal_id, _AT) is None
    assert await repository.find_active_for_animal(uuid4(), _AT) is None


async def test_custody_activity_respects_the_half_open_window(session: AsyncSession) -> None:
    """`[start_at, end_at)` en SQL comme dans le domaine : debut inclus, fin exclue."""
    animal_id = uuid4()
    await _seed_animal(session, animal_id)
    await _seed_custody(session, animal_id, uuid4(), start_at=_FIRST_START, end_at=_HANDOVER_AT)
    repository = SqlAlchemyCustodyRepository(session)

    assert await repository.find_active_for_animal(animal_id, _FIRST_START) is not None
    assert await repository.find_active_for_animal(animal_id, _HANDOVER_AT) is None


async def test_animals_with_active_custody_are_listed_for_account(session: AsyncSession) -> None:
    """La requete de BACK-30 : seuls les animaux a detention ACTIVE du compte."""
    account_id = uuid4()
    kept_id, ceded_id, foreign_id = uuid4(), uuid4(), uuid4()
    for animal_id in (kept_id, ceded_id, foreign_id):
        await _seed_animal(session, animal_id)
    await _seed_custody(session, kept_id, account_id)
    await _seed_custody(session, ceded_id, account_id, start_at=_FIRST_START, end_at=_HANDOVER_AT)
    await _seed_custody(session, foreign_id, uuid4())

    animals = await SqlAlchemyAnimalRepository(session).list_with_active_custody_for_account(
        account_id, _AT
    )

    # L'animal cede a disparu de la liste -- pas de l'historique -- et ceux
    # d'un autre compte n'apparaissent jamais.
    assert [animal.id for animal in animals] == [kept_id]


async def test_second_open_custody_is_refused_by_the_database(session: AsyncSession) -> None:
    """Le critere 1 rendu physique : deux detentions OUVERTES du meme animal."""
    animal_id = uuid4()
    await _seed_animal(session, animal_id)
    await _seed_custody(session, animal_id, uuid4())

    with pytest.raises(IntegrityError):
        await _seed_custody(session, animal_id, uuid4(), start_at=_HANDOVER_AT)


async def test_open_custodies_of_distinct_animals_coexist(session: AsyncSession) -> None:
    """L'unicite est PAR ANIMAL : deux animaux gardent chacun leur detention ouverte."""
    first_animal, second_animal = uuid4(), uuid4()
    await _seed_animal(session, first_animal)
    await _seed_animal(session, second_animal)
    await _seed_custody(session, first_animal, uuid4())
    await _seed_custody(session, second_animal, uuid4())

    assert await SqlAlchemyCustodyRepository(session).find_active_for_animal(second_animal, _AT)


async def test_closed_custodies_do_not_trip_the_partial_index(session: AsyncSession) -> None:
    """L'index ne contraint que l'OUVERTE : l'historique s'accumule librement."""
    animal_id = uuid4()
    await _seed_animal(session, animal_id)
    await _seed_custody(
        session, animal_id, uuid4(), start_at=_FIRST_START, end_at=_FIRST_START + timedelta(days=10)
    )
    await _seed_custody(
        session, animal_id, uuid4(), start_at=_FIRST_START, end_at=_FIRST_START + timedelta(days=20)
    )
    await _seed_custody(session, animal_id, uuid4(), start_at=_HANDOVER_AT)

    history = await SqlAlchemyCustodyRepository(session).list_for_animal(animal_id)

    assert len(history) == 3


async def test_transfer_closes_before_opening_the_next_custody(session: AsyncSession) -> None:
    """Le transfert dans UNE transaction : clore d'abord, ouvrir ensuite."""
    animal_id = uuid4()
    await _seed_animal(session, animal_id)
    previous = await _seed_custody(session, animal_id, uuid4())

    previous.end_at = _AT
    await session.flush()
    await _seed_custody(session, animal_id, uuid4(), start_at=_AT)

    current = await SqlAlchemyCustodyRepository(session).find_active_for_animal(animal_id, _AT)
    assert current is not None and current.start_at == _AT


async def test_transfer_through_the_repositories_follows_the_documented_recipe(
    session: AsyncSession,
) -> None:
    """La recette clore-puis-ouvrir tient via les depots livres, pas seulement en SQL brut.

    C'est le chemin d'ecriture que BACK-30 consommera : `save` pose la cloture
    sur la ligne suivie SANS la flusher (`autoflush=False`), et c'est le `add`
    du depot qui emet les changements pendants avant son INSERT -- sans quoi
    l'index unique partiel, non differable, refuserait un transfert pourtant
    ecrit dans l'ordre documente.
    """
    animal_id = uuid4()
    await _seed_animal(session, animal_id)
    repository = SqlAlchemyCustodyRepository(session)
    previous = Custody.create(animal_id=animal_id, account_id=uuid4(), start_at=_FIRST_START)
    await repository.add(previous)

    previous.end_at = _AT
    await repository.save(previous)
    await repository.add(Custody.create(animal_id=animal_id, account_id=uuid4(), start_at=_AT))

    history = await repository.list_for_animal(animal_id)
    assert [custody.end_at for custody in history] == [_AT, None]


async def test_opening_before_closing_is_refused_by_the_partial_index(
    session: AsyncSession,
) -> None:
    """L'index partiel n'est pas DIFFERABLE : l'ordre inverse echoue au flush.

    Meme si la transaction avait fini coherente, inserer la nouvelle detention
    avant d'avoir clos l'ancienne leve -- le piege documente dans `models.py`,
    que tout cas d'usage de transfert (BACK-30) devra contourner en clotant
    d'abord.
    """
    animal_id = uuid4()
    await _seed_animal(session, animal_id)
    await _seed_custody(session, animal_id, uuid4())

    with pytest.raises(IntegrityError):
        await _seed_custody(session, animal_id, uuid4(), start_at=_AT)


async def test_custody_with_unknown_animal_is_refused_by_the_database(
    session: AsyncSession,
) -> None:
    """`custodies.animal_id` reference `animals` : une fiche inconnue ne s'insere pas."""
    with pytest.raises(IntegrityError):
        await _seed_custody(session, uuid4(), uuid4())


async def test_animal_with_custodies_cannot_be_deleted(session: AsyncSession) -> None:
    """Un dossier se conserve : la suppression d'un animal detenu echoue bruyamment."""
    animal_id = uuid4()
    animal = await _seed_animal(session, animal_id)
    await _seed_custody(session, animal_id, uuid4())

    await session.delete(animal)
    with pytest.raises(IntegrityError):
        await session.flush()


async def test_inverted_window_is_refused_by_the_database(session: AsyncSession) -> None:
    """`ck_custodies_window_bounds` : une fin anterieure au debut ne s'insere pas."""
    animal_id = uuid4()
    await _seed_animal(session, animal_id)

    with pytest.raises(IntegrityError):
        await _seed_custody(
            session, animal_id, uuid4(), start_at=_AT, end_at=_AT - timedelta(days=1)
        )


async def test_animal_table_carries_no_tenant_column(session: AsyncSession) -> None:
    """Le critere 1 rendu executable : aucune colonne de tenance sur les deux tables."""
    assert "group_id" not in AnimalModel.__table__.columns
    assert "group_id" not in CustodyModel.__table__.columns


async def test_naive_reference_instant_is_refused_before_any_query(
    session: AsyncSession,
) -> None:
    """Un `at` naif leve en erreur metier AVANT le SQL -- jamais interprete en silence.

    Sans la garde, PostgreSQL lierait le naif a un `timestamptz` en
    l'interpretant dans le fuseau de la session : une detention close
    redeviendrait active a deux heures pres, sans aucun signal.
    """
    naive_at = datetime(2026, 8, 25, 12, 0)

    with pytest.raises(InvalidWindowError):
        await SqlAlchemyCustodyRepository(session).find_active_for_animal(uuid4(), naive_at)
    with pytest.raises(InvalidWindowError):
        await SqlAlchemyAnimalRepository(session).list_with_active_custody_for_account(
            uuid4(), naive_at
        )


async def test_animal_round_trips_through_the_repository(session: AsyncSession) -> None:
    """Aller-retour depot : enums et date preserves, dans les types du domaine."""
    animal = Animal.create(
        name="Caramel",
        species=Species.CAT,
        breed="europeen",
        sex=AnimalSex.FEMALE,
        sterilization=SterilizationStatus.STERILIZED,
        microchip_number="250269604213456",
    )
    repository = SqlAlchemyAnimalRepository(session)
    await repository.add(animal)

    loaded = await repository.get(animal.id)

    assert loaded == animal
    assert loaded.species is Species.CAT
    assert loaded.sterilization is SterilizationStatus.STERILIZED
