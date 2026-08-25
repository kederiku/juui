"""Intergiciels TaskIQ : correlation, reprise et file de rejets (BACK-15).

Deux intergiciels, deux preoccupations :

- `CorrelationMiddleware` transporte l'identifiant de requete (BACK-11) de
  l'appelant vers le worker, par un label -- automatique, donc impossible a
  oublier, contrairement a un `.with_labels()` manuel sur chaque `kiq`.
- `RetryWithDeadLetterMiddleware` porte la POLITIQUE DE REPRISE entiere :
  relances avec repli exponentiel, puis versement dans une file de rejets a
  l'epuisement. Une seule classe et non deux, parce que « relancer ou rejeter »
  est UNE decision -- la decouper exposerait l'ordre d'appel des intergiciels,
  que taskiq ne garantit pas.

POURQUOI PAS `SmartRetryMiddleware`, QUI EXISTE POURTANT
Verifie dans taskiq 0.12.5 : sans `schedule_source`, son delai part comme label
`delay` -- que ni le receiver (qui ne lit que `ack_type` et `timeout`) ni les
brokers Redis n'interpretent. Le repli « exponentiel » serait un renvoi
IMMEDIAT. La variante `schedule_source` exigerait un processus `taskiq
scheduler` que l'infrastructure livree (INFRA-04, INFRA-05b) n'a pas. Et a
l'epuisement, il se contente d'un avertissement : la file de rejets serait de
toute facon a ecrire. D'ou l'intergiciel maison, calque sur la mecanique de
re-emission de `SimpleRetryMiddleware` (memes labels `_retries` / `max_retries`,
meme `task_id` conserve) pour rester compatible le jour ou un scheduler existera.

LE SOMMEIL DANS `on_error` EST UN COMPROMIS ASSUME
`asyncio.sleep(delay)` occupe un creneau de concurrence async du worker, pas le
worker entier. L'acquittement (`when_saved`, defaut de la CLI) n'a lieu qu'apres
les hooks d'erreur : un worker tue pendant le sommeil ne perd pas le message, le
stream le represente apres son `idle_timeout` (600 s, tres au-dela du plafond de
30 s d'attente). Pas de gigue aleatoire : a trois tentatives par tache, elle ne
protegerait de rien.
"""

import asyncio
import json
import logging
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Final

from redis.asyncio import ConnectionPool, Redis
from redis.exceptions import RedisError
from taskiq import NoResultError, TaskiqMessage, TaskiqMiddleware, TaskiqResult
from taskiq.kicker import AsyncKicker

from app.core.correlation import current_request_id

_LOGGER: Final = logging.getLogger(__name__)

# Nom du label transportant l'identifiant de requete. Hors de la liste des
# labels reserves de taskiq (`_retries`, `max_retries`, `delay`, `timeout`,
# `ack_type`, `queue_name`).
REQUEST_ID_LABEL: Final = "request_id"

# Politique de reprise par defaut : TOUTE tache est relancee, `max_retries`
# compte les EXECUTIONS totales (memes semantiques que les intergiciels
# officiels). Une tache qui ne doit pas etre rejouee declare
# `@broker.task(max_retries=1)` -- un seul bouton a connaitre.
#
# Des constantes de module et non des reglages, comme dans `redis_cache.py` :
# chaque variable de configuration coute deux gabarits `.env.example`, une
# ligne de compose et une ligne de documentation.
DEFAULT_MAX_RETRIES: Final = 3
BASE_RETRY_DELAY_SECONDS: Final = 1.0
RETRY_BACKOFF_FACTOR: Final = 2.0
MAX_RETRY_DELAY_SECONDS: Final = 30.0

# La file de rejets : une liste en base 1, a cote du stream de taskiq. Pas de
# TTL, a dessein -- un rejet est un incident a instruire, pas une donnee
# perissable -- mais une BORNE : la base 1 n'a ni expiration ni eviction
# (convention INFRA-02), une liste sans plafond y croitrait sans fin.
DEAD_LETTER_KEY: Final = "taskiq:dead-letter"
DEAD_LETTER_MAX_LENGTH: Final = 1000

# Delais d'etablissement et de commande du client de la file de rejets : memes
# valeurs et meme motif que `redis_cache.py`.
_CONNECT_TIMEOUT_SECONDS: Final = 2.0
_COMMAND_TIMEOUT_SECONDS: Final = 2.0

# Ce qu'il faut attraper pour dire « Redis est injoignable » -- voir le
# commentaire de `_UNREACHABLE` dans `redis_cache.py`.
_UNREACHABLE: Final = (OSError, RedisError)


class CorrelationMiddleware(TaskiqMiddleware):
    """Transporte l'identifiant de requete de l'appelant vers le worker.

    `pre_send` lit la contextvar cote appelant et la pose en label ;
    `pre_execute` relit le label cote worker et repose la contextvar. Le futur
    filtre de journalisation de BACK-11 la lira sans savoir qu'un worker existe.

    AUCUN NETTOYAGE COTE WORKER, ET C'EST DEMONTRABLE
    Le receiver execute chaque message dans SA PROPRE tache asyncio, et
    `pre_execute` court dans celle-ci, juste avant le corps de la tache. Une
    contextvar posee ici est donc isolee par message et meurt avec lui -- rien
    a remettre en place, contrairement au `use_group` des taches, qui partage la
    contextvar de tenance avec du code appele en profondeur.
    """

    def pre_send(self, message: TaskiqMessage) -> TaskiqMessage:
        """Pose l'identifiant de requete courant en label, s'il existe.

        Args:
            message: le message en partance.

        Returns:
            Le meme message, enrichi du label de correlation le cas echeant.
        """
        request_id = current_request_id.get()
        if request_id is not None:
            message.labels[REQUEST_ID_LABEL] = request_id
        return message

    def pre_execute(self, message: TaskiqMessage) -> TaskiqMessage:
        """Repose l'identifiant de requete d'origine dans la contextvar du worker.

        Args:
            message: le message recu.

        Returns:
            Le meme message, inchange.
        """
        request_id = message.labels.get(REQUEST_ID_LABEL)
        if isinstance(request_id, str):
            current_request_id.set(request_id)
        return message


class RetryWithDeadLetterMiddleware(TaskiqMiddleware):
    """Relance les taches en echec, puis verse les echecs definitifs en rejets.

    La mecanique de re-emission est celle de `SimpleRetryMiddleware`, verifiee
    dans le paquet installe : memes labels (`_retries` incremente, `max_retries`
    lu), meme `task_id` conserve -- `wait_result` sur l'appel d'origine suit
    donc toute la chaine de relances. S'y ajoutent le delai exponentiel avant
    re-emission et le versement en file de rejets a l'epuisement.
    """

    def __init__(
        self,
        *,
        redis_url: str,
        client_name: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_delay_seconds: float = BASE_RETRY_DELAY_SECONDS,
        backoff_factor: float = RETRY_BACKOFF_FACTOR,
        max_delay_seconds: float = MAX_RETRY_DELAY_SECONDS,
        dead_letter_key: str = DEAD_LETTER_KEY,
        dead_letter_max_length: int = DEAD_LETTER_MAX_LENGTH,
    ) -> None:
        """Assemble la politique de reprise et son client vers la file de rejets.

        Construire n'ouvre aucune connexion -- meme garantie que `build_cache` :
        le processus d'API instancie cet intergiciel sans jamais payer le client,
        `on_error` ne courant que cote worker.

        Args:
            redis_url: URL de la base du broker (base 1). Porte le mot de passe :
                ne jamais la journaliser.
            client_name: nom du client dans `CLIENT LIST`, pour distinguer la
                file de rejets du broker et du cache le jour ou il faut
                comprendre qui occupe l'instance.
            max_retries: nombre total d'executions par defaut, label
                `max_retries` prioritaire.
            base_delay_seconds: delai avant la premiere relance.
            backoff_factor: facteur multiplicatif entre deux relances.
            max_delay_seconds: plafond du delai -- a tenir TRES en-deca de
                l'`idle_timeout` du stream (600 s), sans quoi un message dormant
                serait represente a un autre worker pendant l'attente.
            dead_letter_key: cle de la liste des rejets, en base 1.
            dead_letter_max_length: taille maximale de la liste des rejets.
        """
        self._pool = ConnectionPool.from_url(
            redis_url,
            socket_connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            socket_timeout=_COMMAND_TIMEOUT_SECONDS,
            client_name=client_name,
        )
        self._client = Redis(connection_pool=self._pool)
        self._max_retries = max_retries
        self._base_delay_seconds = base_delay_seconds
        self._backoff_factor = backoff_factor
        self._max_delay_seconds = max_delay_seconds
        self._dead_letter_key = dead_letter_key
        self._dead_letter_max_length = dead_letter_max_length

    async def shutdown(self) -> None:
        """Ferme le client puis le pool, sans jamais lever.

        Appelee par `broker.shutdown()` dans les deux processus ; cote API le
        pool n'a jamais ouvert de connexion et la fermeture ne coute rien. Le
        `suppress` tient au meme motif que `RedisCache.aclose` : une exception
        ici sauterait les fermetures qui suivent dans le broker.
        """
        with suppress(*_UNREACHABLE):
            await self._client.aclose()
        with suppress(*_UNREACHABLE):
            await self._pool.aclose()

    def compute_delay(self, attempt: int) -> float:
        """Calcule le delai avant la relance numero `attempt`.

        Fonction pure, exposee pour etre sondee sans broker : 1 s, 2 s, 4 s...
        plafonnes a `max_delay_seconds`.

        Args:
            attempt: numero de la relance a venir, en partant de 1.

        Returns:
            Le delai en secondes.
        """
        delay = self._base_delay_seconds * self._backoff_factor ** (attempt - 1)
        return min(delay, self._max_delay_seconds)

    async def on_error(
        self,
        message: TaskiqMessage,
        result: TaskiqResult[Any],
        exception: BaseException,
    ) -> None:
        """Relance la tache apres un delai, ou la verse en rejets si epuisee.

        Args:
            message: le message dont l'execution a echoue.
            result: le resultat en cours d'enregistrement, mute pour ne pas
                stocker un echec transitoire.
            exception: l'exception levee par la tache.
        """
        # `NoResultError` est le signal interne « ne pas enregistrer de
        # resultat » -- notamment celui pose par une relance precedente. Le
        # traiter comme un echec ferait boucler la politique sur elle-meme.
        if isinstance(exception, NoResultError):
            return

        retries = int(message.labels.get("_retries", 0)) + 1
        max_retries = int(message.labels.get("max_retries", self._max_retries))
        request_id = message.labels.get(REQUEST_ID_LABEL, "-")

        if retries < max_retries:
            delay = self.compute_delay(retries)
            _LOGGER.warning(
                "Tache %s en echec (execution %d/%d, id %s, request_id %s) : "
                "relance dans %.1f s. %r",
                message.task_name,
                retries,
                max_retries,
                message.task_id,
                request_id,
                delay,
                exception,
            )
            await asyncio.sleep(delay)
            # Meme geste que `SimpleRetryMiddleware` : re-emission sous le MEME
            # `task_id`, labels d'origine conserves (correlation comprise),
            # compteur `_retries` incremente.
            kicker: AsyncKicker[Any, Any] = AsyncKicker(
                task_name=message.task_name,
                broker=self.broker,
                labels=message.labels,
            ).with_task_id(message.task_id)
            kicker.with_labels(_retries=retries)
            await kicker.kiq(*message.args, **message.kwargs)
            # Sans cette ligne, le backend enregistrerait l'echec transitoire
            # et un `wait_result` en cours rendrait l'erreur avant la relance.
            result.error = NoResultError()
            return

        _LOGGER.error(
            "Tache %s epuisee apres %d executions (id %s, request_id %s) : "
            "versee dans la file de rejets %s. %r",
            message.task_name,
            retries,
            message.task_id,
            request_id,
            self._dead_letter_key,
            exception,
        )
        await self._push_dead_letter(message, exception, attempts=retries)

    async def _push_dead_letter(
        self,
        message: TaskiqMessage,
        exception: BaseException,
        *,
        attempts: int,
    ) -> None:
        # Les arguments ont voyage en JSON mais le receiver les a RE-TYPES vers
        # les annotations de la tache (un `group_id: UUID` est redevenu UUID) :
        # `default=str` les ramene a leur forme de fil. Acceptable ici et
        # interdit dans le cache (voir `JsonSerializer`), parce que ce document
        # est un constat d'incident que personne ne desserialise vers des types.
        document = json.dumps(
            {
                "task_id": message.task_id,
                "task_name": message.task_name,
                "args": message.args,
                "kwargs": message.kwargs,
                "labels": message.labels,
                "error": {"type": type(exception).__name__, "message": str(exception)},
                "attempts": attempts,
                "failed_at": datetime.now(tz=UTC).isoformat(),
            },
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        try:
            async with self._client.pipeline(transaction=True) as pipe:
                pipe.lpush(self._dead_letter_key, document)
                # `LTRIM 0, N-1` : on garde les N rejets les plus recents. La
                # borne protege le broker ; les plus anciens tombent, et c'est
                # le compromis assume tant qu'aucun outil d'exploitation ne
                # purge la liste.
                pipe.ltrim(self._dead_letter_key, 0, self._dead_letter_max_length - 1)
                await pipe.execute()
        except _UNREACHABLE as error:
            # Dernier filet : si Redis lui-meme est injoignable, le rejet ne
            # peut aller nulle part ailleurs que dans le journal. Le document
            # est ecrit EN ENTIER, pour que rien ne soit perdu en silence.
            _LOGGER.error(
                "File de rejets injoignable (%s) : le rejet est consigne ici meme. %s",
                error,
                document,
            )
