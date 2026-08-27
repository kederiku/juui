"""Tests des reglages de mot de passe et de controle de fuite (BACK-10b).

CE QUE CES QUATRE PLANCHERS DEFENDENT
Aucun n'est une preference de style. Chacun ferme une porte qui laisserait le
service DEMARRER puis se comporter mal, c'est-a-dire la classe de defaut que
`JWTSettings` documente longuement et que BACK-10a a durcie pour les memes
raisons :

- un cout argon2 abaissable a distance, sur un service qui REHACHE
  automatiquement a la connexion, ne produit pas seulement des empreintes neuves
  faibles : il degrade activement toutes les anciennes, compte par compte, a
  mesure que leurs proprietaires se connectent ;
- un cout memoire demesure demarre, puis fait echouer chaque hachage ;
- un delai nul desactive le controle de fuite EN SILENCE, chaque appel expirant
  avant de partir ;
- une adresse en clair ferait voyager le prefixe d'empreinte hors de TLS.

Les modeles sont construits par leurs arguments, jamais par l'environnement : un
test qui lirait le `.env` du poste dirait la configuration de ce poste-la.
"""

import pytest
from pydantic import ValidationError

from app.core.config import HibpSettings, PasswordSettings

pytestmark = pytest.mark.passwords

# La configuration recommandee par l'OWASP a `p=1`, qui est aussi le plancher.
_OWASP_TIME_COST = 2
_OWASP_MEMORY_COST_KIB = 19456


def test_the_default_password_settings_are_the_owasp_configuration() -> None:
    """Les defauts livres sont ceux de l'OWASP, pas une valeur choisie au hasard."""
    settings = PasswordSettings()

    assert settings.argon2_time_cost == _OWASP_TIME_COST
    assert settings.argon2_memory_cost_kib == _OWASP_MEMORY_COST_KIB


@pytest.mark.parametrize(
    "overrides",
    [
        {"argon2_time_cost": _OWASP_TIME_COST - 1},
        {"argon2_memory_cost_kib": _OWASP_MEMORY_COST_KIB - 1},
        {"argon2_time_cost": 0},
        {"argon2_memory_cost_kib": 8},
    ],
    ids=["une passe de moins", "un kibioctet de moins", "zero passe", "8 KiB"],
)
def test_a_cost_below_the_owasp_floor_is_refused(overrides: dict[str, int]) -> None:
    """Le plancher est un ABSOLU : on ne descend pas sous la recommandation."""
    with pytest.raises(ValidationError):
        PasswordSettings(**overrides)


def test_a_memory_cost_large_enough_to_exhaust_the_container_is_refused() -> None:
    """Quatre gibioctets demarreraient, puis feraient echouer chaque hachage."""
    with pytest.raises(ValidationError):
        PasswordSettings(argon2_memory_cost_kib=4 * 1024 * 1024)


def test_costs_above_the_floor_are_accepted() -> None:
    """Le plancher borne vers le BAS : monter le cout reste le geste attendu."""
    settings = PasswordSettings(argon2_time_cost=4, argon2_memory_cost_kib=65536)

    assert settings.argon2_time_cost == 4
    assert settings.argon2_memory_cost_kib == 65536


def test_the_default_hibp_settings_point_at_the_real_service() -> None:
    """Le defaut est utilisable tel quel : rien a regler pour que le controle marche."""
    settings = HibpSettings()

    assert settings.api_url == "https://api.pwnedpasswords.com"
    assert settings.timeout_seconds == 2.0


def test_a_zero_timeout_is_refused_because_it_would_disable_the_check_silently() -> None:
    """Zero n'est pas « pas de limite » : c'est « chaque appel expire avant de partir »."""
    with pytest.raises(ValidationError):
        HibpSettings(timeout_seconds=0)


def test_a_timeout_long_enough_to_hang_a_registration_is_refused() -> None:
    """La borne haute preserve la promesse du ticket : un delai COURT."""
    with pytest.raises(ValidationError):
        HibpSettings(timeout_seconds=60)


@pytest.mark.parametrize(
    "api_url",
    ["http://api.pwnedpasswords.com", "api.pwnedpasswords.com", "ftp://ailleurs.example"],
    ids=["http en clair", "sans schema", "autre protocole"],
)
def test_an_api_url_that_is_not_https_is_refused(api_url: str) -> None:
    """Le prefixe d'empreinte ne voyage pas hors de TLS."""
    with pytest.raises(ValidationError):
        HibpSettings(api_url=api_url)


def test_a_trailing_slash_in_the_api_url_is_trimmed() -> None:
    """L'adaptateur ajoute `/range/...` : deux barres de suite feraient un 404."""
    settings = HibpSettings(api_url="https://api.pwnedpasswords.com/")

    assert settings.api_url == "https://api.pwnedpasswords.com"
