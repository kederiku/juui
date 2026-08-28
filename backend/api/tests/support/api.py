"""Le client HTTP de la suite, et les sondes des tests d'intergiciels.

UNE SEULE DEFINITION DU CLIENT, ET C'EST L'OBJET DE BACK-12
`asgi_client` etait ecrit CINQ FOIS : ici, dans `auth.py`, et en local dans
`test_error_handlers.py`, `test_error_handlers_tenancy.py` et
`test_pagination.py`. Les quatre copies ont disparu. La forme est un
gestionnaire de contexte et non une fixture, parce que plusieurs tests
construisent DEUX applications dans un meme cas -- `test_error_handlers.py` est
parametre sur quatre montages. La fixture `probe_client` du conftest est
l'autre forme, celle du cas courant : une application, un client.

CE QUI SE PROUVE SUR `create_app()` ET CE QUI NE S'Y PROUVE PAS
Les intergiciels ne sont montes que par `create_app()` : ces tests l'appellent
donc, contrairement a ceux des handlers d'erreur qui batissent une application
nue. `ASGITransport` ne declenche pas le `lifespan` : ni PostgreSQL, ni Redis,
ni S3 -- et, tout aussi voulu, aucune configuration de journalisation, qui reste
a la main des tests qui la demandent.

Ce module ne commence pas par `test_` : pytest ne le collecte pas.
"""

import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any, Final

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import AppSettings
from app.main import create_app

# Les trois frontends de developpement, tels que `.env.example` les livre. Les
# recopier ici fait du critere 6 -- « les 3 frontends appellent l'API sans erreur
# CORS » -- une assertion, et non seulement une sonde manuelle.
FRONTEND_ORIGINS: Final[tuple[str, ...]] = (
    "http://localhost:3001",
    "http://localhost:3002",
    "http://localhost:3003",
)

# Environnement SERVI par defaut : c'est celui qui rend du JSON, donc celui dont
# les lignes de journal s'analysent sans deviner.
API_SETTINGS: Final = AppSettings(
    environment="production",
    log_level="INFO",
    cors_origins=list(FRONTEND_ORIGINS),
)

# Message de la ligne d'acces, court par construction : les valeurs vivent dans
# les `extra`, et rien n'est ecrit deux fois.
ACCESS_MESSAGE: Final = "Acces HTTP."


def build_app(settings: AppSettings = API_SETTINGS) -> FastAPI:
    """Construit l'application reelle, intergiciels montes.

    Args:
        settings: les reglages a employer, la liste blanche CORS en tete.

    Returns:
        L'application, prete a recevoir d'eventuelles routes de sonde.
    """
    return create_app(app_settings=settings)


@asynccontextmanager
async def asgi_client(application: FastAPI) -> AsyncIterator[AsyncClient]:
    """Ouvre un client HTTP sur l'application, sans reseau ni `lifespan`.

    `raise_app_exceptions=False` : sans lui, une exception imprevue remonterait
    dans le test au lieu de produire la reponse 500 qu'on veut observer.

    LE GARDE-FOU RESEAU NE LE VOIT PAS, et c'est verifie : `httpx.ASGITransport`
    derive d'`AsyncBaseTransport` et non d'`AsyncHTTPTransport`, or
    `_forbid_outbound_http` ne mord que sur les deux transports qui ouvrent une
    socket. L'hote `test` de `base_url` n'a donc jamais a etre autorise.
    """
    transport = ASGITransport(app=application, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as opened:
        yield opened


def json_lines(rendered: str) -> Iterator[dict[str, Any]]:
    """Decode chaque ligne JSON d'un flux capte."""
    for line in rendered.splitlines():
        if line.strip():
            yield json.loads(line)


def access_lines(rendered: str) -> list[dict[str, Any]]:
    """Ne garde du flux que les lignes du journal d'acces."""
    return [line for line in json_lines(rendered) if line.get("message") == ACCESS_MESSAGE]
