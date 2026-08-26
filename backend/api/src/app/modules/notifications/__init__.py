"""Module notifications : « qui prevenir, par quel canal ».

`identity` prouve qui vous etes, `organization` dit ou vous travaillez,
`medical_records` porte le dossier de l'animal ; celui-ci decide de ce qui part,
vers qui, et par ou. LA decision du socle (ADR-0021) : un module appelant EMET UN
EVENEMENT et ne choisit jamais de canal -- c'est ici, une seule fois pour tous les
modules, que les preferences du compte s'appliquent. Sans cette regle, chaque
module reimplementerait sa propre logique de canal, et les preferences ne
vaudraient que pour celui qui aurait pense a les lire.

CE QUE BACK-22 A LIVRE ICI
Le catalogue ferme des evenements et des canaux, leur classification en
TRANSACTIONNELS -- qui partent quelles que soient les preferences -- et en
optionnels ; l'agregat `NotificationPreferences`, qui retient un choix PAR TYPE
D'EVENEMENT et non un interrupteur global, et refuse qu'on configure un
transactionnel ; les gabarits en texte brut ; le port d'envoi UNIQUE avec ses
trois adaptateurs de canal -- courriel reel, SMS et push journalises sans
fournisseur ; et la tache de fond par laquelle TOUT passe, jamais le fil d'une
requete HTTP.

CE QU'IL N'A PAS LIVRE, ET POURQUOI
Aucune route : lire ou ecrire ses preferences suppose `get_current_active_account`
(BACK-10c), et l'espace personnel se compose en BACK-23. Aucun fournisseur SMS ni
push : un contrat se signe et se paie, la portee du ticket l'ecarte. Aucun journal
d'envoi persiste : le critere du ticket demande de journaliser, ce que fait le cas
d'usage au format de BACK-11 ; la table qui l'archiverait n'a pas d'emetteur.

ET SURTOUT, PAS LE CODE DE VERIFICATION D'ADRESSE
La carte cite l'OTP de BACK-17 en exemple de message transactionnel, et il ne
passe pourtant pas par ce module : un evenement de notification voyage par la
file, ou tout argument est lisible en clair dans un stream sans TTL, et un OTP est
un secret engendre dans le worker (ADR-0020). Ce que BACK-22 lui a repris est le
TRANSPORT -- le dialogue SMTP, descendu en port technique de `shared/`
(ADR-0022) --, pas le parcours. La regle qu'il illustre, elle, est bien celle
d'ici : son expediteur ne consulte aucune preference.

SURFACE PUBLIQUE
Le catalogue, l'agregat, la valeur emise, les ports, l'unite de travail et la
dependance FastAPI que le point de composition consommera. Le declencheur de
taches n'est PAS re-exporte ici : il vit dans `infrastructure/tasks/`, et
l'importer depuis ce fichier ferait croire qu'un emetteur peut l'assembler
lui-meme. Le re-export est EXPLICITE parce que Mypy tourne avec
`no_implicit_reexport` (implique par `strict`).
"""

from app.modules.notifications.domain.entities import (
    NotificationPreferences,
    NotificationRequest,
)
from app.modules.notifications.domain.policies import (
    DEFAULT_CHANNELS,
    NotificationChannel,
    NotificationEvent,
    RenderedMessage,
    is_transactional,
    render,
    required_payload,
    resolve_channels,
)
from app.modules.notifications.domain.ports import (
    NotificationDeliveryError,
    NotificationDispatcher,
    NotificationPreferencesRepository,
    NotificationSender,
    NotificationsUnitOfWork,
)
from app.modules.notifications.unit_of_work import (
    NotificationsUowDep,
    get_notifications_uow,
)

__all__ = [
    "DEFAULT_CHANNELS",
    "NotificationChannel",
    "NotificationDeliveryError",
    "NotificationDispatcher",
    "NotificationEvent",
    "NotificationPreferences",
    "NotificationPreferencesRepository",
    "NotificationRequest",
    "NotificationSender",
    "NotificationsUnitOfWork",
    "NotificationsUowDep",
    "RenderedMessage",
    "get_notifications_uow",
    "is_transactional",
    "render",
    "required_payload",
    "resolve_channels",
]
