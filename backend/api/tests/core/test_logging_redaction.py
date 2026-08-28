"""Masquage des valeurs sensibles dans les journaux (BACK-11, criteres 5 et 8).

DEUX MECANISMES, ET LE SECOND N'EST QU'UN FILET
`redact_mapping` travaille sur des NOMS DE CLE : c'est le mecanisme, et il n'a
pas de faux negatif. `redact_text` travaille sur des formes dans un message deja
interpole : il rattrape l'oubli, il ne le legitime pas. Le dernier test du
fichier consigne le contre-exemple qui en decoule -- une limite connue vaut mieux
qu'une limite decouverte en incident.
"""

import json
import logging
from typing import Final

import pytest

from app.core.logging import REDACTED, JsonFormatter, redact_mapping, redact_query, redact_text
from tests.support.logs import log_sink, make_record

pytestmark = pytest.mark.observability

# Les six termes que le ticket enumere. `cookie`, ajoute par l'implementation,
# n'y figure pas : ce test doit continuer a prouver LE CRITERE, pas la constante.
TICKET_TERMS: Final = ("password", "token", "authorization", "secret", "otp", "chip_number")

# Une valeur unique par terme : les assertions cherchent des SOUS-CHAINES dans le
# flux rendu. Ce qui fuirait par un `repr()`, par `record.args` ou par un attribut
# que personne n'a pense a masquer se voit ici, et nulle part ailleurs.
SENTINELS: Final[dict[str, str]] = {
    "password": "SENTINEL-PASSWORD-9f3a",
    "token": "SENTINEL-TOKEN-4c1e",
    "authorization": "Bearer SENTINEL-AUTHZ-77bd",
    "secret": "SENTINEL-SECRET-e021",
    "otp": "SENTINEL-OTP-135790",
    "chip_number": "SENTINEL-CHIP-250269604000000",
}


# --- Le mecanisme : par nom de cle -------------------------------------------


@pytest.mark.parametrize("term", TICKET_TERMS)
def test_each_term_of_the_ticket_is_masked_in_a_mapping(term: str) -> None:
    assert redact_mapping({term: "valeur-en-clair"}) == {term: REDACTED}


@pytest.mark.parametrize("key", ["PASSWORD", "Authorization", "Token", "OTP"])
def test_masking_is_case_insensitive(key: str) -> None:
    assert redact_mapping({key: "valeur-en-clair"}) == {key: REDACTED}


@pytest.mark.parametrize(
    "key",
    ["access_token", "refresh_token", "hashed_password", "otp_code", "jwt_secret", "set-cookie"],
)
def test_a_composite_key_containing_a_sensitive_term_is_masked(key: str) -> None:
    """La correspondance est une SOUS-CHAINE : c'est ce qui couvre les noms reels."""
    assert redact_mapping({key: "valeur-en-clair"}) == {key: REDACTED}


def test_a_nested_mapping_is_masked() -> None:
    masked = redact_mapping({"payload": {"user": "alice", "password": "en-clair"}})
    assert masked == {"payload": {"user": "alice", "password": REDACTED}}


def test_a_mapping_inside_a_sequence_is_masked() -> None:
    masked = redact_mapping({"items": [{"otp": "135790"}, {"page": 2}]})
    assert masked == {"items": [{"otp": REDACTED}, {"page": 2}]}


def test_the_mask_never_reveals_the_length_of_the_value() -> None:
    """Un masque proportionnel divulguerait une partie du secret."""
    assert redact_mapping({"password": "x" * 40})["password"] == REDACTED


def test_the_other_fields_survive_untouched() -> None:
    assert redact_mapping({"password": "x", "page": 2, "path": "/a"}) == {
        "password": REDACTED,
        "page": 2,
        "path": "/a",
    }


def test_masking_does_not_mutate_the_caller_mapping() -> None:
    """L'appelant garde SES donnees : le masquage ne s'applique qu'a la copie."""
    original = {"password": "en-clair", "nested": {"token": "en-clair"}}
    redact_mapping(original)
    assert original == {"password": "en-clair", "nested": {"token": "en-clair"}}


def test_a_self_referencing_structure_does_not_hang_the_masking() -> None:
    """Un formateur qui boucle est une panne sans journal pour l'expliquer."""
    looping: dict[str, object] = {"page": 1}
    looping["self"] = looping
    assert redact_mapping({"payload": looping})["payload"] is not None


# --- Le filet : par forme, dans un message deja interpole ---------------------


@pytest.mark.parametrize(
    "message",
    [
        "password=en-clair",
        'payload={"password": "en-clair"}',
        "password: en-clair",
        "ACCESS_TOKEN=en-clair",
    ],
)
def test_the_three_assignment_forms_are_masked_in_a_message(message: str) -> None:
    assert "en-clair" not in redact_text(message)


def test_url_credentials_are_masked_without_any_key_name() -> None:
    """Le filet le plus utile : trois modules repetent que leurs URL portent le mot de passe."""
    assert redact_text("postgresql+asyncpg://juui:en-clair@localhost/app") == (
        f"postgresql+asyncpg://juui:{REDACTED}@localhost/app"
    )
    assert (
        redact_text("redis://:en-clair@localhost:6379/1") == f"redis://:{REDACTED}@localhost:6379/1"
    )


def test_a_bare_bearer_token_is_masked() -> None:
    assert redact_text("jeton recu : Bearer eyJhbG.en-clair") == f"jeton recu : Bearer {REDACTED}"


def test_a_named_bearer_token_is_masked_once_and_entirely() -> None:
    """Le prefixe de schema est avale par l'affectation : un seul masque, pas deux."""
    assert redact_text("Authorization: Bearer eyJhbG.en-clair") == f"Authorization: {REDACTED}"


# --- Les chaines de requete --------------------------------------------------


def test_a_sensitive_query_parameter_is_masked_and_the_rest_survives() -> None:
    assert redact_query("token=en-clair&page=2") == f"token={REDACTED}&page=2"


def test_the_masked_query_stays_readable() -> None:
    """Sans `safe`, `urlencode` rendrait `%2A%2A%2A`, qu'aucun grep humain ne reconnait."""
    assert "%2A" not in redact_query("chip_number=250269604000000")


def test_an_empty_query_stays_empty() -> None:
    assert redact_query("") == ""


# --- Le critere 8, de bout en bout -------------------------------------------


def test_the_masking_covers_records_propagated_from_a_child_logger() -> None:
    """Le masquage vit dans le FORMATEUR, donc aupres du handler.

    Un `logging.Filter` pose sur un logger ne verrait pas les enregistrements
    propages depuis ses enfants -- c'est-a-dire rien de ce que journalise
    `app.modules.*`. C'est la raison structurelle pour laquelle ce projet n'en
    pose aucun, et ce test la fige.
    """
    with log_sink(JsonFormatter()) as sink:
        logging.getLogger(f"{sink.logger.name}.enfant.petit_enfant").error(
            "Echec.", extra={"password": "en-clair"}
        )
    assert sink.only_json()["password"] == REDACTED


def test_no_sentinel_reaches_the_rendered_stream() -> None:
    """Le critere 8 en un test : aucune des six valeurs n'existe dans la sortie.

    Assertion par SOUS-CHAINE et non par cle -- c'est ce qui distingue « la cle
    password vaut *** » de « le mot de passe n'est nulle part ». Les deux sont
    utiles ; celle-ci est celle qui tient le critere.
    """
    with log_sink(JsonFormatter()) as sink:
        sink.logger.info("Sonde structuree.", extra={"context": dict(SENTINELS)})
        sink.logger.warning("Sonde positionnelle : %s", dict(SENTINELS))
        sink.logger.error("Sonde d'affectation : password=%s", SENTINELS["password"])
    rendered = sink.stream.getvalue()
    for term, sentinel in SENTINELS.items():
        assert sentinel not in rendered, f"« {term} » a fui dans la sortie."


def test_a_bare_secret_inside_an_exception_message_escapes_the_net() -> None:
    """CONTRE-EXEMPLE CONSIGNE : le filet ne dispense pas de la regle.

    Un secret leve dans un message d'exception, SANS nom de cle aux alentours,
    n'est masquable par aucun mecanisme fonde sur les noms -- rien ne distingue
    `RuntimeError: hunter2` d'un message legitime. La limite est inscrite au
    registre des ecarts ; ce test existe pour qu'elle ne se decouvre pas en
    incident, et pour qu'il faille le lire avant de la lever.

    La contrepartie tient au test qui precede : des qu'un nom de cle accompagne
    la valeur -- ce qui est le cas de tout message ecrit avec soin --, le filet
    l'attrape, y compris dans une trace.
    """
    with log_sink(JsonFormatter()) as sink:
        try:
            raise RuntimeError(SENTINELS["token"])
        except RuntimeError:
            sink.logger.exception("Sonde de trace nue.")
    assert SENTINELS["token"] in sink.only_line()

    with log_sink(JsonFormatter()) as named:
        try:
            raise RuntimeError(f"echec, token={SENTINELS['token']}")
        except RuntimeError:
            named.logger.exception("Sonde de trace nommee.")
    assert SENTINELS["token"] not in named.only_line()


def test_a_reserved_log_record_attribute_is_never_shadowed_by_an_extra() -> None:
    """Les cles de la ligne d'acces sont libres, et ce test le verrouille.

    `logging` leve un `KeyError` si un `extra` porte le nom d'un attribut de
    `LogRecord` -- sur le chemin de journalisation, c'est-a-dire au pire endroit.
    `pathname` est reserve, `path` ne l'est pas : la nuance vaut un test.
    """
    record = make_record(
        extra={"method": "GET", "path": "/x", "status": 200, "duration_ms": 1.0, "query": "a=1"}
    )
    rendered = json.loads(JsonFormatter().format(record))
    assert rendered["path"] == "/x"
    assert rendered["status"] == 200
