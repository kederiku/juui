"""Tache de remise d'une notification, et son declencheur (BACK-22).

TOUT CE QUE FAIT CE MODULE SE PASSE ICI, ET C'EST UNE EXIGENCE DU TICKET
« Envoi systematiquement via tache de fond (BACK-15), jamais dans le fil de la
requete HTTP. » Une session TLS vers un fournisseur de messagerie prend le temps
qu'elle prend ; le geste metier qui a declenche la notification -- prendre un
rendez-vous, l'annuler -- ne doit pas en dependre. L'emetteur passe donc par
`TaskNotificationDispatcher`, qui met en file et rend la main.

CE QUI VOYAGE SUR LE FIL, ET CE QUI N'Y VOYAGE PAS
Des chaines et des identifiants, comme l'exige BACK-15 : compte, evenement,
destinataire, nom, variables du gabarit. Jamais une entite, jamais un objet ORM.
Et jamais un SECRET : c'est la raison pour laquelle le code de verification
d'adresse (BACK-17) ne passe pas par ce module -- un argument de tache reste
lisible en clair dans un stream que BACK-15 borne en nombre d'entrees, jamais en
duree (ADR-0020). Une adresse e-mail, elle, y transite : ce n'est pas un secret,
et sans elle le module devrait tenir sa propre copie des coordonnees.

LE GROUPE TRAVERSE LA FILE QUAND IL Y EN A UN
Le patron de `demo.record_ping` veut le `group_id` en tete et repose dans la
contextvar en premiere instruction (ADR-0008). Il est ici FACULTATIF, et le motif
est le meme que pour la tache d'OTP : un rappel de rendez-vous nait dans un
groupe, une notification de compte -- reinitialisation de mot de passe, actualites
-- n'appartient a aucun. L'exiger rendrait ces dernieres impossibles a emettre.

LES RESSOURCES DU MODULE S'OUVRENT A LA PREMIERE TACHE
`shared/infrastructure/tasks/lifecycle.py` ouvre la base et le cache au demarrage
du worker, mais le contrat `service-spaces` lui interdit d'importer
`app.modules.*` : il ne peut donc pas construire les adaptateurs de canal. Ils se
construisent au premier besoin et se rangent dans l'etat du broker sous une cle
stable -- meme mecanique que le magasin d'OTP d'identity. Rien a confier a
`remember_module_resource` ici : aucun des trois n'ouvre de ressource durable.
"""

from collections.abc import Mapping, Sequence
from typing import Annotated, Final
from uuid import UUID

from redis.exceptions import RedisError
from taskiq import Context, TaskiqDepends

from app.core import get_settings
from app.modules.notifications.application.use_cases.deliver_notification import (
    DeliverNotification,
)
from app.modules.notifications.domain.entities import NotificationRequest
from app.modules.notifications.domain.policies import NotificationEvent
from app.modules.notifications.domain.ports import (
    NotificationDeliveryError,
    NotificationDispatcher,
    NotificationSender,
    NotificationsUnitOfWork,
)
from app.modules.notifications.infrastructure.clients.email_sender import (
    build_email_notification_sender,
)
from app.modules.notifications.infrastructure.clients.push_sender import LoggingPushSender
from app.modules.notifications.infrastructure.clients.sms_sender import LoggingSmsSender
from app.modules.notifications.unit_of_work import SqlAlchemyNotificationsUnitOfWork
from app.shared.infrastructure.tasks.broker import broker
from app.shared.infrastructure.tasks.lifecycle import get_task_database
from app.shared.infrastructure.tenancy import use_group

# Cle sous laquelle la collection d'expediteurs se range dans l'etat du worker.
# Une constante et non un litteral recopie -- meme forme que `CACHE_STATE_KEY`.
_SENDERS_STATE_KEY: Final = "notification_senders"

# Nom de la tache sur le fil. EXPLICITE et non deduit du chemin du module :
# renommer un fichier ne doit pas rendre orphelins les messages deja en file.
# Forme `module.ressource.action`, comme `identity.otp.send_verification`.
_TASK_NAME: Final = "notifications.delivery.deliver"

# Ce qu'il faut attraper quand la mise en file echoue : le broker parle a Redis.
_BROKER_UNREACHABLE: Final = (OSError, RedisError)


def get_task_notification_senders(
    context: Annotated[Context, TaskiqDepends()],
) -> Sequence[NotificationSender]:
    """Retourne les adaptateurs de canal du worker, en les construisant au premier appel.

    LES TROIS CANAUX SONT TOUJOURS PRESENTS, y compris les deux qui ne remettent
    rien : c'est ce qui fait qu'une preference SMS activee produit une ligne de
    journal plutot qu'un `skipped` silencieux. Le cas d'usage traite l'absence
    d'un adaptateur comme un canal muet, mais cette absence ne doit pas etre la
    facon normale de dire « pas de fournisseur ».

    Args:
        context: le contexte d'execution de la tache, injecte par TaskIQ.

    Returns:
        Les expediteurs du processus worker, un par canal.
    """
    senders = getattr(context.state, _SENDERS_STATE_KEY, None)
    if isinstance(senders, tuple):
        return senders
    built: tuple[NotificationSender, ...] = (
        build_email_notification_sender(get_settings()),
        LoggingSmsSender(),
        LoggingPushSender(),
    )
    setattr(context.state, _SENDERS_STATE_KEY, built)
    return built


def get_task_notifications_uow(
    context: Annotated[Context, TaskiqDepends()],
) -> NotificationsUnitOfWork:
    """Construit l'unite de travail de notifications pour la tache en cours.

    JAMAIS `get_notifications_uow`, qui suppose une requete HTTP : une tache prend
    la fabrique de sessions ouverte par le demarrage du worker et batit la sienne.
    L'unite livree est FERMEE -- la session ne s'ouvrira qu'au `async with` du cas
    d'usage.

    Args:
        context: le contexte d'execution de la tache, injecte par TaskIQ.

    Returns:
        L'unite de travail du module, typee par son port.
    """
    return SqlAlchemyNotificationsUnitOfWork(get_task_database(context).sessionmaker)


@broker.task(task_name=_TASK_NAME)
async def deliver_notification(
    account_id: UUID,
    event: NotificationEvent,
    recipient: str,
    recipient_name: str,
    payload: Mapping[str, str],
    group_id: UUID | None = None,
    # LES DEPENDANCES EN VALEUR PAR DEFAUT, ET NON EN `Annotated` : le type de
    # `kiq` est calque sur la signature de la tache, si bien qu'une dependance
    # annotee devient un argument OBLIGATOIRE a l'appel -- l'appelant devrait
    # fournir l'unite de travail du worker. Le piege a ete releve en BACK-17, et
    # il mord ici pour de bon : le declencheur ci-dessous appelle `kiq` et passe
    # sous Mypy.
    uow: NotificationsUnitOfWork = TaskiqDepends(get_task_notifications_uow),
    senders: Sequence[NotificationSender] = TaskiqDepends(get_task_notification_senders),
) -> None:
    """Remet une notification a un compte, canaux choisis d'apres ses preferences.

    `group_id` EN DERNIER DES ARGUMENTS SERIALISABLES, et non en tete comme chez
    `demo.record_ping` : il est FACULTATIF ici, et Python n'admet pas un argument
    a defaut avant un argument sans defaut. La regle de fond est tenue -- il
    voyage explicitement et se repose dans la contextvar en premiere instruction,
    plutot que de manquer en silence au worker.

    Args:
        account_id: le compte a prevenir -- sert a retrouver ses preferences.
        event: ce qui s'est produit. Le canal, lui, n'est PAS un argument : c'est
            le module qui le choisit (ADR-0021).
        recipient: l'adresse e-mail du destinataire, fournie par l'emetteur.
        recipient_name: son nom affiche.
        payload: les variables du gabarit de l'evenement.
        group_id: le groupe actif au moment de l'emission, quand il y en a un.
        uow: l'unite de travail du module, injectee.
        senders: les adaptateurs de canal, injectes -- jamais construits ici.
    """
    # `use_group(None)` est un usage LEGITIME et documente du contexte : il
    # execute le bloc HORS de toute tenance, ou tout acces a un agregat tenant
    # echouerait bruyamment. Ce n'est donc pas « ne rien faire », c'est poser
    # explicitement l'absence de groupe -- et les preferences, qui ne sont pas
    # tenant, se lisent parfaitement ainsi.
    with use_group(group_id):
        use_case = DeliverNotification(uow=uow, senders=senders)
        await use_case.execute(
            NotificationRequest(
                account_id=account_id,
                event=event,
                recipient=recipient,
                recipient_name=recipient_name,
                payload=payload,
            )
        )


class TaskNotificationDispatcher(NotificationDispatcher):
    """Declencheur adosse a la file : met la tache en file, et rend la main.

    L'ADAPTATEUR EST SANS ETAT, et c'est ce qui le rend banal a assembler : la
    tache decoree connait deja son broker. Il existe pour une raison
    d'architecture et une seule -- un emetteur ne peut pas importer
    `infrastructure/tasks/` sans retourner la fleche des couches, et c'est lui qui
    garantit qu'aucun envoi ne se fait dans le fil d'une requete.
    """

    async def dispatch(
        self,
        *,
        account_id: UUID,
        event: NotificationEvent,
        recipient: str,
        recipient_name: str,
        payload: Mapping[str, str],
        group_id: UUID | None = None,
    ) -> None:
        """Met en file la remise de cet evenement. Voir le port pour le contrat."""
        try:
            await deliver_notification.kiq(
                account_id=account_id,
                event=event,
                recipient=recipient,
                recipient_name=recipient_name,
                payload=payload,
                group_id=group_id,
            )
        except _BROKER_UNREACHABLE as error:
            message = "La demande de remise de notification n'a pas pu etre mise en file."
            raise NotificationDeliveryError(message) from error
