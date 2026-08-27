"""Tests des reglages de signature des jetons (BACK-03, durcis par BACK-10a).

PREMIERS TESTS DE `Settings` DU DEPOT. `tests/core/` ne portait jusqu'ici que
la journalisation, et l'ecart est consigne : trois des quatre regles verifiees
ici ne sont pas des preferences de style mais les seules gardes qui existent
contre des defauts silencieux -- une cle trop courte, un algorithme
indisponible, deux audiences identiques.

Les modeles sont construits par leurs arguments, jamais par l'environnement :
un test qui lirait le `.env` du poste dirait la configuration de ce poste-la.
"""

import pytest
from pydantic import ValidationError

from app.core.config import JWTSettings

pytestmark = pytest.mark.tokens

_VALID_KEY = "cle-de-test-assez-longue-pour-hs256-0123456"


def _settings(**overrides: object) -> JWTSettings:
    """Construit une section JWT valide, que chaque test degrade a sa facon."""
    values: dict[str, object] = {
        "secret_key": _VALID_KEY,
        "audience_professional": "juui-pro",
        "audience_individual": "juui-particulier",
        "audience_admin": "juui-admin",
    }
    values.update(overrides)
    return JWTSettings(**values)


def test_the_default_settings_are_usable() -> None:
    """Les defauts livres suffisent a demarrer : seul le secret est obligatoire."""
    settings = JWTSettings(secret_key=_VALID_KEY)

    assert settings.algorithm == "HS256"
    assert settings.access_token_expire_minutes == 15
    assert settings.refresh_token_expire_days == 7
    assert settings.audience_professional != settings.audience_individual


def test_a_short_signing_key_is_refused() -> None:
    """Le RFC 7518 exige 32 octets pour HS256 ; PyJWT ne fait que le murmurer."""
    with pytest.raises(ValidationError) as refus:
        # La dispense S106 porte sur le SUJET du test : une cle deliberement
        # trop courte, dont on verifie precisement qu'elle est refusee.
        _settings(secret_key="trop-courte")  # noqa: S106

    assert "32" in str(refus.value)


@pytest.mark.parametrize(
    ("algorithm", "length"),
    [("HS384", 47), ("HS512", 63)],
)
def test_a_key_too_short_for_a_larger_algorithm_is_refused(algorithm: str, length: int) -> None:
    """LA BORNE SUIT L'ALGORITHME, sous peine de rendre 500 a chaque emission.

    Une borne unique de 32 octets laissait passer HS384 et HS512 : la
    configuration validait, le service demarrait, et PyJWT levait une
    `InvalidKeyError` -- hors de sa propre hierarchie de jetons -- a chaque
    signature. Le refus doit tomber au demarrage, ou il ne sert a rien.
    """
    with pytest.raises(ValidationError) as refus:
        _settings(secret_key="k" * length, algorithm=algorithm)

    assert algorithm in str(refus.value)


def test_a_non_ascii_key_is_measured_in_bytes_not_in_characters() -> None:
    """Trente-deux caracteres accentues pesent plus de trente-deux octets.

    L'inverse serait le piege : compter les caracteres accepterait une cle de
    trente-deux caracteres dont l'encodage ferait moins d'octets -- ce qui
    n'arrive jamais en UTF-8, mais la borne dit ce qu'elle mesure.
    """
    assert _settings(secret_key="é" * 16).secret_key.get_secret_value() == "é" * 16


def test_an_asymmetric_algorithm_is_refused_at_startup() -> None:
    """`cryptography` n'est pas installe : RS256 rendrait 500 a chaque emission.

    Sans cette borne, le service DEMARRE, passe la validation, puis echoue sur
    chaque login avec une erreur hors de la hierarchie de PyJWT -- donc en 500,
    sans que rien n'ait signale la configuration fautive.
    """
    with pytest.raises(ValidationError) as refus:
        _settings(algorithm="RS256")

    assert refus.value.errors()[0]["type"] == "literal_error"


@pytest.mark.parametrize(
    ("algorithm", "length"),
    [("HS256", 32), ("HS384", 48), ("HS512", 64)],
)
def test_the_hmac_family_is_accepted_with_an_adequate_key(algorithm: str, length: int) -> None:
    """Les trois algorithmes sont utilisables -- avec la cle que chacun exige."""
    settings = _settings(secret_key="k" * length, algorithm=algorithm)

    assert settings.algorithm == algorithm


def test_two_identical_audiences_are_refused() -> None:
    """Deux audiences egales suppriment une frontiere, sans lever nulle part ailleurs."""
    with pytest.raises(ValidationError) as refus:
        _settings(audience_individual="juui-pro")

    assert "distinctes" in str(refus.value)


def test_an_empty_audience_is_refused() -> None:
    """Une audience vide serait absente du jeton, donc recevable partout."""
    with pytest.raises(ValidationError) as refus:
        _settings(audience_admin="")

    assert refus.value.errors()[0]["type"] == "string_too_short"


@pytest.mark.parametrize("field", ["access_token_expire_minutes", "refresh_token_expire_days"])
def test_a_non_positive_lifetime_is_refused(field: str) -> None:
    """Une duree nulle emettrait des jetons deja expires."""
    with pytest.raises(ValidationError):
        _settings(**{field: 0})


@pytest.mark.parametrize(
    ("field", "value"),
    [("access_token_expire_minutes", 1441), ("refresh_token_expire_days", 366)],
)
def test_an_absurd_lifetime_is_refused(field: str, value: int) -> None:
    """Sans borne haute, `iat + duree` finit par deborder la date.

    Le service demarrerait sur une valeur assez grande, puis leverait un
    `OverflowError` a chaque emission -- exactement le schema que la borne de
    longueur de cle vient de fermer.
    """
    with pytest.raises(ValidationError):
        _settings(**{field: value})


@pytest.mark.parametrize("audience", ["  ", "juui-admin "])
def test_an_audience_that_is_blank_or_padded_is_refused(audience: str) -> None:
    """Une espace de bordure produirait un refus reserve a une seule application.

    Elle rendrait l'audience DISTINCTE de celle que l'application attend, sans
    rien changer a sa lecture : une panne aussi selective que penible a
    diagnostiquer.
    """
    with pytest.raises(ValidationError):
        _settings(audience_admin=audience)
