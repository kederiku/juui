"""Sondes de journalisation : rendre une ligne sans dependre de `caplog` (BACK-11).

POURQUOI PAS `caplog`, ET CE N'EST PAS UNE PREFERENCE
`caplog` attache SON handler avec SON formateur. `caplog.text` prouve donc le
format de `caplog`, jamais le notre -- un test qui asserterait
`'"level": "INFO"' in caplog.text` passerait avec le formateur par defaut. Et
`caplog.records` rend les enregistrements AVANT tout formatage : il montre qu'une
ligne a ete emise et ce qu'elle porte, jamais ce qui sort sur le flux. Or c'est
exactement ce que les criteres 2, 5 et 8 du ticket demandent de prouver.

TROIS NIVEAUX, DU MOINS AU PLUS INVASIF
1. `make_record()` + `formatter.format(record)` -- le formateur seul, aucun
   etat global touche. Pour le schema JSON, les cles, l'horodatage, la trace.
2. `log_sink()` -- un logger PRIVE, `propagate = False`, un handler vers un
   `StringIO`. Pour ce qui traverse reellement un logger, propagation depuis un
   enfant comprise. Rien de global n'est touche non plus.
3. `isolated_logging()` -- la vraie `configure_logging()`, l'etat anterieur
   restaure a la sortie. Pour les tests de bout en bout. TOUJOURS l'employer :
   `logging` est un etat global de PROCESSUS, et un test qui laisse la racine
   configuree pollue tous les suivants. Le garde-fou `autouse` du conftest
   racine refuse d'ailleurs de laisser passer l'oubli.

Ce module ne commence pas par `test_` : pytest ne le collecte pas. Meme role que
`tests/shared/tenancy_stubs.py`.
"""

import io
import json
import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import Any
from uuid import uuid4

from app.core.config import AppSettings
from app.core.logging import LogContextProvider, configure_logging

# Loggers dont `configure_logging` modifie l'etat, et qu'il faut donc restaurer.
_TOUCHED_LOGGERS = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.asgi",
    "uvicorn.access",
    "asyncio",
    "boto3",
    "botocore",
    "s3transfer",
    "urllib3",
    "watchfiles",
)


def make_record(
    *,
    message: str = "Ligne de sonde.",
    level: int = logging.INFO,
    logger_name: str = "app.tests.probe",
    args: tuple[object, ...] = (),
    exc_info: tuple[type[BaseException], BaseException, TracebackType | None] | None = None,
    extra: Mapping[str, object] | None = None,
) -> logging.LogRecord:
    """Fabrique un enregistrement nu, sans passer par aucun logger.

    Ni niveau, ni handler, ni propagation, ni `caplog` n'entrent en jeu : c'est
    le niveau 1, celui a preferer des qu'on eprouve le FORMATEUR seul.
    """
    record = logging.LogRecord(
        name=logger_name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=args,
        exc_info=exc_info,
    )
    for key, value in (extra or {}).items():
        setattr(record, key, value)
    return record


@dataclass(frozen=True, slots=True)
class LogSink:
    """Un logger, son flux memoire, et de quoi relire ce qui en sort."""

    logger: logging.Logger
    stream: io.StringIO

    def lines(self) -> list[str]:
        """Les lignes non vides ecrites dans le flux."""
        return [line for line in self.stream.getvalue().splitlines() if line]

    def only_line(self) -> str:
        """L'unique ligne attendue, ou un message qui dit combien il y en a."""
        lines = self.lines()
        if len(lines) != 1:
            message = f"Une seule ligne attendue, {len(lines)} obtenue(s) : {lines}"
            raise AssertionError(message)
        return lines[0]

    def json_lines(self) -> list[dict[str, Any]]:
        """Chaque ligne decodee -- echoue en disant laquelle n'est pas du JSON."""
        decoded: list[dict[str, Any]] = []
        for index, line in enumerate(self.lines()):
            try:
                decoded.append(json.loads(line))
            except json.JSONDecodeError as error:
                message = f"Ligne {index} non parsable ({error}) : {line!r}"
                raise AssertionError(message) from error
        return decoded

    def only_json(self) -> dict[str, Any]:
        """L'unique objet JSON attendu."""
        return json.loads(self.only_line())


@contextmanager
def log_sink(formatter: logging.Formatter, *, level: int = logging.DEBUG) -> Iterator[LogSink]:
    """Ouvre un logger prive dote du formateur a eprouver.

    Le logger porte un nom unique et ne propage pas : deux tests concurrents ne
    se voient pas, et rien ne remonte a la racine.
    """
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    logger = logging.getLogger(f"app.tests.sink.{uuid4().hex}")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(level)
    try:
        yield LogSink(logger=logger, stream=stream)
    finally:
        logger.handlers = []
        logger.disabled = True


@contextmanager
def isolated_logging(
    settings: AppSettings,
    *,
    context_providers: Mapping[str, LogContextProvider] | None = None,
    colors: bool | None = None,
) -> Iterator[io.StringIO]:
    """Applique la vraie configuration sur un flux memoire, puis remet tout en place.

    C'est la seule facon correcte d'appeler `configure_logging()` depuis un test :
    la racine, les loggers d'uvicorn et les planchers des bibliotheques bavardes
    sont des etats de PROCESSUS.
    """
    root = logging.getLogger()
    saved_root = (list(root.handlers), root.level)
    saved = {
        name: (
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).level,
            logging.getLogger(name).propagate,
        )
        for name in _TOUCHED_LOGGERS
    }
    stream = io.StringIO()
    configure_logging(settings, context_providers=context_providers, stream=stream, colors=colors)
    try:
        yield stream
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
        root.handlers.extend(saved_root[0])
        root.setLevel(saved_root[1])
        for name, (handlers, level, propagate) in saved.items():
            logger = logging.getLogger(name)
            logger.handlers = handlers
            logger.setLevel(level)
            logger.propagate = propagate
        logging.captureWarnings(capture=False)
