"""Fabrique de sessions et acces aux ressources de persistance (BACK-05).

Ce module livre la FABRIQUE, pas la session. La difference n'est pas de style :
ouvrir une session, la refermer et decider quand la transaction se valide sont
le travail de l'unite de travail (BACK-06a), dont le but declare est que la
couche application ne voie jamais une `AsyncSession`. Une dependance
`get_session()` publiee ici serait exactement l'affordance qui rend cette
promesse intenable -- la premiere route pressee s'en servirait.

L'unite de travail (BACK-06a) est le consommateur prevu : elle prend ici la
fabrique, ouvre une session par bloc `async with` et la referme a la sortie. Le
depot recoit sa session en argument et n'en cree jamais, et la sonde de sante
(BACK-08) interroge le moteur.
"""

from dataclasses import dataclass
from typing import Final

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm.session import JoinTransactionMode

# Cle unique sous laquelle le `lifespan` range les ressources de persistance
# dans `app.state`. Une constante plutot qu'un litteral : celui qui ecrit et
# celui qui lit doivent parler du meme nom.
STATE_KEY: Final = "database"


def build_sessionmaker(
    bind: AsyncEngine | AsyncConnection,
    *,
    join_transaction_mode: JoinTransactionMode = "conditional_savepoint",
) -> async_sessionmaker[AsyncSession]:
    """Construit la fabrique de sessions du service.

    `expire_on_commit=False` N'EST PAS FACULTATIF EN ASYNCHRONE
    Avec le defaut, `commit()` perime toutes les instances suivies, et le
    premier acces a un attribut declenche un SELECT paresseux. En asynchrone, ce
    SELECT part hors du contexte greenlet et leve `MissingGreenlet` : le mapping
    `_to_entity(model)` juste apres un commit casserait.

    Ce que cela coute, honnetement : les objets gardent les valeurs de LEUR
    transaction. Une ligne modifiee entre-temps par une autre requete ne se voit
    pas. Avec une session par requete, la fenetre dure une requete, et le
    passage par une entite du domaine fait que la peremption ne sort jamais de
    l'infrastructure.

    DEUX PIEGES QUE L'UNITE DE TRAVAIL (BACK-06a) AFFRONTE
    `rollback()` perime les instances QUOI QU'IL ARRIVE : journaliser
    `account.email` apres l'annulation leve `MissingGreenlet` au lieu de rendre
    une valeur perimee -- capturer ce qu'on veut tracer AVANT. Et une session
    reutilisee d'un bloc `async with` a l'autre resservirait son identity map
    sans relire la base : l'unite de travail fabrique pour cela une session
    NEUVE a chaque bloc.

    `autoflush=False` : avec le defaut, la premiere lecture venue declenche un
    flush implicite, et une violation de contrainte remonte alors depuis la
    LECTURE -- au mauvais endroit, sous le mauvais nom. Le flush a lieu aux
    ecritures qui le demandent -- `add()` du depot generique flushe sa ligne,
    pour qu'elle soit visible de son propre bloc -- et au commit, jamais au
    detour d'une lecture.

    UNE CONNEXION EST UN LIEN ACCEPTABLE, ET C'EST POUR LE HARNAIS (BACK-12)
    `bind` accepte une `AsyncConnection` en plus d'un moteur, et
    `join_transaction_mode` est reglable. Les deux defauts sont ceux de
    SQLAlchemy et de la production : le `lifespan` passe son moteur et n'y pense
    jamais. Le harnais de test, lui, lie sa fabrique a une connexion DEJA sous
    transaction et passe `create_savepoint`, si bien qu'un `commit()` applicatif
    relache un savepoint au lieu de valider pour de bon -- et que le rollback de
    la connexion emporte tout, y compris ce que le code sous test a valide.

    Le faire ICI plutot que de recopier `async_sessionmaker(...)` dans les
    fixtures est la seule facon que `expire_on_commit=False` et
    `autoflush=False` -- les deux reglages ci-dessus, longuement justifies --
    ne divergent jamais entre la production et les tests.

    Args:
        bind: le moteur ouvert par le `lifespan`, ou une connexion deja ouverte.
        join_transaction_mode: ce que fait une session qui trouve une
            transaction deja commencee sur son lien.

    Returns:
        La fabrique de sessions, a partager pour toute la duree du processus.
    """
    return async_sessionmaker(
        bind,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode=join_transaction_mode,
    )


@dataclass(frozen=True, slots=True)
class Database:
    """Ressources de persistance vivant le temps du processus.

    Un objet unique plutot que deux attributs poses cote a cote sur `app.state` :
    ils naissent ensemble, ils meurent ensemble, et un seul point d'entree suffit
    a savoir si le `lifespan` a bien tourne.
    """

    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]


def get_database(request: Request) -> Database:
    """Retourne les ressources de persistance ouvertes par le `lifespan`.

    Forme de reference pour les ressources de longue duree : une cle, un type, un
    accesseur. Le client Redis (BACK-14) et le broker TaskIQ (BACK-15) la
    reprendront ; l'unite de travail (BACK-06a) en est le premier consommateur
    reel -- `get_identity_uow` y prend la fabrique de sessions.

    L'`isinstance` n'est pas de la defense pour rien. `app.state` est type `Any`,
    et Mypy en mode strict refuse d'en retourner la valeur telle quelle. Il
    transforme au passage une application construite sans son `lifespan` -- ce
    que produit un test mal cable -- en message lisible, plutot qu'en
    `AttributeError` au milieu d'une requete.

    Args:
        request: la requete en cours, d'ou l'on remonte a l'application.

    Returns:
        Les ressources de persistance du processus.

    Raises:
        RuntimeError: si le `lifespan` n'a pas tourne.
    """
    database = getattr(request.app.state, STATE_KEY, None)
    if not isinstance(database, Database):
        message = (
            "Les ressources de persistance ne sont pas ouvertes : "
            "l'application a-t-elle ete construite sans son lifespan ?"
        )
        raise RuntimeError(message)
    return database
