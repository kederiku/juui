"""Demande et emission d'un code de verification d'adresse (BACK-17).

DEUX CAS D'USAGE DANS UN SEUL FICHIER, ET LA FRONTIERE EST UN PROCESSUS
`RequestEmailVerificationOtp` s'execute la ou l'on repond a l'utilisateur : il
controle, il refuse s'il y a lieu, et il demande un envoi.
`IssueEmailVerificationOtp` s'execute dans le WORKER : c'est lui qui tire le
code, en range l'empreinte et le confie au transport.

POURQUOI LE CODE NAIT DANS LE WORKER ET NON ICI
Un argument de tache voyage en clair dans le stream Redis, lequel n'a pas de TTL
(BACK-15 le borne en nombre d'entrees, pas en duree). Engendrer le code du cote
qui repond en HTTP obligerait a le passer a la tache, c'est-a-dire a deposer le
secret a cote de son propre condense, dans la meme instance. Ce que la file
transporte se limite donc a un identifiant de compte, et la lecture de
`OtpDispatcher` dit pourquoi ce port existe.

CE QUE LE PREMIER CAS D'USAGE NE FAIT PAS
Il ne verifie pas que l'appelant est bien le titulaire du compte : cela releve
des dependances d'authentification (BACK-10c), qui poseront `account_id` a
partir du jeton. Tant qu'elles n'existent pas, aucune route ne l'expose -- c'est
BACK-28 qui l'appellera, juste apres avoir cree le compte.
"""

import logging
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from app.modules.identity.domain.exceptions import (
    EmailAlreadyVerifiedError,
    OtpResendThrottledError,
)
from app.modules.identity.domain.policies import OtpRules, generate_otp_code
from app.modules.identity.domain.ports import (
    IdentityUnitOfWork,
    OtpDispatcher,
    OtpSender,
    OtpStore,
)

_LOGGER: Final = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RequestEmailVerificationCommand:
    """Intention de faire partir un code vers le titulaire d'un compte.

    Attributes:
        account_id: le compte dont l'adresse est a verifier.
        client_ip: l'adresse IP REELLE de l'appelant, telle que l'intergiciel de
            uvicorn la reecrit depuis `X-Forwarded-For` sous la garde de
            `FORWARDED_ALLOW_IPS` (INFRA-04). `None` hors requete HTTP. Sans elle,
            le plafond par IP ne s'applique pas -- et avec une IP fausse, il
            s'appliquerait a tout le monde d'un coup.
    """

    account_id: UUID
    client_ip: str | None = None


class RequestEmailVerificationOtp:
    """Controle qu'un code peut partir, consomme les quotas, et le demande.

    L'ORDRE DES TROIS GESTES EST LE SUJET : on refuse un compte deja verifie AVANT
    de toucher aux quotas -- sinon une demande sans objet consommerait le droit
    d'en faire une utile -- et on ne demande l'envoi QU'APRES le tourniquet. C'est
    cette garantie « controle donc envoye » que le port de dispatch existe pour
    tenir : sans lui, chaque appelant devrait rejouer la sequence, et le premier
    qui l'oublierait ouvrirait le robinet.
    """

    def __init__(
        self,
        *,
        uow: IdentityUnitOfWork,
        otp_store: OtpStore,
        dispatcher: OtpDispatcher,
        rules: OtpRules,
    ) -> None:
        """Assemble le cas d'usage a partir de ses ports et de ses bornes.

        Args:
            uow: l'unite de travail du module, pour relire le compte.
            otp_store: le magasin, ici pour ses seuls quotas de renvoi.
            dispatcher: ce qui fait partir la demande hors du fil de la requete.
            rules: les bornes de cadence, lues de la configuration a l'assemblage.
        """
        self._uow = uow
        self._otp_store = otp_store
        self._dispatcher = dispatcher
        self._rules = rules

    async def execute(self, command: RequestEmailVerificationCommand) -> None:
        """Applique la demande.

        Args:
            command: l'intention d'envoi.

        Raises:
            AccountNotFoundError: si aucun compte ne porte cet identifiant.
            EmailAlreadyVerifiedError: si l'adresse est deja verifiee -- il n'y a
                rien a verifier, et le dire ne divulgue rien a qui detient deja
                l'identifiant du compte.
            OtpResendThrottledError: si le delai minimal n'est pas ecoule, ou si
                l'un des deux plafonds de la fenetre est atteint.
            OtpStoreUnavailableError: si le magasin ne repond pas -- un quota
                qu'on ne peut pas verifier bloque l'envoi plutot que de le
                laisser passer.
        """
        async with self._uow:
            account = await self._uow.accounts.get(command.account_id)

        if account.email_verified:
            message = "L'adresse de ce compte est deja verifiee."
            raise EmailAlreadyVerifiedError(message)

        verdict = await self._otp_store.register_resend(
            account_id=account.id,
            client_ip=command.client_ip,
            rules=self._rules,
        )
        if not verdict.allowed:
            # Le message ne dit NI lequel des trois controles a parle, NI combien
            # d'unites restent : « votre adresse est bloquee » et « votre IP est
            # bloquee » se distinguent trop bien, et un compteur restant indique a
            # un attaquant le moment de changer de cible. Le delai, lui, sort --
            # par l'en-tete `Retry-After`, que le client sait exploiter.
            message = (
                "Trop de codes ont ete demandes recemment. Merci de patienter "
                "avant d'en redemander un."
            )
            raise OtpResendThrottledError(message, retry_after_seconds=verdict.retry_after_seconds)

        await self._dispatcher.dispatch_verification(account_id=account.id)


class IssueEmailVerificationOtp:
    """Tire un code, en range l'empreinte, et le confie au transport.

    S'EXECUTE DANS LE WORKER, jamais dans le fil d'une requete : c'est le corps de
    la tache `identity.otp.send_verification`.

    IDEMPOTENCE, AU SENS OU BACK-15 L'EXIGE
    La politique de reprise rejoue une tache en echec, et le stream represente un
    message dont l'acquittement s'est perdu. Rejouee, cette emission ecrit un code
    NEUF par ecrasement absolu : l'etat final est le meme -- un seul code valide
    pour ce compte --, et le precedent, qui n'avait de toute facon pas ete remis,
    devient invalide. C'est le meme raisonnement que le `SET` absolu de
    `demo.record_ping`, pas un compteur qu'on incremente.
    """

    def __init__(
        self,
        *,
        uow: IdentityUnitOfWork,
        otp_store: OtpStore,
        sender: OtpSender,
        rules: OtpRules,
    ) -> None:
        """Assemble le cas d'usage a partir de ses ports et de ses bornes.

        Args:
            uow: l'unite de travail du module, pour relire le compte -- une tache
                recoit des identifiants, jamais une entite (BACK-15).
            otp_store: le magasin, qui ne conservera que l'empreinte du code.
            sender: le transport.
            rules: les bornes -- duree de validite et nombre de tentatives.
        """
        self._uow = uow
        self._otp_store = otp_store
        self._sender = sender
        self._rules = rules

    async def execute(self, account_id: UUID) -> None:
        """Emet un code pour ce compte et le fait partir.

        Args:
            account_id: le compte destinataire.

        Raises:
            AccountNotFoundError: si le compte a disparu entre la demande et
                l'execution de la tache.
            OtpStoreUnavailableError: si le magasin ne repond pas. La tache echoue
                et sera reprise : mieux vaut un code en retard qu'un code envoye
                que rien ne pourra verifier.
            OtpDeliveryError: si la remise echoue -- la tache sera reprise.
        """
        async with self._uow:
            account = await self._uow.accounts.get(account_id)

        if account.email_verified:
            # Course benigne : le titulaire a verifie son adresse entre la demande
            # et l'execution -- ou bien la tache est rejouee apres coup. On ne
            # renvoie pas un code pour une adresse deja verifiee, et on ne leve
            # pas non plus : il n'y a rien a reprendre.
            _LOGGER.info(
                "Emission d'OTP sans objet : l'adresse du compte est deja verifiee.",
                extra={"account_id": account.id},
            )
            return

        code = generate_otp_code()

        # LE RANGEMENT AVANT L'ENVOI, et l'ordre n'est pas indifferent : un code
        # remis que le magasin ne connait pas serait refuse a la saisie, ce que
        # l'utilisateur vit comme une panne. L'inverse -- range mais non remis --
        # se resout tout seul, par un renvoi.
        await self._otp_store.issue(account_id=account.id, code=code, rules=self._rules)

        await self._sender.send_verification_code(
            recipient=account.email,
            recipient_name=account.full_name,
            code=code,
            ttl_seconds=self._rules.ttl_seconds,
        )
