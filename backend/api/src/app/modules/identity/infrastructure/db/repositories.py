"""Adaptateur SQLAlchemy du port `AccountRepository` (BACK-04, refonte BACK-06a).

C'est ICI, et nulle part ailleurs, que le modele de persistance rencontre
l'entite du domaine. Le cas d'usage ne voit passer que des `Account` ; la
couche d'API ne voit jamais un `AccountModel`. Le depot est la charniere, et le
mapping y est ECRIT A LA MAIN.

POURQUOI UN MAPPING MANUEL ET NON UNE COPIE DE CHAMPS
Un `Account(**model.__dict__)` marcherait aujourd'hui et casserait au premier
champ que le domaine nomme autrement que la base -- silencieusement, en
remplissant l'entite de valeurs par defaut. Le mapping explicite echoue a la
compilation de Mypy, pas en production. Il rend aussi visibles les conversions
qui comptent : `str` en base, `AccountType` dans le domaine.

CE QUE BACK-06A A CHANGE ICI
La classe herite du depot generique de `shared/`, qui porte get/list/add/save/
delete et la mecanique du mapping. Ne restent declares ici que ce qui
appartient au compte : les deux fonctions de mapping, l'erreur d'absence et
son message, et la recherche par adresse -- le vocabulaire du module. Le
CONTRAT du port, lui, n'a pas bouge. `list` et `delete` existent sur la classe
sans entrer au port : le port ne s'elargit pas parce que la classe sait faire
plus.

CE QUE BACK-06B AJOUTERA
Le filtrage automatique par groupe. Il ne concernera PAS ce depot : `Account` ne
declare pas `TenantMixin` (voir `models.py`).
"""

from sqlalchemy import select

from app.modules.identity.domain.entities import Account, AccountStatus, AccountType
from app.modules.identity.domain.exceptions import AccountNotFoundError
from app.modules.identity.domain.ports import AccountRepository
from app.modules.identity.infrastructure.db.models import AccountModel
from app.shared.infrastructure.db.repositories.base import SqlAlchemyRepository


class SqlAlchemyAccountRepository(SqlAlchemyRepository[Account, AccountModel], AccountRepository):
    """Depot de comptes adosse a PostgreSQL."""

    _model_type = AccountModel
    _not_found_error = AccountNotFoundError
    _not_found_message = "Aucun compte ne porte l'identifiant {entity_id}."

    def _to_entity(self, model: AccountModel) -> Account:
        """Reconstitue l'entite du domaine a partir d'une ligne de la table.

        Args:
            model: la ligne relue par SQLAlchemy.

        Returns:
            Le compte, avec ses valeurs converties dans les types du domaine.
        """
        return Account(
            id=model.id,
            email=model.email,
            first_name=model.first_name,
            last_name=model.last_name,
            account_type=AccountType(model.account_type),
            phone=model.phone,
            status=AccountStatus(model.status),
            email_verified=model.email_verified,
        )

    def _apply_to_model(self, entity: Account, model: AccountModel) -> None:
        """Reporte l'etat d'un compte sur sa ligne, sans toucher a `id`.

        L'identifiant n'est jamais reporte : une entite ne change pas
        d'identite, et le depot generique est seul a le poser, a la creation.

        Args:
            entity: le compte dont l'etat fait foi.
            model: la ligne a mettre au meme etat.
        """
        model.email = entity.email
        model.first_name = entity.first_name
        model.last_name = entity.last_name
        model.account_type = entity.account_type.value
        model.phone = entity.phone
        model.status = entity.status.value
        model.email_verified = entity.email_verified

    async def find_by_email(self, email: str) -> Account | None:
        """Cherche un compte par son adresse normalisee.

        Args:
            email: l'adresse, deja normalisee par le domaine.

        Returns:
            Le compte, ou None si l'adresse est libre.
        """
        statement = select(AccountModel).where(AccountModel.email == email)
        model = (await self._session.execute(statement)).scalar_one_or_none()
        return None if model is None else self._to_entity(model)
