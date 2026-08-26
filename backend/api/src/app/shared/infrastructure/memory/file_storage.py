"""Doublure en memoire du port `FileStorage` (BACK-06c).

Cinq operations, un dictionnaire, et AUCUN MinIO. La suite
`tests/shared/conformance/test_file_storage_conformance.py` la joue contre
l'adaptateur reel pour que les deux ne divergent pas.

LA VALIDATION DES CLES EST CELLE DE LA PRODUCTION
`validate_storage_key` est appelee sur CHAQUE cle recue, comme dans
`s3_storage.py`. Une doublure qui accepterait `../../evasion.pdf` laisserait
passer en test la traversee de prefixe que le vrai adaptateur refuse -- et le
seul cloisonnement des fichiers d'une entite est justement leur prefixe de cle.
Meme parti pour la `UploadPolicy` : type puis taille, avant tout depot.

ELLE NE DEGRADE JAMAIS, ET C'EST LE SUJET
Le port l'ecrit en premiere regle, a rebours du cache : un `upload` silencieux
est un fichier PERDU, un `exists` qui rendrait `False` sur panne declarerait
inexistant un document de sante qui existe. `unavailable=True` fait donc LEVER
`FileStorageUnavailableError` sur les quatre operations asynchrones, la ou la
meme option fait DEGRADER `InMemoryCache`. Les deux doublures sont volontairement
dissymetriques : c'est la dissymetrie des ports qu'elles servent.

L'URL PRE-SIGNEE EST FACTICE, SES CONTROLES NE LE SONT PAS
Signer sans secret n'a pas de sens ; la doublure rend donc une URL `memory://`
reconnaissable. Ce qui PRECEDE la signature, en revanche, est reproduit a
l'identique -- cle validee, duree strictement positive et bornee a sept jours,
type MIME exige pour un televersement et refuse pour un telechargement, politique
appliquee au type annonce. C'est la partie que le service peut se tromper a
ecrire ; la signature elle-meme appartient a botocore.
"""

from typing import Final

from app.shared.domain.ports.file_storage import (
    DEFAULT_UPLOAD_POLICY,
    FileStorage,
    FileStorageUnavailableError,
    PresignedOperation,
    StoredFileNotFoundError,
    UploadPolicy,
)
from app.shared.infrastructure.clients.s3_storage import (
    DEFAULT_PRESIGNED_EXPIRE_SECONDS,
    MAX_PRESIGNED_EXPIRE_SECONDS,
)
from app.shared.infrastructure.clients.storage_keys import validate_storage_key

# Bucket par defaut de la doublure. Un nom qui ne peut pas etre confondu avec
# celui de MinIO ou d'Amazon dans un message d'erreur recopie quelque part.
_DEFAULT_BUCKET: Final = "memory-bucket"


class InMemoryFileStorage(FileStorage):
    """Stockage objet en memoire : des octets et un type MIME, par cle.

    Le type MIME est conserve SUR L'OBJET, comme le fait S3 : c'est lui que le
    navigateur relit a travers une URL pre-signee, donc lui qui decide entre
    afficher et telecharger. Une doublure qui ne garderait que les octets ferait
    passer en test un enregistrement qui perd cette information.
    """

    def __init__(
        self,
        *,
        bucket: str = _DEFAULT_BUCKET,
        policy: UploadPolicy = DEFAULT_UPLOAD_POLICY,
        default_expires_in: int = DEFAULT_PRESIGNED_EXPIRE_SECONDS,
        unavailable: bool = False,
    ) -> None:
        """Assemble la doublure, vide.

        Args:
            bucket: le nom du bucket, repris dans les URLs factices.
            policy: ce qu'un upload doit respecter. Celle du port par defaut,
                comme cote reel.
            default_expires_in: duree de validite appliquee quand l'appelant n'en
                donne pas. Le MEME defaut que l'adaptateur S3, importe de lui.
            unavailable: si vrai, les quatre operations asynchrones levent
                `FileStorageUnavailableError`. Ce port ne degrade pas.
        """
        self._bucket = bucket
        self._policy = policy
        self._default_expires_in = default_expires_in
        self.unavailable = unavailable
        self._objects: dict[str, tuple[bytes, str]] = {}

    @property
    def target(self) -> str:
        """Ce qui apparait dans les messages, a la place d'un endpoint reel."""
        return f"memory://{self._bucket}"

    def keys(self) -> list[str]:
        """Rend les cles presentes, triees -- pour les assertions.

        Returns:
            Les cles des objets ranges, dans l'ordre alphabetique.
        """
        return sorted(self._objects)

    async def upload(self, key: str, content: bytes, content_type: str) -> None:
        """Depose un objet, apres validation. Voir le port pour le contrat."""
        validate_storage_key(key)
        # AVANT le stockage, et dans cet ordre : le type d'abord, la taille
        # ensuite -- un fichier de quarante mebioctets au format refuse doit
        # s'entendre dire que le format est refuse.
        self._policy.validate(content, content_type)
        self._require_available("depot", key)
        # Ecrase silencieusement un objet de meme cle : c'est la semantique de S3,
        # qui n'a pas de « creer seulement si absent ».
        self._objects[key] = (content, content_type)

    async def download(self, key: str) -> bytes:
        """Relit un objet en entier. Voir le port pour le contrat."""
        validate_storage_key(key)
        self._require_available("lecture", key)
        stored = self._objects.get(key)
        if stored is None:
            message = f"Aucun objet ne porte la cle {key!r} dans {self.target}."
            raise StoredFileNotFoundError(message)
        return stored[0]

    def stored_content_type(self, key: str) -> str:
        """Rend le type MIME conserve sur l'objet -- inspecteur, hors du port.

        HORS DE LA SUITE DE CONFORMITE, et il faut savoir pourquoi : le port
        n'expose pas cette lecture -- c'est le stockage qui rend le type au
        navigateur, jamais l'API --, l'adaptateur S3 n'a donc pas d'equivalent a
        comparer. Ce que cette methode permet est plus modeste et suffit : prouver
        que la doublure ne PERD pas le type, sans quoi le ticket qui exposera le
        televersement testerait sur un stockage qui oublie ce que S3 conserve.

        Args:
            key: la cle complete de l'objet.

        Returns:
            Le type MIME depose avec l'objet.

        Raises:
            StoredFileNotFoundError: si aucun objet ne porte cette cle.
        """
        validate_storage_key(key)
        stored = self._objects.get(key)
        if stored is None:
            message = f"Aucun objet ne porte la cle {key!r} dans {self.target}."
            raise StoredFileNotFoundError(message)
        return stored[1]

    async def delete(self, key: str) -> bool:
        """Retire un objet. Voir le port pour le contrat."""
        validate_storage_key(key)
        self._require_available("suppression", key)
        return self._objects.pop(key, None) is not None

    async def exists(self, key: str) -> bool:
        """Dit si un objet est present. Voir le port pour le contrat."""
        validate_storage_key(key)
        self._require_available("presence", key)
        return key in self._objects

    def generate_presigned_url(
        self,
        key: str,
        *,
        expires_in: int | None = None,
        operation: PresignedOperation = PresignedOperation.DOWNLOAD,
        content_type: str | None = None,
    ) -> str:
        """Emet une URL factice, apres les VRAIS controles. Voir le port.

        SYNCHRONE ET SANS CONTROLE DE DISPONIBILITE, comme cote reel : signer
        n'appelle personne. Une URL peut donc etre emise pour un stockage
        injoignable -- c'est vrai en production aussi, et c'est ce qui rend le
        chemin principal du stockage objet gratuit pour l'API.
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
        match operation:
            case PresignedOperation.UPLOAD:
                if content_type is None:
                    message = (
                        "Une URL pre-signee de televersement exige son type MIME : sans "
                        "lui, le depot direct echapperait entierement a la politique."
                    )
                    raise ValueError(message)
                # Le contenu vide passe la borne de taille : c'est le TYPE qu'on
                # valide ici, comme cote reel avant de l'epingler dans la signature.
                self._policy.validate(b"", content_type)
            case PresignedOperation.DOWNLOAD:
                if content_type is not None:
                    message = (
                        "Une URL pre-signee de telechargement n'accepte pas de type MIME : "
                        "l'objet porte deja le sien, pose a son depot."
                    )
                    raise ValueError(message)
        return f"{self.target}/{key}?operation={operation.value}&expires_in={seconds}"

    async def ping(self) -> bool:
        """Dit si la doublure repond, sans jamais lever.

        Returns:
            Faux seulement quand l'indisponibilite est simulee.
        """
        return not self.unavailable

    def _require_available(self, operation: str, key: str) -> None:
        """Leve si l'indisponibilite est simulee -- ce port ne degrade jamais.

        Args:
            operation: le geste tente, pour le message.
            key: la cle visee.

        Raises:
            FileStorageUnavailableError: si l'indisponibilite est simulee.
        """
        if self.unavailable:
            message = (
                f"Stockage objet simule injoignable sur {self.target} : "
                f"{operation} de {key!r} impossible."
            )
            raise FileStorageUnavailableError(message)
