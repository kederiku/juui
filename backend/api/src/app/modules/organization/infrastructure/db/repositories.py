"""Adaptateurs SQLAlchemy des ports du module organization (BACK-16).

Le mapping est ECRIT A LA MAIN, comme chez identity : `str` en base,
`GroupRole` / `ClinicRole` dans le domaine, et l'ecart echoue chez Mypy plutot
qu'en production.

DEUX CLASSES DE BASE, ET LE CHOIX EST LE COEUR DU TICKET
`SqlAlchemyMembershipRepository` herite du depot generique NU : ses requetes
tournent a l'emission du jeton, hors de tout contexte de tenance, et son
mapping renseigne `group_id` -- colonne propre du module, pas celle du mixin.
`SqlAlchemyAssignmentRepository` herite du depot TENANT : le filtre de groupe
s'applique a toutes ses lectures, et son mapping ne touche JAMAIS `group_id`,
que le socle estampille a l'insertion (la garde de `_to_model` y veille).

Toute requete maison part de `self._select()` -- jamais d'un `select(...)`
importe : c'est la couture que le filtre tenant sait atteindre.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import or_

from app.modules.organization.domain.entities import (
    Assignment,
    ClinicRole,
    GroupRole,
    Membership,
    ensure_aware_instant,
)
from app.modules.organization.domain.exceptions import (
    AssignmentNotFoundError,
    MembershipNotFoundError,
)
from app.modules.organization.domain.ports import AssignmentRepository, MembershipRepository
from app.modules.organization.infrastructure.db.models import AssignmentModel, MembershipModel
from app.shared.infrastructure.db.repositories.base import SqlAlchemyRepository
from app.shared.infrastructure.db.repositories.tenant import TenantSqlAlchemyRepository


class SqlAlchemyMembershipRepository(
    SqlAlchemyRepository[Membership, MembershipModel], MembershipRepository
):
    """Depot d'appartenances adosse a PostgreSQL -- volontairement NON tenant."""

    _model_type = MembershipModel
    _not_found_error = MembershipNotFoundError
    _not_found_message = "Aucune appartenance ne porte l'identifiant {entity_id}."

    def _to_entity(self, model: MembershipModel) -> Membership:
        """Reconstitue l'entite du domaine a partir d'une ligne de la table.

        Args:
            model: la ligne relue par SQLAlchemy.

        Returns:
            L'appartenance, role converti dans le type du domaine.
        """
        return Membership(
            id=model.id,
            account_id=model.account_id,
            group_id=model.group_id,
            role=GroupRole(model.role),
            start_at=model.start_at,
            end_at=model.end_at,
        )

    def _apply_to_model(self, entity: Membership, model: MembershipModel) -> None:
        """Reporte l'etat d'une appartenance sur sa ligne, sans toucher a `id`.

        `group_id` EST reporte ici, a l'inverse des depots tenant : la colonne
        appartient au module, et l'entite en est la source de verite.

        Args:
            entity: l'appartenance dont l'etat fait foi.
            model: la ligne a mettre au meme etat.
        """
        model.account_id = entity.account_id
        model.group_id = entity.group_id
        model.role = entity.role.value
        model.start_at = entity.start_at
        model.end_at = entity.end_at

    async def list_active_for_account(self, account_id: UUID, at: datetime) -> Sequence[Membership]:
        """Rend les appartenances d'un compte actives a l'instant donne.

        Args:
            account_id: le compte dont on cherche les appartenances.
            at: l'instant de reference.

        Returns:
            Les appartenances actives, du debut le plus ancien au plus recent.

        Raises:
            InvalidWindowError: si l'instant est naif -- lie tel quel a un
                `timestamptz`, il serait interprete dans le fuseau de la
                session, en silence.
        """
        ensure_aware_instant(at)
        statement = (
            self._select()
            .where(
                MembershipModel.account_id == account_id,
                MembershipModel.start_at <= at,
                or_(MembershipModel.end_at.is_(None), MembershipModel.end_at > at),
            )
            .order_by(MembershipModel.start_at, MembershipModel.id)
        )
        models = (await self._session.execute(statement)).scalars().all()
        return [self._to_entity(model) for model in models]

    async def find_active_role(
        self, account_id: UUID, group_id: UUID, at: datetime
    ) -> GroupRole | None:
        """Cherche le role d'un compte dans un groupe donne, a l'instant donne.

        En cas d'appartenances chevauchantes au meme groupe, l'ordre
        `start_at DESC, id DESC` rend le role de la decision la plus recente,
        de maniere deterministe -- `id` departage deux debuts identiques, les
        UUIDv7 etant ordonnes dans le temps.

        Args:
            account_id: le compte interroge.
            group_id: le groupe dans lequel le role est cherche.
            at: l'instant de reference.

        Returns:
            Le role de perimetre groupe, ou None si aucune appartenance a ce
            groupe n'est active a cet instant.

        Raises:
            InvalidWindowError: si l'instant est naif.
        """
        ensure_aware_instant(at)
        statement = (
            self._select()
            .where(
                MembershipModel.account_id == account_id,
                MembershipModel.group_id == group_id,
                MembershipModel.start_at <= at,
                or_(MembershipModel.end_at.is_(None), MembershipModel.end_at > at),
            )
            .order_by(MembershipModel.start_at.desc(), MembershipModel.id.desc())
            .limit(1)
        )
        model = (await self._session.execute(statement)).scalars().first()
        return None if model is None else GroupRole(model.role)


class SqlAlchemyAssignmentRepository(
    TenantSqlAlchemyRepository[Assignment, AssignmentModel], AssignmentRepository
):
    """Depot d'affectations adosse a PostgreSQL -- tenant, filtre herite."""

    _model_type = AssignmentModel
    _not_found_error = AssignmentNotFoundError
    _not_found_message = "Aucune affectation ne porte l'identifiant {entity_id}."

    def _to_entity(self, model: AssignmentModel) -> Assignment:
        """Reconstitue l'entite du domaine a partir d'une ligne de la table.

        Le `group_id` de la ligne n'est PAS reporte : l'entite tenant ne porte
        pas la colonne du socle.

        Args:
            model: la ligne relue par SQLAlchemy.

        Returns:
            L'affectation, role converti dans le type du domaine.
        """
        return Assignment(
            id=model.id,
            account_id=model.account_id,
            clinic_id=model.clinic_id,
            role=ClinicRole(model.role),
            start_at=model.start_at,
            end_at=model.end_at,
        )

    def _apply_to_model(self, entity: Assignment, model: AssignmentModel) -> None:
        """Reporte l'etat d'une affectation sur sa ligne, sans `id` ni `group_id`.

        La tenance est estampillee par le socle a l'insertion ; un mapping qui
        s'en melerait serait refuse par la garde de `_to_model`.

        Args:
            entity: l'affectation dont l'etat fait foi.
            model: la ligne a mettre au meme etat.
        """
        model.account_id = entity.account_id
        model.clinic_id = entity.clinic_id
        model.role = entity.role.value
        model.start_at = entity.start_at
        model.end_at = entity.end_at

    async def list_active_for_account(self, account_id: UUID, at: datetime) -> Sequence[Assignment]:
        """Rend les affectations d'un compte actives dans le groupe actif.

        Le filtre de groupe est HERITE : `self._select()` restreint deja la
        requete au perimetre du contexte, ou leve hors de tout perimetre.

        Args:
            account_id: le compte dont on cherche les affectations.
            at: l'instant de reference.

        Returns:
            Les affectations actives dans le groupe actif, du debut le plus
            ancien au plus recent.

        Raises:
            InvalidWindowError: si l'instant est naif.
            MissingTenantContextError: si aucun perimetre de tenance n'est
                pose.
        """
        ensure_aware_instant(at)
        statement = (
            self._select()
            .where(
                AssignmentModel.account_id == account_id,
                AssignmentModel.start_at <= at,
                or_(AssignmentModel.end_at.is_(None), AssignmentModel.end_at > at),
            )
            .order_by(AssignmentModel.start_at, AssignmentModel.id)
        )
        models = (await self._session.execute(statement)).scalars().all()
        return [self._to_entity(model) for model in models]
