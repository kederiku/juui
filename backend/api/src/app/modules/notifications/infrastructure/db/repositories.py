"""Adaptateur SQLAlchemy du port des preferences (BACK-22).

C'est ICI, et nulle part ailleurs, que le document JSONB rencontre l'entite du
domaine. Le cas d'usage ne voit passer que des `NotificationPreferences` ; il
ignore jusqu'a l'existence d'un ORM et d'un document.

LE MAPPING EST ECRIT A LA MAIN, ET IL EST PLUS QU'UNE COPIE DE CHAMPS
Il TRADUIT : le domaine parle en `NotificationEvent` et en `NotificationChannel`,
la base en chaines de caracteres. Un `dict` recopie tel quel donnerait une entite
peuplee de `str` la ou les comparaisons attendent des membres d'enum -- une
egalite qui passerait sur `StrEnum` et casserait au premier `frozenset`.

UNE VALEUR INCONNUE LEVE, ELLE N'EST PAS IGNOREE
Le catalogue est ferme et stocke en texte : un evenement retire du code laisse
derriere lui des documents que plus rien ne sait interpreter. Les avaler en
silence rendrait au compte le DEFAUT de l'evenement voisin -- c'est-a-dire lui
enverrait des messages qu'il avait coupes. Le refus est explicite et nomme la
valeur fautive.
"""

from uuid import UUID

from app.modules.notifications.domain.entities import NotificationPreferences
from app.modules.notifications.domain.exceptions import (
    NotificationPreferencesNotFoundError,
    UnknownNotificationChannelError,
    UnknownNotificationEventError,
)
from app.modules.notifications.domain.policies import NotificationChannel, NotificationEvent
from app.modules.notifications.domain.ports import NotificationPreferencesRepository
from app.modules.notifications.infrastructure.db.models import NotificationPreferencesModel
from app.shared.infrastructure.db.repositories.base import SqlAlchemyRepository


def _to_event(value: str) -> NotificationEvent:
    """Retrouve l'evenement du catalogue derriere une valeur relue en base.

    Args:
        value: la cle du document JSONB.

    Returns:
        Le membre du catalogue.

    Raises:
        UnknownNotificationEventError: si le catalogue ne connait plus cette
            valeur.
    """
    try:
        return NotificationEvent(value)
    except ValueError as error:
        message = f"L'evenement « {value} » est inconnu du catalogue de notifications."
        raise UnknownNotificationEventError(message) from error


def _to_channel(value: str) -> NotificationChannel:
    """Retrouve le canal derriere une valeur relue en base.

    Args:
        value: l'element de la liste du document JSONB.

    Returns:
        Le canal.

    Raises:
        UnknownNotificationChannelError: si aucun canal ne porte cette valeur.
    """
    try:
        return NotificationChannel(value)
    except ValueError as error:
        message = f"Le canal « {value} » est inconnu du module notifications."
        raise UnknownNotificationChannelError(message) from error


class SqlAlchemyNotificationPreferencesRepository(
    SqlAlchemyRepository[NotificationPreferences, NotificationPreferencesModel],
    NotificationPreferencesRepository,
):
    """Depot des preferences adosse a PostgreSQL."""

    _model_type = NotificationPreferencesModel
    _not_found_error = NotificationPreferencesNotFoundError
    _not_found_message = "Aucune preference de notification ne porte l'identifiant {entity_id}."

    def _to_entity(self, model: NotificationPreferencesModel) -> NotificationPreferences:
        """Reconstitue l'entite du domaine a partir d'une ligne de la table.

        Args:
            model: la ligne relue par SQLAlchemy.

        Returns:
            Les preferences, valeurs converties dans les types du domaine.

        Raises:
            UnknownNotificationEventError: si le document porte un evenement
                inconnu.
            UnknownNotificationChannelError: si le document porte un canal
                inconnu.
        """
        return NotificationPreferences(
            id=model.id,
            account_id=model.account_id,
            channels_by_event={
                _to_event(event): frozenset(_to_channel(channel) for channel in channels)
                for event, channels in model.channels_by_event.items()
            },
        )

    def _apply_to_model(
        self, entity: NotificationPreferences, model: NotificationPreferencesModel
    ) -> None:
        """Reporte l'etat des preferences sur leur ligne, sans toucher a `id`.

        LES CANAUX SONT TRIES A L'ECRITURE, et ce n'est pas cosmetique : un
        `frozenset` n'a pas d'ordre, si bien que deux enregistrements du meme etat
        produiraient deux documents differents. SQLAlchemy verrait alors une
        modification a chaque `save`, et un `diff` de sauvegarde de base
        deviendrait illisible.

        Le document est REMPLACE et non modifie en place : un JSONB mute sur place
        n'est pas detecte par SQLAlchemy, qui ne suit pas les mutations d'un type
        JSON sans `MutableDict`. L'ecriture passerait silencieusement a la trappe.

        Args:
            entity: les preferences dont l'etat fait foi.
            model: la ligne a mettre au meme etat.
        """
        model.account_id = entity.account_id
        model.channels_by_event = {
            event.value: sorted(channel.value for channel in channels)
            for event, channels in entity.channels_by_event.items()
        }

    async def find_for_account(self, account_id: UUID) -> NotificationPreferences | None:
        """Cherche les preferences d'un compte. Voir le port pour le contrat."""
        statement = self._select().where(NotificationPreferencesModel.account_id == account_id)
        model = (await self._session.execute(statement)).scalar_one_or_none()
        return None if model is None else self._to_entity(model)
