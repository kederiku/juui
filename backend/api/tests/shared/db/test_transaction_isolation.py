"""Le harnais isole-t-il vraiment ? Et que perd-on a l'isoler ainsi (BACK-12).

Ces trois tests ne testent pas le service : ils testent LE HARNAIS. Ils existent
parce que la strategie d'isolation retenue -- une transaction externe par test,
des sessions inscrites en `create_savepoint` -- est une machinerie, et qu'une
machinerie silencieuse qui cesse de fonctionner ne se manifeste que par des
tests d'integration devenus mysterieusement instables, des semaines plus tard,
dans des fichiers innocents.

Deux d'entre eux forment une PAIRE ORDONNEE : le premier commite pour de bon,
le second exige que rien n'en subsiste. Le troisieme prend le probleme par
l'autre bout et nomme ce que le patron coute.
"""

from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.shared.tenancy_stubs import (
    PlainNote,
    PlainNoteModel,
    PlainNoteNotFoundError,
    SqlAlchemyNoteUnitOfWork,
)

pytestmark = pytest.mark.conformance

# Identifiant FIGE, partage par les deux tests de la paire ordonnee. Il le faut :
# le second doit chercher exactement ce que le premier a ecrit, et un uuid4()
# tire deux fois ne prouverait rien.
_LEAKED_NOTE_ID: UUID = UUID("0198e3a0-0000-7000-8000-00000000ba5e")


async def test_a_commit_inside_a_test_is_undone_by_the_harness(
    bound_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """PREMIER DE LA PAIRE : commite une ligne pour de bon, et ne nettoie rien.

    Ne pas nettoyer est le sujet. Si ce test purgeait derriere lui, le suivant
    passerait quelle que soit la strategie d'isolation, et la paire ne prouverait
    plus rien du tout.
    """
    uow = SqlAlchemyNoteUnitOfWork(bound_sessionmaker)
    async with uow:
        await uow.plain_notes.add(PlainNote(id=_LEAKED_NOTE_ID, label="fuite"))
        await uow.commit()

    # Le commit est bien un commit DU POINT DE VUE DE LA SESSION : une seconde
    # unite de travail, ouverte apres coup sur la meme fabrique, relit la ligne.
    # C'est cette propriete-la que la suite de conformite eprouve, et elle est
    # intacte sous savepoint.
    async with SqlAlchemyNoteUnitOfWork(bound_sessionmaker) as reader:
        assert (await reader.plain_notes.get(_LEAKED_NOTE_ID)).label == "fuite"


async def test_nothing_survives_the_previous_test(
    bound_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """SECOND DE LA PAIRE : la ligne commitee par le test precedent a disparu.

    C'EST LE TEST QUI GARDE LE HARNAIS. Le jour ou `create_savepoint` cesserait
    d'operer -- une fabrique reconstruite sur le moteur au lieu de la connexion,
    un `join_transaction_mode` perdu au detour d'un refactor --, c'est ici que
    cela se verrait, en une ligne et avec un nom qui dit quoi, plutot qu'a
    travers deux cents tests d'integration devenus dependants de leur ordre.

    Il depend de l'ordre de collecte, et c'est assume : pytest joue les tests
    d'un fichier dans l'ordre du source, et les deux ne sont separables ni de
    fait ni de sens.
    """
    async with SqlAlchemyNoteUnitOfWork(bound_sessionmaker) as uow:
        with pytest.raises(PlainNoteNotFoundError):
            await uow.plain_notes.get(_LEAKED_NOTE_ID)


async def test_a_commit_is_visible_from_another_connection(
    engine_sessionmaker: async_sessionmaker[AsyncSession], engine: AsyncEngine
) -> None:
    """LA LIMITE DU PATRON, ecrite plutot que subie.

    Toute la conformite tourne desormais sous `create_savepoint` : un `commit()`
    y relache un savepoint et ne rend rien durable HORS de la transaction du
    test. La propriete « une ecriture validee survit a la connexion qui l'a
    faite » n'y est donc plus prouvee -- et c'est exactement celle que la moitie
    reelle existait pour prouver.

    Ce test-la, et lui seul, sort du patron : il commite sur le MOTEUR, relit
    depuis une CONNEXION DISTINCTE, et purge lui-meme -- des deux cotes, comme
    la conformite le faisait avant BACK-12.
    """
    note = PlainNote(id=uuid4(), label="durable")
    uow = SqlAlchemyNoteUnitOfWork(engine_sessionmaker)
    try:
        async with uow:
            await uow.plain_notes.add(note)
            await uow.commit()
        async with engine.connect() as other:
            found = await other.execute(
                select(PlainNoteModel.label).where(PlainNoteModel.id == note.id)
            )
            assert found.scalar_one() == "durable"
    finally:
        async with engine.begin() as cleanup:
            await cleanup.execute(delete(PlainNoteModel).where(PlainNoteModel.id == note.id))
