"""Conformite du cache : Redis et la doublure en memoire (BACK-06c).

Une seule suite, deux sujets. `TestRedisCacheConformance` la joue contre le Redis
du poste, `TestInMemoryCacheConformance` contre `InMemoryCache`. Ce qui est
compare n'est pas « ca marche des deux cotes » mais le CONTRAT du port : la
sentinelle d'absence distincte d'un `None` mis en cache, le refus d'une entree
sans expiration, le cloisonnement par groupe, et l'aller-retour de serialisation.

LA SYNTAXE DES MOTIFS EST EPINGLEE, ET ELLE LE DOIT. Redis et `fnmatch` se
ressemblent puis divergent sur quatre points, dont une inversion complete
(`[^a]` contre `[!a]`) : quatre tests plus bas les fixent, et c'est ce qui
justifie le portage de `memory/glob.py` plutot qu'un `fnmatch` qui « marchait ».

CE QUE LA SUITE NE COUVRE PAS, ET POURQUOI
La degradation gracieuse. Elle se simule d'un cote (`unavailable=True`) et
demanderait d'arreter Redis de l'autre : elle est donc eprouvee sur la seule
doublure, dans `tests/shared/memory/`. Ce qui est verifie ici est que les deux
cotes VALIDENT avant de toucher au stockage -- ce qui est la moitie du contrat
qu'une panne ne doit justement pas relacher.

LES CLES SONT TIREES AU HASARD A CHAQUE TEST, ET AUCUN `FLUSHDB` N'EST EMIS :
l'instance est partagee avec la file de taches. Les entrees portent des TTL
courts et disparaissent d'elles-memes.
"""

import asyncio
from collections.abc import AsyncIterator, Iterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from app.core import get_settings
from app.shared.domain.ports.cache import MISSING, Cache, CacheScope
from app.shared.infrastructure.clients.redis_cache import build_cache
from app.shared.infrastructure.memory.cache import build_in_memory_cache
from app.shared.infrastructure.tenancy import MissingTenantContextError, use_group

pytestmark = pytest.mark.conformance

# TTL des entrees de conformite. Assez long pour qu'aucun test ne coure apres son
# horloge, assez court pour que rien ne traine dans l'instance partagee.
_TTL = 30


def a_key(label: str) -> str:
    """Une cle logique unique, pour que deux executions ne se croisent jamais."""
    return f"conformance:{label}:{uuid4()}"


class CacheConformance:
    """La suite commune. Les sous-classes ne fournissent que la fixture `cache`."""

    @pytest.fixture
    def cache(self) -> Cache:
        """Le sujet sous test -- fourni par la sous-classe."""
        raise NotImplementedError

    async def test_a_value_survives_the_round_trip(self, cache: Cache, group_a: UUID) -> None:
        key = a_key("dossier")
        with use_group(group_a):
            await cache.set(key, {"note": "vu"}, ttl=_TTL)
            assert await cache.get(key) == {"note": "vu"}

    async def test_an_absent_key_is_missing(self, cache: Cache, group_a: UUID) -> None:
        with use_group(group_a):
            assert await cache.get(a_key("jamais ecrite")) is MISSING

    async def test_a_cached_none_is_distinct_from_an_absence(
        self, cache: Cache, group_a: UUID
    ) -> None:
        """LA sentinelle. Sans elle, « ce dossier n'existe pas » ne serait jamais servi."""
        key = a_key("resultat nul")
        with use_group(group_a):
            await cache.set(key, None, ttl=_TTL)
            relu = await cache.get(key)
        assert relu is None
        assert relu is not MISSING

    async def test_exists_follows_set_then_delete(self, cache: Cache, group_a: UUID) -> None:
        key = a_key("presence")
        with use_group(group_a):
            assert await cache.exists(key) is False
            await cache.set(key, 1, ttl=_TTL)
            assert await cache.exists(key) is True
            assert await cache.delete(key) is True
            assert await cache.exists(key) is False

    async def test_deleting_an_absent_key_reports_false(self, cache: Cache, group_a: UUID) -> None:
        with use_group(group_a):
            assert await cache.delete(a_key("deja partie")) is False

    async def test_an_empty_key_is_refused(self, cache: Cache, group_a: UUID) -> None:
        with use_group(group_a), pytest.raises(ValueError, match="vide"):
            await cache.get("")

    async def test_a_non_positive_ttl_is_refused(self, cache: Cache, group_a: UUID) -> None:
        """Toute entree expire : un TTL nul est refuse, pas tolere."""
        with use_group(group_a), pytest.raises(ValueError, match="strictement positif"):
            await cache.set(a_key("eternelle"), 1, ttl=0)

    async def test_a_value_that_does_not_serialise_is_refused(
        self, cache: Cache, group_a: UUID
    ) -> None:
        """Une valeur non serialisable echoue A L'ECRITURE, la ou elle se corrige."""
        with use_group(group_a), pytest.raises(TypeError):
            await cache.set(a_key("uuid nu"), uuid4())  # type: ignore[arg-type]

    async def test_a_tuple_comes_back_as_a_list(self, cache: Cache, group_a: UUID) -> None:
        """Ce qui ressort est ce qu'un aller-retour JSON fait de ce qui est entre."""
        key = a_key("couple")
        with use_group(group_a):
            await cache.set(key, (1, 2), ttl=_TTL)  # type: ignore[arg-type]
            assert await cache.get(key) == [1, 2]

    async def test_a_tenant_entry_is_invisible_to_another_group(
        self, cache: Cache, group_a: UUID, group_b: UUID
    ) -> None:
        """LE cloisonnement : un remplacant qui change de structure change de segment."""
        key = a_key("dossier partage par erreur")
        with use_group(group_a):
            await cache.set(key, "vu par A", ttl=_TTL)
        with use_group(group_b):
            assert await cache.get(key) is MISSING

    async def test_a_shared_entry_crosses_groups(
        self, cache: Cache, group_a: UUID, group_b: UUID
    ) -> None:
        """Le hors-norme se declare : `SHARED` est ecrit, jamais omis."""
        key = a_key("catalogue")
        with use_group(group_a):
            await cache.set(key, "commun", ttl=_TTL, scope=CacheScope.SHARED)
        with use_group(group_b):
            assert await cache.get(key, scope=CacheScope.SHARED) == "commun"

    async def test_a_tenant_key_without_a_group_is_refused(self, cache: Cache) -> None:
        with pytest.raises(MissingTenantContextError):
            await cache.get(a_key("hors contexte"))

    async def test_a_shared_key_needs_no_group(self, cache: Cache) -> None:
        key = a_key("hors tenance")
        await cache.set(key, "sans groupe", ttl=_TTL, scope=CacheScope.SHARED)
        assert await cache.get(key, scope=CacheScope.SHARED) == "sans groupe"

    async def test_invalidation_stays_inside_its_own_group(
        self, cache: Cache, group_a: UUID, group_b: UUID
    ) -> None:
        """Une purge inter-groupes n'est pas exprimable, si large soit le motif."""
        marker = uuid4()
        key = f"conformance:liste:{marker}"
        with use_group(group_a):
            await cache.set(key, "chez A", ttl=_TTL)
        with use_group(group_b):
            await cache.set(key, "chez B", ttl=_TTL)
            assert await cache.invalidate_pattern(f"conformance:liste:{marker}*") == 1
            assert await cache.get(key) is MISSING
        with use_group(group_a):
            assert await cache.get(key) == "chez A"

    async def test_invalidation_of_a_pattern_matching_nothing_reports_zero(
        self, cache: Cache, group_a: UUID
    ) -> None:
        with use_group(group_a):
            assert await cache.invalidate_pattern(f"conformance:vide:{uuid4()}:*") == 0

    async def test_a_negated_class_follows_the_redis_syntax(
        self, cache: Cache, group_a: UUID
    ) -> None:
        """`[^x]` nie, `[!x]` est litteral -- et `fnmatch` fait exactement l'inverse.

        LE CAS LE PLUS DANGEREUX DES QUATRE : selon la syntaxe employee, une purge
        efface tout d'un cote et rien de l'autre. Un test qui ne l'epingle pas
        laisse croire qu'une invalidation a eu lieu.
        """
        marker = uuid4().hex[:8]
        with use_group(group_a):
            await cache.set(f"conf:{marker}:b", 1, ttl=_TTL)
            await cache.set(f"conf:{marker}:!", 1, ttl=_TTL)
            # `[^!]` NIE : il retire « b » et laisse « ! ». Sous `fnmatch`, le
            # meme motif serait la classe litterale {^, !} et retirerait « ! ».
            assert await cache.invalidate_pattern(f"conf:{marker}:[^!]") == 1
            assert await cache.get(f"conf:{marker}:b") is MISSING
            assert await cache.get(f"conf:{marker}:!") == 1
            # `[!b]` est LITTERAL : la classe {!, b}, dont seul « ! » subsiste.
            assert await cache.invalidate_pattern(f"conf:{marker}:[!b]") == 1
            assert await cache.get(f"conf:{marker}:!") is MISSING

    async def test_a_backslash_escapes_a_wildcard(self, cache: Cache, group_a: UUID) -> None:
        """Un `*` echappe vise l'asterisque litteral, pas n'importe quelle suite."""
        marker = uuid4().hex[:8]
        with use_group(group_a):
            await cache.set(f"conf:{marker}:a*b", 1, ttl=_TTL)
            await cache.set(f"conf:{marker}:axb", 1, ttl=_TTL)
            assert await cache.invalidate_pattern(f"conf:{marker}:a\\*b") == 1
            assert await cache.get(f"conf:{marker}:a*b") is MISSING
            assert await cache.get(f"conf:{marker}:axb") == 1

    async def test_an_unclosed_class_stays_a_class(self, cache: Cache, group_a: UUID) -> None:
        """Un crochet non referme ne rend pas le motif invalide : il se referme tout seul."""
        marker = uuid4().hex[:8]
        with use_group(group_a):
            await cache.set(f"conf:{marker}:a", 1, ttl=_TTL)
            await cache.set(f"conf:{marker}:z", 1, ttl=_TTL)
            assert await cache.invalidate_pattern(f"conf:{marker}:[abc") == 1
            assert await cache.get(f"conf:{marker}:a") is MISSING
            assert await cache.get(f"conf:{marker}:z") == 1

    async def test_a_question_mark_matches_one_byte_not_one_character(
        self, cache: Cache, group_a: UUID
    ) -> None:
        """LE `?` COMPTE UN OCTET, et ce n'est pas un cas de laboratoire ici.

        Le service est francophone : une seule cle accentuee suffit a faire
        diverger n'importe quel motif a `?` entre Redis et un moteur qui compterait
        des caracteres.
        """
        marker = uuid4().hex[:8]
        with use_group(group_a):
            await cache.set(f"conf:{marker}:e", 1, ttl=_TTL)
            await cache.set(f"conf:{marker}:\u00e9", 1, ttl=_TTL)
            assert await cache.invalidate_pattern(f"conf:{marker}:?") == 1
            assert await cache.get(f"conf:{marker}:e") is MISSING
            assert await cache.get(f"conf:{marker}:\u00e9") == 1
            assert await cache.invalidate_pattern(f"conf:{marker}:??") == 1
            assert await cache.get(f"conf:{marker}:\u00e9") is MISSING

    async def test_an_empty_pattern_is_refused(self, cache: Cache, group_a: UUID) -> None:
        with use_group(group_a), pytest.raises(ValueError, match="vide"):
            await cache.invalidate_pattern("")

    async def test_an_entry_expires_on_its_own(self, cache: Cache, group_a: UUID) -> None:
        """LE SEUL TEST QUI DORT de toute la suite, et il ne peut pas faire autrement.

        Piloter l'horloge ne vaut que pour la doublure ; le TTL de l'autre moitie
        est tenu par Redis, qui n'a pas d'horloge injectable. Une seconde de TTL et
        une attente courte est le prix de la seule preuve qui vaille des deux
        cotes : que l'entree disparait sans que personne la supprime.
        """
        key = a_key("ephemere")
        with use_group(group_a):
            await cache.set(key, "bientot partie", ttl=1)
            await asyncio.sleep(1.2)
            assert await cache.get(key) is MISSING
            assert await cache.exists(key) is False


class TestRedisCacheConformance(CacheConformance):
    """La suite, jouee contre le Redis du poste."""

    @pytest_asyncio.fixture
    async def cache(self) -> AsyncIterator[Cache]:
        """Cache Redis reel, ou test ignore si l'instance ne repond pas."""
        opened = build_cache(get_settings())
        if not await opened.ping():
            await opened.aclose()
            pytest.skip("Redis n'est pas joignable : `make up` a la racine (INFRA-02).")
        yield opened
        await opened.aclose()


class TestInMemoryCacheConformance(CacheConformance):
    """La MEME suite, jouee contre `InMemoryCache`."""

    @pytest.fixture
    def cache(self) -> Iterator[Cache]:
        """Doublure construite comme la production, depuis la meme configuration.

        `build_in_memory_cache` et non un constructeur nu : la doublure porte
        ainsi le MEME segment d'environnement et le MEME TTL par defaut, si bien
        que les deux moities comparent la meme convention de cles.
        """
        yield build_in_memory_cache(get_settings())
