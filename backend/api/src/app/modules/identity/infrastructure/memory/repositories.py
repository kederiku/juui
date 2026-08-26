"""Doublure en memoire du port `AccountRepository` (BACK-06c).

Le pendant de `SqlAlchemyAccountRepository`, adosse a un dictionnaire. Elle
herite du depot generique en memoire, qui porte get/list/add/save/delete, la
pagination et la mise en attente des ecritures ; ne vit ici que ce qui appartient
au compte : l'erreur d'absence, son message, et la recherche par adresse.

LE MESSAGE D'ABSENCE EST CELUI DU DEPOT REEL, MOT POUR MOT. Ce n'est pas un
souci d'esthetique : la suite de conformite compare les deux implementations, et
un test qui verifierait le message aupres de l'une passerait aupres de l'autre.
Le gabarit est donc recopie tel quel de `infrastructure/db/repositories.py` --
les deux doivent bouger ensemble.

`list` et `delete` existent ici sans entrer au port, exactement comme cote
SQLAlchemy : le port ne s'elargit pas parce que la classe sait faire plus.
"""

from app.modules.identity.domain.entities import Account
from app.modules.identity.domain.exceptions import AccountNotFoundError
from app.modules.identity.domain.ports import AccountRepository
from app.shared.infrastructure.memory.repository import InMemoryRepository


class InMemoryAccountRepository(InMemoryRepository[Account], AccountRepository):
    """Depot de comptes en memoire, ecritures en attente de validation."""

    _not_found_error = AccountNotFoundError
    _not_found_message = "Aucun compte ne porte l'identifiant {entity_id}."

    async def find_by_email(self, email: str) -> Account | None:
        """Cherche un compte par son adresse, sans erreur si rien ne correspond.

        PART DE `self._scope()`, jamais du magasin : c'est la meme convention que
        cote SQLAlchemy, ou tout finder maison part de `self._select()`. Un
        agregat non tenant n'y gagne rien aujourd'hui -- le compte n'en est pas un
        -- mais la convention est ce qui fera porter le filtre aux finders du
        premier module tenant qui en ecrira.

        LA COMPARAISON EST EXACTE, alors que la base compare en minuscules
        (`ix_accounts_email_lower`, INFRA-09). Ce n'est pas une divergence
        tolerable par negligence : l'adresse est NORMALISEE par le domaine avant
        d'atteindre le port (`normalize_email`), donc les deux cotes voient deja
        la meme chaine. Ce que la base garantit en plus -- qu'aucune insertion
        concurrente ne cree un doublon de casse -- est une contrainte de
        STOCKAGE, prouvee par les tests d'infrastructure et non reproductible ici.

        Args:
            email: l'adresse, deja normalisee par le domaine.

        Returns:
            Le compte, ou None si l'adresse est libre.
        """
        for row in self._scope():
            if row.entity.email == email:
                return row.entity
        return None
