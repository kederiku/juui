"""Adaptateur SQLAlchemy du port `AccountRepository` (BACK-04).

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

CE QUE BACK-06a CHANGERA ICI
Cette classe heritera du depot generique de `shared/`, qui portera get/list/add/
save/delete et le mapping dans les deux sens. Les methodes ci-dessous
disparaitront au profit de deux fonctions de mapping declarees a la classe. Le
CONTRAT, lui, ne bouge pas.

CE QUE BACK-06b AJOUTERA
Le filtrage automatique par groupe. Il ne concernera PAS ce depot : `Account` ne
declare pas `TenantMixin` (voir `models.py`).
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.domain.entities import Account, AccountStatus, AccountType
from app.modules.identity.domain.exceptions import AccountNotFoundError
from app.modules.identity.domain.ports import AccountRepository
from app.modules.identity.infrastructure.db.models import AccountModel


def _to_entity(model: AccountModel) -> Account:
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


def _to_model(account: Account) -> AccountModel:
    """Construit la ligne a inserer pour un compte neuf.

    Args:
        account: l'entite a persister.

    Returns:
        Le modele SQLAlchemy correspondant, pas encore rattache a une session.
    """
    return AccountModel(
        id=account.id,
        email=account.email,
        first_name=account.first_name,
        last_name=account.last_name,
        account_type=account.account_type.value,
        phone=account.phone,
        status=account.status.value,
        email_verified=account.email_verified,
    )


def _apply_to_model(account: Account, model: AccountModel) -> None:
    """Reporte l'etat d'une entite sur la ligne deja suivie par la session.

    Modifier la ligne EXISTANTE plutot que d'en construire une neuve : c'est ce
    qui laisse SQLAlchemy emettre un UPDATE. Un `session.merge()` d'un objet
    reconstruit produirait le meme resultat au prix d'un SELECT de plus.

    L'identifiant n'est jamais reporte : une entite ne change pas d'identite.

    Args:
        account: l'entite modifiee.
        model: la ligne correspondante, rattachee a la session.
    """
    model.email = account.email
    model.first_name = account.first_name
    model.last_name = account.last_name
    model.account_type = account.account_type.value
    model.phone = account.phone
    model.status = account.status.value
    model.email_verified = account.email_verified


class SqlAlchemyAccountRepository(AccountRepository):
    """Depot de comptes adosse a PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        """Rattache le depot a la session de la requete en cours.

        La session est FOURNIE, jamais creee ici : sa duree de vie est celle de
        la requete, et c'est l'unite de travail (BACK-06a) qui l'ouvrira et la
        refermera. Un depot qui ouvrirait sa propre session rendrait impossible
        d'ecrire deux agregats dans une seule transaction.

        Args:
            session: la session asynchrone de la requete. Sa fabrique est
                livree par BACK-05 ; c'est l'unite de travail (BACK-06a) qui la
                fera tourner et l'injectera ici.
        """
        self._session = session

    async def get(self, account_id: UUID) -> Account:
        """Retourne le compte portant cet identifiant.

        Args:
            account_id: l'identifiant du compte.

        Returns:
            Le compte reconstitue.

        Raises:
            AccountNotFoundError: si aucune ligne ne porte cet identifiant.
        """
        model = await self._session.get(AccountModel, account_id)
        if model is None:
            message = f"Aucun compte ne porte l'identifiant {account_id}."
            raise AccountNotFoundError(message)
        return _to_entity(model)

    async def find_by_email(self, email: str) -> Account | None:
        """Cherche un compte par son adresse normalisee.

        Args:
            email: l'adresse, deja normalisee par le domaine.

        Returns:
            Le compte, ou None si l'adresse est libre.
        """
        statement = select(AccountModel).where(AccountModel.email == email)
        model = (await self._session.execute(statement)).scalar_one_or_none()
        return None if model is None else _to_entity(model)

    async def add(self, account: Account) -> None:
        """Ajoute un compte neuf a la session, sans valider la transaction.

        Aucun `commit` ici : c'est l'unite de travail (BACK-06a) qui decide
        quand la transaction se referme. Un depot qui validerait tout seul
        rendrait impossible d'annuler l'ensemble d'un cas d'usage.

        Args:
            account: le compte a creer.
        """
        self._session.add(_to_model(account))

    async def save(self, account: Account) -> None:
        """Reporte l'etat d'un compte deja enregistre.

        Args:
            account: le compte modifie.

        Raises:
            AccountNotFoundError: si le compte n'existe pas en base.
        """
        model = await self._session.get(AccountModel, account.id)
        if model is None:
            message = f"Aucun compte ne porte l'identifiant {account.id}."
            raise AccountNotFoundError(message)
        _apply_to_model(account, model)
