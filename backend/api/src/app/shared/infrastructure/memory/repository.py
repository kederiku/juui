"""Depot generique en memoire -- cinq operations, un dictionnaire (BACK-06c).

C'est la classe dont les doublures de depot des modules heritent, et le pendant
exact de `db/repositories/base.py`. Elle porte ce qui se repete d'un agregat a
l'autre -- get, list, add, save, delete, la pagination, la mise en attente des
ecritures -- pour qu'une doublure concrete ne declare plus que ce qui lui
appartient : son erreur d'absence, son message, et ses champs triables.

LA MEME FORME QUE LE DEPOT SQLALCHEMY, ET LES MEMES DEUX COUTURES
`_scope()` est le point de depart de TOUTE lecture -- `list` comme les finders
maison des doublures concretes -- et `_load()` le chargement par identifiant que
`get`, `save` et `delete` partagent. Ce sont les deux seuls endroits que le
filtre de tenance surcharge, plus bas dans `InMemoryTenantRepository`, exactement
comme `tenant.py` surcharge `_select()` et `_load()` cote SQLAlchemy. Deux
implementations qui se surchargent aux memes endroits divergent moins que deux
implementations qui se ressemblent.

LES ECRITURES SONT MISES EN ATTENTE, Y COMPRIS LES SUPPRESSIONS
Le magasin tient trois etats : ce qui est VALIDE, ce que le bloc a ecrit, ce que
le bloc a supprime. Le commit replie les deux derniers dans le premier, le
rollback les jette. Une doublure qui mettrait les seules ecritures en attente
laisserait un `delete()` survivre a un rollback -- et le test « une exception
avant le commit n'ecrit rien » passerait en ne prouvant que la moitie de ce
qu'il annonce.

CE QUI ENTRE ET CE QUI SORT EST UNE COPIE
Toujours, dans les deux sens. Un depot qui rendrait l'objet range laisserait un
`entity.verify_email()` NON VALIDE modifier l'etat « persiste » : le test
d'annulation passerait sans rien prouver. C'est la seule facon de reproduire ce
que fait la vraie persistance, ou l'etat vit dans une base et non dans le tas du
processus.

UNE LIMITE CONNUE DU TRI. Un champ triable qui vaut parfois `None` compare mal en
Python la ou PostgreSQL trierait NULLS LAST. Aucun champ triable declare
aujourd'hui n'est nullable ; le jour ou l'un le devient, c'est ici que la
convention devra etre ecrite -- et dans la suite de conformite avant tout.
"""

from abc import ABC
from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, ClassVar, assert_never
from uuid import UUID

from app.shared.domain.exceptions import NotFoundError
from app.shared.domain.pagination import (
    PageRequest,
    PageResult,
    Sort,
    SortDirection,
    UnknownSortFieldError,
)
from app.shared.domain.ports.repository import Identified
from app.shared.infrastructure.tenancy import (
    AllGroups,
    MissingTenantContextError,
    current_group_id,
    require_current_group_id,
)


@dataclass(slots=True)
class _Row[EntityT]:
    """Ce que le magasin range : une entite, et le groupe qui la porte.

    LE GROUPE EST SUR LA LIGNE, PAS SUR L'ENTITE, et c'est le point : une entite
    du domaine ne declare aucun `group_id` -- `TenantNote` le dit en toutes
    lettres, l'estampillage est l'affaire du socle. La ligne joue donc ici le
    role que la colonne `group_id` joue en base, et la doublure reproduit la
    tenance sans que le domaine ait a la connaitre.

    Attributes:
        entity: l'entite, deja copiee par le magasin.
        group_id: le groupe estampille a l'insertion, ou `None` pour un agregat
            non tenant.
    """

    entity: EntityT
    group_id: UUID | None = None


@dataclass(slots=True)
class InMemoryStore[EntityT: Identified]:
    """Etat d'un agregat : ce qui est valide, et ce que le bloc en cours change.

    Le magasin appartient a l'UNITE DE TRAVAIL et survit a ses blocs ; le depot
    n'en est qu'une vue. C'est ce partage qui rend le commit atomique entre
    plusieurs depots d'un meme module : une seule unite replie tous ses magasins,
    ou aucun.

    Attributes:
        copy: la fonction qui duplique une entite, appelee dans les deux sens.
            `deepcopy` par defaut -- correcte par construction, y compris pour
            une entite portant un dictionnaire ou une liste, la ou un
            `dataclasses.replace` nu partagerait ce champ avec l'etat range et
            ferait passer les tests d'annulation sans rien prouver. Une doublure
            qui sait faire moins cher peut la remplacer, jamais l'alleger sans
            raison ecrite.
    """

    copy: Callable[[EntityT], EntityT] = deepcopy
    _committed: dict[UUID, _Row[EntityT]] = field(default_factory=dict, init=False)
    _written: dict[UUID, _Row[EntityT]] = field(default_factory=dict, init=False)
    _deleted: set[UUID] = field(default_factory=set, init=False)

    def seed(self, entity: EntityT, *, group_id: UUID | None = None) -> None:
        """Pose un etat VALIDE initial, hors de tout bloc.

        C'est l'equivalent du semis par session brute des tests d'integration :
        il contourne le depot, donc le filtre de tenance, et sert de verite
        terrain a laquelle comparer le comportement filtre.

        Args:
            entity: l'entite a poser comme deja persistee.
            group_id: le groupe qui la porte, pour un agregat tenant.
        """
        self._committed[entity.id] = _Row(entity=self.copy(entity), group_id=group_id)

    def rows(self) -> dict[UUID, _Row[EntityT]]:
        """Rend ce que le bloc en cours voit : le valide, amende de ses ecritures.

        Returns:
            Les lignes visibles, entites copiees. Les ecritures du bloc masquent
            le valide, les suppressions du bloc le retirent.
        """
        visible = {**self._committed, **self._written}
        return {
            entity_id: _Row(entity=self.copy(row.entity), group_id=row.group_id)
            for entity_id, row in visible.items()
            if entity_id not in self._deleted
        }

    def row(self, entity_id: UUID) -> _Row[EntityT] | None:
        """Rend une ligne visible du bloc, ou `None`.

        Args:
            entity_id: l'identifiant cherche.

        Returns:
            La ligne, entite copiee, ou `None` si le bloc ne la voit pas.
        """
        if entity_id in self._deleted:
            return None
        row = self._written.get(entity_id) or self._committed.get(entity_id)
        if row is None:
            return None
        return _Row(entity=self.copy(row.entity), group_id=row.group_id)

    def write(self, row: _Row[EntityT]) -> None:
        """Inscrit une ligne dans le bloc, sans valider la transaction.

        Args:
            row: la ligne a ecrire. L'entite est copiee : ce que l'appelant garde
                en main ne peut plus toucher l'etat range.
        """
        entity_id = row.entity.id
        self._deleted.discard(entity_id)
        self._written[entity_id] = _Row(entity=self.copy(row.entity), group_id=row.group_id)

    def remove(self, entity_id: UUID) -> None:
        """Marque une ligne supprimee dans le bloc, sans valider la transaction.

        Args:
            entity_id: l'identifiant de la ligne a supprimer.
        """
        self._written.pop(entity_id, None)
        self._deleted.add(entity_id)

    def commit(self) -> None:
        """Replie les ecritures et les suppressions du bloc dans l'etat valide."""
        self._committed.update(self._written)
        for entity_id in self._deleted:
            self._committed.pop(entity_id, None)
        self._written.clear()
        self._deleted.clear()

    def rollback(self) -> None:
        """Jette ce que le bloc a ecrit et supprime depuis le dernier commit."""
        self._written.clear()
        self._deleted.clear()

    def committed_entity(self, entity_id: UUID) -> EntityT | None:
        """Relit l'etat VALIDE, sans egard pour le bloc en cours.

        C'est ce qu'un test interroge pour assurer qu'une ecriture a bien ete
        validee -- ou qu'elle ne l'a pas ete.

        Args:
            entity_id: l'identifiant cherche.

        Returns:
            Une copie de l'entite validee, ou `None`.
        """
        row = self._committed.get(entity_id)
        return None if row is None else self.copy(row.entity)


class InMemoryRepository[EntityT: Identified](ABC):
    """Socle des doublures de depot : les operations communes a tout agregat.

    Chaque doublure concrete declare deux choses en corps de classe -- l'erreur
    d'absence de son module (`_not_found_error`) et le gabarit de son message
    (`_not_found_message`, avec `{entity_id}`) --, plus les champs qu'elle rend
    triables. Tout le reste est herite, y compris des operations que son port
    metier n'expose pas : le port ne s'elargit pas parce que la classe sait faire
    plus, doctrine BACK-06a, valable des deux cotes du miroir.
    """

    _not_found_error: type[NotFoundError]
    _not_found_message: str

    # Liste blanche du tri public (BACK-24), en NOMS D'ATTRIBUTS de l'entite --
    # la ou le depot SQLAlchemy nomme des colonnes. Le nom expose par l'API et le
    # nom de l'attribut coincident ici : une doublure n'a pas de schema physique
    # dont le vocabulaire pourrait diverger de celui du domaine.
    _sortable: ClassVar[frozenset[str]] = frozenset()

    def __init__(self, store: InMemoryStore[EntityT]) -> None:
        """Rattache la doublure au magasin de l'unite de travail.

        Le magasin est FOURNI, jamais cree ici : c'est l'unite de travail qui le
        possede et qui decide du commit, exactement comme elle possede la session
        cote SQLAlchemy. Une doublure qui fabriquerait son propre magasin rendrait
        impossible d'ecrire deux agregats dans une seule transaction.

        Args:
            store: le magasin de l'agregat, servi par l'unite de travail.

        Raises:
            TypeError: si la classe concrete ne declare pas ses deux attributs de
                configuration. Meme garde et meme motif que le depot SQLAlchemy :
                Mypy ne peut pas voir cet oubli, les annotations de la base lui
                faisant croire qu'ils existent.
        """
        for required in ("_not_found_error", "_not_found_message"):
            if not hasattr(type(self), required):
                message = (
                    f"{type(self).__name__} ne declare pas `{required}` : les deux "
                    "attributs de la doublure de depot se posent en corps de classe."
                )
                raise TypeError(message)
        self._store = store

    def _not_found(self, entity_id: UUID) -> NotFoundError:
        """Fabrique l'erreur d'absence du module, prete a etre levee.

        Args:
            entity_id: l'identifiant qui n'a rien trouve.

        Returns:
            L'exception du module concret, message renseigne.
        """
        return self._not_found_error(self._not_found_message.format(entity_id=entity_id))

    def _scope(self) -> Iterable[_Row[EntityT]]:
        """Point de depart de TOUTE lecture sur l'agregat.

        Les finders maison des doublures concretes partent d'ici plutot que du
        magasin : c'est la couture que la doublure tenante surcharge pour
        restreindre au groupe courant, pendant exact de `self._select()`.

        Returns:
            Les lignes du perimetre courant -- ici, toutes celles du bloc.
        """
        return self._store.rows().values()

    def _load(self, entity_id: UUID) -> _Row[EntityT]:
        """Charge la ligne portant cet identifiant, ou leve l'erreur d'absence.

        Chemin commun de `get`, `save` et `delete`, et seconde couture de la
        tenance.

        Args:
            entity_id: l'identifiant cherche.

        Returns:
            La ligne, entite copiee.

        Raises:
            NotFoundError: l'erreur d'absence declaree par la doublure concrete,
                si aucune ligne ne porte cet identifiant.
        """
        row = self._store.row(entity_id)
        if row is None:
            raise self._not_found(entity_id)
        return row

    def _stamp(self, entity: EntityT) -> _Row[EntityT]:
        """Construit la ligne a inserer pour une entite neuve.

        Pendant de `_to_model` : c'est ici que la doublure tenante estampille le
        groupe, et nulle part ailleurs.

        Args:
            entity: l'entite a persister.

        Returns:
            La ligne correspondante, sans groupe pour un agregat non tenant.
        """
        return _Row(entity=entity)

    def _sorted(self, rows: Iterable[_Row[EntityT]], sort: Sort | None) -> list[_Row[EntityT]]:
        """Ordonne les lignes selon la convention de BACK-24.

        Sans tri demande, l'identifiant seul : les UUIDv7 sont horodates, l'ordre
        par defaut est donc chronologique ET deterministe -- meme propriete que la
        cle primaire cote SQL. Avec un tri, l'identifiant depart les egalites DANS
        LE MEME SENS, ce que `reverse=True` applique au couple entier.

        Args:
            rows: les lignes du perimetre courant.
            sort: le tri public demande, ou `None` pour l'ordre par defaut.

        Returns:
            Les lignes ordonnees.

        Raises:
            UnknownSortFieldError: si le champ n'est pas dans `_sortable` --
                defense en profondeur derriere la bordure HTTP, pour les chemins
                qui ne la traversent pas.
        """
        if sort is None:
            return sorted(rows, key=lambda row: row.entity.id)
        if sort.field not in self._sortable:
            raise UnknownSortFieldError(
                f"Le champ de tri « {sort.field} » n'est pas triable sur cette ressource.",
                details={"field": sort.field, "sortable_fields": sorted(self._sortable)},
            )
        # Capture hors du lambda : la variable fermee doit rester le nom du champ,
        # et non un `sort` que Mypy pourrait relire comme facultatif.
        field_name = sort.field

        def key(row: _Row[EntityT]) -> tuple[Any, UUID]:
            """Compose la cle de tri : le champ public, puis l'identifiant."""
            return (getattr(row.entity, field_name), row.entity.id)

        return sorted(rows, key=key, reverse=sort.direction is SortDirection.DESC)

    def _paginate(self, rows: Iterable[_Row[EntityT]], page: PageRequest) -> PageResult[EntityT]:
        """Compte puis fenetre un perimetre -- la couture commune des listes.

        `rows` DOIT venir de `self._scope()` : c'est ce qui rend le total juste,
        c'est-a-dire celui du perimetre courant et non celui du magasin. Les
        finders parametres des doublures concretes filtrent puis delegent ici.

        Args:
            rows: les lignes du perimetre courant.
            page: la fenetre demandee -- numero, taille, tri eventuel.

        Returns:
            La page d'entites et le total du perimetre courant. Une page au-dela
            de la fin est vide et porte le total reel : une page est une fenetre,
            pas une ressource.

        Raises:
            UnknownSortFieldError: si le champ de tri n'est pas dans `_sortable`.
        """
        ordered = self._sorted(rows, page.sort)
        window = ordered[page.offset : page.offset + page.page_size]
        return PageResult(
            items=[row.entity for row in window],
            total=len(ordered),
            page=page.page,
            page_size=page.page_size,
        )

    async def get(self, entity_id: UUID, /) -> EntityT:
        """Retourne l'entite portant cet identifiant.

        Args:
            entity_id: l'identifiant cherche.

        Returns:
            Une COPIE de l'entite rangee.

        Raises:
            NotFoundError: l'erreur d'absence declaree par la doublure concrete,
                si aucune entite ne porte cet identifiant.
        """
        return self._load(entity_id).entity

    async def list(self, page: PageRequest, /) -> PageResult[EntityT]:
        """Retourne UNE page d'entites et le total du perimetre courant.

        Args:
            page: la fenetre demandee -- numero, taille, tri eventuel.

        Returns:
            La page d'entites, avec le total du perimetre courant.

        Raises:
            UnknownSortFieldError: si le champ de tri n'est pas dans `_sortable`.
        """
        return self._paginate(self._scope(), page)

    async def add(self, entity: EntityT, /) -> None:
        """Inscrit une entite neuve dans le bloc, sans valider la transaction.

        L'ecriture est aussitot visible du reste du bloc -- la relire, la modifier
        ou la supprimer avant le commit fonctionne -- mais rien n'est valide.

        La collision d'identifiant est le SEUL controle de stockage reproduit ici,
        et il ne l'est pas par gout de la fidelite : sans lui, la doublure
        ECRASERAIT en silence une entite existante, ce qu'aucune base ne fait. Les
        autres contraintes -- unicite metier, cle etrangere, NOT NULL -- ne sont
        pas reproduites, et c'est un choix : les inventer ici ferait echouer des
        tests pour des regles que la vraie base n'applique peut-etre pas de la
        meme facon. Elles sont l'objet des tests d'infrastructure sur vraie base.

        Args:
            entity: l'entite a creer.

        Raises:
            RuntimeError: si une entite porte deja cet identifiant -- defaut de
                programmation du test, comme l'ouverture d'un bloc deja ouvert.
        """
        if self._store.row(entity.id) is not None:
            message = (
                f"Une entite porte deja l'identifiant {entity.id} dans cette doublure : "
                "`add` cree, il ne remplace pas -- utiliser `save` pour modifier."
            )
            raise RuntimeError(message)
        self._store.write(self._stamp(entity))

    async def save(self, entity: EntityT, /) -> None:
        """Reporte l'etat d'une entite deja enregistree, sans valider.

        LE GROUPE DE LA LIGNE N'EST JAMAIS REPORTE : il est relu de la ligne
        existante, exactement comme `_apply_to_model` ne touche pas `group_id`
        cote SQLAlchemy. Une entite ne change pas de groupe par une ecriture.

        Args:
            entity: l'entite modifiee.

        Raises:
            NotFoundError: l'erreur d'absence declaree par la doublure concrete,
                si l'entite n'a jamais ete enregistree.
        """
        existing = self._load(entity.id)
        self._store.write(_Row(entity=entity, group_id=existing.group_id))

    async def delete(self, entity_id: UUID, /) -> None:
        """Supprime l'entite portant cet identifiant, sans valider.

        La ligne est CHARGEE puis retiree, jamais retiree a l'aveugle : c'est ce
        qui donne a la doublure tenante une ligne en main pour verifier la
        tenance avant de la laisser partir.

        Args:
            entity_id: l'identifiant de l'entite a supprimer.

        Raises:
            NotFoundError: l'erreur d'absence declaree par la doublure concrete,
                si aucune entite ne porte cet identifiant.
        """
        self._load(entity_id)
        self._store.remove(entity_id)


class InMemoryTenantRepository[EntityT: Identified](InMemoryRepository[EntityT]):
    """Socle des doublures d'agregats tenant : le filtre de groupe, reproduit.

    ELLE NE REDEFINIT AUCUNE DES CINQ OPERATIONS, et c'est le meme parti que
    `TenantSqlAlchemyRepository` : elle surcharge les deux coutures -- `_scope`
    et `_load` -- plus l'estampillage `_stamp`, et `get`, `list`, `add`, `save`
    et `delete` en heritent le filtre. Le filtre reste OPT-IN, agregat par
    agregat : une doublure non tenante herite de `InMemoryRepository` et ne porte
    rien de tout ceci.

    POURQUOI CETTE CLASSE EXISTE PLUTOT QUE RIEN
    Le ticket le dit sans detour : si le filtrage tenant n'est pas reproduit dans
    les doublures, les tests d'application passent sur une isolation que la
    production applique et pas eux -- et le premier vrai bogue d'isolation ne
    sera jamais attrape en test rapide. C'est aussi l'argument que l'ADR-0013
    oppose a `with_loader_criteria` : un filtre pose sur la session SQLAlchemy
    serait INVISIBLE d'ici, et les deux moities du test de conformite ne
    parleraient plus de la meme chose.
    """

    def _missing_context(self) -> MissingTenantContextError:
        """Fabrique l'erreur d'acces tenant hors de tout contexte de groupe.

        Returns:
            L'erreur, prete a etre levee -- jamais un repli silencieux qui
            rendrait les donnees de tous les groupes.
        """
        message = (
            f"Acces a l'agregat tenant « {type(self).__name__} » sans groupe dans le "
            "contexte : poser `use_group(group_id)`, ou assumer le mode « tous "
            "groupes » par `use_all_groups(reason=...)`."
        )
        return MissingTenantContextError(message)

    def _scope(self) -> Iterable[_Row[EntityT]]:
        """Restreint toute lecture au perimetre de tenance courant.

        Returns:
            Les lignes du groupe actif -- ou toutes sous le mode « tous
            groupes », qui est un choix ecrit, pas un defaut.

        Raises:
            MissingTenantContextError: si aucun perimetre n'est pose.
        """
        rows = super()._scope()
        scope = current_group_id.get()
        match scope:
            case UUID() as group_id:
                return [row for row in rows if row.group_id == group_id]
            case AllGroups():
                return rows
            case None:
                raise self._missing_context()
            case _:
                assert_never(scope)

    def _load(self, entity_id: UUID) -> _Row[EntityT]:
        """Charge la ligne puis verifie son appartenance au groupe courant.

        Le contexte est lu AVANT le magasin : hors de tout perimetre, aucune
        lecture n'a lieu. Une ligne d'un autre groupe leve l'erreur d'ABSENCE du
        module -- le meme mot que pour un identifiant inexistant, pour ne pas
        confirmer que la ressource existe ailleurs. Au niveau HTTP, ce sera un
        404 et jamais un 403.

        Args:
            entity_id: l'identifiant cherche.

        Returns:
            La ligne, appartenant au perimetre courant.

        Raises:
            MissingTenantContextError: si aucun perimetre n'est pose.
            NotFoundError: l'erreur d'absence declaree par la doublure concrete,
                si aucune entite ne porte cet identifiant -- ou si elle appartient
                a un autre groupe.
        """
        scope = current_group_id.get()
        if scope is None:
            raise self._missing_context()
        row = super()._load(entity_id)
        match scope:
            case UUID() as group_id:
                if row.group_id != group_id:
                    raise self._not_found(entity_id)
            case AllGroups():
                pass
            case _:
                assert_never(scope)
        return row

    def _stamp(self, entity: EntityT) -> _Row[EntityT]:
        """Construit la ligne a inserer, estampillee du groupe courant.

        Le mode « tous groupes » echoue ici : lire partout n'est pas ecrire
        n'importe ou. Ecrire dans un groupe donne se fait par un bloc
        `use_group(group_id)` imbrique -- le patron du seed d'INFRA-08.

        Args:
            entity: l'entite a persister.

        Returns:
            La ligne correspondante, groupe renseigne par le socle.

        Raises:
            MissingTenantContextError: si aucun groupe n'est pose, ou si le mode
                « tous groupes » est actif.
        """
        row = super()._stamp(entity)
        row.group_id = require_current_group_id()
        return row
