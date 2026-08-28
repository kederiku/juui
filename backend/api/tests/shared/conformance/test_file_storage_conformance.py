"""Conformite du stockage objet : MinIO et la doublure en memoire (BACK-06c).

Une seule suite, deux sujets. `TestS3FileStorageConformance` la joue contre le
MinIO du poste, `TestInMemoryFileStorageConformance` contre
`InMemoryFileStorage`. Ce qui est compare est le contrat du port : la validation
des cles avant tout acces, l'ordre des controles d'upload, la semantique
d'ecrasement de S3, et les refus de `generate_presigned_url`.

CE QUE LA SUITE NE COMPARE PAS
Le contenu de l'URL pre-signee -- l'une est signee par botocore, l'autre est un
`memory://` reconnaissable. Ce qui est compare est ce que le SERVICE peut se
tromper a ecrire : les controles qui precedent la signature. La signature
elle-meme n'appartient a personne ici.

Ni la reponse a la panne : la simuler d'un cote demanderait d'arreter MinIO de
l'autre. Elle est eprouvee sur la seule doublure, dans `tests/shared/memory/`.

LES CLES SONT TIREES AU HASARD sous un prefixe `conformance`, et ce que chaque
test depose est retire en sortie -- le bucket du poste ne se remplit pas.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import suppress
from uuid import uuid4

import pytest
import pytest_asyncio

from app.core import get_settings
from app.shared.domain.ports.file_storage import (
    FileStorage,
    FileStorageError,
    FileTooLargeError,
    InvalidStorageKeyError,
    PresignedOperation,
    StoredFileNotFoundError,
    UnsupportedContentTypeError,
)
from app.shared.infrastructure.clients.s3_storage import (
    MAX_PRESIGNED_EXPIRE_SECONDS,
    build_file_storage,
)
from app.shared.infrastructure.clients.storage_keys import build_storage_key
from app.shared.infrastructure.memory.file_storage import InMemoryFileStorage
from tests.conftest import require_service

pytestmark = pytest.mark.conformance

_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def a_key(filename: str = "radio.png") -> str:
    """Une cle conforme a la convention, sous un prefixe propre a la suite."""
    return build_storage_key("conformance", uuid4(), filename)


class FileStorageConformance:
    """La suite commune. Les sous-classes ne fournissent que la fixture `storage`."""

    @pytest.fixture
    def storage(self) -> FileStorage:
        """Le sujet sous test -- fourni par la sous-classe."""
        raise NotImplementedError

    @pytest_asyncio.fixture
    async def uploaded(self, storage: FileStorage) -> AsyncIterator[list[str]]:
        """Les cles deposees par le test, retirees a sa sortie.

        Le nettoyage est AU MIEUX : un test qui a deja supprime sa cle, ou qui a
        echoue avant de la deposer, ne doit pas faire echouer le teardown par
        dessus son propre echec.
        """
        keys: list[str] = []
        yield keys
        for key in keys:
            with suppress(FileStorageError):
                await storage.delete(key)

    async def test_an_object_survives_the_round_trip(
        self, storage: FileStorage, uploaded: list[str]
    ) -> None:
        key = a_key()
        await storage.upload(key, _PNG, "image/png")
        uploaded.append(key)
        assert await storage.download(key) == _PNG

    async def test_exists_follows_upload_then_delete(
        self, storage: FileStorage, uploaded: list[str]
    ) -> None:
        key = a_key()
        assert await storage.exists(key) is False
        await storage.upload(key, _PNG, "image/png")
        uploaded.append(key)
        assert await storage.exists(key) is True
        assert await storage.delete(key) is True
        assert await storage.exists(key) is False

    async def test_deleting_an_absent_object_reports_false(self, storage: FileStorage) -> None:
        """Le retour ne ment pas, malgre le `204` que S3 rend dans les deux cas."""
        assert await storage.delete(a_key()) is False

    async def test_downloading_an_absent_object_raises(self, storage: FileStorage) -> None:
        with pytest.raises(StoredFileNotFoundError):
            await storage.download(a_key())

    async def test_an_upload_overwrites_the_same_key(
        self, storage: FileStorage, uploaded: list[str]
    ) -> None:
        """La semantique de S3 : pas de « creer seulement si absent »."""
        key = a_key()
        await storage.upload(key, _PNG, "image/png")
        uploaded.append(key)
        await storage.upload(key, b"remplace", "image/png")
        assert await storage.download(key) == b"remplace"

    async def test_a_traversing_key_is_refused(self, storage: FileStorage) -> None:
        """Le seul cloisonnement d'une entite est son prefixe : `..` le traverse."""
        with pytest.raises(InvalidStorageKeyError):
            await storage.exists("conformance/a/../../autre/dossier.pdf")

    async def test_an_absolute_key_is_refused(self, storage: FileStorage) -> None:
        with pytest.raises(InvalidStorageKeyError):
            await storage.exists("/conformance/dossier.pdf")

    async def test_an_empty_key_is_refused(self, storage: FileStorage) -> None:
        with pytest.raises(InvalidStorageKeyError):
            await storage.exists("")

    async def test_an_unsupported_content_type_is_refused(self, storage: FileStorage) -> None:
        with pytest.raises(UnsupportedContentTypeError):
            await storage.upload(a_key("script.sh"), b"#!/bin/sh", "application/x-sh")

    async def test_a_content_beyond_the_maximum_is_refused(self, storage: FileStorage) -> None:
        with pytest.raises(FileTooLargeError):
            await storage.upload(a_key(), b"0" * (21 * 1024 * 1024), "image/png")

    async def test_the_content_type_is_checked_before_the_size(self, storage: FileStorage) -> None:
        """Un fichier trop gros AU MAUVAIS FORMAT s'entend dire que le format est refuse.

        L'inverse enverrait l'utilisateur compresser en vain un fichier qui aurait
        ete refuse de toute facon.
        """
        with pytest.raises(UnsupportedContentTypeError):
            await storage.upload(a_key("gros.sh"), b"0" * (21 * 1024 * 1024), "application/x-sh")

    async def test_a_presigned_download_url_names_its_object(
        self, storage: FileStorage, uploaded: list[str]
    ) -> None:
        key = a_key()
        await storage.upload(key, _PNG, "image/png")
        uploaded.append(key)
        url = storage.generate_presigned_url(key)
        assert key.rsplit("/", maxsplit=1)[-1] in url

    async def test_a_presigned_upload_url_requires_its_content_type(
        self, storage: FileStorage
    ) -> None:
        """Sans lui, le depot direct echapperait entierement a la politique."""
        with pytest.raises(ValueError, match="type MIME"):
            storage.generate_presigned_url(a_key(), operation=PresignedOperation.UPLOAD)

    async def test_a_presigned_upload_url_refuses_an_unsupported_type(
        self, storage: FileStorage
    ) -> None:
        with pytest.raises(UnsupportedContentTypeError):
            storage.generate_presigned_url(
                a_key("script.sh"),
                operation=PresignedOperation.UPLOAD,
                content_type="application/x-sh",
            )

    async def test_a_presigned_download_url_refuses_a_content_type(
        self, storage: FileStorage
    ) -> None:
        with pytest.raises(ValueError, match="n'accepte pas"):
            storage.generate_presigned_url(a_key(), content_type="image/png")

    async def test_a_non_positive_expiry_is_refused(self, storage: FileStorage) -> None:
        """Une URL qui n'expire pas n'est pas exprimable, et c'est voulu."""
        with pytest.raises(ValueError, match="strictement positive"):
            storage.generate_presigned_url(a_key(), expires_in=0)

    async def test_an_expiry_beyond_the_protocol_ceiling_is_refused(
        self, storage: FileStorage
    ) -> None:
        with pytest.raises(ValueError, match="plafonne"):
            storage.generate_presigned_url(a_key(), expires_in=MAX_PRESIGNED_EXPIRE_SECONDS + 1)

    async def test_a_presigned_url_refuses_a_traversing_key(self, storage: FileStorage) -> None:
        with pytest.raises(InvalidStorageKeyError):
            storage.generate_presigned_url("conformance/a/../evasion.pdf")


class TestS3FileStorageConformance(FileStorageConformance):
    """La suite, jouee contre le MinIO du poste."""

    # SUR LA CLASSE, ET JAMAIS SUR LE MODULE (BACK-12) : un `pytestmark`
    # de module marquerait aussi la moitie EN MEMOIRE, que
    # `-m "not integration"` cesserait alors de jouer -- l'inverse exact de
    # ce que la doublure existe pour permettre. La deduction automatique ne
    # peut pas trancher ici : les deux moities demandent une fixture du meme
    # nom, seul MinIO distingue celle-ci.
    pytestmark = pytest.mark.integration

    @pytest_asyncio.fixture
    async def storage(self, pytestconfig: pytest.Config) -> AsyncIterator[FileStorage]:
        """Stockage S3 reel, ou test ignore si le bucket ne repond pas."""
        opened = build_file_storage(get_settings())
        if not await opened.ping():
            await opened.aclose()
            require_service(
                pytestconfig,
                name="minio",
                remedy="`make up` a la racine demarre la pile (INFRA-03).",
            )
        yield opened
        await opened.aclose()


class TestInMemoryFileStorageConformance(FileStorageConformance):
    """La MEME suite, jouee contre `InMemoryFileStorage`."""

    @pytest.fixture
    def storage(self) -> Iterator[FileStorage]:
        """Doublure neuve a chaque test."""
        yield InMemoryFileStorage()
