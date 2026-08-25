"""Doublures d'agregats pour les tests d'isolation de tenance (BACK-06b).

Aucun agregat reel ne declare `TenantMixin` a ce jour : ces stubs fournissent
la paire minimale qui rend l'isolation testable -- un agregat tenant, un
agregat non tenant, leurs depots. Le module ne porte pas le prefixe `test_` :
pytest ne le collecte pas, et conftest comme tests importent les memes classes
(les tables ne s'enregistrent qu'une fois dans `Base.metadata`).

Les tables portent le suffixe `_test` et ne sont creees que dans la base de
test, par la fixture moteur du conftest. `alembic/env.py` n'importe jamais ce
module : l'autogeneration et `alembic check` ne voient pas ces tables.
"""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.domain.exceptions import DomainError
from app.shared.infrastructure.db.base import Base
from app.shared.infrastructure.db.mixins import TenantMixin, UUIDPrimaryKey
from app.shared.infrastructure.db.repositories.base import SqlAlchemyRepository
from app.shared.infrastructure.db.repositories.tenant import TenantSqlAlchemyRepository


class TenantNoteNotFoundError(DomainError):
    """Aucune note tenant ne porte l'identifiant demande."""


class PlainNoteNotFoundError(DomainError):
    """Aucune note partagee ne porte l'identifiant demande."""


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
