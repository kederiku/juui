"""Cycle de vie du worker TaskIQ : les memes ressources que l'API (BACK-15).

Le worker est un PROCESSUS distinct : il n'herite rien du `lifespan` de
`main.py` et doit ouvrir son propre pool PostgreSQL et son propre client Redis.
Les handlers ci-dessous rejouent la sequence du `lifespan` -- validation de la
configuration, moteur, controle de connectivite et de schema, cache -- avec les
MEMES fabriques (`build_engine`, `build_cache`...), concues des BACK-05 et
BACK-14 pour recevoir `Settings` en argument precisement dans ce but.

PAS D'ABSTRACTION « LIFESPAN COMMUN », ET C'EST UN CHOIX
Les fabriques SONT la factorisation : les deux cycles divergent reellement
(`app.state` contre `TaskiqState`, pas de stockage objet cote worker tant
qu'aucune tache n'en a besoin -- BACK-22 l'ajoutera ici), et une abstraction
qui les couvrirait tous deux n'aurait qu'un seul consommateur chacun.

`verify_connectivity` LEVE, et c'est voulu : un worker sans base de donnees
meurt au demarrage, compose le relance -- le meme fail-fast que l'API, la ou le
cache, lui, se contente de journaliser (asymetrie expliquee dans
`redis_cache.py`).
"""

import logging
from typing import Annotated, Final

from taskiq import Context, TaskiqDepends, TaskiqState

from app.core import get_settings
from app.shared.domain.ports.cache import Cache
from app.shared.infrastructure.clients.redis_cache import CACHE_STATE_KEY, RedisCache, build_cache
from app.shared.infrastructure.db.base import Base, check_schema
from app.shared.infrastructure.db.engine import build_engine, verify_connectivity
from app.shared.infrastructure.db.session import STATE_KEY, Database, build_sessionmaker
from app.shared.infrastructure.tasks.discovery import discover_module_tasks

_LOGGER: Final = logging.getLogger(__name__)


async def worker_startup(state: TaskiqState) -> None:
    """Ouvre les ressources du worker, dans l'ordre du `lifespan` de l'API.

    Les ressources se rangent dans `TaskiqState` sous les MEMES cles que dans
    `app.state` (`STATE_KEY`, `CACHE_STATE_KEY`) : celui qui ecrit et celui qui
    lit parlent du meme nom, des deux cotes de la file.

    Args:
        state: l'etat global du broker, porte jusqu'aux taches par `Context`.

    Raises:
        ConfigurationError: si une variable obligatoire manque.
        DatabaseUnavailableError: si PostgreSQL ne repond pas -- le worker
            meurt, compose le relance.
    """
    # La decouverte AVANT les ressources : un fichier de taches qui ne
    # s'importe pas doit tuer le worker sans avoir ouvert le moindre pool.
    discover_module_tasks()

    settings = get_settings()

    engine = build_engine(settings)
    try:
        await verify_connectivity(engine, settings)
        check_schema(Base.metadata)
    except Exception:
        # Meme motif que le `finally` du `lifespan` : un moteur construit avant
        # un `SELECT 1` en echec doit etre libere, sans quoi la boucle de
        # relance du conteneur fuit un pool a chaque tour.
        await engine.dispose()
        raise
    setattr(state, STATE_KEY, Database(engine=engine, sessionmaker=build_sessionmaker(engine)))

    cache = build_cache(settings)
    setattr(state, CACHE_STATE_KEY, cache)
    # `ping()` sonde et journalise, elle ne leve jamais : sans cache le worker
    # tourne, plus lentement -- meme asymetrie que dans `main.py`.
    await cache.ping()

    _LOGGER.info("Worker pret : base de donnees et cache ouverts.")


async def worker_shutdown(state: TaskiqState) -> None:
    """Ferme les ressources du worker, en ordre inverse de l'ouverture.

    Les `isinstance` rendent la fermeture sure meme si le demarrage a echoue a
    mi-chemin : on ne ferme que ce qui a reellement ete ouvert.

    Args:
        state: l'etat global du broker.
    """
    cache = getattr(state, CACHE_STATE_KEY, None)
    if isinstance(cache, RedisCache):
        await cache.aclose()
    database = getattr(state, STATE_KEY, None)
    if isinstance(database, Database):
        await database.engine.dispose()


def get_task_cache(context: Annotated[Context, TaskiqDepends()]) -> Cache:
    """Retourne le cache ouvert par `worker_startup`.

    L'equivalent worker de `get_cache(request)` : une cle, un type, un
    accesseur. L'`isinstance` porte sur le PORT, pas sur `RedisCache` -- une
    doublure en memoire rangee dans l'etat par un test passera sans toucher a
    ce fichier.

    Args:
        context: le contexte d'execution de la tache, injecte par TaskIQ.

    Returns:
        Le cache du processus worker.

    Raises:
        RuntimeError: si `worker_startup` n'a pas tourne.
    """
    cache = getattr(context.state, CACHE_STATE_KEY, None)
    if not isinstance(cache, Cache):
        message = "Le cache n'est pas ouvert : le demarrage du worker a-t-il tourne ?"
        raise RuntimeError(message)
    return cache


def get_task_database(context: Annotated[Context, TaskiqDepends()]) -> Database:
    """Retourne les ressources de persistance ouvertes par `worker_startup`.

    C'est ici qu'une tache prend la fabrique de sessions pour construire SA
    PROPRE unite de travail -- jamais via `get_identity_uow(request)`, qui
    suppose une requete HTTP.

    Args:
        context: le contexte d'execution de la tache, injecte par TaskIQ.

    Returns:
        Les ressources de persistance du processus worker.

    Raises:
        RuntimeError: si `worker_startup` n'a pas tourne.
    """
    database = getattr(context.state, STATE_KEY, None)
    if not isinstance(database, Database):
        message = (
            "Les ressources de persistance ne sont pas ouvertes : "
            "le demarrage du worker a-t-il tourne ?"
        )
        raise RuntimeError(message)
    return database
