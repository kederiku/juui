"""Refus metier du module medical_records (BACK-19).

Chaque classe descend d'une categorie intermediaire de `shared/` et porte son
code namespace `medical_records.*`, lisible en production sans ouvrir le code.
Aucune ne connait de code HTTP : la traduction est le travail de l'adaptateur
d'API (BACK-09), en un seul endroit.

Les deux erreurs d'absence descendent de `NotFoundError`, et ce n'est pas un
choix libre : l'annotation `type[NotFoundError]` du depot generique verrouille
la non-divulgation en 404.

`InvalidWindowError` est l'HOMONYME de celle d'organization, et c'est voulu :
les deux modules ne s'importent pas (contrat `module-independence`), chacun
porte donc sa classe avec son code -- `medical_records.window.invalid` ici. La
remontee en `shared/` attend le troisieme module date (ecart consigne au
registre).
"""

from typing import ClassVar

from app.shared.domain.exceptions import ConflictError, NotFoundError, ValidationError


class AnimalNotFoundError(NotFoundError):
    """Aucun animal ne porte l'identifiant demande."""

    code: ClassVar[str] = "medical_records.animal.not_found"


class CustodyNotFoundError(NotFoundError):
    """Aucune detention ne porte l'identifiant demande."""

    code: ClassVar[str] = "medical_records.custody.not_found"


class InvalidWindowError(ValidationError):
    """La fenetre de validite est mal formee : bornes naives ou inversees."""

    code: ClassVar[str] = "medical_records.window.invalid"


class CustodyAlreadyActiveError(ConflictError):
    """L'animal a deja une detention ouverte : une seule active a la fois.

    C'est le refus central du ticket (ADR-0006) : ouvrir une seconde detention
    sans avoir clos la premiere donnerait deux detenteurs simultanes. La regle
    qui le leve vit dans `entities.py` (`ensure_custody_openable`) ; l'index
    unique partiel de `models.py` porte la meme garantie cote base.
    """

    code: ClassVar[str] = "medical_records.custody.already_active"
