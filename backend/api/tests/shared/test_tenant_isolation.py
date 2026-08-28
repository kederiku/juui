"""Tests d'isolation multi-tenant : la preuve que le cloisonnement tient (BACK-06b).

Les tests travaillent au niveau DEPOT, sans HTTP : les routes n'existent pas
avant BACK-10c, et c'est le depot qui porte le filtre. La semantique « 404,
jamais 403 » s'y verifie a la source -- une ressource d'un autre groupe leve la
MEME erreur d'absence qu'un identifiant inexistant, et la traduction HTTP de
`DomainError` n'a rien a distinguer.

Le semis des donnees passe par la session BRUTE (`session.add` + `flush`),
qui contourne le depot : c'est la verite terrain a laquelle chaque test
compare le comportement filtre.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.domain.pagination import PageRequest
from app.shared.infrastructure.tenancy import (
    MissingTenantContextError,
    use_all_groups,
    use_group,
)
from tests.support.tenancy_stubs import (
    PlainNote,
    PlainNoteRepository,
    TenantNote,
    TenantNoteModel,
    TenantNoteNotFoundError,
    TenantNoteRepository,
    make_tenant_row,
)

pytestmark = pytest.mark.tenant_isolation


async def _seed(session: AsyncSession, group_id: UUID, label: str) -> TenantNoteModel:
    """Seme une note tenant par la session brute et la rend visible au bloc."""
    row = make_tenant_row(uuid4(), group_id, label)
    session.add(row)
    await session.flush()
    return row


async def test_cross_group_get_is_indistinguishable_from_absence(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    """Une ressource d'un autre groupe repond comme une ressource inexistante."""
    note_b = await _seed(session, group_b, "note du groupe B")
    repository = TenantNoteRepository(session)
    with use_group(group_a):
        with pytest.raises(TenantNoteNotFoundError) as cross_error:
            await repository.get(note_b.id)
        with pytest.raises(TenantNoteNotFoundError) as absent_error:
            await repository.get(uuid4())
    # Meme type et meme gabarit de message : rien ne confirme que la ressource
    # existe ailleurs -- au niveau HTTP, ce sera un 404 et jamais un 403.
    assert type(cross_error.value) is type(absent_error.value)
    assert str(cross_error.value) == f"Aucune note tenant ne porte l'identifiant {note_b.id}."


async def test_cross_group_rows_stay_out_of_list(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    note_a = await _seed(session, group_a, "note du groupe A")
    await _seed(session, group_b, "note du groupe B")
    repository = TenantNoteRepository(session)
    with use_group(group_a):
        notes = (await repository.list(PageRequest())).items
    assert [note.id for note in notes] == [note_a.id]


async def test_locum_context_only_sees_the_active_group(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    """Cas du remplacant : un jeton emis pour A ne voit rien du groupe B.

    Au niveau du socle, le cas se reduit a « contexte pose sur A, donnee du
    groupe B » -- c'est exactement ce que produit un jeton dont le claim
    `active_group_id` vaut A entre les mains d'un remplacant des deux groupes.
    Depuis BACK-16, l'appartenance N:M datee est modelisee et le scenario
    entier -- deux appartenances reelles, une affectation par groupe -- est
    rejoue sur les vraies tables par
    `tests/modules/organization/test_ports.py::test_locum_assignments_stay_in_the_active_group`.
    """
    note_a = await _seed(session, group_a, "consultation chez A")
    note_b = await _seed(session, group_b, "consultation chez B")
    repository = TenantNoteRepository(session)
    with use_group(group_a):
        visible = await repository.get(note_a.id)
        assert visible.label == "consultation chez A"
        with pytest.raises(TenantNoteNotFoundError):
            await repository.get(note_b.id)


async def test_non_tenant_aggregate_works_without_group(session: AsyncSession) -> None:
    """Un agregat sans `TenantMixin` vit hors de tout contexte de groupe."""
    repository = PlainNoteRepository(session)
    note = PlainNote(id=uuid4(), label="notice partagee")
    await repository.add(note)
    assert (await repository.get(note.id)).label == "notice partagee"
    assert [item.id for item in (await repository.list(PageRequest())).items] == [note.id]


async def test_cross_group_save_is_refused(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    note_b = await _seed(session, group_b, "etat d'origine")
    repository = TenantNoteRepository(session)
    with use_group(group_a), pytest.raises(TenantNoteNotFoundError):
        await repository.save(TenantNote(id=note_b.id, label="reecriture pirate"))
    # Verite terrain : la ligne du groupe B n'a pas bouge.
    assert note_b.label == "etat d'origine"


async def test_cross_group_delete_is_refused(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    note_b = await _seed(session, group_b, "a proteger")
    repository = TenantNoteRepository(session)
    with use_group(group_a), pytest.raises(TenantNoteNotFoundError):
        await repository.delete(note_b.id)
    survivor = await session.get(TenantNoteModel, note_b.id)
    assert survivor is not None


async def test_add_stamps_the_current_group(session: AsyncSession, group_a: UUID) -> None:
    """L'insertion recoit `group_id` du contexte, jamais de l'entite."""
    note_id = uuid4()
    repository = TenantNoteRepository(session)
    with use_group(group_a):
        await repository.add(TenantNote(id=note_id, label="estampillee"))
    row = await session.get(TenantNoteModel, note_id)
    assert row is not None
    assert row.group_id == group_a


async def test_add_without_group_raises_and_inserts_nothing(session: AsyncSession) -> None:
    note_id = uuid4()
    repository = TenantNoteRepository(session)
    with pytest.raises(MissingTenantContextError):
        await repository.add(TenantNote(id=note_id, label="orpheline"))
    assert await session.get(TenantNoteModel, note_id) is None


async def test_reads_without_group_raise_instead_of_returning_everything(
    session: AsyncSession, group_b: UUID
) -> None:
    """Sans contexte, une lecture tenant echoue -- jamais « toutes les donnees »."""
    await _seed(session, group_b, "invisible hors contexte")
    repository = TenantNoteRepository(session)
    with pytest.raises(MissingTenantContextError):
        await repository.get(uuid4())
    with pytest.raises(MissingTenantContextError):
        await repository.list(PageRequest())


async def test_use_all_groups_reads_everything_but_writes_nowhere(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    """L'echappatoire nommee voit tous les groupes ; ecrire exige toujours UN groupe."""
    note_a = await _seed(session, group_a, "note du groupe A")
    note_b = await _seed(session, group_b, "note du groupe B")
    repository = TenantNoteRepository(session)
    with use_all_groups(reason="test : lecture transverse assumee"):
        listed = (await repository.list(PageRequest())).items
        assert {note.id for note in listed} == {note_a.id, note_b.id}
        assert (await repository.get(note_b.id)).label == "note du groupe B"
        with pytest.raises(MissingTenantContextError):
            await repository.add(TenantNote(id=uuid4(), label="refusee"))
        # Ecrire sous l'echappatoire passe par un bloc `use_group` imbrique :
        # le patron du seed (INFRA-08).
        nested_id = uuid4()
        with use_group(group_a):
            await repository.add(TenantNote(id=nested_id, label="ecrite chez A"))
    row = await session.get(TenantNoteModel, nested_id)
    assert row is not None
    assert row.group_id == group_a


async def test_use_all_groups_does_not_survive_its_block(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    """Le mode « tous groupes » est un bloc, pas un etat : rien n'en fuit."""
    note_b = await _seed(session, group_b, "note du groupe B")
    repository = TenantNoteRepository(session)
    with use_all_groups(reason="test : bloc referme aussitot"):
        assert (await repository.get(note_b.id)).id == note_b.id
    with use_group(group_a), pytest.raises(TenantNoteNotFoundError):
        await repository.get(note_b.id)
    with pytest.raises(MissingTenantContextError):
        await repository.get(note_b.id)


async def test_use_all_groups_requires_a_written_reason() -> None:
    with pytest.raises(ValueError, match="raison"), use_all_groups(reason="   "):
        pass


async def test_background_task_pattern_reapplies_the_filter(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    """Legs de BACK-15 : le `group_id` voyage en argument et repose le contexte.

    Reproduit le patron de `tasks/demo.py` (`record_ping`) sans broker : la
    tache recoit l'identifiant serialisable, ouvre `use_group(group_id)` en
    premiere instruction, et le filtre du depot s'applique comme dans l'API.
    """
    await _seed(session, group_a, "vue par la tache A")
    await _seed(session, group_b, "vue par la tache B")

    async def fake_task(group_id: UUID) -> list[str]:
        with use_group(group_id):
            result = await TenantNoteRepository(session).list(PageRequest())
            return [note.label for note in result.items]

    assert await fake_task(group_a) == ["vue par la tache A"]
    assert await fake_task(group_b) == ["vue par la tache B"]


async def test_seeded_rows_are_really_there(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    """Garde du harnais : le semis brut contourne bien le filtre du depot."""
    await _seed(session, group_a, "temoin A")
    await _seed(session, group_b, "temoin B")
    statement = select(func.count()).select_from(TenantNoteModel)
    assert (await session.execute(statement)).scalar_one() == 2
