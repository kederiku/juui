"""Broker TaskIQ du service : Redis base 1, resultats, politique de reprise (BACK-15).

CE CHEMIN ET CE NOM SONT UN CONTRAT
L'infrastructure livree (INFRA-04, INFRA-05b) fige la commande du worker :
`taskiq worker app.shared.infrastructure.tasks.broker:broker`. Ce module doit
donc s'appeler exactement ainsi et exposer un attribut nomme `broker`. Le
renommer casserait le conteneur worker sans qu'aucun test local ne le voie.

`RedisStreamBroker` ET PAS `ListQueueBroker`
Les streams Redis portent des acquittements : un worker tue en pleine execution
ne PERD pas le message, il est represente a un autre consommateur apres
l'`idle_timeout`. Avec la liste (`LPUSH`/`BRPOP`), le message sorti de la file
disparait avec le worker -- inacceptable pour le perimetre annonce (e-mails,
PDF, images).

LE VERSANT CLIENT ET LE VERSANT WORKER
Le meme objet sert les deux processus. Cote API, `main.py` appelle
`broker.startup()` sous la garde `is_worker_process` -- ce qui ne demarre que le
backend de resultats, necessaire au `kiq`. Cote worker, la CLI importe ce module
et deroule les handlers de `lifecycle.py` (`WORKER_STARTUP`/`WORKER_SHUTDOWN`),
qui ouvrent pool PostgreSQL et cache.
"""

from typing import Any, Final

from taskiq import AsyncBroker, TaskiqEvents
from taskiq.serializers import JSONSerializer
from taskiq_redis import RedisAsyncResultBackend, RedisStreamBroker

from app.core import Settings, get_settings
from app.shared.infrastructure.tasks.lifecycle import worker_shutdown, worker_startup
from app.shared.infrastructure.tasks.middlewares import (
    CorrelationMiddleware,
    RetryWithDeadLetterMiddleware,
)

# Duree de retention des resultats en base 1. OBLIGATOIRE : la base du broker
# n'a ni politique d'eviction ni TTL par defaut (convention INFRA-02) -- sans
# cette borne, chaque tache executee laisserait sa cle de resultat pour
# toujours. Une heure : assez pour qu'un appelant vienne lire, trop peu pour
# s'accumuler.
RESULT_TTL_SECONDS: Final = 3600

# Borne du stream des taches (XADD ... MAXLEN ~). Le tilde (`approximate=True`,
# defaut) laisse Redis elaguer par pages entieres : la borne est un garde-fou
# contre un producteur devenu fou, pas une limite exacte.
STREAM_MAXLEN: Final = 10_000


def build_broker(settings: Settings) -> AsyncBroker:
    """Construit le broker, son backend de resultats et sa politique de reprise.

    Comme `build_engine` et `build_cache` : construire n'ouvre AUCUNE connexion,
    les pools naissent au premier emprunt. Et comme partout, `settings` vient en
    argument -- les sondes et les tests fabriquent le leur.

    Args:
        settings: la configuration du service, dont la section Redis.

    Returns:
        Le broker assemble, pret a etre demarre par l'un ou l'autre processus.

    """
    environment = settings.app.environment
    # `client_name` : meme geste d'observabilite que `juui-api-cache/...`
    # (BACK-14) -- trois noms distincts pour le stream, les resultats et la
    # file de rejets, afin que `CLIENT LIST` dise qui occupe l'instance.
    #
    # `broker_url` porte le mot de passe en clair : elle se transmet, elle ne se
    # journalise JAMAIS -- meme regle que dans `config.py` et `redis_cache.py`.
    result_backend: RedisAsyncResultBackend[Any] = RedisAsyncResultBackend(
        redis_url=settings.redis.broker_url,
        result_ex_time=RESULT_TTL_SECONDS,
        # JSON et non le pickle par defaut du backend : la regle de BACK-14 --
        # jamais desserialiser du pickle relu de Redis -- vaut pour la base 1
        # comme pour la base 0. `TaskiqResult` sait voyager ainsi, exceptions
        # comprises ; en echange, une valeur de RETOUR de tache doit etre
        # serialisable en JSON -- la meme regle que pour ses arguments.
        serializer=JSONSerializer(),
        client_name=f"juui-api-results/{environment}",
    )
    stream_broker = RedisStreamBroker(
        url=settings.redis.broker_url,
        maxlen=STREAM_MAXLEN,
        client_name=f"juui-api-broker/{environment}",
    )
    return stream_broker.with_result_backend(result_backend).with_middlewares(
        CorrelationMiddleware(),
        RetryWithDeadLetterMiddleware(
            redis_url=settings.redis.broker_url,
            client_name=f"juui-worker-dlq/{environment}",
        ),
    )


# L'UNIQUE entorse assumee a « rien ne se construit a l'import » : la CLI
# `taskiq worker module:attribut` exige un OBJET de module, pas une fabrique.
# Ce que l'entorse coute vraiment : `get_settings()` lit la configuration -- ce
# module n'est donc importable qu'avec un environnement valide, et `main.py`
# ne l'importe que dans le corps du `lifespan` pour que `import app.main`
# reste, lui, sans exigence. Ce qu'elle ne coute pas : aucune connexion ne
# s'ouvre (voir `build_broker`), et `get_settings` est en `lru_cache` -- le
# worker et une eventuelle API du meme processus partagent la meme lecture.
broker: Final[AsyncBroker] = build_broker(get_settings())

# Les handlers vivent dans `lifecycle.py` et s'enregistrent ici : le broker ne
# connait pas son cycle de vie, il le recoit -- et `lifecycle.py` reste
# importable sans configuration, lui.
broker.add_event_handler(TaskiqEvents.WORKER_STARTUP, worker_startup)
broker.add_event_handler(TaskiqEvents.WORKER_SHUTDOWN, worker_shutdown)
