"""Traduction des erreurs en reponses HTTP, a un seul endroit (BACK-09).

Le domaine leve des `DomainError` typees ; ce module est L'UNIQUE endroit qui
les convertit en statut et en corps HTTP, au format `ErrorResponse` a quatre
cles. Les modules n'importent jamais rien d'ici : ils levent, l'adaptateur
traduit.

| Exception                             | Statut | Chemin                      |
| ------------------------------------- | ------ | --------------------------- |
| `NotFoundError`                       | 404    | handler `DomainError`       |
| `AlreadyExistsError`, `ConflictError` | 409    | handler `DomainError`       |
| `ValidationError`                     | 422    | handler `DomainError`       |
| `PermissionDeniedError`               | 403    | handler `DomainError`       |
| `TooManyRequestsError`                | 429    | handler `DomainError`       |
| `DomainError` non typee               | 400    | handler `DomainError`       |
| `RequestValidationError` (Pydantic)   | 422    | handler dedie, reformate    |
| `HTTPException` (routage, 405...)     | tel quel | handler dedie, meme format |
| tout le reste                         | 500    | handler generique, loggue   |

COMMENT STARLETTE RESOUT LES HANDLERS -- DEUX COUCHES
Les handlers de classes ordinaires vivent dans `ExceptionMiddleware`, qui
remonte le MRO de l'exception levee et prend la premiere classe enregistree :
UN handler sur `DomainError` couvre donc toute la hierarchie, et l'ordre
d'enregistrement ne compte pas. Le handler sur `Exception` est A PART :
Starlette le confie a `ServerErrorMiddleware`, la couche la plus externe, qui
envoie la reponse PUIS re-leve l'exception -- uvicorn journalise donc la stack
une seconde fois (doublon assume, ne pas le « corriger »), et les tests du 500
construisent leur transport avec `raise_app_exceptions=False`.

CE QUE LE 500 NE DIT JAMAIS
Le corps du handler generique est fige : ni type d'exception, ni message, ni
stack -- tout cela part au journal, niveau error, avec la stack complete. Les
erreurs techniques du depot (`MissingTenantContextError`,
`DatabaseUnavailableError`...) ne descendent pas de `DomainError` et tombent
ici par construction. `FileStorageUnavailableError`, elle, EN descend (contrat
du port oblige) mais reste une panne technique : le handler `DomainError` la
re-leve vers ce chemin plutot que de la deguiser en refus metier.

Les 4xx, eux, ne se journalisent PAS ICI : un refus metier est un fonctionnement
normal du service, et l'intergiciel d'acces de BACK-11 en produit deja une ligne,
avec son statut et sa duree. Le `request_id` de la reponse, lui, vient de
`core/correlation.py` : il vaut `null` seulement hors de toute requete HTTP --
une `DomainError` levee depuis une tache de fond ou un script.

LE 500 EST LE SEUL A LIRE LE `scope`, ET IL LE FAUT
`ServerErrorMiddleware` etant la couche la plus exterieure, il construit sa
reponse APRES que l'intergiciel de correlation a rendu la main -- donc apres le
`reset(token)`, quand la contextvar vaut de nouveau `None`. Et il repond avec le
`send` D'ORIGINE, si bien qu'aucune enveloppe de sortie ne peut y ajouter
d'en-tete. `_handle_unexpected_error` fait donc les deux gestes lui-meme : il lit
`REQUEST_ID_SCOPE_KEY`, qui vit aussi longtemps que la requete, et pose
`X-Request-ID` sur sa propre reponse. Sans cela, les 500 -- les seules reponses
ou l'identifiant compte vraiment -- seraient les seules a en manquer.
"""

import logging
from collections.abc import Mapping
from http import HTTPStatus
from typing import Final

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.correlation import (
    REQUEST_ID_HEADER,
    REQUEST_ID_SCOPE_KEY,
    current_request_id,
)
from app.shared.domain.exceptions import (
    AlreadyExistsError,
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    TooManyRequestsError,
    ValidationError,
)
from app.shared.domain.ports.file_storage import FileStorageUnavailableError
from app.shared.infrastructure.api.schemas.error import ErrorResponse

__all__ = ["register_error_handlers"]

_LOGGER: Final = logging.getLogger(__name__)

# Correspondance categorie -> statut. Un TUPLE parcouru par `isinstance` et non
# un dict indexe par type : une erreur qui herite de deux categories (les
# erreurs du port de stockage) prend la premiere qui correspond, et une
# sous-classe non listee prend celle de son parent -- ce qu'un acces par cle
# exacte raterait.
_STATUS_BY_TYPE: Final[tuple[tuple[type[DomainError], int], ...]] = (
    (NotFoundError, 404),
    (AlreadyExistsError, 409),
    (ConflictError, 409),
    (ValidationError, 422),
    (PermissionDeniedError, 403),
    (TooManyRequestsError, 429),
)

# Une `DomainError` levee sans categorie intermediaire : refus metier quand
# meme, mais signal de revue -- toute erreur concrete devrait choisir sa classe.
_UNTYPED_DOMAIN_ERROR_STATUS: Final = 400


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: Mapping[str, object] | None,
    headers: Mapping[str, str] | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    """Fabrique la reponse d'erreur au format unique, quatre cles toujours presentes.

    Args:
        status_code: le statut HTTP de la reponse.
        code: le code namespace `<module>.<ressource>.<erreur>`.
        message: la phrase destinee a l'appelant.
        details: le complement structure, passe par `jsonable_encoder` pour que
            les valeurs non natives (UUID, datetime...) sortent en JSON plutot
            qu'en erreur de serialisation.
        headers: en-tetes a poser sur la reponse -- ceux d'une `HTTPException`
            doivent survivre a la traduction (`WWW-Authenticate` en tete).
        request_id: l'identifiant a inscrire, quand l'appelant l'a lu ailleurs
            que dans la contextvar. Seul le handler du 500 s'en sert -- voir la
            docstring du module. `None` fait lire le contexte, ce qui est le
            chemin de tous les autres handlers.

    Returns:
        La reponse JSON prete a etre rendue.
    """
    payload = ErrorResponse.model_validate(
        {
            "code": code,
            "message": message,
            "details": jsonable_encoder(details),
            "request_id": current_request_id.get() if request_id is None else request_id,
        }
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers=dict(headers) if headers is not None else None,
    )


async def _handle_domain_error(request: Request, error: Exception) -> JSONResponse:
    """Traduit un refus metier en reponse HTTP, selon sa categorie.

    Args:
        request: la requete en cours -- inutilisee, la signature `(Request,
            Exception)` est celle qu'exige Starlette.
        error: l'exception levee ; toujours une `DomainError`, la garde ne sert
            que le narrowing de mypy.

    Returns:
        La reponse au format unique, statut selon la table de correspondance.

    Raises:
        Exception: re-levee telle quelle si ce n'est pas une `DomainError`, ou
            si c'est une `FileStorageUnavailableError` -- panne technique qui
            doit suivre le chemin 500 generique, pas se deguiser en refus.
    """
    if not isinstance(error, DomainError):
        raise error
    if isinstance(error, FileStorageUnavailableError):
        raise error
    status_code = _UNTYPED_DOMAIN_ERROR_STATUS
    for error_type, mapped_status in _STATUS_BY_TYPE:
        if isinstance(error, error_type):
            status_code = mapped_status
            break
    return _error_response(
        status_code=status_code,
        code=error.code,
        message=error.message,
        details=error.details,
        headers=_retry_after(error),
    )


def _retry_after(error: DomainError) -> Mapping[str, str] | None:
    """Rend l'en-tete `Retry-After` quand le refus sait dire dans combien de temps.

    Seule `TooManyRequestsError` en porte un, et pas toujours : un quota sur
    fenetre glissante ne sait pas toujours quand il rouvrira. L'en-tete est
    standard (RFC 9110) et se lit par les clients HTTP comme par les navigateurs,
    ce qu'un champ enfoui dans `details` ne ferait pas.

    Args:
        error: le refus metier en cours de traduction.

    Returns:
        L'en-tete a poser, ou `None` s'il n'y a pas de delai a annoncer.
    """
    if not isinstance(error, TooManyRequestsError):
        return None
    if error.retry_after_seconds is None:
        return None
    # Un entier de SECONDES, la forme la plus simple des deux que la RFC admet --
    # l'autre etant une date HTTP, qui obligerait client et serveur a s'accorder
    # sur l'heure.
    return {"Retry-After": str(error.retry_after_seconds)}


async def _handle_request_validation_error(request: Request, error: Exception) -> JSONResponse:
    """Reformate les erreurs de validation Pydantic au format unique.

    Chaque element ne garde que `loc`, `msg` et `type` : `input` renverrait la
    saisie brute a l'identique -- mot de passe compris -- et `ctx` n'est pas
    toujours serialisable (il peut porter l'exception d'origine).

    Args:
        request: la requete en cours -- inutilisee, signature imposee.
        error: l'exception levee ; toujours une `RequestValidationError`.

    Returns:
        La reponse 422 au format unique, les violations sous `details.errors`.

    Raises:
        Exception: re-levee telle quelle si ce n'est pas la classe attendue.
    """
    if not isinstance(error, RequestValidationError):
        raise error
    violations = [
        {"loc": list(item["loc"]), "msg": item["msg"], "type": item["type"]}
        for item in error.errors()
    ]
    return _error_response(
        status_code=422,
        code="http.request.validation_error",
        message="La requete ne respecte pas le schema attendu.",
        details={"errors": violations},
    )


async def _handle_http_exception(request: Request, error: Exception) -> JSONResponse:
    """Aligne les `HTTPException` de Starlette et FastAPI sur le format unique.

    Sans ce handler, un 404 de route inconnue, un 405 ou les futurs 401
    d'authentification (BACK-10) sortiraient en `{"detail": ...}` -- et le
    critere « toutes les erreurs partagent le meme format » serait faux des le
    premier chemin errone. Le code se derive du statut (`http.request.not_found`,
    `http.request.method_not_allowed`) : personne n'a choisi ces erreurs, elles
    n'ont pas de classe metier a nommer.

    Args:
        request: la requete en cours -- inutilisee, signature imposee.
        error: l'exception levee ; toujours une `StarletteHTTPException`.

    Returns:
        La reponse au format unique, statut et en-tetes de l'exception conserves.

    Raises:
        Exception: re-levee telle quelle si ce n'est pas la classe attendue.
    """
    if not isinstance(error, StarletteHTTPException):
        raise error
    try:
        http_status = HTTPStatus(error.status_code)
        status_name, phrase = http_status.name.lower(), http_status.phrase
    except ValueError:
        # Statut hors registre IANA : un code generique vaut mieux qu'un crash
        # dans le traducteur d'erreurs.
        status_name, phrase = "error", "Erreur HTTP."
    if isinstance(error.detail, str):
        message: str = error.detail
        details: Mapping[str, object] | None = None
    else:
        # Un `detail` structure (FastAPI l'autorise) ne se perd pas : il part
        # dans `details`, et le message reste la phrase standard du statut.
        message = phrase
        details = {"detail": error.detail}
    return _error_response(
        status_code=error.status_code,
        code=f"http.request.{status_name}",
        message=message,
        details=details,
        headers=error.headers,
    )


async def _handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
    """Repond 500 sans rien divulguer, et journalise la stack complete.

    Args:
        request: la requete en cours -- methode et chemin partent au journal
            pour situer la panne.
        error: l'exception imprevue, quelle qu'elle soit.

    Returns:
        La reponse 500 au corps fige : code generique, message generique,
        aucun detail interne -- mais l'identifiant de requete, en en-tete comme
        dans le corps, qui est ce qui rendra l'incident relisible.
    """
    _LOGGER.error(
        "Erreur interne non geree sur %s %s.",
        request.method,
        request.url.path,
        exc_info=error,
    )
    # Le `scope` et non la contextvar : celle-ci a deja ete remise a sa valeur
    # precedente quand ce handler s'execute (voir la docstring du module).
    request_id = request.scope.get(REQUEST_ID_SCOPE_KEY)
    return _error_response(
        status_code=500,
        code="http.server.internal_error",
        message="Une erreur interne est survenue.",
        details=None,
        # Pose ici parce qu'aucune enveloppe de sortie ne traversera cette
        # reponse : `ServerErrorMiddleware` repond avec le `send` d'origine.
        headers=None if request_id is None else {REQUEST_ID_HEADER: request_id},
        request_id=request_id,
    )


def register_error_handlers(application: FastAPI) -> None:
    """Enregistre les quatre handlers d'erreur sur l'application.

    Appelee par `create_app()` (BACK-08), une fois, juste apres la construction
    de l'application. Les enregistrements sur `RequestValidationError` et
    `HTTPException` REMPLACENT les handlers par defaut de FastAPI -- c'est le
    but : leur format `{"detail": ...}` disparait de la surface.

    Args:
        application: l'application en cours d'assemblage.
    """
    application.add_exception_handler(DomainError, _handle_domain_error)
    application.add_exception_handler(RequestValidationError, _handle_request_validation_error)
    application.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    application.add_exception_handler(Exception, _handle_unexpected_error)
