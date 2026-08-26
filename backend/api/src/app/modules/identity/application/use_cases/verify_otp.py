"""Verification de l'adresse e-mail par le code recu (BACK-17).

Le pendant de `request_otp.py`, et le seul des deux cas d'usage OTP a s'executer
entierement dans le fil de la requete : il n'y a rien a differer, l'utilisateur
attend une reponse.

CE QUE CE CAS D'USAGE PROTEGE
Trois proprietes, et chacune vient d'une ligne precise :

- USAGE UNIQUE -- le code est detruit des qu'il a servi, par le magasin, dans le
  meme geste que la comparaison ;
- TENTATIVES BORNEES -- trois essais, puis le code est invalide ; c'est ce qui
  rend inatteignable la force brute sur un espace de 10^6 ;
- NON-DIVULGATION -- un code faux, un code expire et l'absence de code produisent
  le MEME refus, avec le MEME message.

CE QUI RESTE A BRANCHER (BACK-10c, BACK-28)
Aucune route ne l'expose encore : c'est la dependance d'authentification qui
posera `account_id` a partir du jeton, et l'ecran de verification qui appellera.
Tant qu'elle n'existe pas, un endpoint prenant l'identifiant de compte dans son
corps serait un oracle -- et une cible de force brute distribuee.
"""

from dataclasses import dataclass
from typing import assert_never
from uuid import UUID

from app.modules.identity.domain.entities import Account
from app.modules.identity.domain.exceptions import (
    EmailAlreadyVerifiedError,
    OtpAttemptsExhaustedError,
    OtpCodeInvalidError,
)
from app.modules.identity.domain.ports import IdentityUnitOfWork, OtpConsumption, OtpStore


@dataclass(frozen=True, slots=True)
class VerifyEmailCommand:
    """Intention de verifier une adresse avec le code qui vient d'etre saisi.

    Attributes:
        account_id: le compte dont l'adresse est verifiee.
        code: les six chiffres saisis. Une CHAINE, jamais un entier : « 004271 »
            perdrait ses zeros de tete au passage, et la comparaison echouerait
            sur un code pourtant juste.
    """

    account_id: UUID
    code: str


class VerifyEmailOtp:
    """Depense une tentative, et bascule le compte en verifie si le code convient."""

    def __init__(self, *, uow: IdentityUnitOfWork, otp_store: OtpStore) -> None:
        """Assemble le cas d'usage a partir de ses deux ports.

        Args:
            uow: l'unite de travail du module -- c'est elle qui possede
                l'atomicite de la bascule.
            otp_store: le magasin des codes.
        """
        self._uow = uow
        self._otp_store = otp_store

    async def execute(self, command: VerifyEmailCommand) -> Account:
        """Applique la commande et retourne le compte verifie.

        L'ORDRE DES GESTES EST DELIBERE. Le compte est relu AVANT que la tentative
        ne soit depensee : un identifiant inconnu ou une adresse deja verifiee ne
        doivent pas consommer un essai, sans quoi un tiers epuiserait le quota
        d'autrui par des appels sans objet. La tentative n'est depensee qu'ensuite,
        et la bascule est ecrite dans la meme transaction.

        Args:
            command: le compte et le code saisi.

        Returns:
            Le compte, adresse verifiee.

        Raises:
            AccountNotFoundError: si aucun compte ne porte cet identifiant.
            EmailAlreadyVerifiedError: si l'adresse est deja verifiee.
            OtpCodeInvalidError: si le code est faux, expire, ou si aucun code
                n'est en cours -- un seul refus pour les trois.
            OtpAttemptsExhaustedError: si le quota de tentatives est epuise. Le
                code est alors detruit : il en faut un nouveau.
            OtpStoreUnavailableError: si le magasin ne repond pas. Aucune
                verification n'est prononcee sur un magasin muet.
        """
        async with self._uow:
            account = await self._uow.accounts.get(command.account_id)
            if account.email_verified:
                message = "L'adresse de ce compte est deja verifiee."
                raise EmailAlreadyVerifiedError(message)

            # Le magasin depense la tentative et rend son verdict d'un seul geste
            # indivisible ; la comparaison des empreintes s'y fait en temps
            # constant. Une exception levee ici sort du bloc sans commit, donc
            # sans rien ecrire.
            consumption = await self._otp_store.consume(account_id=account.id, code=command.code)
            match consumption:
                case OtpConsumption.ACCEPTED:
                    pass
                case OtpConsumption.EXHAUSTED:
                    message = (
                        "Ce code a ete saisi trop de fois : il n'est plus valable. "
                        "Merci d'en demander un nouveau."
                    )
                    raise OtpAttemptsExhaustedError(message)
                case OtpConsumption.REJECTED:
                    # MEME MESSAGE pour un code faux, un code expire et l'absence
                    # de code. Distinguer le deuxieme cas renseignerait sur la
                    # fenetre de validite, le troisieme sur l'existence d'une
                    # demande en cours.
                    message = "Ce code de verification est invalide ou expire."
                    raise OtpCodeInvalidError(message)
                case _:
                    assert_never(consumption)

            account.verify_email()
            await self._uow.accounts.save(account)
            await self._uow.commit()

        # L'entite retournee est une dataclass du domaine : la fermeture de la
        # session ne la perime pas.
        return account
