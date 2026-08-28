"""Conformite du depot et de l'unite de travail : le reel et la doublure (BACK-06c).

Une seule suite, deux sujets. `TestSqlAlchemyNoteConformance` la joue contre
PostgreSQL par la base de test, `TestInMemoryNoteConformance` contre les
dictionnaires du paquet `shared/infrastructure/memory/`. Un comportement qui ne
serait vrai que d'un cote fait echouer la moitie correspondante, et c'est tout ce
qu'on lui demande.

CE QUE LA SUITE COUVRE, ET DANS QUEL ORDRE
Les trois regles du port d'unite de travail, les cinq operations du protocole de
depot, la convention de pagination (BACK-24) et le filtre de tenance (BACK-06b).
Les quatre sujets sont indissociables : un rollback qui n'annule pas une
suppression, ou un total qui compte hors du groupe actif, sont des divergences de
meme nature -- une doublure qui affirme quelque chose que la production ne tient
pas.

LA MOITIE REELLE COMMITE POUR DE BON, et il le faut : « commit et rollback ont un
effet reel observable » ne se prouve pas sur une transaction qu'une fixture
annulera. Les deux tables stubs sont donc PURGEES avant et apres chaque test,
plutot que protegees par le rollback de la fixture `session`. Elles n'existent
que dans la base de test et ne portent aucune donnee applicative.
"""

from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.shared.domain.pagination import (
    PageRequest,
    Sort,
    SortDirection,
    UnknownSortFieldError,
)
from app.shared.infrastructure.tenancy import (
    MissingTenantContextError,
    use_all_groups,
    use_group,
)
from tests.shared.tenancy_stubs import (
    InMemoryNoteUnitOfWork,
    NoteUnitOfWork,
    PlainNote,
    PlainNoteNotFoundError,
    SqlAlchemyNoteUnitOfWork,
    TenantNote,
    TenantNoteNotFoundError,
)

pytestmark = pytest.mark.conformance


def a_plain_note(label: str = "notice") -> PlainNote:
    """Une note non tenant, identifiant neuf."""
    return PlainNote(id=uuid4(), label=label)


def a_tenant_note(label: str = "consultation") -> TenantNote:
    """Une note tenant, identifiant neuf. PAS de groupe : le socle l'estampille."""
    return TenantNote(id=uuid4(), label=label)


class NoteUnitOfWorkConformance:
    """La suite commune. Les sous-classes ne fournissent que la fixture `uow`.

    Elle ne s'appelle pas `Test...` : pytest ne la collecte pas, et un test
    ajoute ici est mecaniquement joue par les deux sous-classes.
    """

    @pytest.fixture
    def uow(self) -> NoteUnitOfWork:
        """Le sujet sous test -- fourni par la sous-classe."""
        raise NotImplementedError

    # --- Les trois regles du port d'unite de travail ------------------------

    async def test_repositories_are_unreachable_outside_a_block(self, uow: NoteUnitOfWork) -> None:
        """Regle 3 : la transaction vit dans le bloc, les depots aussi."""
        with pytest.raises(RuntimeError):
            _ = uow.plain_notes

    async def test_commit_outside_a_block_raises(self, uow: NoteUnitOfWork) -> None:
        with pytest.raises(RuntimeError):
            await uow.commit()

    async def test_rollback_outside_a_block_raises(self, uow: NoteUnitOfWork) -> None:
        with pytest.raises(RuntimeError):
            await uow.rollback()

    async def test_entering_an_open_unit_raises(self, uow: NoteUnitOfWork) -> None:
        """Regle 2 : un seul bloc a la fois, l'imbrication est un defaut."""
        async with uow:
            with pytest.raises(RuntimeError):
                await uow.__aenter__()

    async def test_the_unit_can_be_reopened_after_the_block(self, uow: NoteUnitOfWork) -> None:
        """Regle 2, seconde moitie : rouvrir la MEME unite est permis."""
        note = a_plain_note()
        async with uow:
            await uow.plain_notes.add(note)
            await uow.commit()
        async with uow:
            assert (await uow.plain_notes.get(note.id)).label == "notice"

    # --- Les cinq operations du protocole de depot --------------------------

    async def test_get_of_an_unknown_identifier_raises_the_module_error(
        self, uow: NoteUnitOfWork
    ) -> None:
        async with uow:
            with pytest.raises(PlainNoteNotFoundError):
                await uow.plain_notes.get(uuid4())

    async def test_an_addition_is_visible_inside_its_own_block(self, uow: NoteUnitOfWork) -> None:
        """Ecrire, c'est inscrire dans le bloc courant -- et le bloc le relit."""
        note = a_plain_note()
        async with uow:
            await uow.plain_notes.add(note)
            assert (await uow.plain_notes.get(note.id)).label == "notice"

    async def test_commit_makes_the_write_durable(self, uow: NoteUnitOfWork) -> None:
        note = a_plain_note()
        async with uow:
            await uow.plain_notes.add(note)
            await uow.commit()
        async with uow:
            assert (await uow.plain_notes.get(note.id)).id == note.id

    async def test_leaving_the_block_without_commit_writes_nothing(
        self, uow: NoteUnitOfWork
    ) -> None:
        """LE critere 1 : le rollback de sortie a un effet reel et observable."""
        note = a_plain_note()
        async with uow:
            await uow.plain_notes.add(note)
        async with uow:
            with pytest.raises(PlainNoteNotFoundError):
                await uow.plain_notes.get(note.id)

    async def test_an_exception_inside_the_block_writes_nothing(self, uow: NoteUnitOfWork) -> None:
        note = a_plain_note()
        boom = "Le cas d'usage a echoue apres l'ecriture."
        with pytest.raises(RuntimeError, match="a echoue"):
            async with uow:
                await uow.plain_notes.add(note)
                raise RuntimeError(boom)
        async with uow:
            with pytest.raises(PlainNoteNotFoundError):
                await uow.plain_notes.get(note.id)

    async def test_explicit_rollback_discards_the_write_inside_the_block(
        self, uow: NoteUnitOfWork
    ) -> None:
        """Annuler PUIS continuer dans le meme bloc : le cas que le port prevoit."""
        note = a_plain_note()
        async with uow:
            await uow.plain_notes.add(note)
            await uow.rollback()
            with pytest.raises(PlainNoteNotFoundError):
                await uow.plain_notes.get(note.id)

    async def test_save_reports_the_new_state(self, uow: NoteUnitOfWork) -> None:
        note = a_plain_note("avant")
        async with uow:
            await uow.plain_notes.add(note)
            await uow.plain_notes.save(PlainNote(id=note.id, label="apres"))
            await uow.commit()
        async with uow:
            assert (await uow.plain_notes.get(note.id)).label == "apres"

    async def test_save_of_an_unknown_entity_raises(self, uow: NoteUnitOfWork) -> None:
        async with uow:
            with pytest.raises(PlainNoteNotFoundError):
                await uow.plain_notes.save(a_plain_note())

    async def test_delete_is_visible_inside_its_own_block(self, uow: NoteUnitOfWork) -> None:
        """Une suppression est une ecriture : le bloc doit la voir tout de suite."""
        note = a_plain_note()
        async with uow:
            await uow.plain_notes.add(note)
            await uow.commit()
            await uow.plain_notes.delete(note.id)
            with pytest.raises(PlainNoteNotFoundError):
                await uow.plain_notes.get(note.id)

    async def test_delete_is_undone_by_the_exit_rollback(self, uow: NoteUnitOfWork) -> None:
        """La moitie du critere 1 qu'une doublure sans suppressions en attente rate."""
        note = a_plain_note()
        async with uow:
            await uow.plain_notes.add(note)
            await uow.commit()
        async with uow:
            await uow.plain_notes.delete(note.id)
        async with uow:
            assert (await uow.plain_notes.get(note.id)).id == note.id

    async def test_a_second_delete_raises(self, uow: NoteUnitOfWork) -> None:
        note = a_plain_note()
        async with uow:
            await uow.plain_notes.add(note)
            await uow.commit()
            await uow.plain_notes.delete(note.id)
            with pytest.raises(PlainNoteNotFoundError):
                await uow.plain_notes.delete(note.id)

    async def test_delete_of_an_unknown_identifier_raises(self, uow: NoteUnitOfWork) -> None:
        async with uow:
            with pytest.raises(PlainNoteNotFoundError):
                await uow.plain_notes.delete(uuid4())

    # --- La convention de pagination (BACK-24) ------------------------------

    async def test_default_order_is_by_identifier(self, uow: NoteUnitOfWork) -> None:
        """Sans tri demande, la cle primaire seule -- et le meme ordre des deux cotes."""
        notes = [a_plain_note(f"note {index}") for index in range(3)]
        async with uow:
            for note in notes:
                await uow.plain_notes.add(note)
            await uow.commit()
            page = await uow.plain_notes.list(PageRequest())
        assert [item.id for item in page.items] == sorted(note.id for note in notes)

    async def test_the_window_and_the_total_follow_the_convention(
        self, uow: NoteUnitOfWork
    ) -> None:
        notes = [a_plain_note(f"note {index}") for index in range(5)]
        async with uow:
            for note in notes:
                await uow.plain_notes.add(note)
            await uow.commit()
            page = await uow.plain_notes.list(PageRequest(page=2, page_size=2))
        assert page.total == 5
        assert page.page == 2
        assert page.page_size == 2
        assert [item.id for item in page.items] == sorted(note.id for note in notes)[2:4]

    async def test_a_page_beyond_the_end_is_empty_and_carries_the_real_total(
        self, uow: NoteUnitOfWork
    ) -> None:
        """Une page est une fenetre, pas une ressource : jamais d'erreur d'absence."""
        async with uow:
            await uow.plain_notes.add(a_plain_note())
            await uow.commit()
            page = await uow.plain_notes.list(PageRequest(page=9, page_size=10))
        assert page.items == []
        assert page.total == 1

    async def test_sorting_on_a_whitelisted_field(self, uow: NoteUnitOfWork) -> None:
        async with uow:
            for label in ("charlie", "alpha", "bravo"):
                await uow.plain_notes.add(a_plain_note(label))
            await uow.commit()
            ascending = await uow.plain_notes.list(PageRequest(sort=Sort(field="label")))
            descending = await uow.plain_notes.list(
                PageRequest(sort=Sort(field="label", direction=SortDirection.DESC))
            )
        assert [item.label for item in ascending.items] == ["alpha", "bravo", "charlie"]
        assert [item.label for item in descending.items] == ["charlie", "bravo", "alpha"]

    async def test_a_saved_change_is_visible_to_a_sorted_list_in_the_same_block(
        self, uow: NoteUnitOfWork
    ) -> None:
        """Une modification non validee doit deja ordonner la page de son bloc.

        Le pendant de la visibilite d'une addition, sur le chemin des LISTES. Sans
        elle, un cas d'usage qui modifie puis liste dans la meme transaction recoit
        une page ordonnee sur l'etat d'AVANT sa propre ecriture -- des elements
        justes, dans un ordre faux, et rien pour le signaler.
        """
        first = a_plain_note("zoulou")
        second = a_plain_note("mike")
        async with uow:
            await uow.plain_notes.add(first)
            await uow.plain_notes.add(second)
            await uow.commit()
            await uow.plain_notes.save(PlainNote(id=first.id, label="alpha"))
            page = await uow.plain_notes.list(PageRequest(sort=Sort(field="label")))
        assert [item.label for item in page.items] == ["alpha", "mike"]

    async def test_an_unknown_sort_field_is_refused(self, uow: NoteUnitOfWork) -> None:
        async with uow:
            with pytest.raises(UnknownSortFieldError):
                await uow.plain_notes.list(PageRequest(sort=Sort(field="secret")))

    # --- Le filtre de tenance (BACK-06b) ------------------------------------

    async def test_a_tenant_aggregate_is_unreachable_without_a_group(
        self, uow: NoteUnitOfWork
    ) -> None:
        async with uow:
            with pytest.raises(MissingTenantContextError):
                await uow.tenant_notes.list(PageRequest())

    async def test_a_tenant_write_without_a_group_is_refused(self, uow: NoteUnitOfWork) -> None:
        async with uow:
            with pytest.raises(MissingTenantContextError):
                await uow.tenant_notes.add(a_tenant_note())

    async def test_a_cross_group_read_is_indistinguishable_from_an_absence(
        self, uow: NoteUnitOfWork, group_a: UUID, group_b: UUID
    ) -> None:
        """404 et jamais 403 : rien ne confirme que la ressource existe ailleurs."""
        note_b = a_tenant_note("chez B")
        async with uow:
            with use_group(group_b):
                await uow.tenant_notes.add(note_b)
            await uow.commit()
            with use_group(group_a):
                with pytest.raises(TenantNoteNotFoundError) as cross:
                    await uow.tenant_notes.get(note_b.id)
                with pytest.raises(TenantNoteNotFoundError) as absent:
                    await uow.tenant_notes.get(uuid4())
        assert type(cross.value) is type(absent.value)
        assert str(cross.value) == f"Aucune note tenant ne porte l'identifiant {note_b.id}."

    async def test_cross_group_rows_stay_out_of_the_list_and_of_the_total(
        self, uow: NoteUnitOfWork, group_a: UUID, group_b: UUID
    ) -> None:
        """LE total est celui du perimetre courant, jamais celui de la table."""
        note_a = a_tenant_note("chez A")
        async with uow:
            with use_group(group_a):
                await uow.tenant_notes.add(note_a)
            with use_group(group_b):
                await uow.tenant_notes.add(a_tenant_note("chez B"))
                await uow.tenant_notes.add(a_tenant_note("aussi chez B"))
            await uow.commit()
            with use_group(group_a):
                page = await uow.tenant_notes.list(PageRequest())
        assert [item.id for item in page.items] == [note_a.id]
        assert page.total == 1

    async def test_a_cross_group_save_is_refused(
        self, uow: NoteUnitOfWork, group_a: UUID, group_b: UUID
    ) -> None:
        note_b = a_tenant_note("etat d'origine")
        async with uow:
            with use_group(group_b):
                await uow.tenant_notes.add(note_b)
            await uow.commit()
            with use_group(group_a), pytest.raises(TenantNoteNotFoundError):
                await uow.tenant_notes.save(TenantNote(id=note_b.id, label="reecriture pirate"))
        async with uow:
            with use_group(group_b):
                assert (await uow.tenant_notes.get(note_b.id)).label == "etat d'origine"

    async def test_a_cross_group_delete_is_refused(
        self, uow: NoteUnitOfWork, group_a: UUID, group_b: UUID
    ) -> None:
        note_b = a_tenant_note("chez B")
        async with uow:
            with use_group(group_b):
                await uow.tenant_notes.add(note_b)
            await uow.commit()
            with use_group(group_a), pytest.raises(TenantNoteNotFoundError):
                await uow.tenant_notes.delete(note_b.id)
        async with uow:
            with use_group(group_b):
                assert (await uow.tenant_notes.get(note_b.id)).id == note_b.id

    async def test_a_tenant_entity_does_not_change_group_on_save(
        self, uow: NoteUnitOfWork, group_a: UUID, group_b: UUID
    ) -> None:
        """Le groupe est estampille a l'insertion, jamais reporte par une ecriture."""
        note = a_tenant_note("avant")
        async with uow:
            with use_group(group_a):
                await uow.tenant_notes.add(note)
                await uow.commit()
                await uow.tenant_notes.save(TenantNote(id=note.id, label="apres"))
                await uow.commit()
            with use_group(group_b), pytest.raises(TenantNoteNotFoundError):
                await uow.tenant_notes.get(note.id)
            with use_group(group_a):
                assert (await uow.tenant_notes.get(note.id)).label == "apres"

    async def test_all_groups_reads_across_but_still_refuses_to_write(
        self, uow: NoteUnitOfWork, group_a: UUID, group_b: UUID
    ) -> None:
        """L'echappatoire de BACK-06b : lire partout n'est pas ecrire n'importe ou."""
        async with uow:
            with use_group(group_a):
                await uow.tenant_notes.add(a_tenant_note("chez A"))
            with use_group(group_b):
                await uow.tenant_notes.add(a_tenant_note("chez B"))
            await uow.commit()
            with use_all_groups(reason="suite de conformite"):
                page = await uow.tenant_notes.list(PageRequest())
                assert page.total == 2
                with pytest.raises(MissingTenantContextError):
                    await uow.tenant_notes.add(a_tenant_note("sans groupe designe"))

    async def test_a_non_tenant_aggregate_lives_without_any_group(
        self, uow: NoteUnitOfWork
    ) -> None:
        """Le filtre est OPT-IN : un agregat sans tenance n'en porte rien."""
        note = a_plain_note("notice partagee")
        async with uow:
            await uow.plain_notes.add(note)
            await uow.commit()
            assert (await uow.plain_notes.get(note.id)).label == "notice partagee"


class TestSqlAlchemyNoteConformance(NoteUnitOfWorkConformance):
    """La suite, jouee contre PostgreSQL par la base de test."""

    @pytest.fixture
    def uow(self, bound_sessionmaker: async_sessionmaker[AsyncSession]) -> NoteUnitOfWork:
        """Unite de travail reelle, inscrite dans la transaction du test.

        PLUS DE PURGE, ET CE N'EST PAS UN RELACHEMENT (BACK-12). Elle existait
        parce que cette moitie-ci COMMITE pour de bon -- il le faut, sans quoi
        elle ne prouverait pas ce qu'on lui demande -- et qu'aucun rollback ne la
        rattrapait. La transaction externe de `connection` le fait desormais, et
        mieux : elle rattrape aussi un test interrompu en plein milieu, ce que la
        purge « avant » ne faisait que reparer apres coup.

        CE QUE LA SUITE PROUVE NE CHANGE PAS, sauf sur un point, et il est
        couvert ailleurs. Sous `create_savepoint`, `commit()` reste un vrai commit
        du point de vue de la session : une seconde session relit bien ce que la
        premiere a valide, et un `rollback` l'efface toujours. Ce qui n'est plus
        prouve ICI, c'est la durabilite INTER-CONNEXIONS -- un commit reste dans
        la transaction du test. C'est l'objet de
        `test_a_commit_is_visible_from_another_connection`, qui sort du patron
        pour cette raison precise.
        """
        return SqlAlchemyNoteUnitOfWork(bound_sessionmaker)


class TestInMemoryNoteConformance(NoteUnitOfWorkConformance):
    """La MEME suite, jouee contre les doublures de `shared/infrastructure/memory/`."""

    @pytest.fixture
    def uow(self) -> Iterator[NoteUnitOfWork]:
        """Unite de travail en memoire, neuve a chaque test.

        Aucune purge : un dictionnaire neuf est deja vide. C'est la difference de
        cout que le ticket cherche -- cette moitie tourne sans conteneur.
        """
        yield InMemoryNoteUnitOfWork()
