"""Moteur de connexion asynchrone a PostgreSQL (BACK-05).

Le moteur porte le POOL de connexions : il vit aussi longtemps que le processus,
il est cree une seule fois par le `lifespan` et referme par lui. Rien ici ne
s'ouvre a l'import.

UNE FONCTION DE `Settings`, ET NON UN LECTEUR DE CONFIGURATION
`build_engine` recoit sa configuration en argument au lieu d'appeler
`get_settings()`. Cette fonction est mise en cache par `lru_cache` : un
constructeur qui l'appellerait de l'interieur ne saurait pas fabriquer un moteur
different de celui du processus. Or l'`env.py` d'Alembic (BACK-07) tourne HORS de
l'application, et les fixtures de test (BACK-12) auront besoin d'un moteur a
elles -- avec un `poolclass=NullPool`, la file interne du pool par defaut etant
liee a la boucle d'evenements de sa premiere utilisation. BACK-07 a finalement
construit le sien directement : `NullPool` refuse les `pool_size`/`max_overflow`
transmis ici, et une migration doit s'annoncer sous son propre nom dans
`pg_stat_activity`. BACK-12 a livre les trois parametres qui manquaient --
`url`, `poolclass` et `application_name` --, et la fixture `engine` du harnais
passe desormais par cette fabrique. `alembic/env.py` garde la sienne : il tourne
hors de l'application et ne doit rien lui emprunter.

DIMENSIONNER LE POOL
Le calcul qui compte : connexions totales = workers x (`pool_size` +
`max_overflow`). Avec les valeurs livrees et quatre workers, l'API seule peut
reclamer 60 connexions, auxquelles s'ajouteront le worker TaskIQ (BACK-15) et
pgAdmin -- contre un `max_connections` de 100 par defaut cote serveur.
"""

from typing import Final

import asyncpg
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import Pool

from app.core import Settings

# Delai maximal d'etablissement d'une connexion. Sans lui, un hote qui ne repond
# pas -- resolution DNS suspendue, machine en cours de demarrage -- ferait
# attendre le demarrage du processus sans fin ni message.
_CONNECT_TIMEOUT_SECONDS: Final = 10

# Ce qu'il faut attraper pour dire « PostgreSQL est injoignable ».
#
# PUBLIQUE, parce que ce n'est pas une connaissance de ce module seul : le
# harnais de test (BACK-12) doit distinguer « la base ne repond pas », qui fait
# SAUTER ses tests d'integration, de toute autre panne, qui doit les faire
# ECHOUER. Recopier la liste la ferait diverger le jour ou un pilote change.
#
# SQLAlchemy n'enveloppe que les erreurs levees A TRAVERS le pilote : celles qui
# surviennent DANS `asyncpg.connect()` remontent telles quelles. Un serveur
# arrete donne `ConnectionRefusedError`, un hote inconnu `socket.gaierror` --
# deux `OSError` --, un mot de passe faux `InvalidPasswordError` et une base
# absente `InvalidCatalogNameError`. Un `except SQLAlchemyError` seul n'en
# attraperait aucune. Meme jeu que la boucle d'attente de docker/api/entrypoint.sh.
UNREACHABLE_ERRORS: Final = (OSError, asyncpg.PostgresError, SQLAlchemyError)


class DatabaseUnavailableError(RuntimeError):
    """PostgreSQL est injoignable : la configuration est lue, le serveur non.

    Volontairement distincte de `ConfigurationError` (BACK-03). Celle-la dit
    « une variable manque ou ne vaut rien, corriger le .env » ; celle-ci dit
    « le fichier est juste, demarrer PostgreSQL ou attendre qu'il finisse de
    partir ». Les confondre enverrait l'exploitant relire un fichier correct.
    """


def build_engine(
    settings: Settings,
    *,
    url: str | None = None,
    poolclass: type[Pool] | None = None,
    application_name: str | None = None,
) -> AsyncEngine:
    """Construit le moteur asynchrone, sans ouvrir la moindre connexion.

    `create_async_engine` n'etablit rien : la premiere connexion nait au premier
    emprunt au pool. C'est `verify_connectivity` qui la provoque, et le
    `lifespan` qui decide du moment.

    LES TROIS PARAMETRES FACULTATIFS SONT POUR LE HARNAIS (BACK-12), et l'appel
    du `lifespan` n'en passe aucun. Ils existent pour que la fixture `engine`
    cesse d'appeler `create_async_engine` a la main : le delai de connexion, la
    double garde sur `echo` et le nommage dans `pg_stat_activity` sont des
    reglages du service, pas du fichier qui les recopie.

    `poolclass=NullPool` SUPPRIME `pool_size` ET `max_overflow`, parce que
    `create_engine` les REFUSE dans cette combinaison -- mesure :
    « Invalid argument(s) 'pool_size','max_overflow' ». `pool_pre_ping` et
    `pool_recycle`, eux, restent acceptes et gardent leur sens. C'est le
    parametre dont la suite a besoin : le moteur nait sur la boucle de la
    session pytest et sert des tests qui tournent chacun sur la leur ; une file
    interne se lierait a la premiere boucle venue.

    Args:
        settings: la configuration du service, dont la section base de donnees.
        url: une cible autre que la base applicative -- la base de test, et rien
            d'autre a ce jour.
        poolclass: la classe de pool a employer au lieu du defaut.
        application_name: le nom annonce dans `pg_stat_activity`.

    Returns:
        Le moteur, pret a etre range dans `app.state`.
    """
    # `NullPool` n'a ni file ni debordement : lui transmettre leur taille est une
    # erreur de configuration, pas un reglage sans effet.
    pool_options: dict[str, object] = (
        {"poolclass": poolclass}
        if poolclass is not None
        else {
            "pool_size": settings.db.pool_size,
            "max_overflow": settings.db.max_overflow,
        }
    )
    return create_async_engine(
        settings.db.sqlalchemy_url if url is None else url,
        **pool_options,
        # Une connexion peut mourir sans que le pool le sache : redemarrage du
        # serveur, coupure d'un intermediaire. `pool_pre_ping` verifie la
        # connexion a chaque emprunt, au prix d'un aller-retour ; `pool_recycle`
        # retire d'office les plus vieilles, ce que le ping ne fait pas -- il
        # attendrait le delai TCP sur une socket devenue muette.
        pool_pre_ping=True,
        pool_recycle=settings.db.pool_recycle_seconds,
        # Double garde sur la journalisation SQL : meme si `POSTGRES_ECHO` est
        # laisse a `true` par megarde dans un environnement de production, les
        # parametres lies -- adresses, puis empreintes de mot de passe
        # (BACK-28) et secret TOTP (BACK-18) -- n'y partiront pas en clair.
        echo=settings.db.echo and not settings.app.is_production,
        connect_args={
            "timeout": _CONNECT_TIMEOUT_SECONDS,
            # Nomme la connexion dans `pg_stat_activity` et dans pgAdmin. Sans
            # lui toutes les connexions sont anonymes, et rien ne distingue
            # l'API du worker, d'une migration ou d'une session ouverte a la
            # main le jour ou il faut comprendre qui sature le serveur.
            "server_settings": {
                "application_name": (
                    f"juui-api/{settings.app.environment}"
                    if application_name is None
                    else application_name
                ),
            },
        },
    )


async def verify_connectivity(engine: AsyncEngine, settings: Settings) -> None:
    """Etablit une connexion et execute `SELECT 1`, ou echoue en le disant.

    Verifier au demarrage plutot qu'a la premiere requete : un mot de passe faux
    ou un serveur absent doivent arreter le processus, pas produire une erreur
    500 pour le premier utilisateur. C'est aussi ce qui rend honnete le
    healthcheck du conteneur (INFRA-04), qui declare l'API saine des qu'elle
    repond en HTTP.

    Args:
        engine: le moteur a eprouver.
        settings: la configuration, pour nommer la cible dans le message d'echec.

    Raises:
        DatabaseUnavailableError: si la connexion ne peut pas etre etablie.
    """
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except UNREACHABLE_ERRORS as error:
        # Le message nomme les composants, JAMAIS `sqlalchemy_url` : cette
        # propriete porte le mot de passe en clair, et un message d'erreur finit
        # toujours par etre recopie quelque part.
        message = (
            f"PostgreSQL injoignable sur {settings.db.host}:{settings.db.port} "
            f"(base « {settings.db.db} », utilisateur « {settings.db.user} ») : {error}"
        )
        raise DatabaseUnavailableError(message) from error
