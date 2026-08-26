"""Taches de fond du module notifications (BACK-22).

LE SOUS-PAQUET QUE `discovery.py` CHERCHE, ET SON IMPORT EST UN EFFET RECHERCHE
Au demarrage du worker, `shared/infrastructure/tasks/discovery.py` importe
`app.modules.<module>.infrastructure.tasks` partout ou ce sous-paquet existe :
c'est cet import qui enregistre les taches decorees `@broker.task` aupres du
broker deja construit. `identity` a ouvert la voie en BACK-17 ; le mecanisme de
BACK-15 s'applique ici tel quel -- ni Dockerfile ni compose a toucher, comme
`discovery.py` le promettait nommement a ce ticket.

Sans la ligne d'import ci-dessous, le sous-paquet s'importerait sans rien
enregistrer : le worker demarrerait, les notifications partiraient en file, et
personne ne viendrait jamais les consommer.
"""

from app.modules.notifications.infrastructure.tasks import notifications  # noqa: F401
from app.modules.notifications.infrastructure.tasks.notifications import (
    TaskNotificationDispatcher,
    deliver_notification,
)

__all__ = ["TaskNotificationDispatcher", "deliver_notification"]
