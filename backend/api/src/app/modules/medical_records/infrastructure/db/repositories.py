"""Adaptateurs SQLAlchemy des ports du module medical_records (BACK-19).

Le mapping est ECRIT A LA MAIN, comme partout : `str` en base, `Species` /
`AnimalSex` / `SterilizationStatus` dans le domaine, et l'ecart echoue chez
Mypy plutot qu'en production.

DEUX DEPOTS NUS, ET C'EST LE COEUR DU TICKET
Ni `Animal` ni `Custody` n'est tenant : les deux depots heritent du generique
NU, leurs requetes tournent a l'inscription d'un particulier et dans son
espace personnel, hors de tout contexte de groupe. L'isolation vient de la
RELATION : chaque finder est parametre par un compte ou un animal, jamais
« tout lire ».

Toute requete maison part de `self._select()` -- jamais d'un `select(...)`
importe : la convention vaut pour tous les depots, tenant ou non.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import or_

from app.modules.medical_records.domain.entities import (
    Animal,
    AnimalSex,
    Custody,
    Species,
    SterilizationStatus,
    ensure_aware_instant,
)
from app.modules.medical_records.domain.exceptions import (
    AnimalNotFoundError,
    CustodyNotFoundError,
)
from app.modules.medical_records.domain.ports import AnimalRepository, CustodyRepository
from app.modules.medical_records.infrastructure.db.models import AnimalModel, CustodyModel
from app.shared.infrastructure.db.repositories.base import SqlAlchemyRepository


class SqlAlchemyAnimalRepository(SqlAlchemyRepository[Animal, AnimalModel], AnimalRepository):
    """Depot des fiches animal adosse a PostgreSQL -- volontairement NON tenant."""

    _model_type = AnimalModel
    _not_found_error = AnimalNotFoundError
    _not_found_message = "Aucun animal ne porte l'identifiant {entity_id}."

    def _to_entity(self, model: AnimalModel) -> Animal:
        """Reconstitue l'entite du domaine a partir d'une ligne de la table.

        Args:
            model: la ligne relue par SQLAlchemy.

        Returns:
            La fiche, enums convertis dans les types du domaine.
        """
        return Animal(
            id=model.id,
            name=model.name,
            species=Species(model.species),
            breed=model.breed,
            birth_date=model.birth_date,
            sex=AnimalSex(model.sex),
            sterilization=SterilizationStatus(model.sterilization),
            microchip_number=model.microchip_number,
        )

    def _apply_to_model(self, entity: Animal, model: AnimalModel) -> None:
        """Reporte l'etat d'une fiche sur sa ligne, sans toucher a `id`.

        Args:
            entity: la fiche dont l'etat fait foi.
            model: la ligne a mettre au meme etat.
        """
        model.name = entity.name
        model.species = entity.species.value
        model.breed = entity.breed
        model.birth_date = entity.birth_date
        model.sex = entity.sex.value
        model.sterilization = entity.sterilization.value
        model.microchip_number = entity.microchip_number

    async def list_with_active_custody_for_account(
        self, account_id: UUID, at: datetime
    ) -> Sequence[Animal]:
        """Rend les animaux dont le compte a la detention active a l'instant donne.

        La jointure d'ADR-0006, ecrite une fois ici. Le `distinct()` est une
        ceinture : seule la detention OUVERTE est unique en base, et des
        fenetres closes chevauchantes (fusion BACK-20) pourraient sinon rendre
        deux fois le meme animal.

        Args:
            account_id: le compte particulier interroge.
            at: l'instant de reference.

        Returns:
            Les animaux detenus, du plus anciennement enregistre au plus
            recent -- les identifiants UUIDv7 sont horodates, l'ordre sur la
            cle est chronologique.

        Raises:
            InvalidWindowError: si l'instant est naif.
        """
        ensure_aware_instant(at)
        statement = (
            self._select()
            .join(CustodyModel, CustodyModel.animal_id == AnimalModel.id)
            .where(
                CustodyModel.account_id == account_id,
                CustodyModel.start_at <= at,
                or_(CustodyModel.end_at.is_(None), CustodyModel.end_at > at),
            )
            .distinct()
            .order_by(AnimalModel.id)
        )
        models = (await self._session.execute(statement)).scalars().all()
        return [self._to_entity(model) for model in models]


class SqlAlchemyCustodyRepository(SqlAlchemyRepository[Custody, CustodyModel], CustodyRepository):
    """Depot des detentions adosse a PostgreSQL -- volontairement NON tenant."""

    _model_type = CustodyModel
    _not_found_error = CustodyNotFoundError
    _not_found_message = "Aucune detention ne porte l'identifiant {entity_id}."

    def _to_entity(self, model: CustodyModel) -> Custody:
        """Reconstitue l'entite du domaine a partir d'une ligne de la table.

        Args:
            model: la ligne relue par SQLAlchemy.

        Returns:
            La detention, bornes et identifiants tels quels.
        """
        return Custody(
            id=model.id,
            animal_id=model.animal_id,
            account_id=model.account_id,
            start_at=model.start_at,
            end_at=model.end_at,
        )

    def _apply_to_model(self, entity: Custody, model: CustodyModel) -> None:
        """Reporte l'etat d'une detention sur sa ligne, sans toucher a `id`.

        Args:
            entity: la detention dont l'etat fait foi.
            model: la ligne a mettre au meme etat.
        """
        model.animal_id = entity.animal_id
        model.account_id = entity.account_id
        model.start_at = entity.start_at
        model.end_at = entity.end_at

    async def add(self, entity: Custody, /) -> None:
        """Inscrit une detention neuve, changements pendants emis d'abord.

        L'index unique partiel n'est pas differable, et la session tourne en
        `autoflush=False` (BACK-05) : sans ce flush prealable, la cloture
        posee par `save` resterait PENDANTE au moment ou l'INSERT part -- le
        `flush([model])` du generique ne pousse que la ligne neuve -- et le
        transfert clore-puis-ouvrir echouerait en violation d'integrite alors
        que l'appelant a respecte l'ordre documente. Emettre d'abord tout ce
        que le bloc a change garantit que la recette de `models.py` tient a
        travers les depots livres -- le chemin que BACK-30 consommera.

        Args:
            entity: la detention a creer.
        """
        await self._session.flush()
        await super().add(entity)

    async def find_active_for_animal(self, animal_id: UUID, at: datetime) -> Custody | None:
        """Cherche la detention d'un animal en vigueur a l'instant donne.

        En cas de fenetres closes chevauchantes (fusion BACK-20), l'ordre
        `start_at DESC, id DESC` rend la detention la plus recente, de
        maniere deterministe -- `id` departage deux debuts identiques, les
        UUIDv7 etant ordonnes dans le temps.

        Args:
            animal_id: l'animal interroge.
            at: l'instant de reference.

        Returns:
            La detention en vigueur, ou None si aucune ne couvre l'instant.

        Raises:
            InvalidWindowError: si l'instant est naif.
        """
        ensure_aware_instant(at)
        statement = (
            self._select()
            .where(
                CustodyModel.animal_id == animal_id,
                CustodyModel.start_at <= at,
                or_(CustodyModel.end_at.is_(None), CustodyModel.end_at > at),
            )
            .order_by(CustodyModel.start_at.desc(), CustodyModel.id.desc())
            .limit(1)
        )
        model = (await self._session.execute(statement)).scalars().first()
        return None if model is None else self._to_entity(model)

    async def list_for_animal(self, animal_id: UUID) -> Sequence[Custody]:
        """Rend toutes les detentions d'un animal, l'historique intact.

        Args:
            animal_id: l'animal interroge.

        Returns:
            Les detentions, du debut le plus ancien au plus recent.
        """
        statement = (
            self._select()
            .where(CustodyModel.animal_id == animal_id)
            .order_by(CustodyModel.start_at, CustodyModel.id)
        )
        models = (await self._session.execute(statement)).scalars().all()
        return [self._to_entity(model) for model in models]
