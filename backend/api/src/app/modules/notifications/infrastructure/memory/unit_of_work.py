"""Unite de travail de notifications en memoire (BACK-06c).

Le pendant de `SqlAlchemyNotificationsUnitOfWork`, adosse a un dictionnaire.
Tout le cycle de vie est herite d'`InMemoryUnitOfWork` ; ne vit ici que le depot
du module.

UN SEUL DEPOT, ET C'EST DEJA UNE UNITE DE TRAVAIL COMPLETE : ce qui la justifie
est la GARDE -- lever hors bloc, annuler en sortie sans commit --, non le nombre
de depots. L'argument vaut pour la doublure autant que pour l'adaptateur reel.
"""

from collections.abc import Iterable

from app.modules.notifications.domain.entities import NotificationPreferences
from app.modules.notifications.domain.ports import (
    NotificationPreferencesRepository,
    NotificationsUnitOfWork,
)
from app.modules.notifications.infrastructure.memory.repositories import (
    InMemoryNotificationPreferencesRepository,
)
from app.shared.infrastructure.memory.repository import InMemoryStore
from app.shared.infrastructure.memory.unit_of_work import InMemoryUnitOfWork


class InMemoryNotificationsUnitOfWork(InMemoryUnitOfWork, NotificationsUnitOfWork):
    """Unite de travail de notifications adossee a la memoire du processus."""

    def __init__(self, preferences: Iterable[NotificationPreferences] = ()) -> None:
        """Declare le magasin du module et y seme l'etat valide initial.

        Args:
            preferences: les preferences a poser comme deja persistees. Elles sont
                copiees en profondeur, dictionnaire des ecarts compris.
        """
        super().__init__()
        self._preferences: InMemoryStore[NotificationPreferences] = self._new_store()
        for item in preferences:
            self._preferences.seed(item)

    @property
    def preferences(self) -> NotificationPreferencesRepository:
        """Le depot des preferences, servi par le bloc `async with` en cours.

        Returns:
            Le depot des preferences du bloc en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
        self._require_open()
        return InMemoryNotificationPreferencesRepository(self._preferences)

    @property
    def preferences_store(self) -> InMemoryStore[NotificationPreferences]:
        """Le magasin des preferences, pour relire l'etat VALIDE hors de tout bloc.

        Returns:
            Le magasin des preferences.
        """
        return self._preferences
