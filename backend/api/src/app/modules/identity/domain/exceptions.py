"""Refus metier du module identity (BACK-04, reparentes par BACK-09, OTP en BACK-17).

Chaque classe descend de la categorie intermediaire posee dans `shared/` --
`NotFoundError`, `AlreadyExistsError`, `ConflictError` -- et porte son code
namespace `identity.account.*`, lisible en production sans ouvrir le code.
Aucune ne connait de code HTTP : la traduction est le travail de l'adaptateur
d'API, en un seul endroit (`shared/infrastructure/api/error_handlers.py`). Une
entite qui leverait une `HTTPException` rendrait le meme code inutilisable
depuis une tache de fond.

DEUX RESSOURCES, DEUX NAMESPACES
`identity.account.*` couvre le compte lui-meme ; `identity.otp.*` couvre le
parcours de verification d'adresse (BACK-17). Ce sont deux ressources distinctes
du meme module, et le code d'erreur le dit -- un client qui traite « code
invalide » n'a rien a voir avec un client qui traite « compte introuvable ».

A LIRE AVANT DE S'EN SERVIR DANS UNE ROUTE
`EmailAlreadyUsedError` protege un invariant du domaine ; elle ne doit PAS
ressortir telle quelle sur le parcours d'inscription. BACK-09 et BACK-28 posent
la regle de non-divulgation : une inscription repond STRICTEMENT la meme chose
que l'adresse soit libre ou deja prise, faute de quoi le formulaire devient un
oracle d'existence de compte.
"""

from typing import ClassVar

from app.shared.domain.exceptions import (
    AlreadyExistsError,
    ConflictError,
    NotFoundError,
    TooManyRequestsError,
    ValidationError,
)


class AccountNotFoundError(NotFoundError):
    """Aucun compte ne correspond a l'identifiant ou a l'adresse demandes."""

    code: ClassVar[str] = "identity.account.not_found"


class EmailAlreadyUsedError(AlreadyExistsError):
    """Un compte porte deja cette adresse e-mail, sous sa forme normalisee."""

    code: ClassVar[str] = "identity.account.email_already_used"


class EmailAlreadyVerifiedError(ConflictError):
    """L'adresse de ce compte est deja verifiee : rien a faire."""

    code: ClassVar[str] = "identity.account.email_already_verified"


class InvalidStatusTransitionError(ConflictError):
    """Le statut demande n'est pas atteignable depuis le statut courant."""

    code: ClassVar[str] = "identity.account.invalid_status_transition"


class OtpCodeInvalidError(ValidationError):
    """Le code de verification presente ne convient pas.

    UN SEUL REFUS POUR TROIS SITUATIONS, ET C'EST LE POINT IMPORTANT : code faux,
    code expire, aucun code en cours donnent exactement la meme erreur et le meme
    message. Distinguer « expire » de « faux » renseignerait un attaquant sur la
    fenetre de validite -- il saurait qu'il a trouve le bon moment, sinon le bon
    code -- et distinguer « aucun code » revelerait qu'aucune demande n'est en
    cours pour ce compte. La regle vaut aussi cote client : FRONT-17 l'inscrit
    dans son ticket pour l'ecran 2FA.
    """

    code: ClassVar[str] = "identity.otp.invalid_code"


class OtpAttemptsExhaustedError(TooManyRequestsError):
    """Le code a ete presente trop de fois : il est invalide, il faut en demander un autre.

    Le refus est DISTINCT de `OtpCodeInvalidError` a dessein, et ce n'est pas une
    contradiction avec la regle ci-dessus : ce que l'utilisateur doit savoir, ce
    n'est pas si son code etait faux ou expire -- ca, jamais -- mais qu'il est
    BLOQUE et que reessayer ne sert plus a rien. Sans ce message, il tape trois
    fois de plus puis appelle le support.

    Le compteur restant, lui, ne sort jamais : « il vous reste une tentative »
    indiquerait a un attaquant le moment exact de changer de compte cible.
    """

    code: ClassVar[str] = "identity.otp.attempts_exhausted"


class OtpResendThrottledError(TooManyRequestsError):
    """Trop de codes demandes pour cette adresse, ou depuis cette adresse IP.

    Le quota protege deux victimes differentes, d'ou les deux compteurs de
    `OtpRules` : le titulaire de l'adresse, qu'un formulaire de renvoi sans limite
    transformerait en cible de harcelement par courriel ; et le service, dont la
    reputation d'expedition s'effondre si quelqu'un s'en sert pour arroser mille
    adresses depuis une seule machine.

    Le message ne dit PAS lequel des deux plafonds a parle : « votre adresse est
    bloquee » et « votre IP est bloquee » se distinguent trop bien.
    """

    code: ClassVar[str] = "identity.otp.resend_throttled"
