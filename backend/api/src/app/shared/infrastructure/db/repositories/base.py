"""Depot generique SQLAlchemy -- cinq operations, un mapping declare (BACK-06a).

C'est la classe dont les depots concrets des modules heritent. Elle porte ce
qui se repete a l'identique d'un agregat a l'autre -- get, list, add, save,
delete, et la mecanique du mapping -- pour que chaque depot concret ne declare
plus que ce qui lui appartient : sa classe de modele, son erreur d'absence, et
ses deux fonctions de mapping.

DEUX FONCTIONS DE MAPPING, PAS TROIS
Le depot concret declare `_to_entity` (ligne vers domaine) et `_apply_to_model`
(domaine vers ligne suivie). `_to_model`, le troisieme sens qu'ecrivait
BACK-04, est DERIVE ici : un modele neuf recoit l'identifiant, puis
`_apply_to_model` fait le reste. « L'identifiant n'est jamais reporte » cesse
d'etre une consigne : `save` ne passe que par `_apply_to_model`, qui ne touche
pas a `id` -- structurellement.

L'ERREUR D'ABSENCE EST CELLE DU MODULE
`get`, `save` et `delete` levent l'exception declaree par le depot concret
(`AccountNotFoundError` chez identity), avec son message a lui. Le generique ne
fabrique aucune erreur `shared` : la hierarchie intermediaire des absences
appartient a BACK-09, et une `EntityNotFoundError` posee ici entrerait en
collision avec elle.

CE QUE BACK-06B AJOUTERA ICI
Le filtre de tenance, applique aux seuls modeles declarant `TenantMixin`.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.domain.exceptions import DomainError
from app.shared.domain.ports.repository import Identified
from app.shared.infrastructure.db.base import Base


class SqlAlchemyRepository[EntityT: Identified, ModelT: Base](ABC):
    """Socle des depots SQLAlchemy : les operations communes a tout agregat.

    Chaque depot concret declare quatre choses en corps de classe : la classe
    de modele (`_model_type`), l'erreur d'absence de son module
    (`_not_found_error`), le gabarit de son message (`_not_found_message`,
    avec `{entity_id}`), et ses deux fonctions de mapping. Tout le reste est
    herite -- y compris des operations que son port metier n'expose pas :
    `AccountRepository` ne connait ni `list` ni `delete`, la classe concrete
    les sait faire, et le port ne s'elargit pas parce que la classe sait faire
    plus.
    """

    _model_type: type[ModelT]
    _not_found_error: type[DomainError]
    _not_found_message: str

    def __init__(self, session: AsyncSession) -> None:
        """Rattache le depot a la session du bloc en cours.

        La session est FOURNIE, jamais creee ici : c'est l'unite de travail
        qui l'ouvre, la ferme et decide du commit. Un depot qui ouvrirait sa
        propre session rendrait impossible d'ecrire deux agregats dans une
        seule transaction.

        Args:
            session: la session du bloc `async with` en cours, servie par la
                propriete `_active_session` de l'unite de travail.

        Raises:
            TypeError: si la classe concrete ne declare pas ses trois
                attributs de configuration. Mypy ne peut pas voir cet oubli --
                les annotations de la base lui font croire qu'ils existent --
                et sans cette garde il ne se revelerait qu'en `AttributeError`
                au milieu d'une requete.
        """
        for required in ("_model_type", "_not_found_error", "_not_found_message"):
            if not hasattr(type(self), required):
                message = (
                    f"{type(self).__name__} ne declare pas `{required}` : les trois "
                    "attributs du depot generique se posent en corps de classe."
                )
                raise TypeError(message)
        self._session = session

    @abstractmethod
    def _to_entity(self, model: ModelT) -> EntityT:
        """Reconstitue l'entite du domaine a partir d'une ligne de la table.

        Args:
            model: la ligne relue par SQLAlchemy.

        Returns:
            L'entite, avec ses valeurs converties dans les types du domaine.
        """

    @abstractmethod
    def _apply_to_model(self, entity: EntityT, model: ModelT) -> None:
        """Reporte l'etat d'une entite sur une ligne, SANS toucher a `id`.

        Modifier la ligne EXISTANTE plutot que d'en construire une neuve :
        c'est ce qui laisse SQLAlchemy emettre un UPDATE. Un `session.merge()`
        d'un objet reconstruit produirait le meme resultat au prix d'un SELECT
        de plus. L'identifiant n'est jamais reporte : une entite ne change pas
        d'identite, et `_to_model` est seul a le poser, a la creation.

        Args:
            entity: l'entite dont l'etat fait foi.
            model: la ligne a mettre au meme etat.
        """

    def _to_model(self, entity: EntityT) -> ModelT:
        """Construit la ligne a inserer pour une entite neuve.

        Args:
            entity: l'entite a persister.

        Returns:
            Le modele correspondant, pas encore rattache a une session.
        """
        model = self._model_type(id=entity.id)
        self._apply_to_model(entity, model)
        return model

    def _not_found(self, entity_id: UUID) -> DomainError:
        """Fabrique l'erreur d'absence du module, prete a etre levee.

        Args:
            entity_id: l'identifiant qui n'a rien trouve.

        Returns:
            L'exception du module concret, message renseigne.
        """
        return self._not_found_error(self._not_found_message.format(entity_id=entity_id))

    async def get(self, entity_id: UUID, /) -> EntityT:
        """Retourne l'entite portant cet identifiant.

        Args:
            entity_id: l'identifiant cherche.

        Returns:
            L'entite reconstituee.

        Raises:
            DomainError: l'erreur d'absence declaree par le depot concret, si
                aucune ligne ne porte cet identifiant.
        """
        model = await self._session.get(self._model_type, entity_id)
        if model is None:
            raise self._not_found(entity_id)
        return self._to_entity(model)

    async def list(self) -> Sequence[EntityT]:
        """Retourne toutes les entites, dans leur ordre de creation.

        Le tri suit la cle primaire : les identifiants UUIDv7 (BACK-05) sont
        horodates, l'ordre est donc chronologique ET deterministe, sans
        colonne de tri supplementaire. SANS BORNE, comme le protocole
        l'assume : la pagination est une convention de BACK-24.

        Returns:
            Les entites, de la plus ancienne a la plus recente.
        """
        statement = select(self._model_type).order_by(*self._model_type.__mapper__.primary_key)
        models = (await self._session.execute(statement)).scalars().all()
        return [self._to_entity(model) for model in models]

    async def add(self, entity: EntityT, /) -> None:
        """Inscrit une entite neuve dans le bloc, sans valider la transaction.

        La ligne est FLUSHEE aussitot, jamais commitee : l'INSERT part dans la
        transaction du bloc, que le rollback de sortie sait toujours annuler.
        Sans ce flush, `autoflush=False` (BACK-05) rendrait l'entite invisible
        au reste de son propre bloc -- un `get` juste apres l'`add` leverait
        l'erreur d'absence, et un `delete` declarerait la ligne inexistante
        tout en la laissant partir a l'INSERT au commit. Les contraintes
        remontent donc ICI, depuis l'ecriture qui les viole -- jamais au detour
        d'une lecture.

        Args:
            entity: l'entite a creer.
        """
        model = self._to_model(entity)
        self._session.add(model)
        await self._session.flush([model])

    async def save(self, entity: EntityT, /) -> None:
        """Reporte sur la ligne suivie l'etat d'une entite deja enregistree.

        Args:
            entity: l'entite modifiee.

        Raises:
            DomainError: l'erreur d'absence declaree par le depot concret, si
                l'entite n'a jamais ete enregistree.
        """
        model = await self._session.get(self._model_type, entity.id)
        if model is None:
            raise self._not_found(entity.id)
        self._apply_to_model(entity, model)

    async def delete(self, entity_id: UUID, /) -> None:
        """Supprime l'entite portant cet identifiant.

        La ligne est CHARGEE puis supprimee, jamais effacee par un DELETE
        direct : les cascades declarees a l'ORM s'appliquent, l'identity map
        du bloc reste coherente, et BACK-06b aura une ligne en main pour
        verifier la tenance avant de la laisser partir.

        Args:
            entity_id: l'identifiant de l'entite a supprimer.

        Raises:
            DomainError: l'erreur d'absence declaree par le depot concret, si
                aucune ligne ne porte cet identifiant.
        """
        model = await self._session.get(self._model_type, entity_id)
        if model is None:
            raise self._not_found(entity_id)
        await self._session.delete(model)
