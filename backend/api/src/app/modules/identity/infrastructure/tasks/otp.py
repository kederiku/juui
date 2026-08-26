"""Tache d'emission d'un code de verification, et son declencheur (BACK-17).

LE CODE NAIT ICI, DANS LE WORKER -- C'EST TOUT L'INTERET DU DECOUPAGE
Un argument de tache voyage EN CLAIR dans le stream Redis, que BACK-15 borne en
nombre d'entrees mais jamais en duree : un code passe par la file y resterait
lisible bien apres son expiration, dans la meme instance que son propre
condense. La tache ne recoit donc qu'un identifiant de compte ; generation,
empreinte et envoi se font de ce cote, et le secret ne traverse rien.

LES RESSOURCES DU MODULE S'OUVRENT A LA PREMIERE TACHE
`shared/infrastructure/tasks/lifecycle.py` ouvre la base et le cache au demarrage
du worker, mais il ne PEUT PAS ouvrir le magasin d'OTP : le contrat
`service-spaces` interdit a `shared` d'importer `app.modules.*`. Les deux
dependances ci-dessous construisent donc leur ressource au premier besoin, la
rangent dans l'etat du broker sous une cle stable, et confient ce qui se ferme a
`remember_module_resource`. Aucune course a craindre : les fabriques
n'attendent rien, une coroutine ne peut donc pas s'intercaler entre le controle
et le rangement.

CE QUE CETTE TACHE NE FAIT PAS
Elle ne verifie AUCUN quota : le tourniquet a deja tourne cote appelant, dans
`RequestEmailVerificationOtp`, avant meme la mise en file. Le refaire ici
consommerait deux unites par envoi, et surtout arriverait trop tard pour
repondre 429 a qui que ce soit.
"""

from typing import Annotated, Final
from uuid import UUID

from redis.exceptions import RedisError
from taskiq import Context, TaskiqDepends

from app.core import get_settings
from app.modules.identity.application.use_cases.request_otp import IssueEmailVerificationOtp
from app.modules.identity.domain.ports import (
    IdentityUnitOfWork,
    OtpDeliveryError,
    OtpDispatcher,
    OtpSender,
    OtpStore,
)
from app.modules.identity.infrastructure.clients.email_otp_sender import build_otp_sender
from app.modules.identity.infrastructure.clients.redis_otp_store import (
    OTP_STORE_STATE_KEY,
    build_otp_rules,
    build_otp_store,
)
from app.modules.identity.unit_of_work import SqlAlchemyIdentityUnitOfWork
from app.shared.infrastructure.tasks.broker import broker
from app.shared.infrastructure.tasks.lifecycle import (
    get_task_database,
    remember_module_resource,
)

# Cle sous laquelle l'expediteur se range dans l'etat du worker. Le magasin, lui,
# reprend `OTP_STORE_STATE_KEY` -- la meme cle que dans `app.state`, pour que les
# deux processus nomment la meme chose pareil.
_OTP_SENDER_STATE_KEY: Final = "otp_sender"

# Nom de la tache sur le fil. EXPLICITE et non deduit du chemin du module :
# renommer un fichier ne doit pas rendre orphelins les messages deja en file.
# Forme `module.ressource.action`, comme `shared.demo.record_ping`.
_TASK_NAME: Final = "identity.otp.send_verification"

# Ce qu'il faut attraper quand la mise en file echoue : le broker parle a Redis.
_BROKER_UNREACHABLE: Final = (OSError, RedisError)


def get_task_otp_store(context: Annotated[Context, TaskiqDepends()]) -> OtpStore:
    """Retourne le magasin d'OTP du worker, en l'ouvrant au premier appel.

    Args:
        context: le contexte d'execution de la tache, injecte par TaskIQ.

    Returns:
        Le magasin des codes du processus worker.
    """
    store = getattr(context.state, OTP_STORE_STATE_KEY, None)
    if isinstance(store, OtpStore):
        return store
    opened = build_otp_store(get_settings())
    setattr(context.state, OTP_STORE_STATE_KEY, opened)
    # Confie AUSSITOT, jamais plus tard : un pool construit et non confie fuit a
    # l'arret du worker.
    remember_module_resource(context.state, opened)
    return opened


def get_task_otp_sender(context: Annotated[Context, TaskiqDepends()]) -> OtpSender:
    """Retourne l'expediteur de codes du worker, en le construisant au premier appel.

    Rien a refermer ici, contrairement au magasin : le transport de courriel
    (BACK-22) ouvre et referme une session SMTP par message, il ne detient aucune
    ressource entre deux.

    Args:
        context: le contexte d'execution de la tache, injecte par TaskIQ.

    Returns:
        L'expediteur du processus worker.
    """
    sender = getattr(context.state, _OTP_SENDER_STATE_KEY, None)
    if isinstance(sender, OtpSender):
        return sender
    built = build_otp_sender(get_settings())
    setattr(context.state, _OTP_SENDER_STATE_KEY, built)
    return built


def get_task_identity_uow(context: Annotated[Context, TaskiqDepends()]) -> IdentityUnitOfWork:
    """Construit l'unite de travail d'identity pour la tache en cours.

    JAMAIS `get_identity_uow`, qui suppose une requete HTTP : une tache prend la
    fabrique de sessions ouverte par le demarrage du worker et batit la sienne.
    L'unite livree est FERMEE -- la session ne s'ouvrira qu'au `async with` du cas
    d'usage.

    Args:
        context: le contexte d'execution de la tache, injecte par TaskIQ.

    Returns:
        L'unite de travail du module, typee par son port.
    """
    return SqlAlchemyIdentityUnitOfWork(get_task_database(context).sessionmaker)


@broker.task(task_name=_TASK_NAME)
async def send_email_verification_otp(
    account_id: UUID,
    # LES DEPENDANCES EN VALEUR PAR DEFAUT, ET NON EN `Annotated` COMME
    # `demo.record_ping`. La difference n'est pas cosmetique : le type de `kiq`
    # est calque sur la signature de la fonction, si bien qu'une dependance
    # declaree en `Annotated` devient un argument OBLIGATOIRE a l'appel -- et
    # `send_email_verification_otp.kiq(account_id=...)` echoue au typage, en
    # reclamant l'unite de travail et le magasin que le worker doit precisement
    # fournir lui-meme. Avec un defaut, la signature de `kiq` se reduit aux
    # arguments qui voyagent reellement sur le fil. Le patron de BACK-15 ne s'en
    # apercevait pas : aucun code type ne le `kiq`, seule une sonde du site de
    # documentation le fait.
    uow: IdentityUnitOfWork = TaskiqDepends(get_task_identity_uow),
    otp_store: OtpStore = TaskiqDepends(get_task_otp_store),
    sender: OtpSender = TaskiqDepends(get_task_otp_sender),
) -> None:
    """Emet un code de verification pour ce compte et le fait partir.

    UN SEUL ARGUMENT SERIALISABLE, ET AUCUN `group_id` : la verification d'une
    adresse ne s'inscrit dans AUCUN groupe -- elle se joue a l'inscription, avant
    toute appartenance (BACK-16), et le compte lui-meme n'en porte pas. C'est
    l'exception nommee au patron de `demo.record_ping` : le contexte de tenance
    reste vide, et il le faut, sans quoi une inscription exigerait un groupe qui
    n'existe pas encore.

    Args:
        account_id: le compte dont l'adresse est a verifier.
        uow: l'unite de travail du module, injectee.
        otp_store: le magasin des codes, injecte -- jamais construit dans le corps.
        sender: le transport, injecte.
    """
    use_case = IssueEmailVerificationOtp(
        uow=uow,
        otp_store=otp_store,
        sender=sender,
        rules=build_otp_rules(get_settings()),
    )
    await use_case.execute(account_id)


class TaskOtpDispatcher(OtpDispatcher):
    """Declencheur adosse a la file : met la tache en file, et rend la main.

    L'ADAPTATEUR EST SANS ETAT, et c'est ce qui le rend banal a assembler : la
    tache decoree connait deja son broker. Il existe pour une raison
    d'architecture et une seule -- un cas d'usage ne peut pas importer
    `infrastructure/tasks/` sans retourner la fleche des couches.
    """

    async def dispatch_verification(self, *, account_id: UUID) -> None:
        """Met en file l'emission d'un code pour ce compte. Voir le port."""
        try:
            await send_email_verification_otp.kiq(account_id=account_id)
        except _BROKER_UNREACHABLE as error:
            message = "La demande d'envoi du code de verification n'a pas pu etre mise en file."
            raise OtpDeliveryError(message) from error
