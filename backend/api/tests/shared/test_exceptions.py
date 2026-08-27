"""Tests de la hierarchie des erreurs metier et de ses codes (BACK-09).

Purement en memoire : ni base de donnees, ni HTTP. Ces tests verrouillent le
contrat que l'adaptateur d'API consomme -- les categories descendent toutes de
`DomainError`, chaque classe concrete porte un code namespace, et les
exceptions des modules sont bien rangees sous leur categorie.
"""

import re

from app.modules.identity.domain.exceptions import (
    AccountNotFoundError,
    EmailAlreadyUsedError,
    EmailAlreadyVerifiedError,
    InvalidStatusTransitionError,
)
from app.shared.domain.exceptions import (
    AlreadyExistsError,
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from app.shared.domain.pagination import InvalidPageRequestError, UnknownSortFieldError
from app.shared.domain.ports.file_storage import (
    FileStorageError,
    FileStorageUnavailableError,
    FileTooLargeError,
    StoredFileNotFoundError,
    UnsupportedContentTypeError,
)
from app.shared.domain.ports.token_service import (
    ExpiredTokenError,
    InactiveMembershipError,
    TokenError,
)

# Le gabarit du ticket : `<module>.<ressource>.<erreur>`, trois segments.
_CODE_PATTERN = re.compile(r"^[a-z_]+(\.[a-z_]+){2}$")

_CATEGORIES = (
    NotFoundError,
    AlreadyExistsError,
    ConflictError,
    ValidationError,
    PermissionDeniedError,
)


def _all_domain_error_types() -> set[type[DomainError]]:
    """Collecte recursivement toutes les sous-classes importees de `DomainError`."""
    collected: set[type[DomainError]] = set()
    frontier: list[type[DomainError]] = [DomainError]
    while frontier:
        current = frontier.pop()
        if current in collected:
            continue
        collected.add(current)
        frontier.extend(current.__subclasses__())
    return collected


def test_categories_descend_from_domain_error() -> None:
    for category in _CATEGORIES:
        assert issubclass(category, DomainError)


def test_every_error_carries_a_namespaced_code() -> None:
    """Chaque classe de la hierarchie porte un code `module.ressource.erreur`.

    La garde vaut pour les modules futurs : une classe ajoutee sans code herite
    de celui de son parent -- toujours conforme au gabarit -- et une classe au
    code mal forme fait echouer ce test.
    """
    for error_type in _all_domain_error_types():
        assert _CODE_PATTERN.match(error_type.code), (
            f"{error_type.__name__} porte un code hors gabarit : {error_type.code!r}"
        )


def test_identity_errors_are_reparented() -> None:
    assert issubclass(AccountNotFoundError, NotFoundError)
    assert issubclass(EmailAlreadyUsedError, AlreadyExistsError)
    assert issubclass(EmailAlreadyVerifiedError, ConflictError)
    assert issubclass(InvalidStatusTransitionError, ConflictError)
    assert AccountNotFoundError.code == "identity.account.not_found"
    assert EmailAlreadyUsedError.code == "identity.account.email_already_used"
    assert EmailAlreadyVerifiedError.code == "identity.account.email_already_verified"
    assert InvalidStatusTransitionError.code == "identity.account.invalid_status_transition"


def test_pagination_errors_are_reparented() -> None:
    """Les refus de pagination (BACK-24) sont des erreurs de validation, en 422."""
    assert issubclass(InvalidPageRequestError, ValidationError)
    assert issubclass(UnknownSortFieldError, ValidationError)
    assert InvalidPageRequestError.code == "shared.pagination.invalid"
    assert UnknownSortFieldError.code == "shared.pagination.unknown_sort"


def test_file_storage_errors_keep_their_family_and_gain_a_category() -> None:
    """L'heritage multiple tient les deux promesses : celle du port, et la categorie."""
    assert issubclass(StoredFileNotFoundError, FileStorageError)
    assert issubclass(StoredFileNotFoundError, NotFoundError)
    assert issubclass(FileTooLargeError, FileStorageError)
    assert issubclass(FileTooLargeError, ValidationError)
    assert issubclass(UnsupportedContentTypeError, FileStorageError)
    assert issubclass(UnsupportedContentTypeError, ValidationError)
    # La panne technique reste hors categorie : le handler la re-leve en 500.
    assert not issubclass(FileStorageUnavailableError, NotFoundError)
    assert not issubclass(FileStorageUnavailableError, ValidationError)


def test_token_errors_keep_their_family_and_the_membership_refusal_gains_a_category() -> None:
    """Le port des jetons (BACK-10a) suit le patron du stockage, avec une nuance.

    Une seule de ses erreurs porte une categorie de BACK-09 : celle du refus
    d'appartenance, rangee sous `NotFoundError` par la regle de
    non-divulgation -- un refus de DROIT confirmerait l'existence du groupe. Les
    autres restent sans categorie : leur statut est un 401, que la bordure HTTP
    de BACK-10c posera par `HTTPException`, comme BACK-09 l'a prevu.
    """
    assert issubclass(ExpiredTokenError, TokenError)
    assert issubclass(InactiveMembershipError, TokenError)
    assert issubclass(InactiveMembershipError, NotFoundError)
    assert not issubclass(ExpiredTokenError, NotFoundError)
    assert not issubclass(ExpiredTokenError, ValidationError)
    assert not issubclass(ExpiredTokenError, PermissionDeniedError)
    assert TokenError.code == "shared.token.invalid"
    assert InactiveMembershipError.code == "shared.token.membership_not_active"


def test_error_exposes_message_and_details() -> None:
    error = DomainError("Le message de refus.", details={"champ": "valeur"})
    assert str(error) == "Le message de refus."
    assert error.message == "Le message de refus."
    assert error.details == {"champ": "valeur"}


def test_details_default_to_none_and_are_copied() -> None:
    assert DomainError("Sans complement.").details is None
    source: dict[str, object] = {"champ": "valeur"}
    error = DomainError("Copie a la construction.", details=source)
    source["champ"] = "autre"
    assert error.details == {"champ": "valeur"}
