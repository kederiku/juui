"""Modele de persistance des preferences de notification (BACK-22).

Une seule table, et deux decisions qui meritent d'etre lues avant d'y toucher.

UNE LIGNE PAR COMPTE, LES ECARTS EN JSONB
L'alternative etait une table de jointure `(account_id, evenement, canal)`, plus
normalisee. Elle repond a une question que PERSONNE ne pose : « quels comptes
veulent des SMS ». Toutes les lectures reelles du module sont « les preferences
DE CE COMPTE », c'est-a-dire l'agregat entier, ecrit et relu d'un bloc -- et
c'est exactement la forme que le depot generique de `shared/` sait servir, une
entite pour une ligne. Trois lignes pour trois evenements auraient demande un
depot ecrit a la main pour recomposer l'agregat. Le jour ou une requete par canal
existera, elle justifiera sa table ; l'ecart est consigne au registre.

Le document ne contient QUE LES ECARTS au defaut : un compte neuf n'a aucune
ligne, et un evenement absent du document veut dire « ce compte n'a rien dit ».
C'est ce qui rend gratuit un compte qui n'a jamais touche a ses reglages -- rien
a semer a l'inscription -- et ce qui laisse les defauts evoluer sans migration de
donnees.

PAS DE `TenantMixin`, ET PAS DE CLE ETRANGERE
Une preference appartient a un COMPTE, pas a un groupe : elle se lit dans l'espace
personnel d'un particulier, hors de toute structure -- meme raison que pour
`accounts`, et le contre-exemple que la docstring de `TenantMixin` prevoit. Et
`account_id` reste un identifiant NU : la table `accounts` appartient au module
identity, une cle etrangere inter-modules souderait les deux schemas (ADR-0015).
L'unicite par compte, elle, est bien physique.
"""

from uuid import UUID

from sqlalchemy import Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base
from app.shared.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKey


class NotificationPreferencesModel(UUIDPrimaryKey, TimestampMixin, Base):
    """Table des preferences de notification, une ligne par compte."""

    __tablename__ = "notification_preferences"

    # `unique=True` et non un index nomme a la main : la convention de nommage de
    # `Base` produit `uq_notification_preferences_account_id`, bien en deca des
    # 63 octets que `check_schema` fait respecter. L'unicite est PHYSIQUE parce
    # que deux jeux de preferences pour un meme compte feraient dependre le
    # resultat de l'ordre de lecture -- et que `find_for_account` leverait.
    account_id: Mapped[UUID] = mapped_column(Uuid, unique=True)

    # JSONB et non JSON : le type binaire de PostgreSQL, qui range le document
    # une fois pour toutes au lieu de le reparser a chaque lecture, et qui refuse
    # d'entree un document mal forme. Aucun index dessus -- on n'interroge jamais
    # son contenu, on le relit en entier.
    #
    # La forme est `{"<evenement>": ["<canal>", ...]}`, en TEXTE des deux cotes
    # comme tous les enums du depot : ajouter un evenement ou un canal est une
    # livraison de code, pas une migration. C'est le depot qui traduit, a la main
    # et visiblement, et qui refuse une valeur que le catalogue ne connait plus.
    channels_by_event: Mapped[dict[str, list[str]]] = mapped_column(JSONB, default=dict)
