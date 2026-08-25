"""Port du cache applicatif et son decorateur d'usage (BACK-14).

Le contrat, jamais son adaptateur : ce module ne connait ni Redis, ni FastAPI,
ni la configuration. Il ne peut d'ailleurs pas les connaitre -- le contrat
`domain-purity` de BACK-04b interdit au domaine d'importer une dependance
applicative, `app.core` compris, et il refuse aussi les chaines INDIRECTES.
Consequence directe, qui explique la forme du port : le domaine ne peut ni
composer une cle physique, ni connaitre le TTL par defaut. Les deux appartiennent
a l'adaptateur.

CE QUE LE CACHE EST, ET CE QU'IL N'EST PAS
Un cache est un stockage VOLATILE dont la disparition ne change aucun resultat,
seulement une latence. Tout ce qui suit en decoule : la degradation gracieuse,
l'expiration obligatoire, et l'avertissement de la regle 2 ci-dessous a
l'intention de BACK-10d et BACK-17.
"""

import functools
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from enum import Enum, StrEnum
from hashlib import sha256
from operator import itemgetter
from typing import Concatenate, Final, Protocol, cast

# Ce qui peut entrer dans le cache : l'arbre JSON, et rien d'autre.
#
# La borne est volontairement etroite. Le format de serialisation appartient a
# l'adaptateur (BACK-14 livre JSON, un autre pourra livrer msgpack), mais TOUS
# doivent savoir transporter ce type -- c'est le plus petit denominateur commun
# des formats de cache, et le seul qu'un port puisse promettre.
type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None


class CacheScope(StrEnum):
    """Perimetre d'une entree : liee a un groupe, ou partagee par tout le service.

    Deux valeurs, aucune troisieme, et `TENANT` par defaut partout : l'entree non
    tenant se DECLARE. L'absence de perimetre n'est pas une option -- une cle
    sans groupe lue par une structure et ecrite par une autre, sur des donnees
    medicales, est une fuite et non un defaut d'affichage.
    """

    TENANT = "tenant"
    SHARED = "shared"


class Missing(Enum):
    """Type de la sentinelle d'absence. Un seul membre : `MISSING`."""

    TOKEN = 0


# Absence d'entree, DISTINCTE d'un `None` mis en cache.
#
# Sans cette sentinelle, un cas d'usage qui retourne legitimement `None` -- « ce
# dossier n'existe pas » -- ne serait JAMAIS servi depuis le cache : sa valeur
# mise en cache serait relue comme une absence, et recalculee a chaque appel. Un
# defaut de rendement que rien ne signale, jamais une erreur : exactement le
# genre de bogue qui vit des annees.
#
# Le motif enum plutot qu'un `object()` nu est celui que Mypy sait affiner :
# `if payload is not MISSING:` retire `Missing` de l'union.
MISSING: Final = Missing.TOKEN


class Cache(ABC):
    """Cache applicatif : cle-valeur volatile, expirant, et cloisonne par groupe.

    TROIS REGLES QUI ENGAGENT L'APPELANT

    1. LES CLES RECUES SONT LOGIQUES. L'adaptateur, et lui seul, y appose
       l'environnement et le perimetre. Un appelant ne PEUT donc pas oublier le
       groupe : composer le segment de tenance n'est pas son travail. C'est ce
       qui rend le cloisonnement structurel plutot que conventionnel -- aucun
       motif d'invalidation, si large soit-il, ne peut atteindre un autre groupe.

    2. AUCUNE IMPLEMENTATION NE LEVE QUAND SON STOCKAGE EST INJOIGNABLE.
       `get` rend `MISSING`, `set` et `delete` restent sans effet, `exists` rend
       `False`, `invalidate_pattern` rend `0`. Un cache absent ralentit le
       service, il ne le casse pas.

       CE CONTRAT CONVIENT A UN CACHE ET A RIEN D'AUTRE. Une decision de
       securite lue ici s'ouvrirait toute seule le jour ou le stockage tombe :
       « ce jeton est-il revoque ? » (BACK-10d) rendrait « non », « cet OTP
       a-t-il ete consomme ? » (BACK-17) rendrait « non ». Ces deux tickets
       doivent traiter l'indisponibilite explicitement -- echouer ferme --, pas
       l'heriter d'ici.

    3. TOUTE ENTREE EXPIRE. `ttl=None` signifie « la duree par defaut
       configuree », jamais « pas d'expiration », et un TTL nul ou negatif est
       refuse. La raison est ecrite dans `docker/redis/redis.conf` : l'instance
       est partagee avec la file de taches, et la seule politique d'eviction
       acceptable pour elle -- `volatile-lru` -- ne libere que les cles portant
       un TTL. Une entree eternelle rendrait cette politique inoperante en
       silence.
    """

    @abstractmethod
    async def get(self, key: str, *, scope: CacheScope = CacheScope.TENANT) -> JsonValue | Missing:
        """Lit une valeur, ou rend `MISSING` si elle n'est pas disponible.

        `MISSING` couvre trois cas indistincts et volontairement confondus : cle
        absente, cle expiree, stockage injoignable. Dans les trois, la conduite a
        tenir est la meme -- recalculer.

        Args:
            key: la cle LOGIQUE, sans prefixe d'environnement ni de groupe.
            scope: le perimetre de lecture.

        Returns:
            La valeur relue, ou `MISSING`. Attention : `None` est une VALEUR
            valide, distincte de `MISSING`.

        Raises:
            ValueError: si la cle est vide.
        """

    @abstractmethod
    async def set(
        self,
        key: str,
        value: JsonValue,
        *,
        ttl: int | None = None,
        scope: CacheScope = CacheScope.TENANT,
    ) -> None:
        """Ecrit une valeur, avec une duree de vie toujours posee.

        Args:
            key: la cle logique.
            value: la valeur. Elle doit survivre a un aller-retour dans le format
                de l'adaptateur ; une valeur qui ne s'encode pas n'est pas mise
                en cache, et l'adaptateur le dit plutot que de l'approximer.
            ttl: la duree de vie en secondes. `None` reprend le defaut configure.
            scope: le perimetre d'ecriture.

        Raises:
            ValueError: si la cle est vide, ou si `ttl` n'est pas strictement
                positif -- une entree sans expiration est refusee, pas toleree.
        """

    @abstractmethod
    async def delete(self, key: str, *, scope: CacheScope = CacheScope.TENANT) -> bool:
        """Retire une entree. Ne se plaint pas si elle n'existait pas.

        Args:
            key: la cle logique.
            scope: le perimetre.

        Returns:
            Vrai si une entree a effectivement ete retiree.

        Raises:
            ValueError: si la cle est vide.
        """

    @abstractmethod
    async def exists(self, key: str, *, scope: CacheScope = CacheScope.TENANT) -> bool:
        """Dit si une entree est presente et non expiree.

        Args:
            key: la cle logique.
            scope: le perimetre.

        Returns:
            Vrai si l'entree repond. FAUX AUSSI quand le stockage est
            injoignable : relire la regle 2 de la docstring de classe avant d'en
            faire une condition de securite.

        Raises:
            ValueError: si la cle est vide.
        """

    @abstractmethod
    async def invalidate_pattern(
        self, pattern: str, *, scope: CacheScope = CacheScope.TENANT
    ) -> int:
        """Retire les entrees d'un perimetre correspondant a un motif.

        Le motif s'applique A L'INTERIEUR du perimetre :
        `invalidate_pattern("*")` sous `TENANT` vide le groupe actif, et lui
        seul. Une purge inter-groupes n'est pas exprimable -- c'est une propriete
        de la construction des cles, pas une consigne de prudence.

        Args:
            pattern: le motif, sans prefixe d'environnement ni de groupe. La
                syntaxe est celle des motifs glob (`*`, `?`, `[...]`).
            scope: le perimetre a purger.

        Returns:
            Le nombre d'entrees retirees. Zero si le stockage est injoignable :
            l'invalidation manquee laisse alors des donnees perimees en place
            jusqu'a l'expiration de leur TTL -- c'est precisement pourquoi la
            regle 3 n'admet pas d'exception.

        Raises:
            ValueError: si le motif est vide.
        """


class CacheHolder(Protocol):
    """Ce qu'un cas d'usage doit exposer pour que `@cached` s'y applique.

    Un protocole STRUCTUREL : rien a heriter, rien a enregistrer. Le cas d'usage
    recoit son cache par son constructeur, exactement comme il recoit un depot --
    il n'existe ni registre global, ni contextvar de cache, et c'est ce qui rend
    une doublure en memoire substituable sans rien deposer nulle part.

    Une PROPRIETE en lecture seule et non un attribut : un membre mutable de
    protocole est invariant, et une classe declarant `cache: RedisCache` cesserait
    alors de satisfaire le protocole. Un simple `self.cache = cache` en `__init__`
    suffit a le satisfaire.
    """

    @property
    def cache(self) -> Cache:
        """Le cache dont dispose ce cas d'usage."""
        ...


def cached[**P, S: CacheHolder, J: JsonValue](
    *,
    ttl: int | None = None,
    namespace: str | None = None,
    scope: CacheScope = CacheScope.TENANT,
) -> Callable[
    [Callable[Concatenate[S, P], Awaitable[J]]],
    Callable[Concatenate[S, P], Awaitable[J]],
]:
    """Sert une methode de lecture depuis le cache, et la recalcule a defaut.

    A poser sur une methode de cas d'usage qui LIT. Jamais sur une ecriture : le
    resultat serait memorise et l'effet de bord rejoue ou saute selon l'etat du
    cache.

    LE CACHE VIENT DE `self.cache`, ET MYPY L'EXIGE
    La borne `S: CacheHolder` fait echouer le typage A LA DEFINITION si la classe
    decoree n'expose pas de cache. La question « ou le decorateur trouve-t-il son
    cache, sans requete HTTP ? » est donc tranchee a la compilation, et non par
    une convention que quelqu'un oubliera.

    LE GROUPE N'APPARAIT PAS ICI, ET C'EST VOULU
    Le decorateur vit dans le domaine ; la contextvar de tenance vit dans
    l'infrastructure, ou l'architecture lui interdit d'aller la chercher. C'est
    l'adaptateur qui lit le groupe actif au moment de composer la cle physique --
    ce qui vaut mieux : le decorateur ne peut pas se tromper de groupe puisqu'il
    n'en manipule aucun.

    CE QUE CE DECORATEUR NE FAIT PAS
    Il ne protege pas de l'avalanche (plusieurs appels concurrents manquant la
    meme cle la recalculent tous), et il n'invalide rien -- l'invalidation est du
    cote ECRITURE, par `invalidate_pattern`.

    Args:
        ttl: duree de vie de l'entree, en secondes. `None` reprend le defaut
            configure.
        namespace: prefixe logique de la cle. A defaut, `module:qualname` de la
            methode -- pratique, mais qui change au moindre renommage et vide
            alors le cache existant. Le nommer explicitement est preferable des
            qu'une entree merite de survivre a un refactoring.
        scope: perimetre des entrees produites.

    Returns:
        Le decorateur, a appliquer a une methode asynchrone de lecture.
    """

    def decorate(
        method: Callable[Concatenate[S, P], Awaitable[J]],
    ) -> Callable[Concatenate[S, P], Awaitable[J]]:
        """Enveloppe la methode d'une lecture puis d'une ecriture de cache."""
        label = namespace or f"{method.__module__}:{method.__qualname__}"

        @functools.wraps(method)
        async def wrapper(holder: S, /, *args: P.args, **kwargs: P.kwargs) -> J:
            """Sert l'entree memorisee si elle existe, sinon appelle et memorise."""
            key = f"{label}:{_fingerprint(args, kwargs)}"
            payload = await holder.cache.get(key, scope=scope)
            if payload is not MISSING:
                # `cast` et non une validation : l'adaptateur REFUSE d'ecrire une
                # valeur qui ne survit pas a l'aller-retour de son format, et la
                # borne `J: JsonValue` interdit de decorer une methode dont le
                # retour n'est pas du JSON. Ce qui ressort est donc, par
                # construction, de la forme de ce qui est entre.
                return cast("J", payload)
            result = await method(holder, *args, **kwargs)
            await holder.cache.set(key, result, ttl=ttl, scope=scope)
            return result

        return wrapper

    return decorate


def _fingerprint(args: tuple[object, ...], kwargs: Mapping[str, object]) -> str:
    """Reduit les arguments d'un appel a une empreinte stable et anodine.

    UNE EMPREINTE ET NON LES ARGUMENTS EN CLAIR
    Une cle de cache se lit dans `MONITOR`, dans le `SLOWLOG` et dans la console
    d'inspection. Une cle `…:lire_le_dossier:marie.dupont@exemple.fr` deverserait
    des donnees personnelles dans un outil d'exploitation, ou personne ne les
    cherche et ou personne ne les purge.

    LIMITE A CONNAITRE
    L'empreinte vaut ce que vaut le `repr` des arguments. Les scalaires, les
    `UUID` et les dataclasses gelees -- la forme des commandes et requetes de ce
    service -- ont un `repr` stable. Un objet sans `__repr__` propre y met son
    adresse memoire : la cle changerait a chaque appel, et le cache manquerait
    systematiquement, en silence.

    Args:
        args: les arguments positionnels de l'appel.
        kwargs: ses arguments nommes.

    Returns:
        Une empreinte hexadecimale de 32 caracteres.
    """
    material = f"{args!r}|{sorted(kwargs.items(), key=itemgetter(0))!r}"
    return sha256(material.encode("utf-8")).hexdigest()[:32]
