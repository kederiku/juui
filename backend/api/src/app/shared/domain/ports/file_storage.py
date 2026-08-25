"""Port du stockage objet et sa politique d'upload (BACK-13).

Le contrat, jamais son adaptateur : ce module ne connait ni boto3, ni MinIO, ni
Amazon S3, ni la configuration. Il ne peut d'ailleurs pas les connaitre -- le
contrat `domain-purity` de BACK-04b interdit au domaine d'importer une dependance
applicative, `app.core` compris, et il refuse aussi les chaines INDIRECTES. C'est
cette contrainte, et non un gout pour l'abstraction, qui met la composition des
cles physiques et la construction du client dans l'adaptateur.

CE QUE CE PORT PROMET, ET EN QUOI IL DIFFERE DU CACHE
Les deux ports techniques du noyau partage se ressemblent de loin -- une `ABC`,
des methodes asynchrones, un adaptateur remplacable -- et se comportent a
l'oppose devant une panne. `Cache` DEGRADE : Redis absent, `get` rend `MISSING`
et le service repond plus lentement, sans qu'aucun resultat change. `FileStorage`
LEVE, toujours, parce qu'un stockage absent change les resultats :

- un `upload` qui ne leverait pas serait un fichier PERDU, et l'appelant aurait
  deja repondu « enregistre » a l'utilisateur ;
- un `exists` qui rendrait `False` sur panne declarerait inexistant un document
  de sante qui existe.

Aucune des cinq operations n'a donc de valeur de repli. Relire cette page avant
d'ecrire un `except FileStorageError: pass` quelque part.

POURQUOI LES URLS PRE-SIGNEES SONT LA VOIE PRINCIPALE
Une URL pre-signee porte son autorisation et sa date d'expiration dans sa
signature : le navigateur parle DIRECTEMENT au stockage, et l'octet du fichier ne
traverse jamais l'API. Faire transiter les fichiers par les workers reviendrait a
occuper une boucle d'evenements entiere pendant le televersement d'une
radiographie -- c'est-a-dire a payer en disponibilite ce que le stockage objet
sait faire gratuitement. `upload` et `download` restent offerts pour ce que le
serveur traite lui-meme ; ils ne sont pas le chemin par defaut.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from app.shared.domain.exceptions import DomainError


class FileStorageError(DomainError):
    """Racine des erreurs du stockage objet.

    Toutes les erreurs que ce port laisse sortir descendent d'ici, et AUCUNE
    exception de boto3 n'en sort : c'est la promesse qui permet a un cas d'usage
    d'attraper `FileStorageError` sans jamais importer la bibliotheque du
    fournisseur. Le jour ou l'adaptateur change, les `except` du metier tiennent.
    """


class StoredFileNotFoundError(FileStorageError):
    """La cle demandee ne designe aucun objet du bucket.

    Nommee `Stored...` et non `FileNotFoundError` : ce dernier est un builtin, et
    la regle Ruff `A` refuse de le masquer. L'ecart de nom est preferable a une
    classe qui, attrapee par megarde, avalerait aussi les erreurs du systeme de
    fichiers local.
    """


class FileTooLargeError(FileStorageError):
    """Le contenu depasse la taille maximale autorisee par la politique."""


class UnsupportedContentTypeError(FileStorageError):
    """Le type MIME annonce n'est pas accepte par la politique."""


class InvalidStorageKeyError(FileStorageError):
    """La cle ne respecte pas la convention de nommage, ou tente d'en sortir.

    Levee notamment quand une cle contient `..`, commence par une barre ou porte
    un octet de controle. Ce n'est pas un exces de prudence : le seul
    cloisonnement des fichiers d'une entite est leur PREFIXE de cle, et un
    `../../` bien place le traverse.
    """


class FileStorageUnavailableError(FileStorageError):
    """Le stockage objet est injoignable, ou refuse la requete.

    Volontairement distincte de `StoredFileNotFoundError` : celle-la dit « cet
    objet n'existe pas », celle-ci dit « je ne sais pas s'il existe ». Les
    confondre ferait supprimer d'une base la reference d'un fichier parfaitement
    intact, au seul motif que le reseau avait hoquete.
    """


class PresignedOperation(StrEnum):
    """Ce qu'une URL pre-signee autorise a faire, et rien d'autre.

    La signature enferme le verbe HTTP : une URL de telechargement ne permet PAS
    de televerser, et reciproquement. Deux valeurs plutot qu'un booleen, pour que
    l'appel se lise a la relecture -- `operation=PresignedOperation.UPLOAD` dit ce
    que `write=True` laisserait deviner.
    """

    DOWNLOAD = "download"
    UPLOAD = "upload"


@dataclass(frozen=True, slots=True)
class UploadPolicy:
    """Ce qu'un upload doit respecter AVANT que le reseau ne soit sollicite.

    Une regle du DOMAINE, et c'est pourquoi elle vit ici : « quels fichiers ce
    service accepte-t-il ? » ne depend ni de S3, ni de MinIO, ni du fournisseur
    suivant. L'adaptateur recoit une politique, il n'en invente aucune.

    Gelee : une politique partagee par tout un processus n'a aucune raison d'etre
    mutable, et une politique qu'un appelant pourrait elargir a la volee ne serait
    plus une politique.
    """

    max_bytes: int
    allowed_content_types: frozenset[str]

    def validate(self, content: bytes, content_type: str) -> None:
        """Refuse un contenu non conforme, avant tout appel reseau.

        L'ORDRE COMPTE : le type est verifie avant la taille. Un fichier de 40 Mo
        au format refuse doit s'entendre dire que le format est refuse -- lui
        repondre « trop volumineux » enverrait l'utilisateur le compresser en
        vain.

        Args:
            content: les octets a televerser.
            content_type: le type MIME annonce, sans parametres (`; charset=...`
                est retire par l'appelant, qui seul sait d'ou vient l'en-tete).

        Raises:
            UnsupportedContentTypeError: si le type n'est pas dans la liste.
            FileTooLargeError: si le contenu depasse `max_bytes`.
        """
        if content_type not in self.allowed_content_types:
            autorises = ", ".join(sorted(self.allowed_content_types))
            message = f"Type de fichier refuse : {content_type!r}. Types acceptes : {autorises}."
            raise UnsupportedContentTypeError(message)
        if len(content) > self.max_bytes:
            message = (
                f"Fichier trop volumineux : {len(content)} octets pour un maximum "
                f"de {self.max_bytes}."
            )
            raise FileTooLargeError(message)


# Taille maximale par defaut : 20 Mio.
#
# Le chiffre vient du pire cas REEL du domaine, et non d'une valeur ronde : un
# compte rendu de sante scanne en plusieurs pages pese couramment plus de 10 Mio,
# la ou une photo d'animal depasse rarement 5 Mio. Une borne trop basse ne
# protegerait rien -- elle rendrait le service inutilisable pour le document
# qu'il existe pour transporter.
_DEFAULT_MAX_UPLOAD_BYTES: Final = 20 * 1024 * 1024

# Types acceptes par defaut : ce qu'un dossier veterinaire transporte.
#
# `image/heic` n'y figure PAS, et c'est une lacune CONNUE plutot qu'un oubli :
# c'est le format natif des photos d'iPhone. L'accepter sans conversion cote
# serveur donnerait des fichiers que ni les navigateurs ni les visionneuses de
# bureau n'affichent -- le ticket qui exposera la route de televersement devra
# trancher entre convertir a l'arrivee et convertir dans le navigateur.
_DEFAULT_ALLOWED_CONTENT_TYPES: Final = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "application/pdf",
    }
)

# Politique appliquee quand la fabrique de l'adaptateur n'en impose pas d'autre.
DEFAULT_UPLOAD_POLICY: Final = UploadPolicy(
    max_bytes=_DEFAULT_MAX_UPLOAD_BYTES,
    allowed_content_types=_DEFAULT_ALLOWED_CONTENT_TYPES,
)


class FileStorage(ABC):
    """Stockage objet : depot de fichiers adressables par une cle.

    QUATRE REGLES QUI ENGAGENT L'APPELANT

    1. AUCUNE OPERATION NE DEGRADE. Voir la docstring de module : un stockage
       injoignable leve `FileStorageUnavailableError`, il ne rend jamais une
       valeur de repli. C'est l'inverse exact du port `Cache`, et l'asymetrie est
       le sujet.

    2. LES CLES SONT COMPLETES ET VALIDEES. Contrairement au cache, dont les cles
       sont LOGIQUES et prefixees par l'adaptateur, une cle de stockage est celle
       qui sera PERSISTEE en base : elle ne depend d'aucun contexte d'execution.
       C'est ce qui la rend relisible depuis une tache de fond, ou apres qu'un
       veterinaire remplacant a change de structure. La composer correctement est
       le travail de `StorageKeyBuilder`, cote infrastructure.

    3. LE CLOISONNEMENT ENTRE GROUPES N'EST PAS DANS LE NOMMAGE. Aucun segment de
       tenance n'entre dans les cles -- voir la regle 2, une cle persistee ne peut
       pas dependre d'une contextvar de requete. Qui a le droit de lire ce fichier
       est une question d'AUTORISATION, tranchee avant qu'une URL pre-signee ne
       soit emise. Ne jamais traiter l'opacite d'un UUID comme un controle
       d'acces.

    4. LA VALIDATION PRECEDE LE RESEAU. `upload` applique sa `UploadPolicy` avant
       le premier octet emis. Une URL pre-signee d'upload, elle, ECHAPPE a la
       borne de taille -- lire `generate_presigned_url`.
    """

    @abstractmethod
    async def upload(self, key: str, content: bytes, content_type: str) -> None:
        """Depose un objet, apres validation de son type et de sa taille.

        Ecrase silencieusement un objet de meme cle : c'est la semantique de S3,
        qui n'a pas de « creer seulement si absent ». Un appelant qui tient a ne
        pas ecraser interroge `exists` d'abord, en sachant que rien ne rend les
        deux appels atomiques.

        Args:
            key: la cle complete, telle que `StorageKeyBuilder` l'a composee.
            content: les octets du fichier.
            content_type: le type MIME, conserve sur l'objet -- c'est lui que le
                navigateur relira a travers une URL pre-signee, et donc lui qui
                decide entre afficher et telecharger.

        Raises:
            InvalidStorageKeyError: si la cle ne respecte pas la convention.
            UnsupportedContentTypeError: si le type MIME est refuse.
            FileTooLargeError: si le contenu depasse la taille maximale.
            FileStorageUnavailableError: si le stockage est injoignable.
        """

    @abstractmethod
    async def download(self, key: str) -> bytes:
        """Relit un objet EN ENTIER, en memoire.

        Reservee a ce que le serveur traite lui-meme -- verifier une signature,
        produire une vignette. Pour servir un fichier a un utilisateur, passer par
        `generate_presigned_url` : relire 20 Mio en memoire pour les reemettre
        aussitot occupe un worker que rien n'obligeait a l'etre.

        Args:
            key: la cle complete de l'objet.

        Returns:
            Les octets de l'objet.

        Raises:
            InvalidStorageKeyError: si la cle ne respecte pas la convention.
            StoredFileNotFoundError: si aucun objet ne porte cette cle.
            FileStorageUnavailableError: si le stockage est injoignable.
        """

    @abstractmethod
    async def delete(self, key: str) -> bool:
        """Retire un objet. Ne se plaint pas s'il n'existait pas.

        Args:
            key: la cle complete de l'objet.

        Returns:
            Vrai si un objet a effectivement ete retire. La valeur demande un
            aller-retour de plus que la suppression seule, S3 repondant `204` que
            l'objet ait existe ou non : c'est le prix d'un retour qui ne ment pas.

        Raises:
            InvalidStorageKeyError: si la cle ne respecte pas la convention.
            FileStorageUnavailableError: si le stockage est injoignable.
        """

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Dit si un objet est present.

        Args:
            key: la cle complete de l'objet.

        Returns:
            Vrai si l'objet repond. JAMAIS `False` par defaut de disponibilite --
            relire la regle 1 : l'absence de reponse leve.

        Raises:
            InvalidStorageKeyError: si la cle ne respecte pas la convention.
            FileStorageUnavailableError: si le stockage est injoignable.
        """

    @abstractmethod
    def generate_presigned_url(
        self,
        key: str,
        *,
        expires_in: int | None = None,
        operation: PresignedOperation = PresignedOperation.DOWNLOAD,
        content_type: str | None = None,
    ) -> str:
        """Emet une URL temporaire donnant un acces direct au stockage.

        SYNCHRONE, ET C'EST LE POINT IMPORTANT. Signer une URL ne demande aucun
        appel reseau : c'est un calcul local a partir de la cle secrete, de la
        date et du verbe. La seule des cinq operations a ne rien attendre est
        aussi celle dont le service se sert le plus -- c'est ce qui rend le
        chemin principal du stockage objet gratuit pour l'API.

        POURQUOI UNE URL D'UPLOAD EXIGE SON TYPE MIME
        Sans lui, le chemin principal du ticket echapperait entierement a la
        `UploadPolicy` : le navigateur parle directement au stockage, et l'API
        n'est plus la pour regarder ce qui passe. Le type est donc valide ICI,
        puis EPINGLE dans la signature -- un televersement qui annonce un autre
        `Content-Type` est refuse par le stockage lui-meme. Le rendre facultatif
        aurait fait de la validation une politesse.

        CE QU'UNE URL D'UPLOAD NE PEUT TOUJOURS PAS FAIRE
        Plafonner la TAILLE. Une URL pre-signee de type PUT n'emporte aucune
        condition sur la longueur du corps, et il n'existe aucun moyen de lui en
        ajouter : seul un formulaire pre-signe (POST, avec une condition
        `content-length-range` dans sa policy) l'exprimerait. `max_bytes` ne
        s'applique donc qu'a `upload`. Le ticket qui exposera la route de
        televersement direct devra le savoir -- et, s'il tient a la borne, passer
        au formulaire pre-signe plutot que de croire cette URL suffisante.

        Args:
            key: la cle complete de l'objet.
            expires_in: duree de validite en secondes. `None` reprend le defaut
                configure par l'adaptateur.
            operation: ce que l'URL autorise. Telechargement par defaut.
            content_type: le type MIME du fichier a deposer. EXIGE quand
                `operation` vaut `UPLOAD`, refuse sinon -- une URL de
                telechargement rend le type que porte deja l'objet.

        Returns:
            L'URL signee, valable jusqu'a son expiration.

        Raises:
            InvalidStorageKeyError: si la cle ne respecte pas la convention.
            UnsupportedContentTypeError: si le type annonce pour un upload n'est
                pas accepte par la politique.
            ValueError: si `expires_in` n'est pas strictement positif -- une URL
                qui n'expire pas n'est pas exprimable, et c'est voulu -- ou si
                `content_type` est absent pour un upload, ou fourni pour un
                telechargement.
        """
