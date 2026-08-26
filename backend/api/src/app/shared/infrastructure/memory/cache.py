"""Doublure en memoire du port `Cache` (BACK-06c).

Cinq operations, un dictionnaire, et AUCUN Redis. Ce qu'un test observe ici, il
doit l'observer a l'identique contre l'adaptateur reel -- c'est ce que verifie
`tests/shared/conformance/test_cache_conformance.py`, qui joue la meme suite des
deux cotes.

DEUX EMPRUNTS A L'ADAPTATEUR REEL, ET CE SONT LES DEUX QUI COMPTENT
Le compositeur de cles (`CacheKeyBuilder`) et le serialiseur (`JsonSerializer`)
sont les VRAIS, pas des equivalents. Consequence directe et voulue : une doublure
composee sans groupe actif echoue exactement la ou la production echouerait, et
une valeur qui ne survit pas a l'aller-retour JSON est refusee ici comme la-bas.
Reecrire l'un ou l'autre aurait produit une doublure qui prouve sa propre
convention au lieu de celle du service.

C'est aussi ce qui fait passer un tuple pour une liste au retour, comme en
production : la doublure ne rend pas l'objet qu'on lui a confie, elle rend ce
qu'un aller-retour JSON en fait.

L'INDISPONIBILITE EST SIMULABLE, ET IL LE FAUT
`unavailable=True` reproduit la degradation gracieuse du port : `get` rend
`MISSING`, `set` et `delete` restent sans effet, `exists` rend `False`,
`invalidate_pattern` rend `0`. C'est ce qui permet de prouver « si Redis est
arrete, l'application continue de repondre » sans arreter Redis. Les VALIDATIONS,
elles, s'appliquent quand meme -- cle vide ou TTL nul levent avant tout acces au
stockage, cote reel comme ici.

LE TEMPS EST INJECTE. Sans horloge pilotable, prouver qu'une entree expire
demanderait de dormir la duree du TTL.

LES MOTIFS SONT CEUX DE REDIS, PAS CEUX DE `fnmatch`. La distinction a l'air
d'un detail et ne l'est pas : les deux syntaxes s'opposent sur `[^a]` contre
`[!a]`, et le `?` de Redis compte un OCTET la ou celui de `fnmatch` compte un
caractere. `memory/glob.py` porte la semantique de Redis, et la suite de
conformite epingle les quatre cas.
"""

import logging
from typing import Final

from app.core import Settings
from app.shared.domain.ports.cache import MISSING, Cache, CacheScope, JsonValue, Missing
from app.shared.infrastructure.clients.cache_keys import CacheKeyBuilder, build_key_builder
from app.shared.infrastructure.clients.redis_cache import CacheSerializer, JsonSerializer
from app.shared.infrastructure.memory.clock import DEFAULT_CLOCK, Clock
from app.shared.infrastructure.memory.glob import matches

_LOGGER: Final = logging.getLogger(__name__)


class InMemoryCache(Cache):
    """Cache cle-valeur en memoire, expirant et cloisonne par groupe.

    Utile bien au-dela des tests : un poste de developpement sans Redis peut
    ranger cette doublure dans `app.state` et servir toutes les routes, la
    dependance `get_cache` portant deja son `isinstance` sur le PORT et non sur
    `RedisCache`.
    """

    def __init__(
        self,
        keys: CacheKeyBuilder,
        *,
        default_ttl_seconds: int,
        clock: Clock = DEFAULT_CLOCK,
        serializer: CacheSerializer | None = None,
        unavailable: bool = False,
    ) -> None:
        """Assemble la doublure autour du VRAI compositeur de cles.

        Args:
            keys: le compositeur de cles physiques, celui de la production.
            default_ttl_seconds: la duree de vie appliquee quand l'appelant n'en
                donne pas.
            clock: l'horloge des expirations. `FakeClock` pour piloter le temps.
            serializer: le format de transport. `JsonSerializer` par defaut,
                celui de l'adaptateur Redis.
            unavailable: si vrai, la doublure se comporte comme un stockage
                injoignable -- elle degrade, elle ne leve jamais.
        """
        self._keys = keys
        self._default_ttl_seconds = default_ttl_seconds
        self._clock = clock
        self._serializer: CacheSerializer = serializer or JsonSerializer()
        self.unavailable = unavailable
        self._entries: dict[str, tuple[bytes, float]] = {}

    def physical_keys(self) -> list[str]:
        """Rend les cles PHYSIQUES vivantes, triees -- pour les assertions.

        C'est par elle qu'un test prouve le prefixage : la cle logique
        `dossier:42` ecrite sous un groupe doit apparaitre ici en
        `dev:g-{group_id}:dossier:42`.

        Returns:
            Les cles physiques non expirees, dans l'ordre alphabetique.
        """
        now = self._clock()
        return sorted(key for key, (_, expires_at) in self._entries.items() if expires_at > now)

    async def get(self, key: str, *, scope: CacheScope = CacheScope.TENANT) -> JsonValue | Missing:
        """Lit une valeur, ou rend `MISSING`. Voir le port pour le contrat."""
        physical = self._keys.key(key, scope)
        if self.unavailable:
            self._report("lecture")
            return MISSING
        entry = self._entries.get(physical)
        if entry is None:
            return MISSING
        payload, expires_at = entry
        if expires_at <= self._clock():
            # Expiree : indistincte d'une cle absente, exactement comme cote
            # Redis, ou c'est le TTL qui a fait disparaitre la cle.
            del self._entries[physical]
            return MISSING
        return self._serializer.loads(payload)

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
        # L'encodage precede la sortie sur indisponibilite, dans le meme ordre que
        # l'adaptateur reel : une valeur non serialisable est un defaut de
        # programmation, et il doit remonter que le stockage reponde ou non.
        payload = self._serializer.dumps(value)
        if self.unavailable:
            self._report("ecriture")
            return
        self._entries[physical] = (payload, self._clock() + ttl_seconds)

    async def delete(self, key: str, *, scope: CacheScope = CacheScope.TENANT) -> bool:
        """Retire une entree. Voir le port pour le contrat."""
        physical = self._keys.key(key, scope)
        if self.unavailable:
            self._report("suppression")
            return False
        # Une entree expiree n'est plus la pour Redis : la retirer ne doit pas
        # rendre vrai.
        alive = self._alive(physical)
        self._entries.pop(physical, None)
        return alive

    async def exists(self, key: str, *, scope: CacheScope = CacheScope.TENANT) -> bool:
        """Dit si une entree repond. Voir le port pour le contrat."""
        physical = self._keys.key(key, scope)
        if self.unavailable:
            self._report("presence")
            return False
        return self._alive(physical)

    async def invalidate_pattern(
        self, pattern: str, *, scope: CacheScope = CacheScope.TENANT
    ) -> int:
        """Purge un perimetre par motif. Voir le port pour le contrat."""
        physical = self._keys.pattern(pattern, scope)
        if self.unavailable:
            self._report("invalidation")
            return 0
        targeted = [key for key in self.physical_keys() if matches(physical, key)]
        for key in targeted:
            del self._entries[key]
        return len(targeted)

    async def ping(self) -> bool:
        """Dit si la doublure repond, sans jamais lever.

        Presente pour satisfaire le protocole `SupportsPing` de la sonde de
        disponibilite : ranger cette doublure dans `app.state` ne doit pas faire
        echouer `GET /health/ready`.

        Returns:
            Faux seulement quand l'indisponibilite est simulee.
        """
        return not self.unavailable

    def _alive(self, physical: str) -> bool:
        """Dit si une cle physique est presente ET non expiree.

        Args:
            physical: la cle physique, deja composee.

        Returns:
            Vrai si l'entree repondrait a une lecture.
        """
        entry = self._entries.get(physical)
        return entry is not None and entry[1] > self._clock()

    def _report(self, operation: str) -> None:
        """Journalise la degradation, comme le fait l'adaptateur reel.

        Args:
            operation: le geste qui n'a pas pu aboutir.
        """
        _LOGGER.warning("Cache en memoire simule indisponible : %s ignoree.", operation)


def build_in_memory_cache(settings: Settings, *, clock: Clock = DEFAULT_CLOCK) -> InMemoryCache:
    """Construit la doublure a partir de la configuration du service.

    Meme forme et meme signature que `build_cache` (BACK-14) : c'est ce qui rend
    la substitution possible dans un `lifespan` de test sans rien reecrire, et ce
    qui garantit que la doublure porte le MEME environnement dans ses cles et le
    MEME TTL par defaut que la production.

    Args:
        settings: la configuration du service, dont l'environnement et le TTL.
        clock: l'horloge des expirations.

    Returns:
        La doublure, prete a etre rangee dans `app.state`.
    """
    return InMemoryCache(
        build_key_builder(settings),
        default_ttl_seconds=settings.redis.cache_ttl_seconds,
        clock=clock,
    )
