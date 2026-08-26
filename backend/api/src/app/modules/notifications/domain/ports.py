"""Ports metier du module notifications (BACK-22).

Un port est un BESOIN exprime par le domaine, jamais une technologie. Ceux-ci
disent « je dois pouvoir retrouver ce qu'un compte a choisi », « je dois pouvoir
remettre un message sur un canal » et « je dois pouvoir demander une remise sans
l'attendre » ; ils ne disent ni PostgreSQL, ni SMTP, ni Redis.

UN SEUL PORT D'ENVOI, UN ADAPTATEUR PAR CANAL -- LA DEMANDE LITTERALE DU TICKET
`NotificationSender` est unique, et trois classes le remplissent : e-mail, SMS,
push. C'est ce qui permet au cas d'usage de remettre un message sans savoir par
ou : il choisit des CANAUX a partir des preferences, puis prend l'adaptateur qui
porte ce canal. Un port par canal aurait remis le choix a l'appelant, c'est-a-dire
exactement ce que ce module existe pour lui retirer.

LE PORT TECHNIQUE DE COURRIEL N'EST PAS ICI, ET C'EST VOULU
`EmailTransport` vit dans `shared/domain/ports/` : `identity` en a besoin pour son
code de verification (BACK-17) sans avoir le droit d'importer ce module. Ce qui
est ici est ce qui parle NOTIFICATION -- evenement, preference, canal ; le
dialogue SMTP est un besoin technique partage (ADR-0022).

POURQUOI UN `NotificationDispatcher` EN PLUS DU `NotificationSender`
Meme motif exactement qu'`OtpDispatcher` chez identity, et il vaut d'etre relu :
le ticket exige que TOUT envoi passe par une tache de fond, jamais par le fil de
la requete HTTP. L'appelant a donc besoin d'un port qui MET EN FILE, et il ne
peut pas importer `infrastructure/tasks/` -- le contrat `module-layers` le refuse.
Sans ce port, chaque emetteur devrait connaitre la tache, et le premier qui
l'appellerait directement remettrait le SMTP dans le fil d'une requete.
"""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from uuid import UUID

from app.modules.notifications.domain.entities import NotificationPreferences
from app.modules.notifications.domain.policies import NotificationChannel, NotificationEvent
from app.shared.domain.ports.unit_of_work import AbstractUnitOfWork


class NotificationDeliveryError(RuntimeError):
    """La remise a echoue sur un canal : le message n'est pas parti par la.

    UN `RuntimeError` ET NON UNE `DomainError`, comme `OtpDeliveryError` et
    `EmailDeliveryError` : rien n'est refuse, c'est le transport qui n'a pas
    repondu. Levee depuis un adaptateur de canal, elle remonte a la tache de fond,
    ou elle declenche la politique de reprise de BACK-15 -- reessais avec repli
    exponentiel, puis file de rejets.
    """


class NotificationPreferencesRepository(ABC):
    """Acces aux preferences, exprime en entites du domaine.

    Toutes les methodes echangent des `NotificationPreferences` -- jamais un
    modele SQLAlchemy, jamais un dictionnaire. C'est la frontiere ou le mapping
    s'applique.

    Le port n'expose QUE ce que les cas d'usage du module ont le droit de faire.
    L'implementation, qui herite du depot generique de `shared/`, sait aussi
    lister et supprimer : le port ne s'elargit pas parce que la classe sait faire
    plus -- doctrine BACK-06a, rejouee de BACK-16 et BACK-19.
    """

    @abstractmethod
    async def find_for_account(self, account_id: UUID) -> NotificationPreferences | None:
        """Cherche les preferences d'un compte, sans erreur si rien n'est enregistre.

        `find_` et non `get_` : ici l'absence est un RESULTAT ATTENDU, et meme le
        cas le plus frequent -- un compte qui n'a jamais touche a ses reglages n'a
        aucune ligne, et ce sont les defauts qui s'appliquent. Lever ici
        obligerait chaque appelant a rattraper une erreur pour un cas nominal.

        Args:
            account_id: le compte interroge.

        Returns:
            Les preferences du compte, ou None s'il n'a jamais rien choisi.
        """

    @abstractmethod
    async def add(self, preferences: NotificationPreferences, /) -> None:
        """Enregistre des preferences qui n'existaient pas.

        Args:
            preferences: les preferences a creer.
        """

    @abstractmethod
    async def save(self, preferences: NotificationPreferences, /) -> None:
        """Reporte sur la persistance l'etat de preferences deja connues.

        Args:
            preferences: les preferences modifiees.
        """


class NotificationsUnitOfWork(AbstractUnitOfWork):
    """Unite de travail du module : sa transaction, son depot, rien d'autre.

    UNE UNITE PAR MODULE, jamais une unite globale (ADR-0009). Le depot est une
    PROPRIETE et non un attribut : un attribut pose a l'entree du bloc survivrait
    a sa sortie, depot mort en main ; une propriete repasse par la garde de
    l'unite a chaque acces, et lever hors bloc reste ainsi la regle du port.
    """

    @property
    @abstractmethod
    def preferences(self) -> NotificationPreferencesRepository:
        """Le depot des preferences, servi par le bloc `async with` en cours.

        Raises:
            RuntimeError: si aucun bloc n'est ouvert sur cette unite.
        """


class NotificationSender(ABC):
    """Remise d'un message sur UN canal. Un transport, et rien d'autre.

    Le port ne sait ni quel evenement il porte, ni s'il fallait l'envoyer : on lui
    donne un destinataire et un texte deja rendu, il le fait parvenir. C'est ce
    qui rend la doublure des tests triviale -- elle retient ce qu'on lui confie --
    et ce qui permet d'ajouter un canal sans toucher au cas d'usage.

    CHAQUE IMPLEMENTATION ANNONCE SON CANAL, et c'est ce qui remplace un
    `if canal == ...` dans le cas d'usage : celui-ci recoit la collection des
    expediteurs disponibles, l'indexe par `channel`, et remet a ceux que les
    preferences ont retenus.
    """

    @property
    @abstractmethod
    def channel(self) -> NotificationChannel:
        """Le canal que cet adaptateur dessert."""

    @abstractmethod
    async def send(self, *, recipient: str, recipient_name: str, subject: str, body: str) -> None:
        """Fait parvenir le message a son destinataire.

        Args:
            recipient: la coordonnee du destinataire sur CE canal -- une adresse
                e-mail aujourd'hui, un numero ou un jeton d'appareil le jour ou
                SMS et push remettront vraiment.
            recipient_name: le nom affiche.
            subject: l'objet du message, ou son titre.
            body: le corps, en texte brut.

        Raises:
            NotificationDeliveryError: si la remise echoue.
        """


class NotificationDispatcher(ABC):
    """Demande d'une remise, hors du fil de la requete.

    LA REQUETE HTTP N'ATTEND JAMAIS UN ENVOI : une session TLS vers un fournisseur
    de messagerie prend le temps qu'elle prend, et le geste metier qui a declenche
    la notification ne doit pas en dependre. L'implementation met une tache en file
    (BACK-15) ; preferences, choix des canaux et remise se font de l'autre cote.

    LA TACHE NE TRANSPORTE QUE DU SERIALISABLE : identifiants, chaines, et le
    dictionnaire de variables du gabarit. Jamais une entite, jamais un objet ORM
    (regle de BACK-15) -- et jamais un secret (ADR-0020), ce qui explique que le
    code de verification d'adresse ne passe pas par ici.
    """

    @abstractmethod
    async def dispatch(
        self,
        *,
        account_id: UUID,
        event: NotificationEvent,
        recipient: str,
        recipient_name: str,
        payload: Mapping[str, str],
        group_id: UUID | None = None,
    ) -> None:
        """Met en file la remise de cet evenement a ce compte.

        L'appel rend la main des que la demande est ACCEPTEE, pas quand le message
        est remis : un appelant ne peut donc pas conclure de son retour que
        l'utilisateur a recu quelque chose.

        AUCUN CANAL EN ARGUMENT, et il n'y en aura pas : c'est le module qui
        choisit, a partir des preferences du compte (ADR-0021).

        Args:
            account_id: le compte a prevenir.
            event: ce qui s'est produit.
            recipient: l'adresse e-mail du destinataire, fournie par l'emetteur.
            recipient_name: son nom affiche.
            payload: les variables du gabarit de l'evenement.
            group_id: le groupe actif au moment de l'emission, quand il y en a un.
                Un rappel de rendez-vous nait dans un groupe ; une notification de
                compte, non. Il est REPOSE dans le contexte au demarrage de la
                tache (ADR-0008), sans quoi le worker s'executerait hors contexte.

        Raises:
            NotificationDeliveryError: si la demande n'a meme pas pu etre mise en
                file.
        """
