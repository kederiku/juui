"""Modele de persistance du compte (BACK-04, mixins adoptes en BACK-05).

TROISIEME des trois modeles du guide DDD, et le seul qui parle SQL. Il decrit
des colonnes, des types et des contraintes -- pas des regles metier : un modele
de persistance qui porterait une methode `suspend()` remettrait le domaine dans
l'infrastructure, et le rendrait indissociable de la base.

Syntaxe moderne obligatoire : `Mapped[...]` et `mapped_column(...)`, jamais
l'ancienne API `Column`.

DEUX MIXINS SUR TROIS
`UUIDPrimaryKey` remplace la declaration d'`id` que BACK-04 portait a la main, et
`TimestampMixin` ajoute `created_at` et `updated_at`, tenus par PostgreSQL.
Aucun des deux n'apparait dans l'entite du domaine : le compte n'a pas de regle
metier qui depende de sa date de creation, et le depot n'a donc rien a en
reporter. Le jour ou une regle en aurait besoin, c'est l'entite qui gagnerait le
champ, pas l'inverse.

CE QUE LES TICKETS SUIVANTS AJOUTERONT ICI
La colonne du mot de passe hache arrive en BACK-28, avec le parcours qui la
remplit ; BACK-10b a livre la brique de hachage et le type `PasswordHash`, dont
la docstring donne la forme de colonne attendue (`String(255)`, jamais 97). Le
secret TOTP arrive en BACK-18.

PAS DE `group_id` ICI, ET C'EST DELIBERE
`TenantMixin` (BACK-05) est OPT-IN, et le compte ne le declare pas :
l'appartenance a un groupe est une relation N:M DATEE portee par le module
`organization` (BACK-16). Un veterinaire remplacant intervient dans plusieurs
groupes avec un seul compte.
"""

from sqlalchemy import Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.infrastructure.db.base import Base
from app.shared.infrastructure.db.mixins import TimestampMixin, UUIDPrimaryKey


class AccountModel(UUIDPrimaryKey, TimestampMixin, Base):
    """Table des comptes d'acces au service."""

    __tablename__ = "accounts"
    __table_args__ = (
        # Unicite d'e-mail INSENSIBLE A LA CASSE, rendue physique (INFRA-09,
        # ADR-0016) : `Veto@x.fr` apres `veto@x.fr` echoue sur cet index. Le
        # nom est EXPLICITE, seule entorse a `op.f()` : la convention de
        # nommage (`column_0_N_name`) ne sait pas nommer une expression.
        # Declare ICI et pas seulement en migration : les tests creent les
        # tables par `Base.metadata.create_all`, qui ne lit que le modele.
        Index("ix_accounts_email_lower", text("lower(email)"), unique=True),
    )

    # 320 caracteres : la longueur maximale d'une adresse e-mail selon la RFC
    # 5321 (64 pour la partie locale, 255 pour le domaine, plus l'arobase).
    #
    # Pas de `unique=True` sur la colonne : l'index fonctionnel ci-dessus
    # subsume l'unicite exacte, un second index sur la meme colonne ne serait
    # qu'un cout d'ecriture de plus. L'index refuse le doublon, il ne
    # normalise pas : la forme canonique reste posee par le domaine
    # (`normalize_email`), qui seul sait repondre autre chose qu'un conflit.
    email: Mapped[str] = mapped_column(String(320))

    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    phone: Mapped[str | None] = mapped_column(String(30), default=None)

    # Type et statut stockes en TEXTE, et non en enum natif PostgreSQL. Deux
    # raisons : ajouter une valeur a un enum natif se fait par migration, et le
    # mapping explicite vers `AccountType` / `AccountStatus` -- que le depot
    # ecrit a la main -- devient alors visible plutot que magique. C'est
    # exactement ce que la regle des 3 modeles demande de montrer.
    account_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))

    email_verified: Mapped[bool] = mapped_column(default=False)
