"""Refus metier du module notifications (BACK-22).

Chaque classe descend d'une categorie intermediaire de `shared/` et porte son
code namespace `notifications.*`, lisible en production sans ouvrir le code.
Aucune ne connait de code HTTP : la traduction est le travail de l'adaptateur
d'API (BACK-09), en un seul endroit. Une entite qui leverait une `HTTPException`
rendrait le meme code inutilisable depuis une tache de fond -- or TOUT ce module
s'execute dans une tache de fond.

DEUX RESSOURCES, DEUX NAMESPACES
`notifications.preferences.*` couvre ce qu'un compte a choisi ;
`notifications.delivery.*` couvre la remise elle-meme. Un client qui traite
« gabarit incomplet » n'a rien a voir avec un client qui traite « preferences
introuvables ».

CE FICHIER EST UNE FEUILLE : il n'importe que `shared`, ce qui permet a
`policies.py` de le nommer sans creer de cycle.
"""

from typing import ClassVar

from app.shared.domain.exceptions import ConflictError, NotFoundError, ValidationError


class NotificationPreferencesNotFoundError(NotFoundError):
    """Aucune preference n'est enregistree sous cet identifiant.

    A NE PAS CONFONDRE avec « ce compte n'a rien choisi », qui est un cas NOMINAL
    et se lit `None` au retour de `find_for_account` : les defauts s'appliquent
    alors. Cette erreur-la ne sort que d'un `get` par identifiant, ou l'absence
    trahit une reference cassee.

    Elle descend de `NotFoundError`, et ce n'est pas un choix libre : l'annotation
    `type[NotFoundError]` du depot generique le verrouille.
    """

    code: ClassVar[str] = "notifications.preferences.not_found"


class TransactionalEventNotConfigurableError(ConflictError):
    """Cet evenement est transactionnel : il n'y a rien a y configurer.

    LE REFUS CENTRAL DU TICKET, cote preferences. Un message transactionnel part
    quelles que soient les preferences (ADR-0021) ; accepter qu'on le configure
    laisserait croire au contraire, et l'utilisateur qui aurait « desactive » sa
    reinitialisation de mot de passe la recevrait quand meme -- ce qui est pire
    qu'un refus franc.

    Un `ConflictError` et non un `ValidationError` : la demande est bien formee,
    c'est l'etat des choses qui la rend sans objet.
    """

    code: ClassVar[str] = "notifications.preferences.event_not_configurable"


class UnknownNotificationEventError(ValidationError):
    """Un evenement inconnu du catalogue a ete presente, ou relu en base.

    Le catalogue est FERME et stocke en texte : une valeur retiree du code laisse
    derriere elle des lignes que plus rien ne sait interpreter. Le depot leve donc
    plutot que de les ignorer -- une preference silencieusement perdue est une
    notification que quelqu'un recevra sans l'avoir voulu.
    """

    code: ClassVar[str] = "notifications.preferences.unknown_event"


class UnknownNotificationChannelError(ValidationError):
    """Un canal inconnu a ete presente, ou relu en base. Meme motif que ci-dessus."""

    code: ClassVar[str] = "notifications.preferences.unknown_channel"


class MissingNotificationPayloadError(ValidationError):
    """Le gabarit de l'evenement exige une variable que l'emetteur n'a pas fournie.

    Levee au RENDU, dans le worker, et nommant l'evenement et les variables
    manquantes : sans elle, `format_map` leverait un `KeyError` nu qui ne dirait
    ni l'un ni les autres. C'est un defaut d'emetteur, pas une faute
    d'utilisateur -- il se corrige en code, et la tache echoue franchement plutot
    que de remettre un message a trous.
    """

    code: ClassVar[str] = "notifications.delivery.missing_payload"
