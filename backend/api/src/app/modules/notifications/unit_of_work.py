"""Unite de travail du module notifications (BACK-22).

A la RACINE du module, comme chez identity, organization et medical_records :
l'unite de travail n'appartient ni au domaine (elle manipule une transaction) ni
tout a fait a l'infrastructure (elle expose le depot au cas d'usage) -- elle est
le point d'assemblage du module, et la seule exemption du contrat `module-layers`.

    async with uow:
        preferences = await uow.preferences.find_for_account(account_id)

UN SEUL DEPOT, ET C'EST DEJA UNE UNITE DE TRAVAIL COMPLETE
La forme ne change pas parce que le module n'a qu'une table : ce qui la justifie
est la GARDE -- lever hors bloc, annuler en sortie sans commit -- et non le
nombre de depots. Un cas d'usage qui prendrait le depot nu contournerait la
transaction le jour ou une seconde table naitra.

LE NOM `NotificationsUnitOfWork` EST CELUI DU PORT, PAS DE CETTE CLASSE
Le port vit dans `domain/ports.py`, et c'est lui que les consommateurs nomment ;
l'implementation d'ici s'appelle `SqlAlchemyNotificationsUnitOfWork`. NE JAMAIS
IMPORTER CE FICHIER DEPUIS `application/` -- la dependance FastAPI ci-dessous
existe pour que l'assemblage se fasse au point de composition, et nulle part
ailleurs.

LA DEPENDANCE FASTAPI N'A ENCORE AUCUN APPELANT, ET ELLE EST LA QUAND MEME
Le module n'expose aucune route (BACK-10c et BACK-23 les apporteront), mais la
livrer coute trois lignes et evite qu'un ticket futur invente sa propre facon
d'ouvrir la session -- ce que les trois modules precedents ont deja evite ainsi.
Le worker, lui, construit la sienne dans `infrastructure/tasks/` : `Request` n'y
existe pas.
"""

from typing import Annotated

from fastapi import Depends, Request

from app.modules.notifications.domain.ports import (
    NotificationPreferencesRepository,
    NotificationsUnitOfWork,
)
from app.modules.notifications.infrastructure.db.repositories import (
    SqlAlchemyNotificationPreferencesRepository,
)
from app.shared.infrastructure.db.session import get_database
from app.shared.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork


class SqlAlchemyNotificationsUnitOfWork(SqlAlchemyUnitOfWork, NotificationsUnitOfWork):
    """Unite de travail de notifications adossee a PostgreSQL.

    Tout le cycle de vie -- session par bloc, rollback de sortie, gardes -- est
    herite de `SqlAlchemyUnitOfWork` ; ne vit ici que ce qui appartient au module :
    son depot.
    """

    @property
    def preferences(self) -> NotificationPreferencesRepository:
        """Le depot des preferences, servi par le bloc `async with` en cours.

        Une propriete PARESSEUSE : le depot est une enveloppe sans etat autour de
        la session du bloc, construite a l'acces -- il ne peut jamais etre servi
        hors d'un bloc ouvert, ni survivre a sa sortie.

        Returns:
            Le depot des preferences du bloc en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """
        return SqlAlchemyNotificationPreferencesRepository(self._active_session)


async def get_notifications_uow(request: Request) -> NotificationsUnitOfWork:
    """Fournit l'unite de travail de notifications de la requete en cours.

    UNE INSTANCE PAR REQUETE, livree FERMEE : la session ne s'ouvrira qu'au
    `async with` du consommateur. `get_notifications_uow` et non `get_uow` -- une
    unite par module, le nom porte la frontiere.

    Args:
        request: la requete en cours, d'ou l'on remonte aux ressources de
            persistance du processus.

    Returns:
        L'unite de travail du module, typee par son port.

    Raises:
        RuntimeError: si le `lifespan` n'a pas tourne.
    """
    return SqlAlchemyNotificationsUnitOfWork(get_database(request).sessionmaker)


# Alias a annoter les parametres de route : `uow: NotificationsUowDep`. Le type
# expose est le PORT : une route ne sait pas quelle technologie la sert, et
# `InMemoryNotificationsUnitOfWork` (BACK-06c) s'y substitue sans toucher aux
# signatures.
NotificationsUowDep = Annotated[NotificationsUnitOfWork, Depends(get_notifications_uow)]
