"""Gardes propres au socle de depot en memoire (BACK-06c).

Ce que la conformite ne peut pas comparer : ce qui protege la DOUBLURE d'elle-meme.
Une doublure qui rendrait ses entites par reference, ou qui ecraserait en silence
une entite existante, ferait passer des tests en ne prouvant rien -- et la suite
de conformite, qui compare des comportements observables, ne le verrait pas.
"""

from uuid import uuid4

import pytest

from app.shared.domain.pagination import PageRequest
from app.shared.infrastructure.memory.repository import InMemoryRepository, InMemoryStore
from app.shared.infrastructure.tenancy import use_group
from tests.shared.tenancy_stubs import (
    InMemoryNoteUnitOfWork,
    InMemoryPlainNoteRepository,
    PlainNote,
    PlainNoteNotFoundError,
    TenantNote,
)

pytestmark = pytest.mark.conformance


async def test_a_returned_entity_is_a_copy_of_the_stored_one() -> None:
    """LA garde qui rend les tests d'annulation significatifs.

    Un depot qui rendrait l'objet range laisserait une mutation NON VALIDEE
    modifier l'etat « persiste ». Le test « une exception avant le commit n'ecrit
    rien » passerait alors sans rien prouver -- il compare deux references au meme
    objet.
    """
    uow = InMemoryNoteUnitOfWork()
    note = PlainNote(id=uuid4(), label="etat range")
    async with uow:
        await uow.plain_notes.add(note)
        await uow.commit()
        relu = await uow.plain_notes.get(note.id)
        relu.label = "mutation hors transaction"
        assert (await uow.plain_notes.get(note.id)).label == "etat range"


async def test_the_entity_handed_to_add_is_copied_too() -> None:
    """L'aliasing coupe DANS LES DEUX SENS : ce que l'appelant garde en main."""
    uow = InMemoryNoteUnitOfWork()
    note = PlainNote(id=uuid4(), label="a la creation")
    async with uow:
        await uow.plain_notes.add(note)
        await uow.commit()
    note.label = "modifie apres coup"
    async with uow:
        assert (await uow.plain_notes.get(note.id)).label == "a la creation"


async def test_adding_twice_the_same_identifier_is_refused() -> None:
    """Ecraser en silence est le seul comportement qu'aucune base n'a."""
    uow = InMemoryNoteUnitOfWork()
    note = PlainNote(id=uuid4(), label="premiere")
    async with uow:
        await uow.plain_notes.add(note)
        with pytest.raises(RuntimeError, match="porte deja l'identifiant"):
            await uow.plain_notes.add(PlainNote(id=note.id, label="seconde"))


async def test_an_identifier_deleted_in_the_block_can_be_added_again() -> None:
    """Le corollaire : la collision porte sur ce que le BLOC voit, pas sur l'historique."""
    uow = InMemoryNoteUnitOfWork()
    note = PlainNote(id=uuid4(), label="premiere")
    async with uow:
        await uow.plain_notes.add(note)
        await uow.commit()
        await uow.plain_notes.delete(note.id)
        await uow.plain_notes.add(PlainNote(id=note.id, label="renaissance"))
        await uow.commit()
    async with uow:
        assert (await uow.plain_notes.get(note.id)).label == "renaissance"


def test_a_repository_without_its_class_attributes_is_refused() -> None:
    """Mypy ne voit pas cet oubli : les annotations de la base lui font croire le contraire."""

    class IncompleteRepository(InMemoryRepository[PlainNote]):
        """Doublure qui oublie ses deux attributs de configuration."""

    with pytest.raises(TypeError, match="_not_found_error"):
        IncompleteRepository(InMemoryStore())


async def test_the_store_survives_the_block_and_the_repository_does_not() -> None:
    """Le magasin tient lieu de base : il survit au bloc comme une base a une session."""
    uow = InMemoryNoteUnitOfWork()
    note = PlainNote(id=uuid4(), label="durable")
    async with uow:
        await uow.plain_notes.add(note)
        await uow.commit()
    assert uow.plain_store.committed_entity(note.id) == note
    with pytest.raises(RuntimeError):
        _ = uow.plain_notes


async def test_the_commit_counter_tells_how_many_times_the_block_validated() -> None:
    uow = InMemoryNoteUnitOfWork()
    assert uow.commits == 0
    async with uow:
        await uow.plain_notes.add(PlainNote(id=uuid4(), label="une"))
        await uow.commit()
        await uow.plain_notes.add(PlainNote(id=uuid4(), label="deux"))
        await uow.commit()
    assert uow.commits == 2


async def test_a_commit_folds_every_store_of_the_unit() -> None:
    """L'atomicite entre depots d'un meme module : tous les magasins, ou aucun."""
    uow = InMemoryNoteUnitOfWork()
    group = uuid4()
    plain = PlainNote(id=uuid4(), label="partagee")
    tenant = TenantNote(id=uuid4(), label="tenant")
    async with uow:
        await uow.plain_notes.add(plain)
        with use_group(group):
            await uow.tenant_notes.add(tenant)
    assert uow.plain_store.committed_entity(plain.id) is None
    assert uow.tenant_store.committed_entity(tenant.id) is None


async def test_a_seeded_state_is_visible_without_any_commit() -> None:
    """Le semis contourne le depot, comme la session brute des tests d'integration."""
    uow = InMemoryNoteUnitOfWork()
    note = PlainNote(id=uuid4(), label="semee")
    uow.plain_store.seed(note)
    async with uow:
        assert (await uow.plain_notes.get(note.id)).label == "semee"


async def test_a_repository_reads_the_store_it_was_given() -> None:
    """Le depot est une enveloppe SANS ETAT : deux instances voient la meme chose."""
    store: InMemoryStore[PlainNote] = InMemoryStore()
    note = PlainNote(id=uuid4(), label="commune")
    store.seed(note)
    first = InMemoryPlainNoteRepository(store)
    second = InMemoryPlainNoteRepository(store)
    await first.delete(note.id)
    with pytest.raises(PlainNoteNotFoundError):
        await second.get(note.id)
    assert (await second.list(PageRequest())).total == 0
