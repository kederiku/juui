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

LES RESSOURCES DES MODULES NE PEUVENT PAS S'OUVRIR ICI (BACK-17)
Le contrat `service-spaces` interdit a `shared` d'importer `app.modules.*` : ce
fichier ne peut donc pas construire le magasin d'OTP d'`identity`, ni ce que les
modules suivants ouvriront. Chaque module construit donc SA ressource a la
premiere tache qui en a besoin, et la confie a `remember_module_resource` pour
que la fermeture ci-dessous la retrouve. C'est le pendant, cote worker, de ce que
`main.py` fait explicitement dans son `lifespan` -- lui a le droit de nommer les
modules, c'est le point d'assemblage.

`verify_connectivity` LEVE, et c'est voulu : un worker sans base de donnees
meurt au demarrage, compose le relance -- le meme fail-fast que l'API, la ou le
cache, lui, se contente de journaliser (asymetrie expliquee dans
`redis_cache.py`).
"""

import logging
from typing import Annotated, Final, Protocol, runtime_checkable

from taskiq import Context, TaskiqDepends, TaskiqState

from app.core import configure_logging, get_settings
from app.shared.domain.ports.cache import Cache
from app.shared.infrastructure.clients.redis_cache import CACHE_STATE_KEY, RedisCache, build_cache
from app.shared.infrastructure.db.base import Base, check_schema
from app.shared.infrastructure.db.engine import build_engine, verify_connectivity
from app.shared.infrastructure.db.session import STATE_KEY, Database, build_sessionmaker
from app.shared.infrastructure.tasks.discovery import discover_module_tasks
from app.shared.infrastructure.tenancy import current_group_label

_LOGGER: Final = logging.getLogger(__name__)

# Cle sous laquelle s'accumulent les ressources ouvertes par les modules.
_MODULE_RESOURCES_KEY: Final = "module_resources"


@runtime_checkable
class AsyncClosable(Protocol):
    """Ce qu'une ressource de module doit savoir faire pour etre refermee ici.

    Un protocole STRUCTUREL, et c'est ce qui permet a `shared` de fermer un objet
    d'`app.modules.*` sans jamais nommer sa classe -- ce que le contrat
    `service-spaces` lui interdirait.
    """

    async def aclose(self) -> None:
        """Libere la ressource. Ne doit pas lever."""
        ...


def remember_module_resource(state: TaskiqState, resource: AsyncClosable) -> None:
    """Confie au cycle de vie du worker une ressource ouverte par un module.

    A APPELER DANS LA FOULEE DE LA CONSTRUCTION, jamais plus tard : une ressource
    construite et non confiee fuit a l'arret du worker.

    Args:
        state: l'etat global du broker.
        resource: la ressource a refermer, dans l'ordre inverse d'ouverture.
    """
    resources = getattr(state, _MODULE_RESOURCES_KEY, None)
    if not isinstance(resources, list):
        resources = []
        setattr(state, _MODULE_RESOURCES_KEY, resources)
    resources.append(resource)


async def _close_module_resources(state: TaskiqState) -> None:
    """Referme les ressources des modules, en ordre inverse d'ouverture.

    Chaque fermeture est isolee : une ressource recalcitrante ne doit pas empecher
    les suivantes, ni le `dispose()` du moteur qui vient apres.

    Args:
        state: l'etat global du broker.
    """
    resources = getattr(state, _MODULE_RESOURCES_KEY, None)
    if not isinstance(resources, list):
        return
    for resource in reversed(resources):
        if not isinstance(resource, AsyncClosable):
            continue
        try:
            await resource.aclose()
        except Exception:
            _LOGGER.exception("Fermeture d'une ressource de module en echec, ignoree.")
    resources.clear()


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
    settings = get_settings()

    # La journalisation avant tout le reste (BACK-11), pour la meme raison que
    # dans le `lifespan` de l'API : ce qui suit doit sortir au format du projet,
    # l'echec de decouverte compris. Le worker n'appelle jamais `create_app()` --
    # c'est ici, et nulle part ailleurs, qu'il herite de la configuration.
    #
    # Les deux commandes du worker portent `--no-configure-logging` (Dockerfile
    # et docker-compose.override.yml) : sans lui, le `basicConfig` de TaskIQ
    # court AVANT cet appel et poserait un second handler sur la racine.
    #
    # `current_group_label` passe en argument comme cote API : `core` ne peut pas
    # importer `shared`, et c'est ce pont qui fait apparaitre le groupe d'une
    # tache dans ses journaux.
    configure_logging(settings.app, context_providers={"group_id": current_group_label})

    # La decouverte AVANT les ressources : un fichier de taches qui ne
    # s'importe pas doit tuer le worker sans avoir ouvert le moindre pool.
    # `get_settings()` ci-dessus n'ouvre rien, la promesse tient.
    discover_module_tasks()

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
    # Les ressources des modules d'abord : ouvertes en dernier, a la premiere
    # tache qui en avait besoin, elles se ferment en premier.
    await _close_module_resources(state)

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
