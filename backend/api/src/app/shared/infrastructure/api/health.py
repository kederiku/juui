"""Sondes de sante du service (BACK-08).

Deux routes, deux questions distinctes :

- `GET /health/live` -- « le processus repond-il ? ». Aucune dependance
  externe : c'est la sonde du conteneur (INFRA-04), et une base arretee ne doit
  pas faire redemarrer l'API en boucle.
- `GET /health/ready` -- « le service peut-il servir ? ». Interroge PostgreSQL
  (le `SELECT 1` de `verify_connectivity`) et Redis (PING), et repond 503 en
  nommant le composant defaillant.

HORS DE /api/v1, A DESSEIN. L'URL d'une sonde est un contrat d'EXPLOITATION
(compose, orchestrateur, supervision), pas un contrat d'API : elle doit
survivre a une v2 sans reconfigurer quoi que ce soit -- et le healthcheck du
compose vise litteralement /health/live.

REDIS EST BLOQUANT ICI, ET SEULEMENT ICI. Les routes metier degradent sans
cache (BACK-14) ; la sonde de disponibilite, elle, doit dire la verite d'une
panne. Retirer l'instance du trafic n'est pas casser le service -- c'est
donner a l'orchestrateur l'information qu'il demande.

S3 N'EST PAS SONDE : aucune route ne depend encore du stockage objet
(BACK-13), et une panne S3 ne justifierait pas de retirer du trafic un service
qui n'en fait rien. A rediscuter au premier module consommateur de fichiers.
"""

import asyncio
import logging
from typing import Annotated, Final, Literal, Protocol, runtime_checkable

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from app.core import Settings, SettingsDep
from app.shared.infrastructure.api.schemas.error import ErrorResponse
from app.shared.infrastructure.clients.redis_cache import CACHE_STATE_KEY
from app.shared.infrastructure.db.engine import DatabaseUnavailableError, verify_connectivity
from app.shared.infrastructure.db.session import Database, get_database

_LOGGER: Final = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


@runtime_checkable
class SupportsPing(Protocol):
    """Ce que la sonde attend du cache : savoir dire s'il repond.

    Un protocole STRUCTUREL plutot qu'un ajout au port `Cache` : sonder est un
    geste d'exploitation, pas de cache -- le port promet des lectures et des
    ecritures, rien d'autre -- et `RedisCache.ping()` existe deja (BACK-14).
    `InMemoryCache` (BACK-06c) porte le sien et convient donc sans que ce fichier
    ait eu a changer -- ce qui etait tout l'interet du protocole.
    """

    async def ping(self) -> bool:
        """Dit si le composant repond, sans jamais lever."""
        ...


class LivenessReport(BaseModel):
    """Reponse de la sonde de vie : le processus repond, rien de plus."""

    status: Literal["alive"] = "alive"


class ReadinessComponents(BaseModel):
    """Etat de chaque dependance interrogee par la sonde de disponibilite."""

    postgres: Literal["ok", "unreachable"]
    redis: Literal["ok", "unreachable"]


class ReadinessReport(BaseModel):
    """Reponse de la sonde de disponibilite, composant par composant."""

    status: Literal["ready", "unready"]
    components: ReadinessComponents


def get_pingable_cache(request: Request) -> SupportsPing:
    """Retourne le cache du `lifespan`, vu par sa seule capacite a repondre au PING.

    Meme forme que `get_cache` (BACK-14) -- une cle, un type, un accesseur --
    mais le type est le protocole ci-dessus : la sonde n'a pas besoin d'un
    cache, elle a besoin d'un `ping()`.

    Args:
        request: la requete en cours, d'ou l'on remonte a l'application.

    Returns:
        Le cache du processus, reduit a sa sonde.

    Raises:
        RuntimeError: si le `lifespan` n'a pas tourne.
    """
    cache = getattr(request.app.state, CACHE_STATE_KEY, None)
    if not isinstance(cache, SupportsPing):
        message = (
            "Le cache n'est pas ouvert : l'application a-t-elle ete construite sans son lifespan ?"
        )
        raise RuntimeError(message)
    return cache


@router.get("/live", operation_id="check_liveness", summary="Sonde de vie")
async def check_liveness() -> LivenessReport:
    """Repond immediatement, sans toucher a aucune dependance externe.

    Returns:
        Le rapport de vie -- toujours le meme : si cette fonction s'execute,
        le processus est vivant.
    """
    return LivenessReport()


@router.get(
    "/ready",
    operation_id="check_readiness",
    summary="Sonde de disponibilite",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ReadinessReport,
            "description": "Au moins un composant est injoignable.",
        },
        # LE 500 SE DECLARE ICI, ET C'EST FRONT-10 QUI LE DEMANDE.
        # Cette route repond DEJA `http.server.internal_error` au format unique de
        # BACK-09 quand l'application est cassee -- `tests/shared/test_error_handlers.py`
        # le prouve depuis toujours. Ce qui manquait, c'est que le CONTRAT le dise :
        # `ErrorResponse` n'etait declare que sur le 422 du routeur v1, qui n'a
        # encore aucune route, si bien que le composant n'entrait pas dans l'OpenAPI
        # et qu'Orval n'en generait aucun type. Le client d'API devait donc reecrire
        # a la main un type que le serveur possede.
        #
        # SUR LA ROUTE ET NON SUR LE ROUTEUR : `/health/live` ne touche a aucune
        # dependance externe, et l'ecart consigne en BACK-09 refuse nommement de
        # declarer un statut sur une route qui ne le produit pas. Les statuts METIER
        # des routes v1 restent a BACK-28.
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": ErrorResponse,
            "description": "Une erreur interne est survenue.",
        },
    },
)
async def check_readiness(
    response: Response,
    database: Annotated[Database, Depends(get_database)],
    cache: Annotated[SupportsPing, Depends(get_pingable_cache)],
    settings: SettingsDep,
) -> ReadinessReport:
    """Interroge PostgreSQL et Redis, et repond 503 si l'un des deux manque.

    Les deux sondes partent EN PARALLELE : le pire cas vaut le maximum des deux
    delais (10 s cote moteur, 2 s cote Redis), pas leur somme.

    Le parametre `response` est le mecanisme FastAPI qui laisse poser le code
    503 tout en gardant `ReadinessReport` comme modele de reponse unique -- le
    corps a la meme forme en panne et en sante, seul le code change.

    Args:
        response: la reponse en construction, pour y poser le code.
        database: les ressources de persistance du `lifespan`.
        cache: le cache du `lifespan`, reduit a son PING.
        settings: la configuration, pour nommer la cible en cas d'echec.

    Returns:
        Le rapport, composant par composant.
    """
    postgres_ok, redis_ok = await asyncio.gather(
        _probe_postgres(database, settings),
        cache.ping(),
    )
    report = ReadinessReport(
        status="ready" if postgres_ok and redis_ok else "unready",
        components=ReadinessComponents(
            postgres="ok" if postgres_ok else "unreachable",
            redis="ok" if redis_ok else "unreachable",
        ),
    )
    if report.status == "unready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report


async def _probe_postgres(database: Database, settings: Settings) -> bool:
    """Execute le `SELECT 1` canonique et dit si la base repond.

    Reutilise `verify_connectivity` (BACK-05) : meme requete, meme tuple
    d'exceptions, meme message -- qui nomme les composants et jamais l'URL. Le
    detail part au journal ; la reponse HTTP, elle, ne dit que « unreachable »,
    un corps de 503 finissant toujours par etre lu par n'importe qui.

    Args:
        database: les ressources de persistance du `lifespan`.
        settings: la configuration, pour le message d'echec.

    Returns:
        Vrai si PostgreSQL a repondu.
    """
    try:
        await verify_connectivity(database.engine, settings)
    except DatabaseUnavailableError as error:
        _LOGGER.warning("Sonde de disponibilite : %s", error)
        return False
    return True
