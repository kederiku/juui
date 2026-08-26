"""Adaptateur S3 du port `FileStorage`, et son cycle de vie (BACK-13).

Le client vit aussi longtemps que le processus : il est cree une fois par le
`lifespan` et referme par lui. Rien ici ne s'ouvre a l'import.

UN SEUL PARAMETRE DISTINGUE MINIO D'AMAZON S3
`settings.s3.endpoint_url`. Rempli, boto3 parle a MinIO ; VIDE, il retombe sur
les endpoints Amazon reels, calcules a partir de la region. C'est la promesse que
les deux `.env.example` publient depuis SETUP-05, et ce fichier est ce qui la
tient : aucune ligne de code ne connait le nom « MinIO ».

UNE FONCTION DE `Settings`, ET NON UN LECTEUR DE CONFIGURATION
`build_file_storage` recoit sa configuration en argument, pour la raison deja
ecrite dans `db/engine.py` et `redis_cache.py` : `get_settings()` est mise en
cache par `lru_cache`, et un constructeur qui l'appellerait de l'interieur ne
saurait pas fabriquer un client different de celui du processus. Le worker TaskIQ
(BACK-15) et les fixtures de BACK-12 auront besoin du leur.

L'ASYMETRIE A TROIS TEMPS DU SERVICE, ET LA PLACE DE CE FICHIER DEDANS
BACK-05 livre `verify_connectivity`, qui LEVE et arrete le processus : sans base,
aucune route ne repond juste. BACK-14 livre un cache qui DEGRADE en silence :
sans lui, toutes repondent, plus lentement. Le stockage objet est le troisieme
cas, et le seul des trois a se comporter differemment au demarrage et a l'appel :

- au DEMARRAGE, `ping()` journalise et ne leve pas. Aucune route ne depend encore
  du bucket, et refuser de partir priverait le service de tout ce qui n'a rien a
  voir avec les fichiers ;
- a l'APPEL, toute operation LEVE. Un `upload` qui se tairait serait un fichier
  perdu apres qu'on a repondu « enregistre » a l'utilisateur.

Un stockage injoignable rend donc le service partiellement indisponible, ce qui
est exact -- ni tout, comme PostgreSQL, ni rien, comme le cache.

POURQUOI boto3 SYNCHRONE PLUTOT QU'aioboto3
Les cinq operations passent par `asyncio.to_thread`. Ce n'est pas un pis-aller :
`generate_presigned_url` -- la seule que le service appellera a chaque requete --
NE FAIT AUCUN I/O, c'est une signature calculee localement, et elle reste donc
synchrone jusqu'au bout. Les quatre autres transportent des octets et ne sont pas
sur le chemin des requetes de lecture. Face a cela, aioboto3 imposerait aiobotocore,
qui epingle botocore a la version pres, et rendrait inutiles les `boto3-stubs[s3]`
deja verrouilles -- pour un gain qui ne se mesurerait nulle part.

Le client boto3 est partage par tous ces threads. C'est admis : botocore documente
ses clients comme utilisables depuis plusieurs threads, contrairement aux
`resource`, qui ne le sont pas et dont ce fichier n'emploie aucun.
"""

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING, Final

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Request

from app.core import Settings
from app.shared.domain.ports.file_storage import (
    DEFAULT_UPLOAD_POLICY,
    FileStorage,
    FileStorageUnavailableError,
    PresignedOperation,
    StoredFileNotFoundError,
    UploadPolicy,
)
from app.shared.infrastructure.clients.storage_keys import validate_storage_key

if TYPE_CHECKING:
    # Sous `TYPE_CHECKING` parce que `mypy_boto3_s3` appartient au groupe `dev` :
    # l'image d'INFRA-04 est construite par `uv sync --frozen --no-dev`, ou ce
    # paquet n'existe pas. Un import a l'execution ferait echouer le demarrage du
    # conteneur, et seulement celui-la -- le genre de panne qui ne se voit qu'en
    # production.
    from mypy_boto3_s3.client import S3Client

_LOGGER: Final = logging.getLogger(__name__)

# Cle unique sous laquelle le `lifespan` range le stockage dans `app.state`. Meme
# forme que `STATE_KEY` et `CACHE_STATE_KEY` : une constante, pas un litteral.
STORAGE_STATE_KEY: Final = "file_storage"

# Delai d'etablissement de la connexion. Cinq secondes et non les deux du cache :
# le stockage n'est pas sur le chemin d'une requete de lecture, et abandonner trop
# tot ferait echouer un televersement que rien n'obligeait a echouer.
_CONNECT_TIMEOUT_SECONDS: Final = 5

# Delai de lecture d'une reponse. Trente secondes, parce que c'est la seule des
# valeurs de ce fichier qui porte des OCTETS : les vingt mebioctets admis par la
# politique par defaut ne traversent pas une liaison montante domestique en deux
# secondes. Une borne trop courte se manifesterait par des televersements qui
# echouent « au hasard », c'est-a-dire selon la taille du fichier.
_READ_TIMEOUT_SECONDS: Final = 30

# Tentatives par appel, mode `standard`. Trois et non zero, a l'INVERSE du cache :
# la ou une lecture de cache manquee se recalcule, une operation de stockage
# manquee se perd. Le mode `standard` ne rejoue que ce qui est rejouable -- codes
# 429, 500, 502, 503, 504 et erreurs de connexion --, jamais un refus
# d'autorisation.
_MAX_ATTEMPTS: Final = 3

# Duree de validite par defaut d'une URL pre-signee : quinze minutes. Assez pour
# afficher une page et televerser une piece jointe, trop peu pour qu'une URL
# recopiee dans un courriel ou un journal reste utile longtemps.
#
# Constante de module et non variable d'environnement, meme arbitrage qu'en
# BACK-05 et BACK-14 : chaque variable coute deux gabarits, une ligne de compose
# et une ligne de documentation, et l'appelant peut deja passer `expires_in`.
#
# PUBLIQUE DEPUIS BACK-06c, comme `environment_slug` l'est devenue en BACK-17 :
# la doublure en memoire applique le MEME defaut, faute de quoi le test de
# conformite comparerait deux durees differentes en croyant comparer un contrat.
DEFAULT_PRESIGNED_EXPIRE_SECONDS: Final = 15 * 60

# Plafond de la signature V4, impose par le protocole et non par ce service : sept
# jours. Une valeur superieure produirait une URL que le stockage refuserait, avec
# un message qui ne nomme pas la cause.
#
# PUBLIQUE DEPUIS BACK-06c, meme motif que la constante ci-dessus : une borne
# recopiee dans la doublure derive au premier ajustement de l'une des deux.
MAX_PRESIGNED_EXPIRE_SECONDS: Final = 7 * 24 * 60 * 60

# Codes d'erreur signifiant « cet objet n'existe pas ».
#
# TROIS ET NON UN SEUL. `get_object` rend `NoSuchKey`, mais `head_object` -- qui
# n'a pas de corps de reponse ou loger un code -- rend le statut HTTP nu, `404`,
# et certaines passerelles compatibles S3 rendent `NotFound`. S'en tenir a
# `NoSuchKey` ferait passer une absence pour une panne dans `exists()`, c'est-a-dire
# ferait lever la methode dont le travail est de repondre non.
_NOT_FOUND_CODES: Final = frozenset({"NoSuchKey", "NoSuchBucket", "NotFound", "404"})

# Statut HTTP nu rendu par `head_object`, qui n'a pas de corps ou loger un code.
_HTTP_NOT_FOUND: Final = 404

# Ce qu'il faut attraper pour dire « le stockage est injoignable ».
#
# `BotoCoreError` couvre `EndpointConnectionError`, `ConnectTimeoutError` et
# `ReadTimeoutError`, qui en heritent tous -- verifie. `OSError` n'est pas
# redondant : une resolution DNS en echec peut remonter telle quelle avant que
# botocore ne l'enveloppe. Meme raisonnement que les `_UNREACHABLE` de
# `db/engine.py` et de `redis_cache.py`.
#
# `ClientError` n'y figure PAS : elle porte une reponse du serveur, donc une
# information a lire -- c'est `_translate` qui la trie.
_UNREACHABLE: Final = (OSError, BotoCoreError)


class S3FileStorage(FileStorage):
    """Stockage objet adosse a un service compatible S3 -- MinIO ou Amazon.

    AUCUNE DEGRADATION, JAMAIS. Voir la docstring du port : contrairement au
    cache, aucune methode n'a de valeur de repli. Ce qui suit ne contient donc pas
    l'equivalent du drapeau `_degraded` de `RedisCache`, et ce n'est pas un oubli
    -- il n'y a rien a taire, chaque echec remonte a son appelant.
    """

    def __init__(
        self,
        *,
        client: S3Client,
        bucket: str,
        target: str,
        policy: UploadPolicy = DEFAULT_UPLOAD_POLICY,
        default_expires_in: int = DEFAULT_PRESIGNED_EXPIRE_SECONDS,
    ) -> None:
        """Assemble l'adaptateur autour d'un client deja construit.

        Args:
            client: le client S3 synchrone, partage par le processus.
            bucket: le bucket applicatif, cree par `minio-init` (INFRA-03).
            target: endpoint et bucket, pour les messages. JAMAIS les clefs
                d'acces, ni une URL qui les porterait.
            policy: ce qu'un upload doit respecter. Voir `UploadPolicy`.
            default_expires_in: duree de validite appliquee quand l'appelant n'en
                donne pas.
        """
        self._client = client
        self._bucket = bucket
        self._target = target
        self._policy = policy
        self._default_expires_in = default_expires_in

    @property
    def target(self) -> str:
        """Endpoint et bucket vises, tels qu'ils apparaissent dans les messages."""
        return self._target

    async def upload(self, key: str, content: bytes, content_type: str) -> None:
        """Depose un objet, apres validation. Voir le port pour le contrat."""
        validate_storage_key(key)
        # AVANT le reseau, et dans cet ordre : refuser un fichier de quarante
        # mebioctets apres l'avoir televerse serait une plaisanterie.
        self._policy.validate(content, content_type)
        await self._call(
            lambda: self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content,
                # Conserve SUR L'OBJET : c'est ce type que le stockage renverra a
                # travers une URL pre-signee, et donc lui qui decidera si le
                # navigateur affiche le fichier ou le telecharge.
                ContentType=content_type,
            ),
            operation="depot",
            key=key,
        )

    async def download(self, key: str) -> bytes:
        """Relit un objet en entier. Voir le port pour le contrat."""
        validate_storage_key(key)
        response = await self._call(
            lambda: self._client.get_object(Bucket=self._bucket, Key=key),
            operation="lecture",
            key=key,
        )
        # `read()` est bloquant lui aussi : le corps n'est pas encore transfere
        # quand `get_object` rend la main. Le laisser hors du thread ramenerait
        # dans la boucle d'evenements precisement ce que ce fichier en sort.
        return await self._call(
            lambda: response["Body"].read(),
            operation="lecture",
            key=key,
        )

    async def delete(self, key: str) -> bool:
        """Retire un objet. Voir le port pour le contrat.

        DEUX ALLERS-RETOURS, ET C'EST LE PRIX D'UN RETOUR HONNETE. S3 repond `204`
        a une suppression, que l'objet ait existe ou non : sans le `head_object`
        prealable, cette methode ne pourrait que rendre `True` en permanence, ce
        qui reviendrait a ne rien rendre du tout.

        Course connue, et sans consequence ici : un objet supprime par quelqu'un
        d'autre entre les deux appels fait rendre `True` a tort. Le fichier est
        parti dans les deux cas -- c'est un compte rendu imprecis, jamais un etat
        incoherent.
        """
        validate_storage_key(key)
        existed = await self.exists(key)
        await self._call(
            lambda: self._client.delete_object(Bucket=self._bucket, Key=key),
            operation="suppression",
            key=key,
        )
        return existed

    async def exists(self, key: str) -> bool:
        """Dit si un objet est present. Voir le port pour le contrat."""
        validate_storage_key(key)
        try:
            await self._call(
                lambda: self._client.head_object(Bucket=self._bucket, Key=key),
                operation="presence",
                key=key,
            )
        except StoredFileNotFoundError:
            # LE SEUL `except` DU FICHIER QUI AVALE UNE ERREUR, et il n'avale que
            # celle-la : une absence est la reponse normale de cette methode. Une
            # panne, elle, continue de remonter -- c'est ce qui distingue « ce
            # document n'existe pas » de « je ne sais pas s'il existe ».
            return False
        return True

    def generate_presigned_url(
        self,
        key: str,
        *,
        expires_in: int | None = None,
        operation: PresignedOperation = PresignedOperation.DOWNLOAD,
        content_type: str | None = None,
    ) -> str:
        """Emet une URL temporaire. Voir le port pour le contrat.

        SYNCHRONE, ET SANS `to_thread`. Signer n'appelle personne : botocore
        calcule une empreinte a partir de la cle secrete, de la date et du verbe.
        La faire passer par un thread ajouterait le cout d'un basculement a une
        operation qui n'attend rien.

        LIMITE D'EXPLOITATION A CONNAITRE. L'URL porte l'HOTE de `endpoint_url`.
        Dans la pile Docker, c'est `http://minio:9000`, qui n'est resolvable que
        depuis `app_network` : une URL emise par l'API en conteneur n'est PAS
        ouvrable depuis le navigateur du poste. C'est sans consequence tant
        qu'aucune route ne la publie ; le ticket qui exposera ces URLs au frontend
        devra distinguer l'endpoint INTERNE de l'endpoint PUBLIC -- ce que le
        present ticket ecarte, ayant pose qu'un seul parametre separe MinIO
        d'Amazon.
        """
        validate_storage_key(key)
        seconds = self._default_expires_in if expires_in is None else expires_in
        if seconds <= 0:
            message = (
                f"La duree de validite d'une URL pre-signee doit etre strictement "
                f"positive, recu {seconds} : une URL qui n'expire pas n'est pas exprimable."
            )
            raise ValueError(message)
        if seconds > MAX_PRESIGNED_EXPIRE_SECONDS:
            message = (
                f"Duree de validite de {seconds} secondes refusee : la signature V4 "
                f"plafonne a {MAX_PRESIGNED_EXPIRE_SECONDS} secondes (sept jours). "
                "Au-dela, le stockage refuserait l'URL sans en dire la raison."
            )
            raise ValueError(message)
        params: dict[str, str] = {"Bucket": self._bucket, "Key": key}
        match operation:
            case PresignedOperation.UPLOAD:
                if content_type is None:
                    message = (
                        "Une URL pre-signee de televersement exige son type MIME : sans "
                        "lui, le depot direct echapperait entierement a la politique."
                    )
                    raise ValueError(message)
                # Valide PUIS epingle dans la signature : le stockage refusera un
                # depot qui annonce un autre type. La borne de TAILLE, elle, reste
                # inatteignable par ce chemin -- voir la docstring du port.
                self._policy.validate(b"", content_type)
                params["ContentType"] = content_type
                client_method = "put_object"
            case PresignedOperation.DOWNLOAD:
                if content_type is not None:
                    message = (
                        "Une URL pre-signee de telechargement n'accepte pas de type MIME : "
                        "l'objet porte deja le sien, pose a son depot."
                    )
                    raise ValueError(message)
                client_method = "get_object"
        return self._client.generate_presigned_url(
            ClientMethod=client_method,
            Params=params,
            ExpiresIn=seconds,
        )

    async def ping(self) -> bool:
        """Sonde le bucket au demarrage, sans jamais empecher le demarrage.

        Le pendant de `RedisCache.ping()`, et pour la meme raison : l'exploitant
        doit voir la panne dans la ligne de demarrage plutot qu'a la premiere
        piece jointe. La difference avec le cache est ce qui se passe ENSUITE --
        ici, les operations levent.

        `head_bucket` et non un listage : c'est la seule sonde qui verifie a la
        fois que l'endpoint repond, que les clefs d'acces sont bonnes et que le
        bucket existe, sans rien lire de son contenu.

        Returns:
            Vrai si le bucket a repondu.
        """
        try:
            await asyncio.to_thread(lambda: self._client.head_bucket(Bucket=self._bucket))
        except (ClientError, *_UNREACHABLE) as error:
            _LOGGER.warning(
                "Stockage objet injoignable sur %s (demarrage) : les operations sur "
                "les fichiers ECHOUERONT tant que la panne dure. %s",
                self._target,
                error,
            )
            return False
        _LOGGER.info("Stockage objet joignable sur %s.", self._target)
        return True

    async def aclose(self) -> None:
        """Ferme le client, sans jamais lever.

        Le `suppress` n'est pas de la superstition : cette methode est appelee
        depuis le `finally` du `lifespan`, et une exception levee ici sauterait la
        fermeture du cache et le `engine.dispose()` qui suivent -- ce qui ferait
        fuir le pool PostgreSQL a chaque redemarrage de conteneur.
        """
        with suppress(*_UNREACHABLE):
            await asyncio.to_thread(self._client.close)

    async def _call[T](self, action: Callable[[], T], *, operation: str, key: str) -> T:
        """Execute un appel boto3 hors de la boucle, et traduit ce qui en sort.

        LE SEUL ENDROIT DU SERVICE QUI CONNAISSE LES EXCEPTIONS DE boto3. C'est ce
        qui rend vraie la promesse du port : un cas d'usage attrape
        `FileStorageError` sans importer la bibliotheque du fournisseur, et le
        jour ou l'adaptateur change, ses `except` tiennent encore.

        Args:
            action: l'appel boto3, sans argument -- une lambda qui capture ce
                qu'il lui faut.
            operation: le mot francais qui nommera l'operation dans le message.
            key: la cle concernee, pour que le message dise sur quoi.

        Returns:
            Ce que rend l'appel, tel quel.

        Raises:
            StoredFileNotFoundError: si le serveur dit que l'objet n'existe pas.
            FileStorageUnavailableError: pour tout le reste -- panne, refus
                d'autorisation, bucket absent.
        """
        try:
            return await asyncio.to_thread(action)
        except ClientError as error:
            raise self._translate(error, operation=operation, key=key) from error
        except _UNREACHABLE as error:
            message = (
                f"Stockage objet injoignable sur {self._target} ({operation} de {key!r}) : {error}"
            )
            raise FileStorageUnavailableError(message) from error

    def _translate(self, error: ClientError, *, operation: str, key: str) -> Exception:
        """Traduit une reponse d'erreur du serveur en exception du domaine.

        Args:
            error: l'erreur levee par boto3, qui porte la reponse du serveur.
            operation: le mot francais qui nommera l'operation.
            key: la cle concernee.

        Returns:
            L'exception du domaine a lever. RENDUE et non levee, pour que
            l'appelant ecrive `raise ... from error` et conserve la cause.
        """
        response = error.response
        code = str(response.get("Error", {}).get("Code", ""))
        status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        # Le statut EN PLUS du code : `head_object` ne renvoie aucun corps, donc
        # aucun code a lire, et botocore y reporte le statut nu. Les deux sources
        # sont interrogees parce qu'aucune n'est presente a tous les coups.
        if code in _NOT_FOUND_CODES or status == _HTTP_NOT_FOUND:
            message = f"Aucun objet a la cle {key!r} dans {self._target}."
            return StoredFileNotFoundError(message)
        message = (
            f"Le stockage objet a refuse l'operation de {operation} sur {key!r} "
            f"({self._target}) : {code or status or 'motif inconnu'}."
        )
        return FileStorageUnavailableError(message)


def build_file_storage(settings: Settings) -> S3FileStorage:
    """Construit le client S3, sans ouvrir la moindre connexion.

    Comme `build_engine` et `build_cache`, construire ne connecte pas : la
    premiere connexion nait au premier appel, et c'est `ping()` qui la provoque au
    moment choisi par le `lifespan`.

    Args:
        settings: la configuration du service, dont la section S3.

    Returns:
        Le stockage, pret a etre range dans `app.state`.
    """
    client = boto3.client(
        "s3",
        # VIDE en production : boto3 calcule alors l'endpoint Amazon a partir de
        # la region. `or None` et non la valeur telle quelle -- une chaine vide
        # lue d'un `.env` serait prise pour une URL et ferait echouer la
        # construction du client.
        endpoint_url=settings.s3.endpoint_url or None,
        region_name=settings.s3.region,
        aws_access_key_id=settings.s3.access_key.get_secret_value(),
        aws_secret_access_key=settings.s3.secret_key.get_secret_value(),
        config=Config(
            # Exigee par MinIO, et de toute facon la seule que signent les
            # regions Amazon ouvertes apres 2014. L'ecrire evite de dependre du
            # defaut de la version de botocore installee.
            signature_version="s3v4",
            s3={
                # `path` et non `virtual` : le style par defaut place le bucket
                # dans le NOM D'HOTE, ce qui donnerait `juui-dev.minio:9000` --
                # un nom que le resolveur d'`app_network` ne connait pas, et
                # qu'aucun certificat ne couvrirait devant un MinIO en HTTPS.
                "addressing_style": "path",
            },
            connect_timeout=_CONNECT_TIMEOUT_SECONDS,
            read_timeout=_READ_TIMEOUT_SECONDS,
            retries={"max_attempts": _MAX_ATTEMPTS, "mode": "standard"},
            # Pendant de l'`application_name` de BACK-05 et du `client_name` de
            # BACK-14 : c'est ce qui distingue l'API du worker TaskIQ dans les
            # journaux d'acces du stockage, le jour ou il faut comprendre qui
            # ecrit quoi.
            user_agent_extra=f"juui-api-storage/{settings.app.environment}",
        ),
    )
    return S3FileStorage(
        client=client,
        bucket=settings.s3.bucket,
        # L'endpoint et le bucket, JAMAIS les clefs d'acces : un message d'erreur
        # finit toujours recopie quelque part. Meme regle qu'en BACK-05 et
        # BACK-14. `endpoint_url` vide donne « Amazon S3 », qui est exact.
        target=f"{settings.s3.endpoint_url or 'Amazon S3'}/{settings.s3.bucket}",
    )


def get_file_storage(request: Request) -> FileStorage:
    """Retourne le stockage ouvert par le `lifespan`.

    Meme forme que `get_database` (BACK-05) et `get_cache` (BACK-14). L'`isinstance`
    porte sur le PORT et non sur `S3FileStorage` : c'est ce qui laisse BACK-06c
    ranger une doublure en memoire dans `app.state` sans toucher a ce fichier. Il
    est de toute facon obligatoire, `app.state` etant type `Any`.

    Args:
        request: la requete en cours, d'ou l'on remonte a l'application.

    Returns:
        Le stockage objet du processus.

    Raises:
        RuntimeError: si le `lifespan` n'a pas tourne.
    """
    storage = getattr(request.app.state, STORAGE_STATE_KEY, None)
    if not isinstance(storage, FileStorage):
        message = (
            "Le stockage objet n'est pas ouvert : l'application a-t-elle ete "
            "construite sans son lifespan ?"
        )
        raise RuntimeError(message)
    return storage
