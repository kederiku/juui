"""Agregats du module notifications (BACK-22).

`identity` prouve qui vous etes, `medical_records` dit de quel animal il s'agit ;
celui-ci repond a « qui prevenir, par quel canal ». Un seul agregat, et une regle
qui est LA decision du ticket (ADR-0021) :

- `NotificationPreferences` : ce qu'un compte a choisi, CANAL PAR TYPE
  D'EVENEMENT. Surtout pas un interrupteur global : « rappels de rendez-vous par
  SMS mais actualites par e-mail » est le besoin reel du cahier des charges, et
  un booleen unique ne le couvre pas. L'agregat ne stocke que les ECARTS au
  defaut, ce qui rend un compte neuf gratuit -- aucune ligne a semer a
  l'inscription -- et laisse les defauts evoluer sans migration de donnees.

- `NotificationRequest` : l'evenement tel que l'emetteur le confie, avec son
  destinataire et les variables de son gabarit. Ce n'est pas une entite mais une
  VALEUR : elle ne vit que le temps d'une remise, elle n'a pas d'identite.

LE DESTINATAIRE VOYAGE AVEC L'EVENEMENT, ET IL LE FAUT
`notifications` ne lit PAS l'adresse dans `identity` : le contrat
`module-independence` le lui interdit, et une seconde copie des coordonnees ici
serait une donnee personnelle de plus a tenir a jour. L'emetteur, qui la detient
deja, la fournit. Corollaire assume : une adresse e-mail transite par la file,
la ou l'ADR-0020 refusait qu'un SECRET le fasse -- une adresse n'en est pas un,
et le stream est borne en nombre d'entrees (BACK-15).

CE QUE `NotificationPreferences` NE PORTE PAS
Ni tenance -- une preference appartient a un COMPTE, pas a un groupe, et se lit
dans l'espace personnel hors de toute structure, comme `accounts` --, ni
coordonnees, ni journal d'envoi. Le journal est une ligne de log (critere 5 du
ticket) ; la table qui l'archiverait est nommee par la docstring de `TenantMixin`
et n'a pas d'emetteur a ce jour.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Self
from uuid import UUID, uuid7

from app.modules.notifications.domain.exceptions import TransactionalEventNotConfigurableError
from app.modules.notifications.domain.policies import (
    NotificationChannel,
    NotificationEvent,
    is_transactional,
    resolve_channels,
)


@dataclass(slots=True, kw_only=True)
class NotificationPreferences:
    """Les canaux qu'un compte a choisis, evenement par evenement.

    Construire l'objet directement est reserve a la RECONSTITUTION depuis la
    persistance -- c'est ce que fait le depot en relisant une ligne. Une creation
    metier passe par `NotificationPreferences.create()`.

    `account_id` reste un identifiant NU : le compte vit chez `identity`, et les
    deux modules ne s'importent pas (ADR-0015). L'unicite par compte est tenue par
    un index en base, la relation par l'usage.

    `channels_by_event` NE CONTIENT QUE LES ECARTS. Un evenement absent de la
    table veut dire « ce compte n'a rien dit », et non « aucun canal » : c'est la
    distinction que `resolve_channels` fait valoir, et la confondre reactiverait
    en silence ce qu'un utilisateur vient de couper.
    """

    id: UUID
    account_id: UUID
    channels_by_event: dict[NotificationEvent, frozenset[NotificationChannel]] = field(
        default_factory=dict
    )

    @classmethod
    def create(cls, *, account_id: UUID) -> Self:
        """Cree des preferences neuves : aucun ecart, donc tous les defauts.

        L'identifiant est tire ICI, dans le domaine, et non par la base : le cas
        d'usage en dispose avant tout aller-retour SQL.

        Args:
            account_id: le compte a qui ces preferences appartiennent.

        Returns:
            Des preferences vides, ou chaque evenement suit son defaut.
        """
        return cls(id=uuid7(), account_id=account_id, channels_by_event={})

    def channels_for(self, event: NotificationEvent) -> frozenset[NotificationChannel]:
        """Rend les canaux par lesquels cet evenement doit partir pour ce compte.

        C'est LA question que pose la remise, et l'agregat y repond seul : un
        evenement transactionnel prend ses canaux imposes, un evenement optionnel
        prend le choix du compte, ou son defaut a defaut de choix.

        Args:
            event: l'evenement a remettre.

        Returns:
            Les canaux retenus. Un ensemble vide vaut « ne rien envoyer », et
            n'est jamais une erreur.
        """
        return resolve_channels(event, configured=self.channels_by_event.get(event))

    def set_channels(
        self, event: NotificationEvent, channels: Iterable[NotificationChannel]
    ) -> None:
        """Fixe les canaux d'un evenement optionnel pour ce compte.

        PAR EVENEMENT, jamais globalement : c'est le critere premier du ticket.
        Deux appels sur deux evenements laissent le compte avec deux reglages
        distincts, ce qu'un interrupteur unique n'aurait jamais permis.

        Args:
            event: l'evenement a configurer.
            channels: les canaux voulus. Vide desactive l'evenement -- une reponse
                legitime, et conservee comme telle.

        Raises:
            TransactionalEventNotConfigurableError: si l'evenement est
                transactionnel. Le refus est EXPLICITE plutot que silencieux :
                accepter puis ignorer laisserait croire a l'utilisateur qu'il a
                coupe un message qu'il continuera de recevoir.
        """
        if is_transactional(event):
            message = (
                f"L'evenement « {event.value} » est transactionnel : il part quelles que "
                "soient les preferences, il n'y a rien a y configurer."
            )
            raise TransactionalEventNotConfigurableError(message)
        self.channels_by_event[event] = frozenset(channels)

    def reset(self, event: NotificationEvent) -> None:
        """Efface le choix du compte pour cet evenement : le defaut reprend la main.

        DISTINCT de `set_channels(event, [])`, et c'est tout l'interet des ecarts :
        celui-la dit « je ne veux plus rien pour cet evenement », celui-ci dit « je
        n'ai pas d'avis, fais comme d'habitude ». Sans lui, on ne saurait pas
        revenir en arriere.

        Args:
            event: l'evenement dont le choix est efface. Efface un choix absent ne
                fait rien -- l'operation est idempotente.
        """
        self.channels_by_event.pop(event, None)


@dataclass(frozen=True, slots=True)
class NotificationRequest:
    """Un evenement confie au module, avec de quoi le remettre.

    GELEE : ce qui a ete emis ne se corrige pas en chemin. Une remise qui
    modifierait sa propre demande rendrait impossible de rejouer la tache a
    l'identique, ce que la politique de reprise de BACK-15 fait pourtant.

    L'EMETTEUR NE NOMME AUCUN CANAL, et c'est la ligne qui compte : il n'y a pas
    de champ `channel` ici, et il n'y en aura pas. Le canal se decide a la remise,
    a partir des preferences du compte.

    Attributes:
        account_id: le compte a prevenir. Sert a retrouver ses preferences, et
            n'est jamais une adresse.
        event: ce qui s'est produit.
        recipient: l'adresse e-mail du destinataire, fournie par l'emetteur --
            voir la docstring du module pour le motif.
        recipient_name: son nom affiche, pour l'en-tete et la formule d'appel.
        payload: les variables du gabarit, toutes en chaines. Ce qui voyage sur la
            file est du JSON, et une date se formate chez l'emetteur, qui seul
            connait le fuseau de son lecteur.
    """

    account_id: UUID
    event: NotificationEvent
    recipient: str
    recipient_name: str
    payload: Mapping[str, str]
