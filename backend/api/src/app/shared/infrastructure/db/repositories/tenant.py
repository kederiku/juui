"""Depot generique filtre par groupe : l'isolation devient mecanique (BACK-06b).

C'est la classe dont heritent les depots des agregats declarant `TenantMixin`.
Elle ne redefinit AUCUNE des cinq operations : elle surcharge les deux coutures
du depot generique -- `_select` et `_load` -- et l'estampillage `_to_model`, et
`get`, `list`, `add`, `save` et `delete` en heritent le filtre. Un depot non
tenant continue d'heriter de `SqlAlchemyRepository` et ne porte rien de tout
ceci : le filtre est OPT-IN, agregat par agregat, comme `TenantMixin` l'exige.

CHARGER PUIS VERIFIER, PLUTOT QU'UN WHERE
`session.get` sert depuis l'identity map SANS emettre de SQL quand la ligne est
deja chargee dans le bloc -- aucun WHERE ne peut donc filtrer ce chemin. La
verification se fait en Python, sur `model.group_id`, une fois la ligne en
main : elle couvre l'identity map comme la requete, et `group_id` est immuable
(`_to_model` est seul a le poser, la garde ci-dessous l'atteste). Une ligne
d'un autre groupe leve l'erreur d'ABSENCE du module, indistincte d'un
identifiant inexistant : au niveau HTTP elle deviendra un 404, jamais un 403
qui confirmerait l'existence de la ressource.

POURQUOI PAS `with_loader_criteria` SUR LA SESSION
L'evenement ORM global aurait filtre les SELECT, mais : il ne couvre pas
l'identity map de `session.get` (aucun SQL emis, aucun critere applique) ; il
ignore l'erreur d'absence du module, que seul le depot connait ; il serait
invisible des doublures en memoire de BACK-06c, dont le test de conformite
commun doit reproduire la meme tenance ; et il deplacerait le filtre hors du
code que la revue lit -- a rebours d'ADR-0004, qui veut un choix visible. La
seconde ceinture prevue est le RLS PostgreSQL, differee par ADR-0004.

TOUTE REQUETE MAISON COMMENCE PAR `self._select()`
Le finder d'un depot tenant part de `self._select()`, jamais d'un
`select(...)` importe : c'est ce qui etend le filtre aux requetes ecrites a la
main. La forme sure est aussi la plus courte, et un `from sqlalchemy import
select` dans un depot devient un signal de revue.

ECRIRE SOUS L'ECHAPPATOIRE
Sous `use_all_groups(reason=...)`, les lectures voient tous les groupes mais
`add` continue d'echouer : rien ne dit dans quel groupe estampiller. Le patron
est celui du seed (INFRA-08) : lire partout sous l'echappatoire, ecrire groupe
par groupe dans des blocs `use_group(group_id)` imbriques.
"""

from typing import assert_never, cast
from uuid import UUID

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.domain.ports.repository import Identified
from app.shared.infrastructure.db.base import Base
from app.shared.infrastructure.db.mixins import TENANT_COLUMN, TenantMixin
from app.shared.infrastructure.db.repositories.base import SqlAlchemyRepository
from app.shared.infrastructure.tenancy import (
    AllGroups,
    MissingTenantContextError,
    current_group_id,
    require_current_group_id,
)


class TenantSqlAlchemyRepository[EntityT: Identified, ModelT: Base](
    SqlAlchemyRepository[EntityT, ModelT]
):
    """Socle des depots d'agregats tenant : le filtre de groupe, herite partout.

    Meme contrat de declaration que `SqlAlchemyRepository` -- classe de modele,
    erreur d'absence, gabarit de message, deux fonctions de mapping -- avec une
    exigence de plus, verifiee au premier usage : le modele declare
    `TenantMixin`. `_apply_to_model` ne touche JAMAIS `group_id` : la tenance
    est estampillee par le socle a l'insertion, et la garde de `_to_model`
    refuse un mapping qui s'en melerait.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Rattache le depot a la session, apres controle du modele.

        PEP 695 ne sait pas exiger « `Base` ET `TenantMixin` » sur `ModelT` --
        une borne d'intersection n'existe pas, et deux CONTRAINTES signifieraient
        l'un OU l'autre. La garde d'execution tient donc le role que le systeme
        de types ne peut pas tenir, et les `cast` vers `TenantMixin` plus bas ne
        font que l'enregistrer.

        Args:
            session: la session du bloc `async with` en cours, servie par la
                propriete `_active_session` de l'unite de travail.

        Raises:
            TypeError: si la classe concrete ne declare pas ses trois attributs
                de configuration, ou si son modele ne declare pas `TenantMixin`.
        """
        super().__init__(session)
        if not issubclass(self._model_type, TenantMixin):
            message = (
                f"{type(self).__name__} herite du depot tenant mais son modele "
                f"{self._model_type.__name__} ne declare pas TenantMixin : le filtre "
                "n'aurait aucune colonne de groupe a comparer."
            )
            raise TypeError(message)

    def _missing_context(self) -> MissingTenantContextError:
        """Fabrique l'erreur d'acces tenant hors de tout contexte de groupe.

        Returns:
            L'erreur, prete a etre levee -- jamais un repli silencieux qui
            rendrait les donnees de tous les groupes.
        """
        message = (
            f"Acces a l'agregat tenant « {self._model_type.__name__} » sans groupe "
            "dans le contexte : poser `use_group(group_id)`, ou assumer le mode "
            "« tous groupes » par `use_all_groups(reason=...)`."
        )
        return MissingTenantContextError(message)

    def _select(self) -> Select[tuple[ModelT]]:
        """Restreint toute requete SELECT au perimetre de tenance courant.

        Returns:
            La requete, filtree sur le groupe actif -- ou sans filtre sous le
            mode « tous groupes », qui est un choix ecrit, pas un defaut.

        Raises:
            MissingTenantContextError: si aucun perimetre n'est pose.
        """
        statement = super()._select()
        scope = current_group_id.get()
        match scope:
            case UUID() as group_id:
                tenant_type = cast("type[TenantMixin]", self._model_type)
                return statement.where(tenant_type.group_id == group_id)
            case AllGroups():
                return statement
            case None:
                raise self._missing_context()
            case _:
                assert_never(scope)

    async def _load(self, entity_id: UUID) -> ModelT:
        """Charge la ligne puis verifie son appartenance au groupe courant.

        Le contexte est lu AVANT `session.get` : hors de tout perimetre, aucune
        requete ne part. Une ligne d'un autre groupe leve l'erreur d'absence du
        module -- le meme mot que pour un identifiant inexistant, pour ne pas
        confirmer que la ressource existe ailleurs. La ligne etrangere chargee
        au passage reste dans l'identity map du bloc : inoffensif, elle n'est
        jamais rendue a l'appelant.

        Args:
            entity_id: l'identifiant cherche.

        Returns:
            La ligne chargee, appartenant au perimetre courant.

        Raises:
            MissingTenantContextError: si aucun perimetre n'est pose.
            DomainError: l'erreur d'absence declaree par le depot concret, si
                aucune ligne ne porte cet identifiant -- ou si elle appartient
                a un autre groupe.
        """
        scope = current_group_id.get()
        if scope is None:
            raise self._missing_context()
        model = await super()._load(entity_id)
        match scope:
            case UUID() as group_id:
                if cast("TenantMixin", model).group_id != group_id:
                    raise self._not_found(entity_id)
            case AllGroups():
                pass
            case _:
                assert_never(scope)
        return model

    def _to_model(self, entity: EntityT) -> ModelT:
        """Construit la ligne a inserer, estampillee du groupe courant.

        L'estampillage a lieu ICI, avant `session.add` : la contrainte NOT NULL
        de `group_id` est satisfaite des le flush, et un contexte manquant
        echoue avant que la session soit touchee. Le mode « tous groupes »
        echoue aussi -- lire partout n'est pas ecrire n'importe ou.

        Args:
            entity: l'entite a persister.

        Returns:
            Le modele correspondant, `group_id` renseigne par le socle.

        Raises:
            TypeError: si `_apply_to_model` a renseigne `group_id` -- la
                tenance n'appartient pas au mapping du module.
            MissingTenantContextError: si aucun groupe n'est pose, ou si le
                mode « tous groupes » est actif.
        """
        model = super()._to_model(entity)
        if TENANT_COLUMN in model.__dict__:
            message = (
                f"{type(self).__name__}._apply_to_model a renseigne « {TENANT_COLUMN} » : "
                "la tenance est estampillee par le socle, jamais par le mapping du module."
            )
            raise TypeError(message)
        cast("TenantMixin", model).group_id = require_current_group_id()
        return model
