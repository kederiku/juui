"""Refus metier du module scheduling (BACK-21).

Chaque classe descend d'une categorie intermediaire de `shared/` et porte son
code namespace `scheduling.*`, lisible en production sans ouvrir le code.
Aucune ne connait de code HTTP : la traduction est le travail de l'adaptateur
d'API (BACK-09), en un seul endroit.

L'erreur d'absence descend de `NotFoundError`, et ce n'est pas un choix libre :
l'annotation `type[NotFoundError]` du depot generique verrouille la
non-divulgation -- une fiche d'un autre groupe repond comme une fiche
inexistante, en 404, jamais en 403.

PAS D'ERREUR DE DOUBLON, ET C'EST DELIBERE
Une seconde fiche pour le meme praticien dans la meme clinique est refusee par
la contrainte d'unicite de la table, mais aucun cas d'usage de ce ticket ne
peut la lever : livrer `PractitionerProfileAlreadyExistsError` sans emetteur
serait du code mort. Le ticket qui livrera l'ECRITURE de la fiche -- celui de
l'ecran « mon compte » cote praticien -- l'apportera AVEC son emetteur.
"""

from typing import ClassVar

from app.shared.domain.exceptions import ConflictError, NotFoundError, ValidationError


class PractitionerProfileNotFoundError(NotFoundError):
    """Aucune fiche technique de praticien ne porte l'identifiant demande."""

    code: ClassVar[str] = "scheduling.practitioner_profile.not_found"


class InvalidTimeRangeError(ValidationError):
    """La plage horaire est mal formee : bornes inversees, egales ou hors journee.

    Le pendant, pour une plage RECURRENTE, de ce qu'`InvalidWindowError` est
    aux fenetres DATEES d'organization et de medical_records. Les deux ne se
    confondent pas : une fenetre de validite se mesure en instants avec fuseau,
    une plage horaire en minutes d'horloge murale.
    """

    code: ClassVar[str] = "scheduling.time_range.invalid"


class OverlappingTimeRangesError(ConflictError):
    """Deux plages horaires du meme jour se recouvrent sur la meme fiche.

    Un CONFLIT et non une erreur de forme : chaque plage prise seule est
    valide, c'est leur coexistence qui est refusee -- la meme distinction que
    `CustodyAlreadyActiveError` chez medical_records. Le domaine REFUSE, il ne
    fusionne pas : un ecran « mon compte » qui reafficherait autre chose que la
    saisie serait surprenant.
    """

    code: ClassVar[str] = "scheduling.time_ranges.overlapping"


class UnknownSpeciesError(ValidationError):
    """Une espece relue en base ne figure plus au catalogue du domaine.

    UNE VALEUR INCONNUE LEVE, ELLE N'EST PAS IGNOREE -- doctrine reprise de
    notifications. Avaler l'espece retiree du catalogue rendrait un praticien
    silencieusement competent pour rien, et l'ecart ne se verrait qu'a
    l'appariement, la ou personne ne le cherche.
    """

    code: ClassVar[str] = "scheduling.species.unknown"
