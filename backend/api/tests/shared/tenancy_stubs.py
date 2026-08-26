"""Doublures d'agregats pour les tests d'isolation de tenance (BACK-06b).

Aucun agregat reel ne declare `TenantMixin` a ce jour : ces stubs fournissent
la paire minimale qui rend l'isolation testable -- un agregat tenant, un
agregat non tenant, leurs depots. Le module ne porte pas le prefixe `test_` :
pytest ne le collecte pas, et conftest comme tests importent les memes classes
(les tables ne s'enregistrent qu'une fois dans `Base.metadata`).

Les tables portent le suffixe `_test` et ne sont creees que dans la base de
test, par la fixture moteur du conftest. `alembic/env.py` n'importe jamais ce
module : l'autogeneration et `alembic check` ne voient pas ces tables.

Les tests de la convention de pagination (BACK-24) reutilisent la meme paire :
les deux depots declarent `label` triable, ce qui suffit a prouver fenetrage,
liste blanche et tenance du total.

CE QUE BACK-06c A AJOUTE ICI : le MIROIR EN MEMOIRE de la meme paire, et une
unite de travail par cote. C'est le vehicule de la suite de conformite -- une
seule suite, deux implementations, et la seule facon de comparer autre chose que
des intentions. Les deux cotes declarent le meme `label` triable, la meme erreur
d'absence et le meme gabarit de message : toute divergence de l'un des trois
ferait passer la suite d'un cote et echouer de l'autre, ce qui est exactement le
service rendu.

POURQUOI UNE UNITE DE TRAVAIL POUR DES STUBS
BACK-06b travaillait sur une `session` nue, ce qui suffisait a prouver un filtre.
La conformite, elle, doit prouver commit et rollback : sans unite de travail des
DEUX cotes, le critere « commit et rollback ont un effet reel observable » n'a
aucun sujet commun a comparer.
"""

from abc import abstractmethod
from dataclasses import dataclass
from typing import ClassVar
from uuid import UUID

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.domain.exceptions import NotFoundError
from app.shared.domain.ports.repository import Repository
from app.shared.domain.ports.unit_of_work import AbstractUnitOfWork
from app.shared.infrastructure.db.base import Base
from app.shared.infrastructure.db.mixins import TenantMixin, UUIDPrimaryKey
from app.shared.infrastructure.db.repositories.base import SqlAlchemyRepository
from app.shared.infrastructure.db.repositories.tenant import TenantSqlAlchemyRepository
from app.shared.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from app.shared.infrastructure.memory.repository import (
    InMemoryRepository,
    InMemoryStore,
    InMemoryTenantRepository,
)
from app.shared.infrastructure.memory.unit_of_work import InMemoryUnitOfWork


class TenantNoteNotFoundError(NotFoundError):
    """Aucune note tenant ne porte l'identifiant demande."""

    code: ClassVar[str] = "tests.tenant_note.not_found"


class PlainNoteNotFoundError(NotFoundError):
    """Aucune note partagee ne porte l'identifiant demande."""

    code: ClassVar[str] = "tests.plain_note.not_found"


@dataclass(slots=True, kw_only=True)
class TenantNote:
    """Entite tenant factice.

    PAS de champ de groupe : l'estampillage est l'affaire du socle, et c'est
    precisement ce que les tests d'ecriture verifient.
    """

    id: UUID
    label: str


@dataclass(slots=True, kw_only=True)
class PlainNote:
    """Entite non tenant factice, miroir de `TenantNote`."""

    id: UUID
    label: str


class TenantNoteModel(UUIDPrimaryKey, TenantMixin, Base):
    """Table tenant de test -- index prefixe par `group_id`, comme la garde l'exige."""

    __tablename__ = "tenant_notes_test"
    __table_args__ = (Index(None, "group_id", "label"),)

    label: Mapped[str] = mapped_column(String(100))


class PlainNoteModel(UUIDPrimaryKey, Base):
    """Table non tenant de test : aucun `group_id`, aucun filtre."""

    __tablename__ = "plain_notes_test"

    label: Mapped[str] = mapped_column(String(100))


class TenantNoteRepository(TenantSqlAlchemyRepository[TenantNote, TenantNoteModel]):
    """Depot tenant factice : herite du filtre, ne declare que son mapping."""

    _model_type = TenantNoteModel
    _not_found_error = TenantNoteNotFoundError
    _not_found_message = "Aucune note tenant ne porte l'identifiant {entity_id}."
    _sortable: ClassVar = {"label": TenantNoteModel.label}

    def _to_entity(self, model: TenantNoteModel) -> TenantNote:
        """Reconstitue l'entite depuis la ligne."""
        return TenantNote(id=model.id, label=model.label)

    def _apply_to_model(self, entity: TenantNote, model: TenantNoteModel) -> None:
        """Reporte l'etat sur la ligne, sans toucher ni `id` ni `group_id`."""
        model.label = entity.label


class PlainNoteRepository(SqlAlchemyRepository[PlainNote, PlainNoteModel]):
    """Depot non tenant factice : la base nue, sans tenance."""

    _model_type = PlainNoteModel
    _not_found_error = PlainNoteNotFoundError
    _not_found_message = "Aucune note partagee ne porte l'identifiant {entity_id}."
    _sortable: ClassVar = {"label": PlainNoteModel.label}

    def _to_entity(self, model: PlainNoteModel) -> PlainNote:
        """Reconstitue l'entite depuis la ligne."""
        return PlainNote(id=model.id, label=model.label)

    def _apply_to_model(self, entity: PlainNote, model: PlainNoteModel) -> None:
        """Reporte l'etat sur la ligne, sans toucher a `id`."""
        model.label = entity.label


def make_tenant_row(note_id: UUID, group_id: UUID, label: str) -> TenantNoteModel:
    """Fabrique une ligne tenant a semer par la session BRUTE.

    Le semis contourne volontairement le depot -- le filtre vit dans le depot,
    pas dans la session : c'est la verite terrain que les tests comparent au
    comportement filtre.
    """
    return TenantNoteModel(id=note_id, group_id=group_id, label=label)


class NoteUnitOfWork(AbstractUnitOfWork):
    """Port d'unite de travail des stubs : un agregat tenant, un agregat nu.

    Le sujet de la suite de conformite. Les deux depots vivent dans la MEME
    unite : c'est ce qui permet de prouver qu'un commit les replie ensemble, et
    qu'un rollback annule ce que le bloc a ecrit dans les deux.
    """

    @property
    @abstractmethod
    def tenant_notes(self) -> Repository[TenantNote]:
        """Le depot tenant, servi par le bloc `async with` en cours.

        LE TYPE EXPOSE EST LE PROTOCOLE GENERIQUE, et c'est ce que sa docstring
        annoncait : « le test de conformite commun des deux s'ecrira contre ce
        protocole ». Une suite ecrite contre `Repository[TenantNote]` ne peut
        rien appeler qu'une seule des deux implementations saurait faire -- c'est
        la garantie structurelle que les deux moities parlent du meme contrat.
        """

    @property
    @abstractmethod
    def plain_notes(self) -> Repository[PlainNote]:
        """Le depot non tenant, servi par le bloc `async with` en cours."""


class SqlAlchemyNoteUnitOfWork(SqlAlchemyUnitOfWork, NoteUnitOfWork):
    """Cote REEL de la conformite : PostgreSQL, par la base de test.

    Elle COMMITE pour de bon -- c'est le sujet meme du critere 1, et c'est
    pourquoi la fixture de conformite purge les deux tables avant et apres chaque
    test au lieu de compter sur le rollback de la fixture `session`.
    """

    @property
    def tenant_notes(self) -> TenantNoteRepository:
        """Le depot tenant du bloc en cours."""
        return TenantNoteRepository(self._active_session)

    @property
    def plain_notes(self) -> PlainNoteRepository:
        """Le depot non tenant du bloc en cours."""
        return PlainNoteRepository(self._active_session)


class InMemoryTenantNoteRepository(InMemoryTenantRepository[TenantNote]):
    """Miroir en memoire de `TenantNoteRepository` -- meme erreur, meme message."""

    _not_found_error = TenantNoteNotFoundError
    _not_found_message = "Aucune note tenant ne porte l'identifiant {entity_id}."
    _sortable: ClassVar = frozenset({"label"})


class InMemoryPlainNoteRepository(InMemoryRepository[PlainNote]):
    """Miroir en memoire de `PlainNoteRepository` -- sans tenance, comme lui."""

    _not_found_error = PlainNoteNotFoundError
    _not_found_message = "Aucune note partagee ne porte l'identifiant {entity_id}."
    _sortable: ClassVar = frozenset({"label"})


class InMemoryNoteUnitOfWork(InMemoryUnitOfWork, NoteUnitOfWork):
    """Cote DOUBLURE de la conformite : deux dictionnaires, aucun conteneur."""

    def __init__(self) -> None:
        """Declare les deux magasins et les inscrit au commit atomique."""
        super().__init__()
        self.tenant_store: InMemoryStore[TenantNote] = self._new_store()
        self.plain_store: InMemoryStore[PlainNote] = self._new_store()

    @property
    def tenant_notes(self) -> InMemoryTenantNoteRepository:
        """Le depot tenant du bloc en cours."""
        self._require_open()
        return InMemoryTenantNoteRepository(self.tenant_store)

    @property
    def plain_notes(self) -> InMemoryPlainNoteRepository:
        """Le depot non tenant du bloc en cours."""
        self._require_open()
        return InMemoryPlainNoteRepository(self.plain_store)
