---
title: Cache
description: 'Le port de cache Redis : clé par environnement et groupe, dégradation gracieuse et décorateur @cached.'
---

# Cache

Redis vu du domaine à travers un port unique — cinq opérations asynchrones, des clés préfixées par
environnement et par groupe, et une dégradation gracieuse quand l'instance tombe. Cette page décrit
le contrat, l'adaptateur qui le tient, et les sondes qui le prouvent.

Redis sert de cache applicatif sur la **base 0** ; la base 1 appartient au broker TaskIQ
(BACK-15), et la séparation est une exigence d'INFRA-02 — purger le cache ne doit jamais vider la
file de tâches.

Le domaine ne connaît que le port `Cache`. L'adaptateur Redis, la composition des clés et la
configuration vivent dans `shared/infrastructure/` : le contrat `domain-purity` interdit au domaine
d'importer une dépendance applicative, et il refuse aussi les chaînes **indirectes** — un port ne
peut donc pas même importer `app.core`, qui importe pydantic. C'est cette contrainte, et non un
choix de style, qui explique la forme du port.

## Le port, et ce qu'il promet

Cinq opérations, toutes asynchrones : `get`, `set`, `delete`, `exists`, `invalidate_pattern`. Trois
règles les accompagnent, écrites dans la docstring de `Cache` parce que tout le reste en dépend.

**1. Les clés reçues sont logiques.** L'appelant écrit `dossier:42` ; l'adaptateur, et lui seul, y
appose l'environnement et le périmètre. Un appelant ne _peut_ donc pas oublier le groupe — composer
le segment de tenance n'est pas son travail. C'est ce qui rend le cloisonnement structurel plutôt
que conventionnel.

**2. Toute entrée expire.** `ttl=None` signifie « la durée par défaut configurée »
(`REDIS_CACHE_TTL_SECONDS`, 300 s), jamais « pas d'expiration », et un TTL nul ou négatif lève une
`ValueError`. La raison est écrite dans `docker/redis/redis.conf` : l'instance est partagée avec la
file de tâches, et la seule politique d'éviction acceptable pour elle — `volatile-lru` — ne libère
que les clés portant un TTL. Une entrée éternelle la rendrait inopérante en silence.

**3. Aucune implémentation ne lève quand son stockage est injoignable.** Voir plus bas.

## La clé porte l'environnement et le groupe

```
{environnement}:g-{group_id}:{clé logique}     — CacheScope.TENANT
{environnement}:shared:{clé logique}           — CacheScope.SHARED
```

`ENVIRONMENT=development` donne `dev`, `staging` donne `staging`, `production` donne `prod` : c'est
la promesse que les deux `.env.example` publient depuis SETUP-05, et `_environment_slug` est ce qui
la tient. La traduction passe par un `match` avec `assert_never` — le jour où un quatrième
environnement s'ajoute au `Literal` d'`AppSettings`, **Mypy échoue ici** plutôt que de laisser le
service produire des clés `None:shared:…`.

Le segment de groupe est le cloisonnement de
l'[ADR-0004](../adr/0004-tenance-par-groupe.md) appliqué au cache. Le
corollaire vaut pour l'invalidation : `invalidate_pattern("*")` purge le groupe actif et
**lui seul**, et une purge inter-groupes n'est pas exprimable.

Une entrée non tenant porte un `shared` **écrit**, jamais l'absence de segment. Si l'oubli de
périmètre produisait une clé d'apparence normale, il passerait inaperçu ; il produit une clé
visiblement partagée.

## Le contexte de tenance

Le groupe actif est porté par `current_group_id`, dans `shared/infrastructure/tenancy.py` : lire,
exiger (`require_current_group_id()`), poser le temps d'un bloc (`use_group()`) — et, depuis
BACK-06b, assumer une lecture **tous groupes** par `use_all_groups(reason=...)`, l'échappatoire
nommée de l'[ADR-0013](../adr/0013-filtre-de-tenance-dans-le-depot.md).

`require_current_group_id()` **lève** au lieu de dégrader — le motif est consigné dans
l'[ADR-0004](../adr/0004-tenance-par-groupe.md). La dégradation gracieuse
porte sur Redis absent, pas sur un appelant qui ignore de quel groupe il parle. Elle lève aussi
sous `use_all_groups` : une clé `TENANT` n'a pas de sens « tous groupes », et composer une clé
comme estampiller une insertion exigent **un** groupe — un bloc `use_group` imbriqué le désigne.

Le filtre SQLAlchemy que ce contexte promettait est livré (BACK-06b), dans
`db/repositories/tenant.py` — voir [Persistance](./persistance.md). L'intergiciel qui alimentera
la contextvar depuis l'authentification appartient à BACK-10c ; un piège l'attend, écrit dans la
docstring de `tenancy.py` : `BaseHTTPMiddleware` exécute l'aval de la chaîne dans une **tâche
distincte**, donc un `set()` fait dans son `dispatch()` n'atteindrait pas l'endpoint.

## Ce que la dégradation gracieuse promet — et ce qu'elle ne promet pas

Redis injoignable : `get` rend `MISSING`, `set` et `delete` restent sans effet, `exists` rend
`False`, `invalidate_pattern` rend `0`. Un avertissement part **une seule fois** à la chute, un
autre à la reprise — un avertissement par appel noierait le journal pendant une coupure de dix
minutes, et un journal noyé est un journal que personne ne lit.

L'application **démarre** sans Redis, contrairement à ce qu'elle fait sans PostgreSQL. L'asymétrie
est le sujet, pas un oubli : sans base, aucune route ne peut répondre juste et échouer vite est
correct ; sans cache, toutes répondent, plus lentement. Il n'existe donc ni `verify_connectivity`
bloquant, ni `CacheUnavailableError` — cette classe n'aurait aucun endroit où être levée.
`RedisCache.ping()` sonde quand même au démarrage et journalise, pour que l'exploitant voie la panne
dans la ligne de démarrage plutôt qu'à la première requête.

:::warning Un contrat réservé au cache
**Ce contrat convient à un cache, et à rien d'autre.** Une décision de sécurité lue ici s'ouvrirait
toute seule le jour où Redis tombe : « ce jeton est-il révoqué ? » (BACK-10d) répondrait « non »,
« cet OTP a-t-il été consommé ? » (BACK-17) répondrait « non ». Ces deux tickets doivent traiter
l'indisponibilité explicitement — échouer fermé — et non l'hériter d'ici.
:::

`MISSING` est une sentinelle, distincte de `None`. Sans elle, un cas d'usage qui retourne
légitimement `None` — « ce dossier n'existe pas » — ne serait **jamais** servi depuis le cache : sa
valeur serait relue comme une absence et recalculée à chaque appel. Un défaut de rendement que rien
ne signale.

## Le décorateur `@cached`

À poser sur une méthode de lecture d'un cas d'usage. Jamais sur une écriture : le résultat serait
mémorisé, et l'effet de bord rejoué ou sauté selon l'état du cache.

```python
class LireLeDossier:
    def __init__(self, cache: Cache) -> None:
        self.cache = cache

    @cached(ttl=60, namespace="medical_records.dossier")
    async def execute(self, animal_id: UUID) -> dict[str, JsonValue]: ...
```

Le cache vient de `self.cache`, jamais d'un registre global : la borne `S: CacheHolder` fait
**échouer le typage à la définition** si la classe décorée n'expose pas de cache. La question « où le
décorateur trouve-t-il son cache, sans requête HTTP ? » est donc tranchée à la compilation, et non
par une convention que quelqu'un oubliera. Décorer une classe qui n'en a pas donne :

```
error: Value of type variable "S" of function cannot be "SansCache"  [type-var]
```

Et le type de retour garde sa précision — `dict[str, JsonValue]` reste `dict[str, JsonValue]`, il
n'est pas élargi à `JsonValue`.

Le groupe n'apparaît pas dans la signature, et c'est voulu : le décorateur vit dans le domaine, la
contextvar dans l'infrastructure, où l'architecture lui interdit d'aller la chercher. C'est
l'adaptateur qui lit le groupe au moment de composer la clé physique — le décorateur ne peut donc pas
se tromper de groupe, puisqu'il n'en manipule aucun.

La clé est `namespace` (ou `module:qualname` à défaut) suivi d'une **empreinte SHA-256** des
arguments. Une empreinte et non les arguments en clair : une clé Redis se lit dans `MONITOR`, dans le
`SLOWLOG` et dans la console d'inspection, et `…:lire_le_dossier:marie.dupont@exemple.fr` y
déverserait une donnée personnelle. Limite à connaître : l'empreinte vaut ce que vaut le `repr` des
arguments — un objet sans `__repr__` propre y met son adresse mémoire, et le cache manquerait alors
systématiquement, en silence.

Ce que le décorateur ne fait pas : il ne protège pas de l'avalanche, et il n'invalide rien.
L'invalidation est du côté écriture, par `invalidate_pattern`.

## Vérifier que le cache tient

Cinq sondes. Les deux premières ne demandent **aucun** conteneur.

**1. Les cinq opérations, le TTL, le décorateur et la bascule de groupe — sans Redis.** La sonde
définissait sa propre doublure ; depuis BACK-06c elle importe la **vraie**,
[`InMemoryCache`](./doublures-en-memoire.md), construite par `build_in_memory_cache` depuis la même
configuration que la production — donc avec le même compositeur de clés, le même sérialiseur et le
même TTL par défaut. Une suite de conformité la joue par ailleurs contre le vrai Redis : ce que la
sonde montre ici est ce que l'adaptateur fait là-bas.

```bash
uv run python - <<'PY'
import asyncio
from uuid import UUID

from app.core import get_settings
from app.shared.domain.ports.cache import MISSING, CacheScope, JsonValue, cached
from app.shared.infrastructure.memory.cache import build_in_memory_cache
from app.shared.infrastructure.memory.clock import FakeClock
from app.shared.infrastructure.tenancy import MissingTenantContextError, use_group

A = UUID("01931f2a-0000-7000-8000-00000000000a")
B = UUID("01931f2a-0000-7000-8000-00000000000b")


class LireLeDossier:
    def __init__(self, cache):
        self.cache = cache
        self.appels = 0

    @cached(ttl=60, namespace="sonde.dossier")
    async def execute(self, animal_id: str) -> dict[str, JsonValue]:
        self.appels += 1
        return {"animal": animal_id, "appels": self.appels}


async def main() -> None:
    # L'horloge est pilotee : l'expiration se prouve sans dormir.
    horloge = FakeClock()
    cache = build_in_memory_cache(get_settings(), clock=horloge)

    with use_group(A):
        await cache.set("dossier:42", {"note": "vu par le groupe A"}, ttl=60)
        print("1. set (ttl=60) puis get:", await cache.get("dossier:42"))
        print("2. exists               :", await cache.exists("dossier:42"))
        await cache.set("liste:1", 1, ttl=60)
        await cache.set("liste:2", 2, ttl=60)
        print("3. invalidate_pattern   :", await cache.invalidate_pattern("liste:*"))
        await cache.set("ephemere", "x", ttl=1)
        horloge.advance(2)
        print("4. TTL expire           :", await cache.get("ephemere") is MISSING)
        cas = LireLeDossier(cache)
        await cas.execute("rex")
        await cas.execute("rex")
        print("5. @cached, deux appels :", cas.appels, "execution(s) reelle(s)")

    with use_group(B):
        print("6. le groupe B ne lit rien du groupe A :", await cache.get("dossier:42") is MISSING)
        await cache.set("dossier:42", {"note": "vu par le groupe B"}, ttl=60)

    with use_group(A):
        print("7. le groupe A relit la sienne        :", await cache.get("dossier:42"))
        print("8. delete                             :", await cache.delete("dossier:42"))

    await cache.set("otp:0612345678", "123456", ttl=60, scope=CacheScope.SHARED)
    try:
        await cache.set("dossier:1", "x", ttl=60)
    except MissingTenantContextError as erreur:
        print("9. hors contexte de groupe            :", type(erreur).__name__)

    print("10. cles physiques :")
    for cle in cache.physical_keys():
        print("      ", cle)


asyncio.run(main())
PY
```

Attendu — la ligne 6 est le critère de bascule de groupe, la ligne 7 sa contrepartie (l'écriture du
groupe B n'a pas écrasé celle du groupe A) :

```
1. set (ttl=60) puis get: {'note': 'vu par le groupe A'}
2. exists               : True
3. invalidate_pattern   : 2
4. TTL par defaut expire: True
5. @cached, deux appels : 1 execution(s) reelle(s)
6. le groupe B ne lit rien du groupe A : True
7. le groupe A relit la sienne        : {'note': 'vu par le groupe A'}
8. delete                             : True
9. hors contexte de groupe            : MissingTenantContextError
10. cles physiques :
       dev:g-01931f2a-0000-7000-8000-00000000000a:sonde.dossier:0459e6e24fb37678a201e3cbeeacfaa9
       dev:g-01931f2a-0000-7000-8000-00000000000b:dossier:42
       dev:shared:otp:0612345678
```

**2. Le préfixe suit l'environnement.** La même commande, précédée d'une variable — les variables du
processus passent devant le fichier `.env` :

```bash
ENVIRONMENT=staging uv run python - <<'PY'
...  # la meme sonde qu'au point 1
PY
```

Attendu : les trois mêmes clés, préfixées `staging:` au lieu de `dev:`.

**3. Aller-retour réel, expiration réelle, séparation des bases.** Pile levée.

```bash
uv run python - <<'PY'
import asyncio
from uuid import UUID

from app.core import get_settings
from app.shared.domain.ports.cache import CacheScope
from app.shared.infrastructure.clients.redis_cache import build_cache
from app.shared.infrastructure.tenancy import use_group

A = UUID("01931f2a-0000-7000-8000-00000000000a")
B = UUID("01931f2a-0000-7000-8000-00000000000b")


async def main() -> None:
    settings = get_settings()
    cache = build_cache(settings)
    try:
        print("0. ping                  :", await cache.ping(), "sur", cache.target)
        with use_group(A):
            await cache.set("sonde:dossier", {"valeur": 42}, ttl=60)
            print("1. relu depuis Redis     :", await cache.get("sonde:dossier"))
            await cache.set("sonde:liste:1", 1, ttl=60)
            await cache.set("sonde:liste:2", 2, ttl=60)
            print("2. invalidate_pattern    :", await cache.invalidate_pattern("sonde:liste:*"))
            await cache.set("sonde:ephemere", "x", ttl=2)
            await asyncio.sleep(2.5)
            print("3. TTL expire cote Redis :", await cache.exists("sonde:ephemere") is False)
        with use_group(B):
            await cache.set("sonde:dossier", {"valeur": 99}, ttl=60)
        await cache.set("sonde:partagee", "x", ttl=60, scope=CacheScope.SHARED)
        print("4. bases                 : cache", settings.redis.cache_db,
              "/ broker", settings.redis.broker_db, "(BACK-15)")
    finally:
        await cache.aclose()


asyncio.run(main())
PY
```

Puis, **depuis la racine du dépôt**, la vérification qui compte — chaque entrée porte-t-elle un TTL,
et le cache a-t-il touché la base du broker ?

```bash
docker compose --project-directory . -f docker/docker-compose.yml exec -T redis \
  sh -c "redis-cli -n 0 --scan --pattern 'dev:*sonde*' | while read c; do echo \"\$(redis-cli -n 0 ttl \"\$c\")s  \$c\"; done" | sort -k2
```

```bash
docker compose --project-directory . -f docker/docker-compose.yml exec -T redis \
  redis-cli -n 1 --scan --pattern 'dev:*' | wc -l
```

Attendu : trois clés, **toutes** porteuses d'un TTL positif — c'est la promesse faite à
`redis.conf` —, la même clé logique déclinée sous deux groupes, et `0` clé de cache en base 1. Le
décompte de secondes ci-dessous dépend évidemment du moment de la lecture ; c'est sa positivité qui
se vérifie, pas sa valeur.

```
51s  dev:g-01931f2a-0000-7000-8000-00000000000a:sonde:dossier
53s  dev:g-01931f2a-0000-7000-8000-00000000000b:sonde:dossier
53s  dev:shared:sonde:partagee
```

Nettoyer ensuite : `redis-cli -n 0 --scan --pattern 'dev:*sonde*' | xargs -r redis-cli -n 0 unlink`.

**4. Redis coupé : un avertissement, puis on continue.** Le port hors service passe par une variable,
comme la sonde de BACK-05 — inutile d'arrêter le conteneur.

```bash
REDIS_PORT=6399 uv run python - <<'PY'
import asyncio

from app.core import get_settings
from app.shared.domain.ports.cache import MISSING, CacheScope, JsonValue, cached
from app.shared.infrastructure.clients.redis_cache import build_cache


class LireLeDossier:
    def __init__(self, cache):
        self.cache = cache
        self.appels = 0

    @cached(ttl=60, namespace="sonde.degradee", scope=CacheScope.SHARED)
    async def execute(self, animal_id: str) -> dict[str, JsonValue]:
        self.appels += 1
        return {"animal": animal_id}


async def main() -> None:
    cache = build_cache(get_settings())
    try:
        print("0. ping             :", await cache.ping())
        print("1. get              :", await cache.get("x", scope=CacheScope.SHARED) is MISSING)
        print("2. set              :", await cache.set("x", 1, scope=CacheScope.SHARED))
        print("3. exists           :", await cache.exists("x", scope=CacheScope.SHARED))
        print("4. invalidate       :", await cache.invalidate_pattern("*", scope=CacheScope.SHARED))
        print("5. delete           :", await cache.delete("x", scope=CacheScope.SHARED))
        cas = LireLeDossier(cache)
        await cas.execute("rex")
        await cas.execute("rex")
        print("6. @cached, 2 appels:", cas.appels, "execution(s) reelle(s), aucune exception")
    finally:
        await cache.aclose()


asyncio.run(main())
PY
echo "code de sortie : $?"
```

Attendu : **un seul** avertissement sur la sortie d'erreur malgré huit opérations, toutes les valeurs
dégradées, et un code de sortie `0`. La queue du message vient de la bibliothèque et dépend de
l'ordre de résolution IPv4/IPv6 du poste — c'est le préfixe qui compte, pas elle.

```
Cache Redis injoignable sur localhost:6399 (base 0) (demarrage) : le service continue SANS cache. Error 61 connecting to localhost:6399. Connection refused.
0. ping             : False
1. get              : True
2. set              : None
3. exists           : False
4. invalidate       : 0
5. delete           : False
6. @cached, 2 appels: 2 execution(s) reelle(s), aucune exception
code de sortie : 0
```

L'avertissement paraît ici sans qu'aucune journalisation soit configurée : cette sonde s'exécute
hors du `lifespan`, et le `lastResort` de la bibliothèque standard sert les `WARNING` sur `stderr`.
Dans le service, la journalisation est posée par le `lifespan`
([Journalisation](./journalisation.md)) : le message `INFO` de `ping()` réussi est visible, et la
reprise du cache — écrite en `WARNING` tant que rien n'était configuré, faute de quoi la fin d'une
panne aurait été invisible — est repassée en `INFO`.

**5. L'application démarre et répond sans Redis, et le pool meurt avec le processus.**

```bash
REDIS_PORT=6399 uv run uvicorn app.main:app --port 8001
```

Attendu : l'avertissement, **puis** `Application startup complete.` — à comparer avec
`POSTGRES_PORT=5999`, qui donne `Application startup failed. Exiting.` et un code de sortie 3. Dans
un autre terminal, `curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8001/openapi.json`
rend `200`.

Puis, la pile levée et l'API relancée sans la variable, depuis la racine :

```bash
docker compose --project-directory . -f docker/docker-compose.yml exec -T redis \
  redis-cli client list | grep "name=juui-api-cache"
```

Attendu : une ligne portant `name=juui-api-cache/development` et `db=0` — c'est le pendant exact de
la sonde `pg_stat_activity` de BACK-05. Après un `Ctrl-C` sur uvicorn, la même commande ne rend plus
rien : le `finally` du `lifespan` a bien fermé le client **et** le pool.

Les écarts assumés avec le ticket BACK-14 sont consignés au
[registre des écarts](../ecarts/back.md#écarts-assumés-avec-le-ticket-back-14).
