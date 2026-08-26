"""Format des journaux, seuil et idempotence de la configuration (BACK-11, critere 2).

Le format se prouve sur le FORMATEUR, jamais sur `caplog` -- voir la docstring de
`logging_probes.py` pour le detail du raisonnement.
"""

import json
import logging
import sys
from datetime import UTC, datetime

import pytest

from app.core.config import AppSettings
from app.core.logging import ConsoleFormatter, JsonFormatter, configure_logging
from app.main import create_app
from tests.core.logging_probes import isolated_logging, log_sink, make_record

pytestmark = pytest.mark.observability

_ESCAPE = "\033"


# --- Le format JSON des environnements servis --------------------------------


def test_production_renders_one_json_object_per_line() -> None:
    with log_sink(JsonFormatter()) as sink:
        sink.logger.info("Premiere.")
        sink.logger.info("Seconde.")
    assert [line["message"] for line in sink.json_lines()] == ["Premiere.", "Seconde."]


def test_the_json_line_carries_the_expected_keys() -> None:
    rendered = json.loads(JsonFormatter().format(make_record(message="Ligne.")))
    assert list(rendered) == ["timestamp", "level", "logger", "message"]
    assert rendered["level"] == "INFO"
    assert rendered["logger"] == "app.tests.probe"


def test_the_json_timestamp_is_iso_8601_in_utc() -> None:
    rendered = json.loads(JsonFormatter().format(make_record()))
    stamp = rendered["timestamp"]
    assert stamp.endswith("Z")
    moment = datetime.fromisoformat(stamp)
    assert moment.tzinfo == UTC


def test_a_message_carrying_braces_and_quotes_stays_valid_json() -> None:
    hostile = '{"cle": "valeur"} et \\ et "guillemets"'
    rendered = json.loads(JsonFormatter().format(make_record(message=hostile)))
    assert rendered["message"] == hostile


def test_a_message_carrying_a_newline_stays_on_one_json_line() -> None:
    line = JsonFormatter().format(make_record(message="deux\nlignes"))
    assert "\n" not in line
    assert json.loads(line)["message"] == "deux\nlignes"


def test_a_stack_trace_is_serialised_into_a_single_json_line() -> None:
    try:
        message = "panne de sonde"
        raise RuntimeError(message)
    except RuntimeError:
        record = make_record(level=logging.ERROR, exc_info=sys.exc_info())  # type: ignore[arg-type]
    line = JsonFormatter().format(record)
    assert "\n" not in line
    rendered = json.loads(line)
    assert rendered["exception_type"] == "RuntimeError"
    assert "panne de sonde" in rendered["exception"]


def test_a_non_serialisable_extra_falls_back_to_its_text_form() -> None:
    """Une ligne de journal ne se perd JAMAIS pour cause de serialisation."""

    class Opaque:
        def __str__(self) -> str:
            return "objet-opaque"

    rendered = json.loads(JsonFormatter().format(make_record(extra={"thing": Opaque()})))
    assert rendered["thing"] == "objet-opaque"


def test_the_extras_are_merged_at_the_root() -> None:
    rendered = json.loads(JsonFormatter().format(make_record(extra={"status": 200})))
    assert rendered["status"] == 200


def test_an_extra_never_shadows_a_key_of_the_schema() -> None:
    """`level` vient du niveau reel, pas de ce qu'un appelant distrait y ecrirait."""
    rendered = json.loads(
        JsonFormatter().format(make_record(level=logging.INFO, extra={"level": "CRITICAL"}))
    )
    assert rendered["level"] == "INFO"


# --- Le format lisible du poste de developpement -----------------------------


def test_development_renders_a_readable_line() -> None:
    line = ConsoleFormatter(colors=False).format(
        make_record(message="Acces HTTP.", logger_name="app.shared.infrastructure.api.middlewares")
    )
    assert "INFO" in line
    # Le prefixe `app.` ne distingue rien : tout le service le porte.
    assert "shared.infrastructure.api.middlewares" in line
    assert not line.startswith("app.")
    assert line.rstrip().endswith("Acces HTTP.")


def test_development_colours_the_level() -> None:
    line = ConsoleFormatter(colors=True).format(make_record(level=logging.ERROR))
    assert _ESCAPE in line


def test_the_console_formatter_can_be_built_without_colours() -> None:
    """Le rendu doit rester exploitable quand la sortie part dans un fichier."""
    line = ConsoleFormatter(colors=False).format(make_record(level=logging.ERROR))
    assert _ESCAPE not in line


def test_a_long_logger_name_is_shortened_from_the_left() -> None:
    """La QUEUE du nom est la partie informative : c'est elle qu'on garde."""
    line = ConsoleFormatter(colors=False).format(
        make_record(logger_name="app.shared.infrastructure.api.error_handlers.tres.long.suffixe")
    )
    assert "long.suffixe" in line


def test_the_console_line_carries_the_extras() -> None:
    line = ConsoleFormatter(colors=False).format(make_record(extra={"status": 200}))
    assert "status=200" in line


# --- Le seuil et le choix du format ------------------------------------------


def test_staging_renders_json_like_production() -> None:
    """Le pre-production existe pour REPETER la production, ingestion comprise."""
    with isolated_logging(AppSettings(environment="staging")) as stream:
        logging.getLogger("app.probe").info("Ligne de pre-production.")
    assert json.loads(stream.getvalue().strip())["message"] == "Ligne de pre-production."


def test_development_does_not_render_json() -> None:
    with isolated_logging(AppSettings(environment="development"), colors=False) as stream:
        logging.getLogger("app.probe").info("Ligne de developpement.")
    with pytest.raises(json.JSONDecodeError):
        json.loads(stream.getvalue().strip())


@pytest.mark.parametrize("level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
def test_the_configured_level_matches_log_level(level: str) -> None:
    with isolated_logging(AppSettings(environment="production", log_level=level)):  # type: ignore[arg-type]
        assert logging.getLogger().level == logging.getLevelNamesMapping()[level]


def test_a_record_below_the_configured_level_is_not_emitted() -> None:
    with isolated_logging(AppSettings(environment="production", log_level="WARNING")) as stream:
        logging.getLogger("app.probe").info("Ne doit pas sortir.")
        logging.getLogger("app.probe").warning("Doit sortir.")
    assert "Ne doit pas sortir." not in stream.getvalue()
    assert "Doit sortir." in stream.getvalue()


def test_a_chatty_library_keeps_its_floor_even_under_debug() -> None:
    """`LOG_LEVEL=DEBUG` doit rester utilisable pour suivre NOTRE code."""
    with isolated_logging(AppSettings(environment="production", log_level="DEBUG")) as stream:
        logging.getLogger("botocore.auth").debug("Negociation de signature.")
        logging.getLogger("app.probe").debug("Notre trace.")
    assert "Negociation de signature." not in stream.getvalue()
    assert "Notre trace." in stream.getvalue()


# --- Idempotence et loggers du serveur ---------------------------------------


def test_the_root_logger_carries_exactly_one_handler() -> None:
    with isolated_logging(AppSettings(environment="production")):
        assert len(logging.getLogger().handlers) == 1


def test_configuring_twice_does_not_duplicate_the_handlers() -> None:
    """Deux appels convergent, ils ne s'ajoutent jamais -- sinon lignes en double."""
    settings = AppSettings(environment="production")
    with isolated_logging(settings) as stream:
        configure_logging(settings, stream=stream)
        assert len(logging.getLogger().handlers) == 1
        logging.getLogger("app.probe").info("Une seule fois.")
    assert stream.getvalue().count("Une seule fois.") == 1


def test_the_uvicorn_loggers_join_the_single_handler() -> None:
    with isolated_logging(AppSettings(environment="production")) as stream:
        logging.getLogger("uvicorn.error").info("Application startup complete.")
    assert json.loads(stream.getvalue().strip())["logger"] == "uvicorn.error"


def test_the_uvicorn_access_logger_is_silenced() -> None:
    """L'ANTI-DOUBLON du journal d'acces, et il ne tient qu'aux deux conditions.

    Uvicorn interroge `self.access_logger.hasHandlers()` a chaque connexion pour
    decider s'il emet sa propre ligne. Sans handler ET sans propagation, la
    reponse est fausse : il n'emet plus rien, et notre intergiciel reste seul --
    la sienne journalisait le chemin AVEC sa chaine de requete.
    """
    with isolated_logging(AppSettings(environment="production")) as stream:
        access = logging.getLogger("uvicorn.access")
        assert access.handlers == []
        assert access.propagate is False
        assert access.hasHandlers() is False
        access.info('GET /login?token=SECRET HTTP/1.1" 200')
    assert stream.getvalue() == ""


def test_create_app_does_not_touch_the_process_logging() -> None:
    """La configuration appartient au `lifespan`, pas a la fabrique d'application.

    Sans cette regle, les sept tests qui construisent une application
    reconfigureraient la racine -- et arracheraient le handler de `caplog`.
    """
    root = logging.getLogger()
    before = (list(root.handlers), root.level)
    create_app(app_settings=AppSettings(environment="production", log_level="CRITICAL"))
    assert (list(root.handlers), root.level) == before
