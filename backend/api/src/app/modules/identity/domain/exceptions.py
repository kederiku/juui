"""Refus metier du module identity (BACK-04, reparentes par BACK-09).

Chaque classe descend de la categorie intermediaire posee dans `shared/` --
`NotFoundError`, `AlreadyExistsError`, `ConflictError` -- et porte son code
namespace `identity.account.*`, lisible en production sans ouvrir le code.
Aucune ne connait de code HTTP : la traduction est le travail de l'adaptateur
d'API, en un seul endroit (`shared/infrastructure/api/error_handlers.py`). Une
entite qui leverait une `HTTPException` rendrait le meme code inutilisable
depuis une tache de fond.

A LIRE AVANT DE S'EN SERVIR DANS UNE ROUTE
`EmailAlreadyUsedError` protege un invariant du domaine ; elle ne doit PAS
ressortir telle quelle sur le parcours d'inscription. BACK-09 et BACK-28 posent
la regle de non-divulgation : une inscription repond STRICTEMENT la meme chose
que l'adresse soit libre ou deja prise, faute de quoi le formulaire devient un
oracle d'existence de compte.
"""

from typing import ClassVar

from app.shared.domain.exceptions import AlreadyExistsError, ConflictError, NotFoundError


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
