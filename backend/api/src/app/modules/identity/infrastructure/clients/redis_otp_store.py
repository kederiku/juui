"""Magasin Redis des codes de verification d'adresse (BACK-17).

L'adaptateur du port `OtpStore`, et le contraire assume de `RedisCache` : celui-la
degrade en silence quand Redis tombe, celui-ci LEVE. La docstring du port `Cache`
(BACK-14) le disait deja de ce ticket -- « cet OTP a-t-il ete consomme ? » rendu
« non » par defaut ouvrirait la porte que le mecanisme entier existe pour fermer.

CE QUI EST STOCKE, ET CE QUI NE L'EST PAS
Une EMPREINTE poivree du code (HMAC-SHA256), jamais le code. Le poivre est derive
de `JWT_SECRET_KEY` -- il ne vit donc pas dans Redis, ce qui est toute la raison
d'etre du hachage : un condense nu de six chiffres se casse par force brute
exhaustive en une fraction de seconde.

LA BASE 0, SANS PERIMETRE DE TENANCE
Meme base que le cache (INFRA-02 n'en prevoit que deux, la 1 etant au broker),
mais un client, un pool et une composition de cles qui lui sont propres. Surtout,
les cles NE PASSENT PAS par `CacheKeyBuilder` : son perimetre `TENANT` exige un
groupe actif, or la verification d'adresse se joue a l'inscription, avant toute
appartenance -- composer la cle par lui leverait `MissingTenantContextError` sur
le parcours le plus banal du service. Un OTP appartient a un COMPTE, pas a une
structure.

CE QUE `volatile-lru` FERAIT A CES CLES
`docker/redis/redis.conf` laisse `maxmemory` a zero aujourd'hui, donc rien n'est
evince. Le jour ou une borne serait posee avec `volatile-lru`, ces cles portent
toutes un TTL et deviendraient donc eligibles : un code evince se lit comme un
code expire -- l'utilisateur en redemande un, sans consequence de securite --,
mais un COMPTEUR DE RENVOI evince rouvrirait un quota. A reexaminer le jour ou
`maxmemory` cessera d'etre nul, et non avant : ce serait alors une base dediee.
"""

import hmac
import logging
from hashlib import sha256
from typing import Final
from uuid import UUID

from fastapi import Request
from redis.asyncio import ConnectionPool, Redis
from redis.backoff import NoBackoff
from redis.commands.core import AsyncScript
from redis.exceptions import RedisError
from redis.retry import Retry

from app.core import Settings
from app.modules.identity.domain.policies import (
    OTP_PEPPER_LABEL,
    OtpRules,
    codes_match,
    fingerprint_otp_code,
)
from app.modules.identity.domain.ports import (
    OtpConsumption,
    OtpStore,
    OtpStoreUnavailableError,
    ResendVerdict,
)
from app.shared.infrastructure.clients.cache_keys import environment_slug

_LOGGER: Final = logging.getLogger(__name__)

# Cle sous laquelle le `lifespan` et le demarrage du worker rangent le magasin.
# Meme forme que `CACHE_STATE_KEY` et `STATE_KEY` : une constante, pas un
# litteral recopie des deux cotes.
OTP_STORE_STATE_KEY: Final = "otp_store"

# Delais d'etablissement et de commande, alignes sur ceux du cache. Deux secondes
# et non les cinq de la bibliotheque : ce delai est ce que paie une requete quand
# Redis absorbe les paquets sans repondre.
_CONNECT_TIMEOUT_SECONDS: Final = 2.0
_COMMAND_TIMEOUT_SECONDS: Final = 2.0

# Champs du document de code. Deux, et pas un de plus : l'empreinte, et ce qui
# reste de tentatives.
_FIELD_FINGERPRINT: Final = "fingerprint"
_FIELD_ATTEMPTS_LEFT: Final = "attempts_left"

# Ce qu'il faut attraper pour dire « Redis est injoignable ». Meme raisonnement
# que dans `redis_cache.py` : la `ConnectionError` de redis-py n'herite PAS de
# l'`OSError` integre, et une resolution DNS en echec remonte telle quelle.
_UNREACHABLE: Final = (OSError, RedisError)

# Depense une tentative et rend ce qu'il faut pour juger, D'UN SEUL GESTE.
#
# POURQUOI UN SCRIPT ET NON TROIS COMMANDES. `HINCRBY` sur une cle ABSENTE la
# CREE, et sans TTL : verifier un code inexistant laisserait derriere lui un
# document eternel, dans une instance ou toute cle doit expirer. Le script teste
# donc l'existence d'abord. Et le decrement doit etre indivisible : deux requetes
# concurrentes ne peuvent pas depenser la meme tentative, sinon trois essais en
# deviennent trente, lances en parallele.
#
# POURQUOI LA COMPARAISON N'EST PAS FAITE ICI. Le `==` de Lua s'arrete au premier
# octet different ; la comparaison de decision se fait cote Python, en temps
# constant. Le script s'en sert malgre tout pour DETRUIRE la cle -- une
# suppression ne revele rien par sa duree, et la faire ici evite un aller-retour
# pendant lequel un code deja accepte resterait valide.
_CONSUME_SCRIPT: Final = """
local stored = redis.call('HGET', KEYS[1], ARGV[2])
if not stored then
  return {'', -1}
end
local left = redis.call('HINCRBY', KEYS[1], ARGV[3], -1)
if left <= 0 or stored == ARGV[1] then
  redis.call('DEL', KEYS[1])
end
return {stored, left}
"""

# Passe le tourniquet des envois : delai minimal, plafond par compte, plafond par
# IP. Rend 0 si la demande passe, sinon le nombre de secondes a attendre.
#
# LES CONTROLES D'ABORD, LA CONSOMMATION ENSUITE, et le tout indivisible : un
# double-clic ne doit pas franchir le delai minimal puis bruler quand meme une
# unite du plafond horaire. C'est aussi ce qui interdit a deux requetes
# simultanees de lire « 4 sur 5 » toutes les deux et de passer ensemble.
#
# `#KEYS >= 3` : la cle d'IP est absente quand la demande ne vient pas d'une
# requete HTTP. Le plafond par IP est alors sans objet -- il n'y a personne a
# compter --, et surtout il ne faut PAS lui substituer un seau commun, qui
# bloquerait tout le monde des le premier appelant sans IP.
_RESEND_SCRIPT: Final = """
local window = tonumber(ARGV[2])
local gate_ttl = redis.call('TTL', KEYS[1])
if gate_ttl > 0 then
  return gate_ttl
end
local account_used = tonumber(redis.call('GET', KEYS[2]) or '0')
if account_used >= tonumber(ARGV[3]) then
  local left = redis.call('TTL', KEYS[2])
  if left < 1 then left = window end
  return left
end
if #KEYS >= 3 then
  local ip_used = tonumber(redis.call('GET', KEYS[3]) or '0')
  if ip_used >= tonumber(ARGV[4]) then
    local left = redis.call('TTL', KEYS[3])
    if left < 1 then left = window end
    return left
  end
end
local interval = tonumber(ARGV[1])
if interval > 0 then
  redis.call('SET', KEYS[1], '1', 'EX', interval)
end
local account_now = redis.call('INCR', KEYS[2])
if account_now == 1 then
  redis.call('EXPIRE', KEYS[2], window)
end
if #KEYS >= 3 then
  local ip_now = redis.call('INCR', KEYS[3])
  if ip_now == 1 then
    redis.call('EXPIRE', KEYS[3], window)
  end
end
return 0
"""


def derive_otp_pepper(settings: Settings) -> bytes:
    """Derive le poivre des empreintes a partir de la cle de signature des jetons.

    UNE CLE DERIVEE, PAS UNE CLE REUTILISEE. Se servir de `JWT_SECRET_KEY` telle
    quelle pour un second usage cryptographique est une faute d'hygiene : deux
    usages independants doivent avoir des cles independantes. Le HMAC ci-dessous
    en fabrique une, liee a une etiquette de SEPARATION DE DOMAINE -- connaitre
    le poivre ne donne rien sur la cle de signature, et reciproquement.

    POURQUOI PAS UNE VARIABLE DEDIEE. Elle serait un secret de plus a distribuer,
    a faire tourner et a oublier -- et SETUP-08, qui recense les variables OTP a
    publier, n'en annonce aucune. Le jour ou la rotation des secrets sera un sujet
    a part entiere, cette fonction est l'unique endroit a changer.

    CE QUE COUTE LA DERIVATION : faire tourner `JWT_SECRET_KEY` invalide du meme
    coup les codes en cours. Ils vivent dix minutes ; leurs porteurs en
    redemanderont un.

    Args:
        settings: la configuration du service, dont la cle de signature.

    Returns:
        Trente-deux octets de poivre.
    """
    key = settings.jwt.secret_key.get_secret_value().encode("utf-8")
    return hmac.new(key, OTP_PEPPER_LABEL, sha256).digest()


class RedisOtpStore(OtpStore):
    """Magasin des codes adosse a Redis, echouant ferme.

    AUCUNE DEGRADATION GRACIEUSE, NULLE PART. Chaque methode traduit une panne en
    `OtpStoreUnavailableError` : le service repond 500, ce qui est desagreable et
    honnete, la ou un verdict par defaut serait confortable et faux. C'est aussi
    ce qui empeche de contourner les quotas en faisant tomber Redis.
    """

    def __init__(
        self,
        *,
        client: Redis,
        pool: ConnectionPool,
        environment: str,
        pepper: bytes,
        target: str,
    ) -> None:
        """Assemble l'adaptateur autour d'un client deja construit.

        Args:
            client: le client asynchrone, adosse au pool ci-dessous.
            pool: le pool de connexions, a fermer explicitement a l'arret.
            environment: premier segment des cles (`dev`, `staging`, `prod`).
            pepper: la cle des empreintes, derivee par `derive_otp_pepper`.
            target: hote, port et base, pour les messages. JAMAIS l'URL, qui
                porte le mot de passe en clair.
        """
        self._client = client
        self._pool = pool
        self._environment = environment
        self._pepper = pepper
        self._target = target
        # `register_script` calcule l'empreinte du script et emploie `EVALSHA` :
        # le corps ne repart sur le fil qu'a la premiere execution, ou apres un
        # `SCRIPT FLUSH`.
        self._consume_script: AsyncScript = client.register_script(_CONSUME_SCRIPT)
        self._resend_script: AsyncScript = client.register_script(_RESEND_SCRIPT)

    @property
    def target(self) -> str:
        """Hote, port et base vises, tels qu'ils apparaissent dans les messages."""
        return self._target

    async def issue(self, *, account_id: UUID, code: str, rules: OtpRules) -> None:
        """Range l'empreinte d'un code neuf, et arme son quota. Voir le port."""
        fingerprint = fingerprint_otp_code(code, account_id=account_id, pepper=self._pepper)
        key = self._code_key(account_id)
        try:
            # MULTI/EXEC : la suppression du document precedent, l'ecriture du
            # nouveau et la pose du TTL forment un tout. Sans le `delete`, un
            # document dont le nombre de champs aurait change entre deux versions
            # du service survivrait par fusion.
            async with self._client.pipeline(transaction=True) as pipeline:
                pipeline.delete(key)
                pipeline.hset(
                    key,
                    mapping={
                        _FIELD_FINGERPRINT: fingerprint,
                        _FIELD_ATTEMPTS_LEFT: rules.max_attempts,
                    },
                )
                pipeline.expire(key, rules.ttl_seconds)
                await pipeline.execute()
        except _UNREACHABLE as error:
            raise self._unavailable("emission", error) from error

    async def consume(self, *, account_id: UUID, code: str) -> OtpConsumption:
        """Depense une tentative et juge le code presente. Voir le port."""
        candidate = fingerprint_otp_code(code, account_id=account_id, pepper=self._pepper)
        try:
            raw = await self._consume_script(
                keys=[self._code_key(account_id)],
                args=[candidate, _FIELD_FINGERPRINT, _FIELD_ATTEMPTS_LEFT],
            )
        except _UNREACHABLE as error:
            raise self._unavailable("verification", error) from error

        stored, attempts_left = self._read_consumption(raw)

        # La comparaison de DECISION, en temps constant, et cote service. Une
        # empreinte absente rend une chaine vide, que `codes_match` refuse comme
        # n'importe quelle autre non-correspondance -- meme chemin, meme duree.
        if codes_match(candidate, stored):
            return OtpConsumption.ACCEPTED
        if attempts_left <= 0:
            # Zero : le script vient de detruire le document. Negatif : il n'y
            # avait rien a detruire -- code expire ou jamais emis. Le premier cas
            # merite d'etre dit (« redemandez-en un »), le second doit rester
            # indistinct d'un code faux.
            return OtpConsumption.EXHAUSTED if attempts_left == 0 else OtpConsumption.REJECTED
        return OtpConsumption.REJECTED

    async def register_resend(
        self, *, account_id: UUID, client_ip: str | None, rules: OtpRules
    ) -> ResendVerdict:
        """Passe le tourniquet des envois. Voir le port."""
        keys = [self._gate_key(account_id), self._account_quota_key(account_id)]
        if client_ip:
            keys.append(self._ip_quota_key(client_ip))
        try:
            raw = await self._resend_script(
                keys=keys,
                args=[
                    rules.resend_min_interval_seconds,
                    rules.resend_window_seconds,
                    rules.resend_max_per_email,
                    rules.resend_max_per_ip,
                ],
            )
        except _UNREACHABLE as error:
            raise self._unavailable("quota de renvoi", error) from error

        if not isinstance(raw, int):
            raise self._malformed("quota de renvoi", raw)
        if raw <= 0:
            return ResendVerdict(allowed=True)
        return ResendVerdict(allowed=False, retry_after_seconds=raw)

    async def ping(self) -> bool:
        """Sonde le serveur, sans jamais lever.

        La SEULE methode de cette classe qui ne leve pas, et c'est delibere : elle
        sert le demarrage, ou un Redis absent ne doit pas empecher le service de
        se lever -- les routes qui dependent de l'OTP echoueront, les autres
        repondront. Meme geste que `RedisCache.ping()`, meme asymetrie avec les
        operations, qui, elles, echouent ferme.

        Returns:
            Vrai si Redis a repondu au PING.
        """
        try:
            await self._client.ping()
        except _UNREACHABLE as error:
            _LOGGER.warning(
                "Magasin d'OTP injoignable sur %s : la verification d'adresse "
                "echouera tant qu'il ne repond pas. %s",
                self._target,
                error,
            )
            return False
        _LOGGER.info("Magasin d'OTP joignable sur %s.", self._target)
        return True

    async def aclose(self) -> None:
        """Ferme le client PUIS le pool, sans jamais lever.

        Les deux et dans cet ordre, pour la raison ecrite dans `redis_cache.py` :
        `Redis(connection_pool=...)` ne prend pas possession d'un pool qu'il n'a
        pas cree. Appelee depuis un `finally`, elle ne doit pas lever -- une
        exception ici sauterait les fermetures suivantes.
        """
        for closable in (self._client, self._pool):
            try:
                await closable.aclose()
            except _UNREACHABLE:
                _LOGGER.debug("Fermeture du magasin d'OTP sans reponse de %s.", self._target)

    def _code_key(self, account_id: UUID) -> str:
        """Cle du code en cours pour ce compte."""
        return f"{self._environment}:otp:verify:{account_id}"

    def _gate_key(self, account_id: UUID) -> str:
        """Cle du delai minimal entre deux envois."""
        return f"{self._environment}:otp:resend:gate:{account_id}"

    def _account_quota_key(self, account_id: UUID) -> str:
        """Cle du plafond de renvois par compte -- donc par adresse."""
        return f"{self._environment}:otp:resend:account:{account_id}"

    def _ip_quota_key(self, client_ip: str) -> str:
        """Cle du plafond de renvois par IP, l'adresse reduite a une empreinte.

        UNE EMPREINTE ET NON L'IP EN CLAIR, pour la raison deja ecrite dans
        `cache.py` : une cle se lit dans `MONITOR`, dans le `SLOWLOG` et dans
        toute console d'inspection. Une adresse IP est une donnee personnelle ; la
        deverser dans un outil d'exploitation, ou personne ne la cherche et ou
        personne ne la purge, n'a aucune contrepartie -- un compteur n'a pas besoin
        de savoir qui il compte.
        """
        digest = sha256(client_ip.encode("utf-8")).hexdigest()[:32]
        return f"{self._environment}:otp:resend:ip:{digest}"

    def _read_consumption(self, raw: object) -> tuple[str, int]:
        """Relit la paire rendue par le script de consommation.

        Args:
            raw: ce que le script a rendu.

        Returns:
            L'empreinte conservee (chaine vide si aucun code n'etait en cours) et
            le nombre de tentatives restantes.

        Raises:
            OtpStoreUnavailableError: si la reponse n'a pas la forme attendue.
        """
        if not isinstance(raw, list) or len(raw) != 2:
            raise self._malformed("verification", raw)
        stored, attempts_left = raw[0], raw[1]
        if not isinstance(stored, str) or not isinstance(attempts_left, int):
            raise self._malformed("verification", raw)
        return stored, attempts_left

    def _unavailable(self, operation: str, error: Exception) -> OtpStoreUnavailableError:
        """Fabrique le refus technique, apres l'avoir journalise.

        Journalise ICI et non chez l'appelant : le message porte l'hote vise et
        l'operation, que le handler d'erreur generique n'aura plus sous la main.
        Niveau `error` et a CHAQUE appel, contrairement au drapeau du cache -- une
        panne du magasin d'OTP n'est pas une lenteur, c'est un parcours
        d'inscription a l'arret.
        """
        _LOGGER.error("Magasin d'OTP injoignable sur %s (%s) : %s", self._target, operation, error)
        message = (
            "Le magasin des codes de verification ne repond pas : aucune "
            "verification ne peut etre prononcee."
        )
        return OtpStoreUnavailableError(message)

    def _malformed(self, operation: str, raw: object) -> OtpStoreUnavailableError:
        """Fabrique le refus technique d'une reponse inattendue.

        Une reponse illisible est traitee comme une panne, jamais comme un verdict
        par defaut : c'est la regle 2 du port, et c'est la seule conduite sure.
        """
        _LOGGER.error(
            "Reponse inattendue du magasin d'OTP sur %s (%s) : %r",
            self._target,
            operation,
            raw,
        )
        message = (
            "Le magasin des codes de verification a rendu une reponse "
            "inattendue : aucune verification ne peut etre prononcee."
        )
        return OtpStoreUnavailableError(message)


def build_otp_store(settings: Settings) -> RedisOtpStore:
    """Construit le magasin et son pool, sans ouvrir la moindre connexion.

    Comme `build_cache` et `build_engine` : construire ne connecte pas, la
    premiere connexion nait au premier emprunt. Et comme partout, `settings`
    arrive en argument -- le worker et les tests fabriquent le leur.

    Args:
        settings: la configuration du service, dont les sections Redis et JWT.

    Returns:
        Le magasin, pret a etre range dans `app.state` ou dans l'etat du worker.
    """
    pool = ConnectionPool.from_url(
        settings.redis.cache_url,
        # `True` ici, `False` pour le cache, et la difference se justifie : le
        # cache confie l'encodage a son serialiseur, extensible jusqu'au binaire,
        # tandis que ce magasin ne manipule que du texte -- des empreintes
        # hexadecimales et des entiers.
        decode_responses=True,
        socket_connect_timeout=_CONNECT_TIMEOUT_SECONDS,
        socket_timeout=_COMMAND_TIMEOUT_SECONDS,
        # Zero reprise, comme pour le cache : ce que coute une panne doit rester
        # borne. La difference est ailleurs -- ici l'echec remonte.
        retry=Retry(NoBackoff(), retries=0),
        client_name=f"juui-api-otp/{settings.app.environment}",
    )
    return RedisOtpStore(
        client=Redis(connection_pool=pool),
        pool=pool,
        environment=environment_slug(settings.app.environment),
        pepper=derive_otp_pepper(settings),
        # Les composants, JAMAIS `cache_url` : cette propriete porte le mot de
        # passe en clair, et un message d'erreur finit toujours recopie quelque
        # part.
        target=f"{settings.redis.host}:{settings.redis.port} (base {settings.redis.cache_db})",
    )


def get_otp_store(request: Request) -> OtpStore:
    """Retourne le magasin ouvert par le `lifespan`.

    Meme forme que `get_cache` et `get_database` : une cle, un type, un
    accesseur. L'`isinstance` porte sur le PORT et non sur `RedisOtpStore` --
    c'est ce qui laisse un test ranger une doublure en memoire dans `app.state`
    sans toucher a ce fichier.

    Args:
        request: la requete en cours, d'ou l'on remonte a l'application.

    Returns:
        Le magasin des codes du processus.

    Raises:
        RuntimeError: si le `lifespan` n'a pas tourne.
    """
    store = getattr(request.app.state, OTP_STORE_STATE_KEY, None)
    if not isinstance(store, OtpStore):
        message = (
            "Le magasin des codes de verification n'est pas ouvert : "
            "l'application a-t-elle ete construite sans son lifespan ?"
        )
        raise RuntimeError(message)
    return store


def build_otp_rules(settings: Settings) -> OtpRules:
    """Traduit la section `OTP_` de la configuration en bornes du domaine.

    LE PONT ENTRE `app.core` ET LE DOMAINE, et il est ici parce qu'il ne peut etre
    nulle part ailleurs : le contrat `domain-purity` interdit au domaine
    d'importer la configuration, meme indirectement. Le domaine declare la FORME
    des bornes (`OtpRules`), l'infrastructure les remplit.

    Args:
        settings: la configuration du service, dont la section OTP.

    Returns:
        Les bornes a passer aux cas d'usage.

    Raises:
        ValueError: si une borne est incoherente -- pydantic les valide deja une
            a une, `OtpRules` les revalide pour l'appelant qui les ecrirait a la
            main.
    """
    return OtpRules(
        ttl_seconds=settings.otp.ttl_seconds,
        max_attempts=settings.otp.max_attempts,
        resend_min_interval_seconds=settings.otp.resend_min_interval_seconds,
        resend_window_seconds=settings.otp.resend_window_seconds,
        resend_max_per_email=settings.otp.resend_max_per_email,
        resend_max_per_ip=settings.otp.resend_max_per_ip,
    )
