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

L'ERREUR D'ABSENCE EST CELLE DU MODULE, ET C'EST UNE `NotFoundError`
`get`, `save` et `delete` levent l'exception declaree par le depot concret
(`AccountNotFoundError` chez identity), avec son message a lui. Le generique ne
fabrique aucune erreur `shared`, mais l'annotation `type[NotFoundError]` VERROUILLE
la non-divulgation (BACK-06b, BACK-09) : un depot ne PEUT pas declarer une absence
qui sorte autrement qu'en 404 -- une ressource d'un autre groupe repond donc
mecaniquement comme une ressource inexistante, jamais en 403.

DEUX COUTURES, ET AUCUNE TENANCE ICI
`_select` est le point de depart de TOUTE requete SELECT -- `list` comme les
finders maison des depots concrets -- et `_load` le chargement par identifiant
que `get`, `save` et `delete` partagent. Ce sont les deux seuls endroits que le
filtre de tenance (BACK-06b) surcharge, dans `tenant.py` : cette classe-ci
reste vierge de tenance, comme `TenantMixin` l'exige -- le filtre ne s'applique
qu'aux depots qui heritent de `TenantSqlAlchemyRepository`, jamais globalement.

LES TROIS ECRITURES FLUSHENT, ET C'EST UNE PROPRIETE DU BLOC
`add`, `save` et `delete` poussent leur SQL dans la transaction du bloc des
qu'elles sont appelees -- jamais un commit, que seule l'unite de travail decide.
C'est ce qui rend une ecriture VISIBLE du reste de son propre bloc, requetes
comprises, la ou `autoflush=False` (BACK-05) ferait autrement lire l'etat
d'avant. Seul `add` le faisait jusqu'a BACK-06c ; les deux autres l'ont gagne
quand la suite de conformite a compare ce chemin a celui de la doublure en
memoire.

LA PAGINATION PASSE PAR `_paginate`, ET `_paginate` PART DE `_select`
`list` sert la convention de BACK-24 -- une page par appel, enveloppe avec
total, tri sur liste blanche -- et delegue a `_paginate`, la couture que les
finders parametres des depots concrets reutilisent sur leurs propres requetes.
Comme tout part de `self._select()`, le filtre de tenance s'applique au compte
comme a la fenetre : `total` est le total du perimetre courant, mecaniquement.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import Select, UnaryExpression, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.shared.domain.exceptions import NotFoundError
from app.shared.domain.pagination import (
    PageRequest,
    PageResult,
    Sort,
    SortDirection,
    UnknownSortFieldError,
)
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
    _not_found_error: type[NotFoundError]
    _not_found_message: str

    # Liste blanche du tri public (BACK-24) : nom expose par l'API -> colonne.
    # Vide par defaut -- aucun champ n'est triable tant qu'un depot concret ne
    # l'a pas ecrit, dans l'esprit opt-in du filtre de tenance. La garde du
    # constructeur ne l'exige pas : l'absence de tri est un etat legitime.
    _sortable: ClassVar[Mapping[str, InstrumentedAttribute[Any]]] = {}

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

    def _not_found(self, entity_id: UUID) -> NotFoundError:
        """Fabrique l'erreur d'absence du module, prete a etre levee.

        Args:
            entity_id: l'identifiant qui n'a rien trouve.

        Returns:
            L'exception du module concret, message renseigne.
        """
        return self._not_found_error(self._not_found_message.format(entity_id=entity_id))

    def _select(self) -> Select[tuple[ModelT]]:
        """Point de depart de TOUTE requete SELECT sur l'agregat.

        Les finders maison des depots concrets partent d'ici plutot que d'un
        `select(...)` importe : c'est la couture que le depot tenant (BACK-06b)
        surcharge pour restreindre au groupe courant. La convention rend le
        contournement visible -- un `from sqlalchemy import select` dans un
        depot est un signal de revue.

        Returns:
            La requete nue sur la classe de modele, prete a etre completee.
        """
        return select(self._model_type)

    async def _load(self, entity_id: UUID) -> ModelT:
        """Charge la ligne portant cet identifiant, ou leve l'erreur d'absence.

        Chemin commun de `get`, `save` et `delete` -- et seconde couture de la
        tenance (BACK-06b) : `session.get` sert depuis l'identity map sans SQL
        quand il le peut, aucun WHERE ne peut donc s'y glisser, et c'est la
        surcharge de cette methode qui verifie l'appartenance de la ligne.

        Args:
            entity_id: l'identifiant cherche.

        Returns:
            La ligne chargee, suivie par la session.

        Raises:
            NotFoundError: l'erreur d'absence declaree par le depot concret, si
                aucune ligne ne porte cet identifiant.
        """
        model = await self._session.get(self._model_type, entity_id)
        if model is None:
            raise self._not_found(entity_id)
        return model

    def _order_terms(self, sort: Sort | None) -> tuple[UnaryExpression[Any], ...]:
        """Traduit le tri public en clauses ORDER BY, cle primaire en renfort.

        Sans tri demande, la cle primaire seule : les identifiants UUIDv7
        (BACK-05) sont horodates, l'ordre par defaut est donc chronologique ET
        deterministe, sans colonne supplementaire. Avec un tri, la cle primaire
        depart les egalites DANS LE MEME SENS que le tri (l'idiome de
        `find_active_role`) : deux pages consecutives ne se recouvrent jamais,
        meme quand toutes les lignes portent la meme valeur triee.

        Args:
            sort: le tri public demande, ou None pour l'ordre par defaut.

        Returns:
            Les clauses a passer telles quelles a `order_by`.

        Raises:
            UnknownSortFieldError: si le champ n'est pas dans `_sortable` --
                defense en profondeur derriere la bordure HTTP, pour les
                chemins qui ne la traversent pas.
        """
        primary_key = self._model_type.__mapper__.primary_key
        if sort is None:
            return tuple(column.asc() for column in primary_key)
        attribute = self._sortable.get(sort.field)
        if attribute is None:
            raise UnknownSortFieldError(
                f"Le champ de tri « {sort.field} » n'est pas triable sur cette ressource.",
                details={"field": sort.field, "sortable_fields": sorted(self._sortable)},
            )
        if sort.direction is SortDirection.DESC:
            return (attribute.desc(), *(column.desc() for column in primary_key))
        return (attribute.asc(), *(column.asc() for column in primary_key))

    async def _paginate(
        self, statement: Select[tuple[ModelT]], page: PageRequest
    ) -> PageResult[EntityT]:
        """Compte puis fenetre une requete -- la couture commune des listes.

        `statement` DOIT partir de `self._select()` et venir SANS `order_by` :
        l'ordre appartient a la convention (tri public puis cle primaire), pas a
        l'appelant. Les finders parametres des depots concrets (recherche,
        filtres nommes) posent leurs WHERE puis delegent ici.

        DEUX REQUETES, TOUJOURS : le compte porte sur la requete filtree mise
        en sous-requete -- `order_by(None)` l'en depouille par precaution --
        et reste juste si un `_select` surcharge ajoute un jour un DISTINCT ou
        une jointure, la ou un `count(*)` plaque sur le SELECT d'origine se
        tromperait. Pas de raccourci quand la page est courte : un seul chemin
        de code, un compte toujours identique.

        Args:
            statement: la requete filtree, issue de `self._select()`.
            page: la fenetre demandee -- numero, taille, tri eventuel.

        Returns:
            La page d'entites et le total du perimetre courant. Une page
            au-dela de la fin est vide et porte le total reel : une page est
            une fenetre, pas une ressource -- pas d'erreur d'absence.

        Raises:
            UnknownSortFieldError: si le champ de tri n'est pas dans
                `_sortable`.
        """
        count_statement = select(func.count()).select_from(statement.order_by(None).subquery())
        total: int = (await self._session.execute(count_statement)).scalar_one()
        window = (
            statement.order_by(*self._order_terms(page.sort))
            .limit(page.page_size)
            .offset(page.offset)
        )
        models = (await self._session.execute(window)).scalars().all()
        return PageResult(
            items=[self._to_entity(model) for model in models],
            total=total,
            page=page.page,
            page_size=page.page_size,
        )

    async def get(self, entity_id: UUID, /) -> EntityT:
        """Retourne l'entite portant cet identifiant.

        Args:
            entity_id: l'identifiant cherche.

        Returns:
            L'entite reconstituee.

        Raises:
            NotFoundError: l'erreur d'absence declaree par le depot concret, si
                aucune ligne ne porte cet identifiant.
        """
        return self._to_entity(await self._load(entity_id))

    async def list(self, page: PageRequest, /) -> PageResult[EntityT]:
        """Retourne UNE page d'entites et le total du perimetre courant.

        La convention de BACK-24, appliquee : `_paginate` sur la requete nue de
        l'agregat. Bornes et defauts vivent dans `PageRequest`, l'ordre dans
        `_order_terms` -- voir ces deux-la pour le detail.

        Args:
            page: la fenetre demandee -- numero, taille, tri eventuel.

        Returns:
            La page d'entites, avec le total du perimetre courant.

        Raises:
            UnknownSortFieldError: si le champ de tri n'est pas dans
                `_sortable`.
        """
        return await self._paginate(self._select(), page)

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

        FLUSHEE COMME UN `add`, ET POUR LA MEME RAISON (correction BACK-06c). La
        modification d'une ligne suivie se relit sans SQL par l'identity map, ce
        qui masquait le probleme : mais une REQUETE, elle, part vers la base et
        `autoflush=False` (BACK-05) lui fait lire l'etat d'AVANT. Un cas d'usage
        qui modifie puis liste dans la meme transaction recevait donc une page
        ordonnee -- ou filtree -- sur ce qu'il venait de remplacer. C'est la suite
        de conformite de BACK-06c qui l'a mis au jour, en comparant ce chemin a
        celui de la doublure en memoire.

        Args:
            entity: l'entite modifiee.

        Raises:
            NotFoundError: l'erreur d'absence declaree par le depot concret, si
                l'entite n'a jamais ete enregistree.
        """
        model = await self._load(entity.id)
        self._apply_to_model(entity, model)
        await self._session.flush([model])

    async def delete(self, entity_id: UUID, /) -> None:
        """Supprime l'entite portant cet identifiant.

        La ligne est CHARGEE puis supprimee, jamais effacee par un DELETE
        direct : les cascades declarees a l'ORM s'appliquent, l'identity map
        du bloc reste coherente, et le depot tenant (BACK-06b) a une ligne en
        main pour verifier la tenance avant de la laisser partir.

        FLUSHEE COMME UN `add`, ET POUR LA MEME RAISON (correction BACK-06c).
        Sans ce flush, `session.delete()` ne fait que MARQUER la ligne : elle
        reste dans l'identity map, et le `session.get` de `_load` continue de la
        servir sans SQL. Le bloc voyait donc survivre ce qu'il venait de
        supprimer -- un second `delete` reussissait, et un `get` rendait une
        entite deja partie. La suite de conformite de BACK-06c l'a mis au jour :
        la doublure en memoire, elle, retirait la ligne aussitot.

        Args:
            entity_id: l'identifiant de l'entite a supprimer.

        Raises:
            NotFoundError: l'erreur d'absence declaree par le depot concret, si
                aucune ligne ne porte cet identifiant.
        """
        model = await self._load(entity_id)
        await self._session.delete(model)
        await self._session.flush([model])
