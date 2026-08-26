"""Adaptateur Redis du port `Cache`, et son cycle de vie (BACK-14).

Le pool vit aussi longtemps que le processus : il est cree une fois par le
`lifespan` et referme par lui. Rien ici ne s'ouvre a l'import.

UNE FONCTION DE `Settings`, ET NON UN LECTEUR DE CONFIGURATION
`build_cache` recoit sa configuration en argument, pour la raison deja ecrite
dans `db/engine.py` : `get_settings()` est mise en cache par `lru_cache`, et un
constructeur qui l'appellerait de l'interieur ne saurait pas fabriquer un client
different de celui du processus. Le worker TaskIQ (BACK-15) et les fixtures de
BACK-12 auront besoin du leur.

L'ASYMETRIE AVEC POSTGRESQL EST LE SUJET, PAS UN OUBLI
BACK-05 livre `verify_connectivity`, qui LEVE et arrete le processus. Il n'existe
volontairement pas d'equivalent ici, ni de `CacheUnavailableError` : sans base de
donnees aucune route ne peut repondre juste, tandis que sans cache toutes
repondent, plus lentement. Traiter les deux pareil ferait d'une optimisation une
dependance dure -- et rendrait inatteignable le critere « si Redis est arrete,
l'application continue de repondre ». `RedisCache.ping()` sonde quand meme, et se
contente de journaliser.

LA BASE 0, ET ELLE SEULE
`settings.redis.cache_url` pointe `REDIS_CACHE_DB`. La base 1 appartient au
broker TaskIQ (BACK-15) : purger le cache ne doit jamais vider la file de taches,
et c'est la convention posee par INFRA-02.
"""

import json
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Final, Protocol, cast

from fastapi import Request
from redis.asyncio import ConnectionPool, Redis
from redis.backoff import NoBackoff
from redis.exceptions import RedisError
from redis.retry import Retry

from app.core import Settings
from app.shared.domain.ports.cache import MISSING, Cache, CacheScope, JsonValue, Missing
from app.shared.infrastructure.clients.cache_keys import CacheKeyBuilder, build_key_builder

_LOGGER: Final = logging.getLogger(__name__)

# Cle unique sous laquelle le `lifespan` range le cache dans `app.state`. Meme
# forme que `STATE_KEY` du socle de persistance : une constante, pas un litteral.
CACHE_STATE_KEY: Final = "cache"

# Delais d'etablissement et de commande. Deux secondes et non les cinq de la
# bibliotheque : ce delai est ce que paie une requete HTTP quand Redis absorbe
# les paquets sans repondre -- un pare-feu en `DROP`, une machine en cours
# d'arret. Un cache ne doit jamais couter plus cher que ce qu'il evite.
#
# Des constantes de module et non des reglages, comme `_CONNECT_TIMEOUT_SECONDS`
# dans `db/engine.py` : chaque variable de configuration coute deux gabarits
# `.env.example`, une ligne de compose et une ligne de documentation.
_CONNECT_TIMEOUT_SECONDS: Final = 2.0
_COMMAND_TIMEOUT_SECONDS: Final = 2.0

# Taille des lots du parcours de cles et des suppressions. Compromis entre le
# nombre d'allers-retours et la duree d'une seule commande : Redis est
# mono-thread, une commande geante le bloque autant qu'un `KEYS`.
_SCAN_COUNT: Final = 500
_UNLINK_BATCH: Final = 500

# Ce qu'il faut attraper pour dire « Redis est injoignable ».
#
# `RedisError` couvre `ConnectionError`, `TimeoutError` et `MaxConnectionsError`,
# qui en heritent tous. `OSError` n'est pas redondant : verifie, la
# `ConnectionError` de redis-py n'herite PAS de l'`OSError` integre, et une
# resolution DNS en echec (`socket.gaierror`) peut remonter telle quelle. Meme
# raisonnement que le `_UNREACHABLE` de `db/engine.py`.
_UNREACHABLE: Final = (OSError, RedisError)


class CacheSerializer(Protocol):
    """Format de transport des valeurs : le point d'extension du ticket.

    Le protocole travaille sur des `bytes` et non sur des `str`, ce qui est la
    raison d'etre du `decode_responses=False` pose sur le pool. Avec un decodage
    cote client, le point d'extension ne porterait que sur des formats TEXTE --
    or les candidats reels du jour ou une liste de consultations pesera 200 ko
    sont msgpack et le JSON compresse, tous deux binaires.
    """

    def dumps(self, value: JsonValue, /) -> bytes:
        """Encode une valeur pour le stockage."""
        ...

    def loads(self, payload: bytes, /) -> JsonValue:
        """Decode une valeur relue du stockage."""
        ...


@dataclass(frozen=True, slots=True)
class JsonSerializer:
    """Format par defaut : JSON compact, UTF-8.

    AUCUN `default=` SUR `json.dumps`, ET C'EST LE POINT IMPORTANT
    Un `default=str` ferait entrer un `UUID` et ressortir une `str`. L'ecart
    n'apparaitrait qu'au premier SUCCES de cache -- c'est-a-dire en production,
    sous charge, et jamais dans une sonde. Une valeur non serialisable echoue
    donc a l'ecriture, bruyamment, la ou le defaut se corrige.

    Jamais `pickle` : desserialiser du pickle depuis une instance Redis sans mot
    de passe est une execution de code arbitraire, pas un choix de format.
    """

    def dumps(self, value: JsonValue, /) -> bytes:
        """Encode en JSON compact.

        Args:
            value: la valeur a encoder.

        Returns:
            Sa representation JSON en UTF-8.

        Raises:
            TypeError: si la valeur ne se serialise pas en JSON.
        """
        return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def loads(self, payload: bytes, /) -> JsonValue:
        """Decode une charge utile JSON.

        Args:
            payload: les octets relus du stockage.

        Returns:
            La valeur reconstituee.

        Raises:
            ValueError: si la charge utile n'est pas du JSON valide.
        """
        return cast("JsonValue", json.loads(payload))


class RedisCache(Cache):
    """Cache adosse a Redis, degradant en silence quand le serveur ne repond pas.

    Un drapeau, pas un compteur : l'avertissement part UNE FOIS a la chute et une
    fois a la reprise. Sans cela, une coupure de dix minutes ecrit un
    avertissement par appel et noie le journal -- et un journal noye est un
    journal que personne ne lit.

    LIMITE ASSUMEE : il n'y a pas de fenetre de circuit ouvert. Chaque appel
    retente sa connexion pendant la panne. Sur un refus de connexion l'echec est
    immediat ; sur un hote qui absorbe les paquets, chaque appel paie
    `_CONNECT_TIMEOUT_SECONDS`. Le service repond toujours, mais plus lentement.
    """

    def __init__(
        self,
        *,
        client: Redis,
        pool: ConnectionPool,
        keys: CacheKeyBuilder,
        default_ttl_seconds: int,
        target: str,
        serializer: CacheSerializer | None = None,
    ) -> None:
        """Assemble l'adaptateur autour d'un client deja construit.

        Args:
            client: le client asynchrone, adosse au pool ci-dessous.
            pool: le pool de connexions, a fermer explicitement a l'arret.
            keys: le compositeur de cles physiques.
            default_ttl_seconds: duree de vie appliquee quand l'appelant n'en
                donne pas.
            target: hote, port et base, pour les messages. JAMAIS l'URL, qui
                porte le mot de passe en clair.
            serializer: format de transport. JSON par defaut.
        """
        self._client = client
        self._pool = pool
        self._keys = keys
        self._default_ttl_seconds = default_ttl_seconds
        self._target = target
        self._serializer: CacheSerializer = JsonSerializer() if serializer is None else serializer
        self._degraded = False
        self._announced = False

    @property
    def target(self) -> str:
        """Hote, port et base vises, tels qu'ils apparaissent dans les messages."""
        return self._target

    async def get(self, key: str, *, scope: CacheScope = CacheScope.TENANT) -> JsonValue | Missing:
        """Lit une valeur, ou rend `MISSING`. Voir le port pour le contrat."""
        physical = self._keys.key(key, scope)
        try:
            raw = await self._client.get(physical)
        except _UNREACHABLE as error:
            self._report("lecture", error)
            return MISSING
        self._recover()
        if not isinstance(raw, bytes):
            return MISSING
        try:
            return self._serializer.loads(raw)
        except ValueError:
            # `UnicodeDecodeError` et `JSONDecodeError` heritent tous deux de
            # `ValueError` : une seule clause couvre les octets illisibles comme
            # le JSON malforme.
            # Entree illisible : un format qui a change entre deux versions du
            # service. On la traite comme absente plutot que de faire echouer la
            # lecture -- un cache chaud ne doit jamais produire une erreur qu'un
            # cache froid n'aurait pas produite.
            _LOGGER.warning("Entree de cache illisible, ignoree : %s", physical)
            return MISSING

    async def set(
        self,
        key: str,
        value: JsonValue,
        *,
        ttl: int | None = None,
        scope: CacheScope = CacheScope.TENANT,
    ) -> None:
        """Ecrit une valeur avec expiration. Voir le port pour le contrat."""
        physical = self._keys.key(key, scope)
        ttl_seconds = self._default_ttl_seconds if ttl is None else ttl
        if ttl_seconds <= 0:
            message = (
                f"Un TTL de cache doit etre strictement positif, recu {ttl_seconds} : "
                "une entree sans expiration romprait la politique d'eviction de "
                "l'instance, partagee avec la file de taches."
            )
            raise ValueError(message)
        # L'encodage precede le try : une valeur non serialisable est un defaut
        # de programmation, pas une panne, et doit remonter comme tel.
        payload = self._serializer.dumps(value)
        try:
            # `ex=` TOUJOURS transmis : c'est ce qui rend chaque entree eligible a
            # `volatile-lru` et laisse les cles de TaskIQ hors d'atteinte.
            await self._client.set(physical, payload, ex=ttl_seconds)
        except _UNREACHABLE as error:
            self._report("ecriture", error)
            return
        self._recover()

    async def delete(self, key: str, *, scope: CacheScope = CacheScope.TENANT) -> bool:
        """Retire une entree. Voir le port pour le contrat."""
        physical = self._keys.key(key, scope)
        try:
            removed = int(await self._client.unlink(physical))
        except _UNREACHABLE as error:
            self._report("suppression", error)
            return False
        self._recover()
        return removed > 0

    async def exists(self, key: str, *, scope: CacheScope = CacheScope.TENANT) -> bool:
        """Dit si une entree repond. Voir le port pour le contrat."""
        physical = self._keys.key(key, scope)
        try:
            found = int(await self._client.exists(physical))
        except _UNREACHABLE as error:
            self._report("presence", error)
            return False
        self._recover()
        return found > 0

    async def invalidate_pattern(
        self, pattern: str, *, scope: CacheScope = CacheScope.TENANT
    ) -> int:
        """Purge un perimetre par motif. Voir le port pour le contrat.

        SCAN ET NON KEYS
        `KEYS` parcourt tout l'espace de cles en UNE commande, et Redis est
        mono-thread : pendant ce parcours l'instance ne sert plus personne. Or le
        compose fait cohabiter le cache (base 0) et le broker TaskIQ (base 1)
        dans le meme processus -- un `KEYS` lance pour invalider un dossier
        medical suspendrait la distribution des taches de fond. `SCAN` rend la
        main entre deux iterations.

        Ce que `SCAN` coute, et qu'il faut savoir : le motif est applique par le
        serveur APRES extraction, donc le cout est proportionnel a la taille de
        la base et non au nombre de cles effacees. C'est une operation du cote
        ECRITURE, jamais un appel par requete de lecture.

        `UNLINK` et non `DEL` : la liberation memoire part dans un thread annexe
        cote serveur, ce qui compte sur une purge de plusieurs milliers de cles.
        """
        physical = self._keys.pattern(pattern, scope)
        removed = 0
        batch: list[bytes] = []
        try:
            async for found in self._client.scan_iter(match=physical, count=_SCAN_COUNT):
                # `decode_responses=False` : le curseur rend des octets, qu'on
                # repasse tels quels a UNLINK. Aucun decodage sur une cle qu'on
                # ne fait qu'effacer.
                batch.append(found)
                if len(batch) >= _UNLINK_BATCH:
                    removed += int(await self._client.unlink(*batch))
                    batch.clear()
            if batch:
                removed += int(await self._client.unlink(*batch))
        except _UNREACHABLE as error:
            self._report("invalidation", error)
            return removed
        self._recover()
        return removed

    async def ping(self) -> bool:
        """Sonde le serveur, sans jamais lever.

        Le pendant de `verify_connectivity` (BACK-05) et son contraire assume :
        celle-la leve, celle-ci journalise. Elle ouvre aussi la premiere
        connexion du pool, ce qui rend le client visible dans `CLIENT LIST` --
        c'est ce qui permet de VERIFIER que le pool naît et meurt avec le
        processus, au lieu de le lire dans le code.

        Deux appelants depuis BACK-08 : le `lifespan` au demarrage, puis la
        sonde de disponibilite `/health/ready`, PERIODIQUEMENT. D'ou l'INFO de
        joignabilite emise au premier succes seulement : un sondage toutes les
        dix secondes n'ecrira pas une ligne par appel, et la reprise apres une
        panne est deja annoncee par `_recover`.

        Returns:
            Vrai si Redis a repondu au PING.
        """
        try:
            await self._client.ping()
        except _UNREACHABLE as error:
            self._report("sonde", error)
            return False
        self._recover()
        if not self._announced:
            self._announced = True
            _LOGGER.info("Cache Redis joignable sur %s.", self._target)
        return True

    async def aclose(self) -> None:
        """Ferme le client PUIS le pool, sans jamais lever.

        Les deux, et dans cet ordre : `Redis(connection_pool=...)` ne prend pas
        possession d'un pool qu'il n'a pas cree, donc fermer le seul client
        laisserait les connexions ouvertes.

        Le `suppress` n'est pas de la superstition. Cette methode est appelee
        depuis le `finally` du `lifespan` ; une exception levee ici sauterait le
        `engine.dispose()` qui suit et ferait fuir le pool PostgreSQL a chaque
        redemarrage de conteneur.
        """
        with suppress(*_UNREACHABLE):
            await self._client.aclose()
        with suppress(*_UNREACHABLE):
            await self._pool.aclose()

    def _report(self, operation: str, error: Exception) -> None:
        """Annonce la premiere chute, et se tait pour les suivantes."""
        if self._degraded:
            return
        self._degraded = True
        _LOGGER.warning(
            "Cache Redis injoignable sur %s (%s) : le service continue SANS cache. %s",
            self._target,
            operation,
            error,
        )

    def _recover(self) -> None:
        """Annonce la reprise, une seule fois."""
        if not self._degraded:
            return
        self._degraded = False
        # INFO, et c'est BACK-11 qui l'a rendu possible : la reprise est une
        # bonne nouvelle, pas un avertissement. Elle etait en WARNING tant
        # qu'aucune journalisation n'etait configuree, parce que le `lastResort`
        # de la bibliotheque standard ne relaie QUE les WARNING et au-dela -- une
        # panne dont on ne voit pas la fin se lit comme une panne qui dure.
        _LOGGER.info("Cache Redis de nouveau joignable sur %s.", self._target)


def build_cache(settings: Settings) -> RedisCache:
    """Construit le cache et son pool, sans ouvrir la moindre connexion.

    Comme `build_engine`, construire ne connecte pas : la premiere connexion nait
    au premier emprunt, et c'est `ping()` qui la provoque au moment choisi par le
    `lifespan`.

    Args:
        settings: la configuration du service, dont la section Redis.

    Returns:
        Le cache, pret a etre range dans `app.state`.
    """
    pool = ConnectionPool.from_url(
        settings.redis.cache_url,
        # Le serialiseur possede l'encodage : voir `CacheSerializer`.
        decode_responses=False,
        socket_connect_timeout=_CONNECT_TIMEOUT_SECONDS,
        socket_timeout=_COMMAND_TIMEOUT_SECONDS,
        # EPINGLAGE DEFENSIF, et non une redite du defaut. Verifie dans redis
        # 8.1 : un pool construit a la main herite de `Retry(NoBackoff(), 0)`,
        # mais `Redis(host=...)` herite de dix tentatives avec repli exponentiel
        # -- soit plusieurs secondes par appel pendant une panne. L'ecrire rend
        # le comportement independant du constructeur employe, et borne a zero le
        # surcout d'un cache injoignable.
        retry=Retry(NoBackoff(), retries=0),
        # Pendant exact de l'`application_name` pose sur PostgreSQL par BACK-05 :
        # sans lui, les connexions sont anonymes dans `CLIENT LIST` et rien ne
        # distingue l'API du worker TaskIQ le jour ou il faut comprendre qui
        # occupe l'instance.
        client_name=f"juui-api-cache/{settings.app.environment}",
    )
    return RedisCache(
        client=Redis(connection_pool=pool),
        pool=pool,
        keys=build_key_builder(settings),
        default_ttl_seconds=settings.redis.cache_ttl_seconds,
        # Les composants, JAMAIS `cache_url` : cette propriete porte le mot de
        # passe en clair, et un message d'erreur finit toujours recopie quelque
        # part. Meme regle qu'en BACK-05.
        target=f"{settings.redis.host}:{settings.redis.port} (base {settings.redis.cache_db})",
    )


def get_cache(request: Request) -> Cache:
    """Retourne le cache ouvert par le `lifespan`.

    Meme forme que `get_database` (BACK-05) : une cle, un type, un accesseur.
    L'`isinstance` porte sur le PORT et non sur `RedisCache` -- c'est ce qui
    laisse `InMemoryCache` (BACK-06c) se ranger dans `app.state` sans
    toucher a ce fichier. Il est de toute facon obligatoire : `app.state` est
    type `Any`, et Mypy strict refuse d'en retourner la valeur telle quelle.

    Args:
        request: la requete en cours, d'ou l'on remonte a l'application.

    Returns:
        Le cache du processus.

    Raises:
        RuntimeError: si le `lifespan` n'a pas tourne.
    """
    cache = getattr(request.app.state, CACHE_STATE_KEY, None)
    if not isinstance(cache, Cache):
        message = (
            "Le cache n'est pas ouvert : l'application a-t-elle ete construite sans son lifespan ?"
        )
        raise RuntimeError(message)
    return cache
