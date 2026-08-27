"""Regles metier pures du module notifications (BACK-22).

Meme doctrine que chez identity, organization et medical_records : une politique
est une regle qui ne tient DANS AUCUNE ENTITE en particulier -- elle s'exprime
sur des valeurs, se teste sans rien construire, et se reutilise d'un cas d'usage
a l'autre. Ce module n'importe rien du reste de notifications hormis
`exceptions.py`, feuille lui aussi : c'est ce qui permet a l'agregat d'appeler
ces regles dans ses comportements sans creer le moindre cycle.

POURQUOI LES DEUX ENUMS SONT ICI ET NON DANS `entities.py`
Chez identity, `AccountType` est l'etat d'un compte : il vit avec lui. Ici, le
catalogue d'evenements et la liste des canaux ne sont l'etat de personne -- ils
sont le VOCABULAIRE du module, parle par l'agregat des preferences, par les
ports, par les trois adaptateurs de canal et par la tache. C'est la definition
meme d'une politique dans ce depot, et c'est ce qui rend testable la regle des
canaux sans construire la moindre preference.

LES DEUX FAMILLES D'EVENEMENTS, ET C'EST LA DECISION DU TICKET (ADR-0021)
Un evenement TRANSACTIONNEL part toujours : sans lui l'utilisateur reste bloque
-- il ne peut pas reprendre la main sur son compte, ou il se presente a un
rendez-vous annule. Un evenement OPTIONNEL est un message de confort, et lui seul
se desactive. La distinction n'est PAS un reglage : elle est portee par le
catalogue, verifiee par l'agregat, et aucune preference ne la renegocie.

CE QUE LE CATALOGUE NE CONTIENT PAS, ET POURQUOI
Le code de verification d'adresse (BACK-17) n'y figure pas, alors que la carte le
cite en exemple de message transactionnel. Il ne PEUT pas passer par ce module :
un evenement de notification voyage par la file, ou tout argument est lisible en
clair dans un stream sans TTL, et un OTP est un secret engendre dans le worker
(ADR-0020). La regle qu'il illustre, elle, est bien celle-ci -- son expediteur ne
consulte aucune preference, exactement comme les evenements transactionnels
ci-dessous.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.modules.notifications.domain.exceptions import MissingNotificationPayloadError


class NotificationChannel(StrEnum):
    """Voie par laquelle un message atteint son destinataire.

    Ensemble FERME et stocke en TEXTE, comme tous les enums du depot : ajouter un
    canal est une livraison de code -- un adaptateur de plus -- et non une
    migration d'enum natif PostgreSQL.

    Les trois canaux du cahier des charges. Seul `EMAIL` remet reellement quelque
    chose a ce stade : `SMS` et `PUSH` existent, sont choisissables et sont
    journalises, mais aucun fournisseur n'est engage (portee du ticket). La
    structure est donc en place, et le jour ou un contrat SMS est signe, un seul
    fichier change.
    """

    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"


class NotificationEvent(StrEnum):
    """Ce qui s'est produit et merite d'etre annonce -- jamais un canal.

    C'EST TOUT CE QU'UN MODULE APPELANT EMET. Il dit « le rendez-vous est
    annule », pas « envoie un SMS » : le canal se decide ici, a partir des
    preferences du compte. Sans cette regle, chaque module reimplementerait sa
    propre logique de canal, et les preferences ne vaudraient que pour celui qui
    aurait pense a les lire.

    Ensemble FERME, et volontairement court : un evenement sans emetteur ni
    gabarit serait du code mort. Les trois evenements de rendez-vous sont deja
    la ; ce qui leur manque est un EMETTEUR, et c'est le moteur de rendez-vous
    qui l'apportera -- le socle de scheduling (BACK-21) n'a livre que la fiche
    technique du praticien, sans cas d'usage. BACK-31 etendra le catalogue pour
    la reinitialisation de mot de passe.
    """

    # S105 est un faux positif : la regle traque une variable nommee comme un
    # secret et affectee d'un litteral, or ceci est un NOM D'EVENEMENT -- il n'y a
    # ni mot de passe ni jeton dans ce fichier, le lien de reinitialisation
    # arrivant en variable de gabarit. Renommer l'evenement pour faire taire la
    # regle rendrait le catalogue moins clair que le `noqa`.
    PASSWORD_RESET = "password_reset"  # noqa: S105
    """Un lien de reinitialisation de mot de passe (BACK-31). TRANSACTIONNEL."""

    APPOINTMENT_CANCELLED = "appointment_cancelled"
    """Un rendez-vous a ete annule. TRANSACTIONNEL : s'y presenter pour rien est
    exactement ce que la notification existe pour eviter."""

    APPOINTMENT_CONFIRMATION = "appointment_confirmation"
    """Un rendez-vous vient d'etre pris. Optionnel."""

    APPOINTMENT_REMINDER = "appointment_reminder"
    """Rappel a l'approche d'un rendez-vous. Optionnel -- l'exemple meme de la
    carte : « rappels de rendez-vous par SMS »."""

    NEWS = "news"
    """Actualites du service. Optionnel, et le premier que l'on desactive."""


# Les evenements qui IGNORENT les preferences. La table vit ici, a cote du
# catalogue qu'elle classe, et non dans un reglage : un exploitant ne doit pas
# pouvoir rendre optionnelle une reinitialisation de mot de passe.
_TRANSACTIONAL_EVENTS: Final[frozenset[NotificationEvent]] = frozenset(
    {
        NotificationEvent.PASSWORD_RESET,
        NotificationEvent.APPOINTMENT_CANCELLED,
    }
)


# Canaux retenus quand le compte n'a rien choisi -- et canaux IMPOSES pour un
# evenement transactionnel, dont la ligne n'est pas un defaut mais une regle.
#
# L'e-mail partout : c'est le seul canal qui remet reellement aujourd'hui, et
# c'est aussi la seule coordonnee que le service detient a coup sur. Un defaut
# sur un canal muet ferait taire toutes les notifications d'un compte neuf.
#
# EXHAUSTIVE PAR CONSTRUCTION : le controle ci-dessous echoue a l'import si un
# evenement ajoute au catalogue n'a pas sa ligne. Un `KeyError` en production, sur
# un rendez-vous annule, se decouvrirait autrement le jour de l'annulation.
DEFAULT_CHANNELS: Final[Mapping[NotificationEvent, frozenset[NotificationChannel]]] = {
    NotificationEvent.PASSWORD_RESET: frozenset({NotificationChannel.EMAIL}),
    NotificationEvent.APPOINTMENT_CANCELLED: frozenset({NotificationChannel.EMAIL}),
    NotificationEvent.APPOINTMENT_CONFIRMATION: frozenset({NotificationChannel.EMAIL}),
    NotificationEvent.APPOINTMENT_REMINDER: frozenset({NotificationChannel.EMAIL}),
    NotificationEvent.NEWS: frozenset({NotificationChannel.EMAIL}),
}


def is_transactional(event: NotificationEvent) -> bool:
    """Dit si cet evenement part quelles que soient les preferences.

    Args:
        event: l'evenement interroge.

    Returns:
        Vrai pour un message transactionnel, faux pour un message de confort.
    """
    return event in _TRANSACTIONAL_EVENTS


def resolve_channels(
    event: NotificationEvent,
    *,
    configured: frozenset[NotificationChannel] | None,
) -> frozenset[NotificationChannel]:
    """Rend les canaux par lesquels cet evenement doit partir.

    LA REGLE DU TICKET, EN QUATRE LIGNES. Un evenement transactionnel prend ses
    canaux imposes SANS MEME REGARDER `configured` -- ce n'est pas une valeur par
    defaut que l'on surcharge, c'est un choix que l'on n'a pas. Un evenement
    optionnel prend ce que le compte a choisi, et le defaut seulement quand il n'a
    rien choisi.

    L'ENSEMBLE VIDE EST UNE REPONSE, et il faut le distinguer de l'absence de
    choix : `frozenset()` veut dire « ce compte a desactive cet evenement », `None`
    veut dire « ce compte n'a rien dit ». Les confondre reactiverait en silence ce
    qu'un utilisateur vient de couper.

    Args:
        event: l'evenement a remettre.
        configured: les canaux choisis par le compte pour cet evenement, ou None
            s'il n'a rien choisi. Un ensemble vide desactive l'evenement.

    Returns:
        Les canaux retenus, eventuellement vides -- ce qui vaut « ne rien
        envoyer », et n'est jamais une erreur.
    """
    if is_transactional(event):
        return DEFAULT_CHANNELS[event]
    if configured is None:
        return DEFAULT_CHANNELS[event]
    return configured


@dataclass(frozen=True, slots=True)
class RenderedMessage:
    """Un message pret a remettre, tous canaux confondus.

    UN SEUL TEXTE POUR LES TROIS CANAUX, et c'est assume a ce stade : un SMS de
    160 caracteres ne se decoupe pas comme un courriel, et une notification push
    porte un titre court. Le jour ou un canal remettra vraiment autre chose que du
    courriel, c'est ici que le gabarit se specialisera -- une variante par canal,
    pas une seconde table de rendu ailleurs.

    Attributes:
        subject: l'objet du message. Sert d'en-tete de courriel, et servira de
            titre de notification push.
        body: le corps, en TEXTE BRUT. Pas de HTML : les messages du service
            portent un code, une date ou un lien, et le HTML n'y ajouterait qu'une
            surface -- images distantes, styles, clients qui les bloquent.
    """

    subject: str
    body: str


@dataclass(frozen=True, slots=True)
class _Template:
    """Gabarit d'un evenement, et la liste de ce qu'il exige pour se remplir."""

    subject: str
    body: str
    required: tuple[str, ...]


# Les gabarits, un par evenement du catalogue. Ecrits en `str.format_map`, sans
# moteur de rendu : cinq messages en texte brut n'en justifient aucun, et une
# dependance de plus serait une dependance de plus dans le domaine -- ce que le
# contrat `domain-purity` refuse.
_TEMPLATES: Final[Mapping[NotificationEvent, _Template]] = {
    NotificationEvent.PASSWORD_RESET: _Template(
        subject="Reinitialisation de votre mot de passe Juui",
        body=(
            "Bonjour {recipient_name},\n\n"
            "Vous avez demande a reinitialiser votre mot de passe.\n"
            "Suivez ce lien pour en choisir un nouveau : {reset_url}\n\n"
            "Si vous n'etes pas a l'origine de cette demande, ignorez ce message : "
            "votre mot de passe reste inchange.\n\n"
            "L'equipe Juui\n"
        ),
        required=("recipient_name", "reset_url"),
    ),
    NotificationEvent.APPOINTMENT_CANCELLED: _Template(
        subject="Votre rendez-vous du {appointment_date} est annule",
        body=(
            "Bonjour {recipient_name},\n\n"
            "Votre rendez-vous du {appointment_date} chez {clinic_name} a ete annule.\n"
            "Vous pouvez en reprendre un depuis votre espace personnel.\n\n"
            "L'equipe Juui\n"
        ),
        required=("recipient_name", "appointment_date", "clinic_name"),
    ),
    NotificationEvent.APPOINTMENT_CONFIRMATION: _Template(
        subject="Votre rendez-vous du {appointment_date} est confirme",
        body=(
            "Bonjour {recipient_name},\n\n"
            "Votre rendez-vous du {appointment_date} chez {clinic_name} est confirme.\n\n"
            "L'equipe Juui\n"
        ),
        required=("recipient_name", "appointment_date", "clinic_name"),
    ),
    NotificationEvent.APPOINTMENT_REMINDER: _Template(
        subject="Rappel : rendez-vous le {appointment_date}",
        body=(
            "Bonjour {recipient_name},\n\n"
            "Petit rappel : vous avez rendez-vous le {appointment_date} "
            "chez {clinic_name}.\n\n"
            "L'equipe Juui\n"
        ),
        required=("recipient_name", "appointment_date", "clinic_name"),
    ),
    NotificationEvent.NEWS: _Template(
        subject="{headline}",
        body=(
            "Bonjour {recipient_name},\n\n"
            "{message}\n\n"
            "Vous recevez ce message parce que vous avez active les actualites Juui. "
            "Vous pouvez les desactiver depuis votre espace personnel.\n\n"
            "L'equipe Juui\n"
        ),
        required=("recipient_name", "headline", "message"),
    ),
}


def required_payload(event: NotificationEvent) -> tuple[str, ...]:
    """Rend les variables que le gabarit de cet evenement exige.

    Publie pour que l'emetteur sache ce qu'il doit fournir, et pour qu'un test le
    verifie sans rendre le message.

    Args:
        event: l'evenement interroge.

    Returns:
        Les noms des variables attendues, dans l'ordre du gabarit.
    """
    return _TEMPLATES[event].required


def render(event: NotificationEvent, payload: Mapping[str, str]) -> RenderedMessage:
    """Remplit le gabarit de cet evenement avec les variables fournies.

    LE CONTROLE AVANT LE RENDU, et il n'est pas decoratif : `format_map` leverait
    un `KeyError` nu sur une variable absente, dans le worker, sans dire laquelle
    manque ni pour quel evenement. Le refus ci-dessous les nomme toutes les deux.

    Les variables EN TROP sont ignorees : un emetteur qui enrichit son evenement
    ne casse pas le rendu d'un gabarit qui ne s'en sert pas encore.

    Args:
        event: l'evenement a rendre.
        payload: les variables du gabarit, toutes en chaines de caracteres -- ce
            qui voyage sur la file est du JSON, et une date se formate chez
            l'emetteur, qui seul connait le fuseau de son lecteur.

    Returns:
        L'objet et le corps du message.

    Raises:
        MissingNotificationPayloadError: si une variable exigee manque.
    """
    template = _TEMPLATES[event]
    missing = tuple(name for name in template.required if name not in payload)
    if missing:
        absents = ", ".join(missing)
        message = f"Variables absentes pour l'evenement « {event.value} » : {absents}."
        raise MissingNotificationPayloadError(message)
    return RenderedMessage(
        subject=template.subject.format_map(payload),
        body=template.body.format_map(payload),
    )


def _ensure_catalogue_is_covered() -> None:
    """Refuse au chargement un evenement sans canaux par defaut ou sans gabarit.

    A L'IMPORT, ET NON A L'EXECUTION. Un evenement ajoute au catalogue et oublie
    ici produirait un `KeyError` le jour ou quelqu'un l'emettrait -- c'est-a-dire
    en production, sur le message que l'on tenait le plus a faire partir. Le
    controle coute cinq lignes et une microseconde au demarrage.

    Raises:
        RuntimeError: si un evenement du catalogue n'est pas couvert.
    """
    for event in NotificationEvent:
        if event not in DEFAULT_CHANNELS or event not in _TEMPLATES:
            message = (
                f"L'evenement « {event.value} » n'a pas de canaux par defaut ou pas de "
                "gabarit : completer DEFAULT_CHANNELS et _TEMPLATES."
            )
            raise RuntimeError(message)


_ensure_catalogue_is_covered()
