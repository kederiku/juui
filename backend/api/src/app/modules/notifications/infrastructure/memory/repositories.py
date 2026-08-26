"""Doublure en memoire du port `NotificationPreferencesRepository` (BACK-06c).

Le pendant de `SqlAlchemyNotificationPreferencesRepository`, adosse a un
dictionnaire. Elle herite du depot generique en memoire ; ne vit ici que ce qui
appartient au module : l'erreur d'absence, son message, la recherche par compte
-- et la fonction de COPIE, qui est le point interessant du fichier.

POURQUOI CETTE DOUBLURE-LA DECLARE SA PROPRE COPIE
`NotificationPreferences` porte un DICTIONNAIRE, `channels_by_event`. La copie
par defaut du socle (`deepcopy`) le duplique correctement -- c'est justement
pourquoi c'est elle le defaut. La declarer ici quand meme serait du bruit ; ce
qui merite d'etre ecrit est le piege qu'elle evite, et il vaut pour toute
doublure future : un `dataclasses.replace` nu copie les CHAMPS mais PARTAGE le
dictionnaire, si bien qu'un `set_channels` sur l'objet rendu modifierait l'etat
« persiste » -- et le test « rien n'est ecrit sans commit » passerait sans rien
prouver. Ce fichier ne redeclare donc rien, et cette docstring dit pourquoi.
"""

from uuid import UUID

from app.modules.notifications.domain.entities import NotificationPreferences
from app.modules.notifications.domain.exceptions import NotificationPreferencesNotFoundError
from app.modules.notifications.domain.ports import NotificationPreferencesRepository
from app.shared.infrastructure.memory.repository import InMemoryRepository


class InMemoryNotificationPreferencesRepository(
    InMemoryRepository[NotificationPreferences], NotificationPreferencesRepository
):
    """Depot de preferences en memoire, ecritures en attente de validation."""

    _not_found_error = NotificationPreferencesNotFoundError
    _not_found_message = "Aucune preference de notification ne porte l'identifiant {entity_id}."

    async def find_for_account(self, account_id: UUID) -> NotificationPreferences | None:
        """Cherche les preferences d'un compte, sans erreur si rien n'est enregistre.

        PART DE `self._scope()`, jamais du magasin -- meme convention que cote
        SQLAlchemy, ou tout finder maison part de `self._select()`.

        Args:
            account_id: le compte interroge.

        Returns:
            Les preferences du compte, ou None s'il n'a jamais rien choisi.
        """
        for row in self._scope():
            if row.entity.account_id == account_id:
                return row.entity
        return None
