"""Journalisation du processus : un format par environnement, un contexte par requete (BACK-11).

Ce module est L'UNIQUE endroit qui configure `logging`. Partout ailleurs le code
ecrit `logging.getLogger(__name__)` et n'a rien a savoir de plus : ni du format,
ni du flux, ni du masquage. C'est ce qui rend la promesse tenable -- une ligne
mal formatee ou un secret journalise se corrige ici, pas en trente endroits.

DEUX FORMATS, UN SEUL CRITERE
`ENVIRONMENT=development` rend une ligne alignee et coloree, faite pour l'oeil.
Tout le reste -- `staging` comme `production` -- rend un objet JSON par ligne,
fait pour un agregateur. Le pre-production suit la production et non le
developpement : il existe pour REPETER la production, et c'est la qu'on valide
l'ingestion des journaux. Un format different entre les deux rendrait cette
repetition sans objet.

BIBLIOTHEQUE STANDARD, NI structlog NI python-json-logger
Arbitrage rendu par l'ADR-0018. Les deux bibliotheques couvrent le `json.dumps`
et rien d'autre de ce qui est ici : ni le rendu de developpement, ni le
masquage, ni la lecture de nos contextvars -- c'est-a-dire les trois quarts du
fichier. structlog imposerait en prime ses propres `bind_contextvars` a cote de
`core/correlation.py`, donc deux mecanismes de contexte a tenir synchrones.

LE CONTEXTE ARRIVE PAR DEUX CHEMINS, ET IL LE FAUT
L'identifiant de requete, le compte et la clinique vivent dans
`core/correlation.py` : ce module les lit directement. Le GROUPE ACTIF, lui, vit
dans `shared/infrastructure/tenancy.py`, et le contrat `service-spaces` interdit
a `core` d'importer `shared`. Il arrive donc par `context_providers`, passe a
`configure_logging()` par les deux points d'entree du processus -- le `lifespan`
de `main.py` et `worker_startup()`. Une seule source de verite, aucune copie a
tenir synchrone, et TOUT ce qui pose un groupe -- une dependance
d'authentification, un `use_group` de tache de fond, le seed d'INFRA-08 --
apparait dans les journaux sans que personne y pense.

CE QUE CE MODULE NE FAIT PAS
Il ne pose aucun `logging.Filter`. Un filtre devrait MUTER l'enregistrement pour
masquer quoi que ce soit, or celui-ci est partage avec tout autre handler
present -- celui de `caplog` en test, un handler d'audit demain. Le masquage vit
donc dans des fonctions pures que les deux formateurs appellent : rien n'est
mute, et le critere « les secrets sont masques » se teste sur une fonction.
"""

import json
import logging
import re
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Final, TextIO
from urllib.parse import parse_qsl, urlencode

from app.core.config import AppSettings
from app.core.correlation import current_account_id, current_clinic_id, current_request_id

__all__ = [
    "REDACTED",
    "ConsoleFormatter",
    "JsonFormatter",
    "LogContextProvider",
    "configure_logging",
    "redact_mapping",
    "redact_query",
    "redact_text",
]

# Fournisseur de contexte : une fonction sans argument qui rend la valeur du
# traitement en cours, ou `None` si elle n'est pas posee. Le type dit tout ce
# qu'un appelant doit savoir -- et `str | None` plutot qu'un type parametre
# parce qu'une ligne de journal ne porte que du texte.
LogContextProvider = Callable[[], str | None]


# =============================================================================
# Masquage
# =============================================================================

# Ce qui ne s'ecrit jamais dans un journal. Fragments cherches en SOUS-CHAINE et
# sans egard a la casse, et les deux choix comptent : une correspondance exacte
# laisserait passer `hashed_password`, `access_token`, `refresh_token`,
# `jwt_secret`, `otp_code` et `authorization_header`, c'est-a-dire la quasi-
# totalite des noms reels.
#
# `cookie` s'ajoute aux six termes du ticket : le jour ou une ligne journalisera
# des en-tetes HTTP, `authorization` sans `cookie` serait une regle a moitie
# tenue. L'ecart est consigne au registre.
_SENSITIVE_FRAGMENTS: Final[tuple[str, ...]] = (
    "password",
    "token",
    "authorization",
    "secret",
    "otp",
    "chip_number",
    "cookie",
)

# Remplacement FIGE, et non `len(valeur) * "*"` : la longueur d'un secret est
# une information, et un masque qui la conserve en divulgue une partie.
REDACTED: Final = "***"

# Marqueur de profondeur, qui rend le masquage insensible aux structures
# auto-referentes : un `dict` qui se contient lui-meme s'arrete ici plutot que
# de faire tourner le formateur indefiniment.
_TOO_DEEP: Final = "<...>"
_MAX_DEPTH: Final = 6

_NAMES: Final = "|".join(re.escape(fragment) for fragment in _SENSITIVE_FRAGMENTS)

# `cle=valeur`, `cle: valeur`, `"cle": "valeur"` -- les trois formes sous
# lesquelles un secret arrive dans un message deja interpole. La valeur s'arrete
# au premier separateur, guillemet ou fermeture, ce qui laisse intact ce qui
# suit.
#
# Le prefixe de schema est explicitement AVALE : sans lui, `Authorization:
# Bearer eyJ...` verrait sa valeur s'arreter au mot `Bearer`, et le jeton
# lui-meme resterait en clair jusqu'a ce que `_BEARER_RE` le rattrape -- deux
# masques a la suite, et une regle qui ne tient que par accident.
_ASSIGNMENT_RE: Final = re.compile(
    r"(?i)(?P<key>[\w.\-]*(?:" + _NAMES + r")[\w.\-]*)"
    r"(?P<separator>[\"']?\s*[=:]\s*)"
    r"(?P<quote>[\"']?)"
    r"(?P<value>(?:Bearer\s+|Basic\s+)?[^\s,;&\"'}\])]+)"
)

# Identifiants dans une URL : `postgresql+asyncpg://juui:MOTDEPASSE@hote/base`,
# `redis://:MOTDEPASSE@hote/1`. Le filet le plus utile du fichier, parce qu'il
# ne repose sur AUCUN nom de cle : `config.py`, `redis_cache.py` et `broker.py`
# repetent tous trois que leurs URL portent le mot de passe en clair.
_URL_CREDENTIALS_RE: Final = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)([^/\s:@]*):([^/\s@]+)@")

# Jeton porteur en clair, qui n'a de nom de cle sur aucune des deux formes.
_BEARER_RE: Final = re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._\-]+")


def _is_sensitive(key: str) -> bool:
    """Dit si un nom de cle designe une valeur qui ne doit pas etre journalisee.

    Args:
        key: le nom de la cle, tel qu'il apparait dans la structure.

    Returns:
        Vrai si le nom contient l'un des fragments sensibles.
    """
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_FRAGMENTS)


def redact_text(text: str) -> str:
    """Masque ce qui ressemble a un secret dans un texte deja rendu.

    C'EST UN FILET, PAS LE MECANISME -- et la nuance doit rester presente a
    l'esprit de qui ecrit un appel de journalisation. Le mecanisme, c'est
    `redact_mapping`, qui travaille sur des NOMS DE CLE et n'a donc aucun faux
    negatif. Ceci rattrape ce qui a deja ete interpole dans une phrase. Un
    secret passe en argument positionnel sans nom de cle aux alentours --
    `_LOGGER.info("valeur : %s", motdepasse)` -- passe entre les mailles :
    la regle reste de ne pas l'ecrire.

    Args:
        text: le message ou la valeur a assainir.

    Returns:
        Le meme texte, secrets reconnus remplaces par `***`.
    """
    # LES AFFECTATIONS D'ABORD, et l'ordre n'est pas indifferent : elles savent
    # nommer ce qu'elles masquent, donc elles avalent la valeur ENTIERE. Les
    # deux expressions suivantes ne rattrapent que ce qui n'a pas de nom de cle
    # -- un `Bearer` nu dans une phrase, une URL de connexion -- et ne peuvent
    # donc pas remasquer un `***` deja pose.
    redacted = _ASSIGNMENT_RE.sub(r"\g<key>\g<separator>\g<quote>" + REDACTED, text)
    redacted = _BEARER_RE.sub(r"\1" + REDACTED, redacted)
    return _URL_CREDENTIALS_RE.sub(r"\1\2:" + REDACTED + "@", redacted)


def _redact_value(value: object, depth: int) -> object:
    """Masque recursivement ce qu'une valeur structuree peut contenir.

    Args:
        value: la valeur a assainir, de forme quelconque.
        depth: la profondeur courante, qui borne la recursion.

    Returns:
        Une valeur de meme forme, secrets masques. L'originale n'est jamais
        mutee : le dictionnaire de l'appelant lui survit intact.
    """
    if depth >= _MAX_DEPTH:
        return _TOO_DEEP
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _is_sensitive(str(key)) else _redact_value(item, depth + 1)
            for key, item in value.items()
        }
    # `str` et `bytes` sont des sequences : les tester avant la branche
    # ci-dessous eviterait de les parcourir caractere par caractere. Ils sont
    # ici traites par la branche suivante, qui ne les cite pas.
    if isinstance(value, list | tuple | set | frozenset):
        return [_redact_value(item, depth + 1) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_mapping(values: Mapping[str, object]) -> dict[str, object]:
    """Masque les valeurs sensibles d'une structure, par NOM DE CLE.

    Le mecanisme de masquage du projet, celui qui n'a pas de faux negatif :
    une cle nommee est une cle reconnue, quelle que soit sa valeur.

    Args:
        values: la structure a assainir -- typiquement les `extra` d'un
            enregistrement de journal.

    Returns:
        Une structure neuve, de meme forme, secrets remplaces par `***`.
    """
    return {
        key: REDACTED if _is_sensitive(key) else _redact_value(value, 1)
        for key, value in values.items()
    }


def redact_query(query: str) -> str:
    """Masque les valeurs sensibles d'une chaine de requete.

    `parse_qsl` plutot qu'une expression reguliere : le decoupage est exact, y
    compris sur les valeurs percent-encodees. La chaine rendue est reencodee,
    elle peut donc differer de l'originale a l'echappement pres -- compromis
    assume, un journal n'a pas a etre rejouable tel quel.

    Args:
        query: la chaine de requete, sans le point d'interrogation.

    Returns:
        La meme chaine, valeurs sensibles remplacees par `***`.
    """
    if not query:
        return ""
    # `safe="*"` pour que le masque reste lisible : sans lui `urlencode` rendrait
    # `%2A%2A%2A`, qu'aucun `grep` humain ne reconnaitrait.
    return urlencode(
        [
            (key, REDACTED if _is_sensitive(key) else value)
            for key, value in parse_qsl(query, keep_blank_values=True)
        ],
        safe="*",
    )


# =============================================================================
# Contexte
# =============================================================================


def _request_id() -> str | None:
    """Identifiant de la requete en cours, ou `None` hors de tout contexte."""
    return current_request_id.get()


def _account_id() -> str | None:
    """Compte au nom duquel le traitement s'execute, ou `None`."""
    account_id = current_account_id.get()
    return None if account_id is None else str(account_id)


def _clinic_id() -> str | None:
    """Clinique active du traitement, ou `None`."""
    clinic_id = current_clinic_id.get()
    return None if clinic_id is None else str(clinic_id)


# Contexte que ce module sait lire seul. Le groupe actif n'y est pas : il vit
# dans `shared/` et arrive par `configure_logging(context_providers=...)`.
_DEFAULT_CONTEXT_PROVIDERS: Final[Mapping[str, LogContextProvider]] = {
    "request_id": _request_id,
    "account_id": _account_id,
    "clinic_id": _clinic_id,
}


# =============================================================================
# Formateurs
# =============================================================================

# Attributs que `logging` pose lui-meme sur chaque enregistrement. Calcules par
# INTROSPECTION et non recopies : Python 3.12 a ajoute `taskName`, et une liste
# ecrite a la main aurait fait apparaitre cette cle dans tous les journaux le
# jour de la montee de version. `asctime` et `message` s'y ajoutent : ils
# n'existent qu'apres formatage, mais un `extra` qui les porterait ferait lever
# `logging` bien avant d'arriver ici.
_RESERVED_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__
) | {"asctime", "message"}


class _ContextualFormatter(logging.Formatter):
    """Socle commun aux deux formateurs : le contexte et les `extra`."""

    def __init__(
        self, *, context_providers: Mapping[str, LogContextProvider] | None = None
    ) -> None:
        """Memorise les fournisseurs de contexte, ceux du module et les autres.

        Args:
            context_providers: fournisseurs SUPPLEMENTAIRES, par nom de cle.
                Ils s'ajoutent a ceux que `core` sait lire seul, et peuvent les
                remplacer -- ce dont un test se sert.
        """
        super().__init__()
        self._providers: dict[str, LogContextProvider] = dict(_DEFAULT_CONTEXT_PROVIDERS)
        if context_providers is not None:
            self._providers.update(context_providers)

    def _context(self) -> dict[str, str]:
        """Contexte du traitement en cours, cles non posees omises.

        Aucun garde-fou autour des fournisseurs, et c'est delibere : un
        fournisseur qui leve est un defaut de cablage, pas un alea. Le taire
        ferait disparaitre le contexte de toutes les lignes sans que rien ne le
        dise -- exactement l'incident qu'on ne saurait pas diagnostiquer.

        Returns:
            Les couples cle/valeur du contexte, dans l'ordre de declaration.
        """
        resolved: dict[str, str] = {}
        for key, provider in self._providers.items():
            value = provider()
            if value is not None:
                resolved[key] = value
        return resolved

    def _extras(self, record: logging.LogRecord) -> dict[str, object]:
        """Valeurs passees par `extra=` a l'appel de journalisation, masquees.

        Args:
            record: l'enregistrement a inspecter.

        Returns:
            Les seuls attributs que l'appelant a ajoutes, secrets masques.
        """
        return redact_mapping(
            {
                key: value
                for key, value in record.__dict__.items()
                if key not in _RESERVED_ATTRIBUTES
            }
        )


class JsonFormatter(_ContextualFormatter):
    """Rend un objet JSON par ligne : le format des environnements servis.

    L'ORDRE DES CLES EST FIXE, et les cles non posees sont ABSENTES plutot que
    nulles. C'est l'inverse de `ErrorResponse` (BACK-09), et pour une bonne
    raison : celui-la est un contrat CLIENT, type par Orval, ou une cle qui
    apparait et disparait casse le typage. Un journal, lui, se lit par `grep` et
    par un agregateur, ou l'absence EST une valeur -- et quatre `null` sur
    chaque ligne d'un worker sont du volume paye pour rien.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Rend l'enregistrement en un objet JSON d'une seule ligne.

        Args:
            record: l'enregistrement a rendre.

        Returns:
            La ligne JSON, sans saut de ligne final -- le handler l'ajoute.
        """
        payload: dict[str, object] = {
            "timestamp": _utc_timestamp(record),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
        }
        payload.update(self._context())
        if record.exc_info is not None:
            exception_type = record.exc_info[0]
            payload["exception_type"] = (
                "UnknownError" if exception_type is None else exception_type.__name__
            )
            # `json.dumps` echappe les sauts de ligne : la trace complete tient
            # sur la meme ligne JSON, et reste lisible apres `jq -r`.
            payload["exception"] = redact_text(self.formatException(record.exc_info))
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        # `setdefault` et non `update` : un `extra` ne recouvre jamais une cle
        # du schema, sinon un appelant distrait pourrait reecrire le niveau.
        for key, value in self._extras(record).items():
            payload.setdefault(key, value)
        # `default=str` parce qu'un `extra` peut porter un UUID ou une date, et
        # qu'une ligne de journal perdue pour cause de serialisation serait le
        # comble. `ensure_ascii=False` parce que les messages sont en francais.
        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(_ContextualFormatter):
    """Rend une ligne alignee et coloree : le format du poste de developpement.

    Les colonnes sont fixes pour que le MESSAGE commence toujours a la meme
    abscisse : c'est ce qui rend le balayage vertical possible. Seul le niveau
    est colore -- une ligne entierement coloree se lit moins bien, pas mieux.
    """

    def __init__(
        self,
        *,
        context_providers: Mapping[str, LogContextProvider] | None = None,
        colors: bool = True,
    ) -> None:
        """Prepare le rendu lisible.

        Args:
            context_providers: fournisseurs de contexte supplementaires.
            colors: faux pour n'emettre aucune sequence ANSI. Un parametre et
                NON un `isatty()` : la sortie d'un conteneur est un tube, pas un
                terminal, et `docker compose logs api` -- l'endroit meme ou ces
                lignes se lisent -- perdrait toute couleur.
        """
        super().__init__(context_providers=context_providers)
        self._colors = colors

    def format(self, record: logging.LogRecord) -> str:
        """Rend l'enregistrement en une ligne alignee.

        Args:
            record: l'enregistrement a rendre.

        Returns:
            La ligne prete a etre ecrite, trace comprise le cas echeant.
        """
        # Heure LOCALE et sans la date : sur une console de developpement, la
        # date est la meme sur toutes les lignes -- douze caracteres gagnes --
        # et l'heure qu'on veut lire est celle de sa propre montre. Le format
        # JSON, lui, horodate en UTC : un agregateur correle des machines.
        moment = datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3]
        level = record.levelname.ljust(_LEVEL_WIDTH)
        if self._colors:
            level = f"{_LEVEL_COLORS.get(record.levelno, '')}{level}{_RESET}"
        logger = _shorten(record.name, _LOGGER_WIDTH)
        if self._colors:
            logger = f"{_DIM}{logger}{_RESET}"

        line = f"{moment} {level} {logger}  {redact_text(record.getMessage())}"

        annotations = {**self._context(), **self._extras(record)}
        if annotations:
            pairs = " ".join(f"{key}={value}" for key, value in annotations.items())
            suffix = f"· {pairs}"
            line = f"{line}  {_DIM}{suffix}{_RESET}" if self._colors else f"{line}  {suffix}"

        if record.exc_info is not None:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        if record.stack_info:
            line = f"{line}\n{self.formatStack(record.stack_info)}"
        return line


# Largeur des deux colonnes de tete. `CRITICAL` fait huit caracteres, et le nom
# de logger le plus long du service, prive de son prefixe `app.`, en fait une
# trentaine.
_LEVEL_WIDTH: Final = 8
_LOGGER_WIDTH: Final = 38

# Sequences ANSI ecrites a la main : ni colorama, ni rich, ni click. Sept
# constantes contre une dependance applicative, et le meme arbitrage que celui
# de l'ADR-0018.
_LEVEL_COLORS: Final[Mapping[int, str]] = {
    logging.DEBUG: "\033[2;37m",
    logging.INFO: "\033[32m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[1;31m",
}
_DIM: Final = "\033[2m"
_RESET: Final = "\033[0m"


def _utc_timestamp(record: logging.LogRecord) -> str:
    """Horodate un enregistrement en RFC 3339, UTC, a la milliseconde.

    UTC parce qu'un conteneur n'a pas de fuseau et qu'une correlation entre deux
    machines exige un referentiel unique. La milliseconde parce que deux
    requetes dans la meme seconde doivent pouvoir s'ordonner.

    Args:
        record: l'enregistrement a horodater.

    Returns:
        L'horodatage, suffixe `Z`.
    """
    moment = datetime.fromtimestamp(record.created, tz=UTC)
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _shorten(name: str, width: int) -> str:
    """Raccourcit un nom de logger a une largeur fixe, en gardant sa queue.

    Le prefixe `app.` ne distingue rien -- tout le service le porte. Et quand il
    faut couper, c'est PAR LA GAUCHE : `...api.middlewares` situe le code,
    `app.shared.infra...` ne dit rien.

    Args:
        name: le nom du logger, tel que `getLogger(__name__)` le donne.
        width: la largeur de la colonne.

    Returns:
        Le nom raccourci, complete a droite pour tenir la colonne.
    """
    short = name.removeprefix("app.")
    if len(short) > width:
        short = "…" + short[-(width - 1) :]
    return short.ljust(width)


# =============================================================================
# Configuration
# =============================================================================

# Loggers d'uvicorn dont les lignes doivent REJOINDRE notre formateur. Uvicorn
# leur pose ses propres handlers dans `Config.__init__`, donc avant meme
# d'importer l'application : les vider et les laisser propager suffit a
# reprendre la main, sans aucun `--log-config`.
_UVICORN_LOGGERS: Final[tuple[str, ...]] = ("uvicorn", "uvicorn.error", "uvicorn.asgi")

# Bibliotheques bavardes, ramenees a un plancher ABSOLU et non a `max(niveau,
# plancher)`. `LOG_LEVEL=DEBUG` doit rester utilisable pour suivre NOTRE code
# sans noyer la console sous les negociations de signature de botocore. Qui veut
# le contraire edite cette table.
#
# `sqlalchemy` n'y figure pas : son propre `log.py` se place deja a WARNING, et
# y toucher interfererait avec `POSTGRES_ECHO`, dont BACK-03 a fait un champ a
# part precisement pour qu'il ne depende pas de `LOG_LEVEL`. `taskiq` non plus :
# ses lignes de demarrage de worker sont utiles.
_NOISY_FLOORS: Final[Mapping[str, int]] = {
    "asyncio": logging.WARNING,
    "boto3": logging.WARNING,
    "botocore": logging.WARNING,
    "s3transfer": logging.WARNING,
    "urllib3": logging.WARNING,
    "watchfiles": logging.WARNING,
}


def configure_logging(
    settings: AppSettings,
    *,
    context_providers: Mapping[str, LogContextProvider] | None = None,
    stream: TextIO | None = None,
    colors: bool | None = None,
) -> None:
    """Installe la journalisation du processus. Idempotente.

    IMPERATIVE ET NON `dictConfig`, et le motif est concret : les formateurs
    recoivent des OBJETS construits a l'execution -- les fournisseurs de
    contexte --, que `dictConfig` ne sait passer qu'a travers une fabrique
    designee par un chemin pointe. Vingt lignes lisibles et typees valent mieux
    qu'un dictionnaire indirect.

    IDEMPOTENTE PAR CONSTRUCTION : les handlers de la racine sont retires avant
    que le notre ne soit pose. Deux appels convergent, ils ne s'ajoutent jamais.
    A SAVOIR EN TEST : cela retire aussi le handler de `caplog`. Un test qui
    veut observer la sortie passe son propre `stream` et lit dedans ; un test
    qui veut eprouver un formateur l'appelle directement.

    APPELEE PAR LES DEUX POINTS D'ENTREE DU PROCESSUS, jamais a l'import ni
    depuis `create_app()` : le `lifespan` de `main.py` et `worker_startup()`.
    `import app.main` doit rester sans effet de bord, et reconfigurer la racine
    a chaque construction d'application arracherait le handler de `caplog` en
    plein test.

    Args:
        settings: les reglages generaux. `log_level` fixe le seuil,
            `environment` choisit le format.
        context_providers: fournisseurs de contexte SUPPLEMENTAIRES, par nom de
            cle. `core` ne peut pas importer `shared` : c'est ainsi que
            `group_id` arrive depuis `tenancy.py`.
        stream: sortie du handler. `None` vaut `sys.stdout` -- un seul
            descripteur, donc aucun entrelacement surprise entre deux flux, et
            la convention des douze facteurs.
        colors: force ou interdit les couleurs du rendu lisible. `None` les
            active hors des environnements servis, qui rendent du JSON.
    """
    level = logging.getLevelNamesMapping()[settings.log_level]
    # `environment != "development"` et non `is_production` : le pre-production
    # rend du JSON lui aussi -- voir la docstring du module.
    json_output = settings.environment != "development"

    formatter: logging.Formatter
    if json_output:
        formatter = JsonFormatter(context_providers=context_providers)
    else:
        formatter = ConsoleFormatter(
            context_providers=context_providers,
            colors=True if colors is None else colors,
        )

    handler = logging.StreamHandler(sys.stdout if stream is None else stream)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for previous in list(root.handlers):
        root.removeHandler(previous)
    root.addHandler(handler)
    root.setLevel(level)

    for name in _UVICORN_LOGGERS:
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True
        # `NOTSET` pour que le seuil de la racine s'applique : uvicorn place
        # sinon ses loggers a INFO et `LOG_LEVEL=WARNING` ne les tairait pas.
        logger.setLevel(logging.NOTSET)

    # `handlers` vide ET `propagate` faux, et les deux ensemble : uvicorn decide
    # d'emettre sa ligne d'acces en interrogeant `self.access_logger.hasHandlers()`,
    # a CHAQUE connexion, donc apres nous. Sans handler et sans propagation, la
    # reponse est fausse et il n'emet plus rien -- c'est exactement ce qu'il
    # fait lui-meme sous `--no-access-log`. Notre `AccessLogMiddleware` REMPLACE
    # cette ligne, il ne s'y ajoute pas : la sienne journalisait le chemin AVEC
    # sa chaine de requete, donc un `?token=...` en clair.
    access = logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False

    for name, floor in _NOISY_FLOORS.items():
        logging.getLogger(name).setLevel(floor)

    # Fait entrer les avertissements de Python -- `DeprecationWarning` en tete --
    # dans le meme flux formate, au lieu de les laisser filer sur `stderr`.
    logging.captureWarnings(capture=True)
