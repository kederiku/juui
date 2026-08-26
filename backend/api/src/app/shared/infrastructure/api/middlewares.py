"""Intergiciels HTTP : identifiant de requete, journal d'acces, CORS (BACK-11).

Trois briques que toute requete traverse, montees par `create_app()` en un seul
appel -- `register_middlewares` --, miroir exact de `register_error_handlers`
livre par BACK-09. Les trois vivent dans le MEME fichier parce que la partie
subtile n'est aucune des trois : c'est leur ORDRE, et il doit s'expliquer a un
seul endroit.

L'ORDRE DE LA PILE
`add_middleware` insere en position 0 : le DERNIER ajoute est le plus exterieur.
D'ou, du plus exterieur au plus interieur :

    ServerErrorMiddleware      <- Starlette, hors de notre portee (voir plus bas)
      RequestIdMiddleware
        AccessLogMiddleware
          CORSMiddleware
            ExceptionMiddleware  <- les handlers de BACK-09
              Router

- L'identifiant EN PREMIER, donc le plus exterieur : il existe avant tout le
  reste, si bien que toute reponse que l'application sait produire le porte --
  y compris la reponse de preflight que le CORS fabrique et qui ne descend
  jamais plus bas.
- Le journal d'acces AU-DESSUS du CORS, et c'est delibere : un REFUS de
  preflight (`400 Disallowed CORS origin`) est fabrique PAR le CORS et n'atteint
  jamais l'application. Place en dessous, le journal serait aveugle au seul
  symptome exploitable d'une origine mal configuree -- cote navigateur, l'erreur
  est muette cote serveur.
- Le CORS le plus interieur des trois : sa position parmi nos intergiciels ne
  change rien aux en-tetes des reponses reelles, qui le traversent toutes.

CE QUI ECHAPPE A CETTE PILE, ET QU'AUCUN ORDRE NE RATTRAPE
`ServerErrorMiddleware` est la couche la plus exterieure de Starlette, et il
repond avec le `send` D'ORIGINE. Une reponse 500 ne traverse donc l'enveloppe de
sortie d'AUCUN intergiciel utilisateur : ni celle qui pose `X-Request-ID`, ni
celle du CORS. Consequences, verifiees et assumees (registre des ecarts) :

| reponse                         | 2xx / 4xx | 500                     |
| ------------------------------- | --------- | ----------------------- |
| en-tetes CORS                   | oui       | non                     |
| en-tete `X-Request-ID`          | oui       | pose par le handler     |
| `request_id` dans le corps JSON | oui       | oui, lu du `scope`      |

L'en-tete et le corps du 500 sont rattrapes par `_handle_unexpected_error`
(BACK-09), qui lit `REQUEST_ID_SCOPE_KEY`. Les en-tetes CORS, eux, ne le sont
pas : les fabriquer demanderait un intergiciel de dernier recours qui
court-circuiterait la decision de BACK-09. Un 500 apparait donc au navigateur
comme une erreur CORS -- le corps reste lisible dans l'onglet Reseau.

LES DEUX INTERGICIELS SONT DES INTERGICIELS ASGI PURS, ET CE N'EST PAS UN STYLE
`BaseHTTPMiddleware` de Starlette execute l'aval de la chaine dans une TACHE
distincte : la copie de contexte part AVANT le `set()` du `dispatch()`, et
l'endpoint ne verrait jamais l'identifiant. Le piege est ecrit en toutes lettres
dans `tenancy.py` et il vaut mot pour mot ici.
"""

import logging
import re
import time
from typing import Final
from uuid import uuid4

from fastapi import FastAPI
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import AppSettings, ConfigurationError
from app.core.correlation import (
    REQUEST_ID_HEADER,
    REQUEST_ID_SCOPE_KEY,
    current_request_id,
)
from app.core.logging import redact_query

__all__ = ["AccessLogMiddleware", "RequestIdMiddleware", "register_middlewares"]

_LOGGER: Final = logging.getLogger(__name__)

# Plafond de longueur d'une valeur CLIENTE. Soixante-quatre : deux fois la
# largeur de ce qu'on genere, assez pour un identifiant de tracage venu
# d'ailleurs, trop peu pour qu'un client s'en serve comme d'un canal de donnees
# vers nos journaux.
_MAX_REQUEST_ID_LENGTH: Final = 64

# Jeu de caracteres admis dans une valeur CLIENTE, delibererement etroit et
# ancre aux deux bouts : ce qui n'entre pas ici est JETE, pas assaini.
#
# TROIS DANGERS, ET ILS SONT REELS. Un `\r\n` ferait deux lignes de journal la
# ou l'exploitant en lit une -- et, renvoye tel quel en en-tete, ce serait une
# scission de reponse HTTP. Un caractere de controle casse le rendu console. Une
# valeur de dix kilo-octets se recopie sur chaque ligne de la requete.
_ACCEPTED_REQUEST_ID: Final = re.compile(
    r"\A[A-Za-z0-9._~+/=-]{1," + str(_MAX_REQUEST_ID_LENGTH) + r"}\Z"
)

# Chemins qui ne se journalisent QUE s'ils vont mal. Le healthcheck du compose
# interroge la sonde de vie toutes les dix secondes : 8 640 lignes par jour et
# par conteneur, qui disent toutes « le processus repond ». Un 503 de la sonde de
# disponibilite, lui, est une information -- d'ou la regle « silencieux tant que
# le statut est bon » plutot qu'une exclusion seche.
_QUIET_PATHS: Final[frozenset[str]] = frozenset({"/health/live", "/health/ready"})

# Statut suppose tant qu'`http.response.start` ne nous est pas parvenu. Si l'aval
# leve, ce message n'arrive JAMAIS -- `ServerErrorMiddleware` est au-dessus de
# nous et repond avec son propre `send`. Sans cette valeur de depart, un 500
# serait la seule issue absente du journal d'acces.
_ASSUMED_STATUS: Final = 500

# Seuil a partir duquel une reponse cesse d'etre un fonctionnement normal.
_CLIENT_ERROR_STATUS: Final = 400

# Methodes autorisees, en toutes lettres et jamais `"*"`. HEAD y figure parce que
# Starlette l'ajoute d'office a toute route GET : l'omettre ferait echouer un
# preflight parfaitement legitime.
ALLOWED_METHODS: Final[tuple[str, ...]] = (
    "GET",
    "HEAD",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    "OPTIONS",
)

# En-tetes que le navigateur a le droit d'ENVOYER. Starlette y adjoint d'office
# les quatre en-tetes « safelisted » (Accept, Accept-Language, Content-Language,
# Content-Type) : les redire serait du bruit.
#   Authorization -- le jeton porteur (BACK-10) ;
#   X-Clinic-Id   -- la clinique active (ADR-0012), que l'intercepteur des
#                    frontends propagera (SHARED-03, FRONT-08) ;
#   X-Request-ID  -- un client qui apporte son propre identifiant de tracage.
ALLOWED_HEADERS: Final[tuple[str, ...]] = ("Authorization", "X-Clinic-Id", "X-Request-ID")

# En-tetes que le JAVASCRIPT du navigateur a le droit de LIRE. Sans cette liste,
# `response.headers.get('X-Request-ID')` rend `null` cote frontend, et
# l'identifiant de correlation ne sert plus qu'a l'exploitant.
EXPOSED_HEADERS: Final[tuple[str, ...]] = ("X-Request-ID",)

# Duree de mise en cache d'un preflight. C'est deja le defaut de Starlette, ecrit
# ici pour etre visible et grepable : dix minutes suffisent a supprimer le cout
# du preflight sur une session de travail, et une modification de la politique
# CORS prend effet dans le quart d'heure plutot que dans deux heures.
CORS_MAX_AGE_SECONDS: Final = 600


def _resolve_request_id(headers: Headers) -> str:
    """Reprend l'identifiant fourni par le client, ou en fabrique un.

    Args:
        headers: les en-tetes de la requete entrante.

    Returns:
        Un identifiant sain : celui du client s'il franchit le jeu de caracteres
        admis, sinon un `uuid4().hex` neuf. Une valeur cliente n'est JAMAIS
        rectifiee -- tronquee ou epuree, elle serait un jeton menteur, qui ne
        correspondrait plus a rien chez celui qui l'a emise.
    """
    candidate = headers.get(REQUEST_ID_HEADER)
    if candidate is not None and _ACCEPTED_REQUEST_ID.fullmatch(candidate):
        return candidate
    # `uuid4().hex` et non `str(uuid4())` : trente-deux caracteres au lieu de
    # trente-six avec des tirets, sur chaque ligne de journal de la requete --
    # et rien a echapper nulle part.
    return uuid4().hex


class RequestIdMiddleware:
    """Pose l'identifiant de requete, le propage, et le renvoie au client.

    L'identifiant vit a DEUX endroits pour la duree de la requete : la contextvar
    `current_request_id`, que le formateur de journal lit dans le contexte de la
    requete, et la cle de `scope` `REQUEST_ID_SCOPE_KEY`, que le handler du 500
    lit HORS de ce contexte. Une seule valeur, deux lecteurs -- et le
    `reset(token)` reste un `finally` ordinaire, sans fuite de contextvar.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Memorise l'aval de la chaine.

        Args:
            app: l'application ASGI que cet intergiciel enveloppe.
        """
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pose l'identifiant pour la duree de la requete et l'ecrit en reponse.

        Args:
            scope: le contexte de connexion ASGI.
            receive: le canal entrant.
            send: le canal sortant.
        """
        # `lifespan` et `websocket` passent sans rien : le premier n'est pas une
        # requete, le second n'existe pas encore dans ce service.
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        request_id = _resolve_request_id(Headers(scope=scope))
        scope[REQUEST_ID_SCOPE_KEY] = request_id
        token = current_request_id.set(request_id)

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                # `setdefault` avant `MutableHeaders` : une application ASGI nue
                # a le droit d'omettre la cle, que le constructeur exige.
                message.setdefault("headers", [])
                # `__setitem__` et non `append` : si une route a pose l'en-tete
                # elle-meme, on ne le laisse pas en double.
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self._app(scope, receive, send_with_request_id)
        finally:
            current_request_id.reset(token)


def _level_for(status_code: int) -> int:
    """Niveau de journal d'une reponse, deduit de son statut.

    La propriete utile qui en decoule : `LOG_LEVEL=WARNING` en production ne
    laisse plus dans le journal d'acces que les requetes qui ont echoue.

    Args:
        status_code: le statut de la reponse.

    Returns:
        Le niveau `logging` correspondant.
    """
    if status_code >= _ASSUMED_STATUS:
        return logging.ERROR
    if status_code >= _CLIENT_ERROR_STATUS:
        return logging.WARNING
    return logging.INFO


class AccessLogMiddleware:
    """Journalise une ligne par requete : methode, chemin, statut, duree.

    IL REMPLACE LA LIGNE D'ACCES D'UVICORN, IL NE S'Y AJOUTE PAS. Voir
    `configure_logging`, qui eteint `uvicorn.access` : la ligne d'uvicorn
    journalisait le chemin AVEC sa chaine de requete, donc un `?token=...` en
    clair. Celle-ci masque la chaine de requete.

    Le MESSAGE est court et les valeurs vivent dans les `extra` : rien n'est
    ecrit deux fois, la ligne JSON porte des champs indexables, et la ligne
    lisible se grepe par `path=`.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Memorise l'aval de la chaine.

        Args:
            app: l'application ASGI que cet intergiciel enveloppe.
        """
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Mesure la requete et en journalise l'issue.

        Args:
            scope: le contexte de connexion ASGI.
            receive: le canal entrant.
            send: le canal sortant.
        """
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        status_code = _ASSUMED_STATUS
        cors_refused = False
        # `perf_counter` et non `time()` : horloge monotone. Un ajustement NTP
        # pendant la requete produirait sinon une duree negative.
        started_at = time.perf_counter()

        async def capture(message: Message) -> None:
            nonlocal status_code, cors_refused
            if message["type"] == "http.response.start":
                status_code = message["status"]
                # OBSERVATION, PAS COUPLAGE : on ne connait pas la liste blanche,
                # on constate seulement que le CORS n'a pose aucun en-tete alors
                # que le navigateur avait annonce une origine. C'est le SEUL
                # signal serveur d'une origine mal configuree -- sans lui, la
                # requete est servie normalement et seul le navigateur jette la
                # reponse, en silence de ce cote-ci.
                response_headers = Headers(raw=message.get("headers", []))
                cors_refused = (
                    "origin" in Headers(scope=scope)
                    and "access-control-allow-origin" not in response_headers
                )
            await send(message)

        try:
            await self._app(scope, receive, capture)
        finally:
            # `finally` et non `else` : un 500 doit produire sa ligne d'acces
            # avant de repartir vers `ServerErrorMiddleware`.
            _log_access(
                scope,
                status_code=status_code,
                started_at=started_at,
                cors_refused=cors_refused,
            )


def _log_access(
    scope: Scope,
    *,
    status_code: int,
    started_at: float,
    cors_refused: bool,
) -> None:
    """Emet la ligne d'acces, sauf pour une sonde de sante qui va bien.

    Args:
        scope: le contexte de connexion ASGI de la requete servie.
        status_code: le statut rendu, ou 500 si l'aval a leve.
        started_at: l'instant monotone du debut de la requete.
        cors_refused: vrai si une origine annoncee n'a pas ete autorisee.
    """
    path: str = scope.get("path", "")
    if path in _QUIET_PATHS and status_code < _CLIENT_ERROR_STATUS:
        return

    # Mesuree jusqu'a la FIN du corps de reponse et non jusqu'au premier octet :
    # c'est le nombre qui a un sens. Le compromis assume est qu'un
    # telechargement long ne produit sa ligne qu'a la fin.
    duration_ms = round((time.perf_counter() - started_at) * 1000, 1)

    # AUCUNE de ces cles n'est un attribut de `LogRecord` -- `logging` leverait
    # un `KeyError` sur le chemin de journalisation, c'est-a-dire au pire
    # endroit. `pathname` est reserve, `path` non ; verifie par test.
    details: dict[str, object] = {
        "method": scope.get("method", "?"),
        # `scope["path"]`, JAMAIS le chemin avec sa chaine de requete.
        "path": path,
        "status": status_code,
        "duration_ms": duration_ms,
    }
    query = redact_query(scope.get("query_string", b"").decode("latin-1"))
    if query:
        details["query"] = query
    client = scope.get("client")
    if client is not None:
        # Deja reecrite par le `ProxyHeadersMiddleware` d'uvicorn, qui enveloppe
        # l'application au-dessus de nous, avec `FORWARDED_ALLOW_IPS` pour garde.
        # C'est une donnee personnelle : la journaliser est un choix delibere
        # (BACK-17 en aura besoin pour la limitation par IP), consigne au
        # registre des ecarts.
        details["client_ip"] = client[0]
    if cors_refused:
        details["origin"] = Headers(scope=scope).get("origin")

    _LOGGER.log(_level_for(status_code), "Acces HTTP.", extra=details)


def _reject_unusable_cors_origins(settings: AppSettings) -> None:
    """Refuse une liste d'origines qui ne peut pas fonctionner, ou ne devrait pas.

    Args:
        settings: les reglages generaux, dont `cors_origins`.

    Raises:
        ConfigurationError: si la liste porte le joker `*`.
    """
    if "*" in settings.cors_origins:
        # `allow_credentials=True` INTERDIT le joker, et l'interdiction n'est pas
        # academique : Starlette echoise l'origine meme sous `allow_origins=["*"]`,
        # si bien qu'observer une reponse ne distinguerait PAS les deux
        # configurations. La garde doit donc etre ici, au demarrage -- c'est le
        # seul endroit ou le critere « jamais de joker » soit verifiable.
        message = (
            "CORS_ORIGINS porte le joker « * », incompatible avec les requetes "
            "authentifiees : enumerer les origines une a une, separees par des "
            "virgules et sans barre finale."
        )
        raise ConfigurationError(message)
    if not settings.cors_origins and settings.environment != "development":
        # AVERTISSEMENT ET NON REFUS : l'asymetrie est la meme que celle du cache
        # dans le `lifespan`. Sans origine, l'API repond toujours -- aux clients
        # qui ne sont pas des navigateurs. Un service d'integration legitime n'a
        # pas a etre arrete pour ca.
        _LOGGER.warning(
            "CORS_ORIGINS est vide en environnement « %s » : aucun navigateur ne "
            "pourra lire les reponses de l'API.",
            settings.environment,
        )


def register_middlewares(application: FastAPI, *, settings: AppSettings) -> None:
    """Monte les trois intergiciels sur l'application, dans le bon ordre.

    Appelee par `create_app()` une fois, juste apres `register_error_handlers`.
    Les appels ci-dessous sont dans l'ordre INVERSE de la pile : `add_middleware`
    insere en position 0, le dernier ajoute est donc le plus exterieur. Voir la
    docstring du module pour ce que cet ordre garantit.

    Args:
        application: l'application en cours d'assemblage.
        settings: les reglages generaux, dont la liste blanche d'origines.

    Raises:
        ConfigurationError: si `CORS_ORIGINS` porte le joker `*`.
    """
    _reject_unusable_cors_origins(settings)

    # Enregistre MEME si la liste est vide : sans lui, un `OPTIONS /api/v1/x`
    # rendrait un 405 de routage ; avec lui, un `400 Disallowed CORS origin` qui
    # nomme la cause. `allow_origin_regex` n'est jamais employe -- une expression
    # mal ancree est la porte par laquelle le joker revient.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=list(ALLOWED_METHODS),
        allow_headers=list(ALLOWED_HEADERS),
        expose_headers=list(EXPOSED_HEADERS),
        max_age=CORS_MAX_AGE_SECONDS,
    )
    application.add_middleware(AccessLogMiddleware)
    application.add_middleware(RequestIdMiddleware)
