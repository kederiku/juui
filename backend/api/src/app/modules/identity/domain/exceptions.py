"""Refus metier du module identity (BACK-04, reparentes par BACK-09).

Toutes descendent de `DomainError`, la racine posee dans `shared/`. Aucune ne
connait de code HTTP : la traduction est le travail de l'adaptateur d'API, en un
seul endroit (BACK-09). Une entite qui leverait une `HTTPException` rendrait le
meme code inutilisable depuis une tache de fond.

CE QUE BACK-09 CHANGERA ICI
Ces classes heriteront des categories intermediaires -- `AccountNotFoundError`
de `NotFoundError`, `EmailAlreadyUsedError` d'`AlreadyExistsError` -- et
porteront leur code namespace `identity.account.not_found`, qui permet de lire
l'origine d'une erreur en production sans ouvrir le code.

A LIRE AVANT DE S'EN SERVIR DANS UNE ROUTE
`EmailAlreadyUsedError` protege un invariant du domaine ; elle ne doit PAS
ressortir telle quelle sur le parcours d'inscription. BACK-09 et BACK-28 posent
la regle de non-divulgation : une inscription repond STRICTEMENT la meme chose
que l'adresse soit libre ou deja prise, faute de quoi le formulaire devient un
oracle d'existence de compte.
"""

from app.shared.domain.exceptions import DomainError


class AccountNotFoundError(DomainError):
    """Aucun compte ne correspond a l'identifiant ou a l'adresse demandes."""


class EmailAlreadyUsedError(DomainError):
    """Un compte porte deja cette adresse e-mail, sous sa forme normalisee."""


class EmailAlreadyVerifiedError(DomainError):
    """L'adresse de ce compte est deja verifiee : rien a faire."""


class InvalidStatusTransitionError(DomainError):
    """Le statut demande n'est pas atteignable depuis le statut courant."""
