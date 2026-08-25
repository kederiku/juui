"""Refus metier du module organization (BACK-16).

Chaque classe descend d'une categorie intermediaire de `shared/` et porte son
code namespace `organization.*`, lisible en production sans ouvrir le code.
Aucune ne connait de code HTTP : la traduction est le travail de l'adaptateur
d'API (BACK-09), en un seul endroit.

Les deux erreurs d'absence descendent de `NotFoundError`, et ce n'est pas un
choix libre : l'annotation `type[NotFoundError]` du depot generique verrouille
la non-divulgation -- une ressource d'un autre groupe repond comme une
ressource inexistante, en 404, jamais en 403.
"""

from typing import ClassVar

from app.shared.domain.exceptions import ConflictError, NotFoundError, ValidationError


class MembershipNotFoundError(NotFoundError):
    """Aucune appartenance ne porte l'identifiant demande."""

    code: ClassVar[str] = "organization.membership.not_found"


class AssignmentNotFoundError(NotFoundError):
    """Aucune affectation ne porte l'identifiant demande."""

    code: ClassVar[str] = "organization.assignment.not_found"


class InvalidWindowError(ValidationError):
    """La fenetre de validite est mal formee : bornes naives ou inversees."""

    code: ClassVar[str] = "organization.window.invalid"


class AssignmentOutsideMembershipError(ConflictError):
    """L'affectation vise une clinique d'un groupe sans appartenance active.

    C'est le refus central du ticket : un compte ne peut etre affecte qu'aux
    cliniques d'un groupe ou il detient une appartenance ACTIVE a l'instant de
    la decision. La regle qui le leve vit dans `entities.py`
    (`ensure_assignment_allowed`).
    """

    code: ClassVar[str] = "organization.assignment.outside_active_membership"
