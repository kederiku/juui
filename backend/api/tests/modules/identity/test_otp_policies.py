"""Primitives du code de verification : tirage, empreinte, comparaison (BACK-17).

Les tests les plus courts du ticket, et ceux qui portent le plus : trois criteres
d'acceptation sur cinq se jouent dans ces trois fonctions -- « genere via
secrets », « stocke hache », « comparaison en temps constant ».
"""

import hmac
from uuid import uuid4

import pytest

from app.modules.identity.domain import policies
from app.modules.identity.domain.policies import (
    OTP_CODE_LENGTH,
    codes_match,
    fingerprint_otp_code,
    generate_otp_code,
)
from tests.modules.identity.otp_doubles import otp_rules


def test_generated_code_has_six_digits() -> None:
    """Six chiffres, et rien d'autre -- ni signe, ni espace, ni lettre."""
    for _ in range(200):
        code = generate_otp_code()
        assert len(code) == OTP_CODE_LENGTH
        assert code.isdigit()


def test_generated_code_keeps_its_leading_zeros(monkeypatch: pytest.MonkeyPatch) -> None:
    """« 004271 » est un code a six chiffres, pas le nombre 4271.

    Le zero de tete est le piege classique de l'OTP numerique : un aller-retour
    par `int` le mange, et la comparaison echoue sur un code pourtant juste.
    """
    monkeypatch.setattr(policies.secrets, "randbelow", lambda _upper: 4271)

    assert generate_otp_code() == "004271"


def test_generated_code_is_drawn_from_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    """Le tirage passe par `secrets`, JAMAIS par `random`.

    Le critere du ticket, verifie a la source : `random` sert un Mersenne Twister
    dont l'etat se reconstitue a partir de quelques sorties observees. Un
    attaquant qui demande des codes pour son propre compte predirait ceux des
    autres -- et aucun test de forme ne le verrait.
    """
    calls: list[int] = []

    def _spy(upper: int) -> int:
        calls.append(upper)
        return 123456

    monkeypatch.setattr(policies.secrets, "randbelow", _spy)

    generate_otp_code()

    assert calls == [10**OTP_CODE_LENGTH]


def test_generated_codes_are_not_all_alike() -> None:
    """Sonde grossiere d'entropie : deux cents tirages ne donnent pas dix valeurs."""
    draws = {generate_otp_code() for _ in range(200)}

    assert len(draws) > 150


def test_fingerprint_is_stable_for_the_same_inputs() -> None:
    """Meme code, meme compte, meme poivre : meme empreinte -- sinon rien ne se verifie."""
    account_id = uuid4()

    first = fingerprint_otp_code("123456", account_id=account_id, pepper=b"poivre")
    second = fingerprint_otp_code("123456", account_id=account_id, pepper=b"poivre")

    assert first == second


def test_fingerprint_never_contains_the_code() -> None:
    """Ce qui est range ne doit pas laisser relire le secret."""
    fingerprint = fingerprint_otp_code("123456", account_id=uuid4(), pepper=b"poivre")

    assert "123456" not in fingerprint
    assert len(fingerprint) == 64


def test_fingerprint_is_bound_to_the_account() -> None:
    """Deux comptes ayant tire le meme code n'ont pas la meme empreinte.

    Une collision de code arrive une fois sur un million, donc souvent a l'echelle
    d'un service. Sans l'identifiant dans l'empreinte, une empreinte relue
    ailleurs vaudrait preuve ici.
    """
    code = "123456"

    first = fingerprint_otp_code(code, account_id=uuid4(), pepper=b"poivre")
    second = fingerprint_otp_code(code, account_id=uuid4(), pepper=b"poivre")

    assert first != second


def test_fingerprint_depends_on_the_pepper() -> None:
    """Sans poivre distinct, le condense se rejoue -- c'est tout l'objet de la cle."""
    account_id = uuid4()

    first = fingerprint_otp_code("123456", account_id=account_id, pepper=b"poivre-a")
    second = fingerprint_otp_code("123456", account_id=account_id, pepper=b"poivre-b")

    assert first != second


def test_fingerprint_refuses_an_empty_pepper() -> None:
    """Un HMAC a cle nulle serait reproductible par qui lit le stockage."""
    with pytest.raises(ValueError, match="poivre"):
        fingerprint_otp_code("123456", account_id=uuid4(), pepper=b"")


def test_codes_match_accepts_identical_fingerprints() -> None:
    """Le cas nominal, sans lequel rien ne se verifierait jamais."""
    assert codes_match("a" * 64, "a" * 64)


def test_codes_match_refuses_different_fingerprints() -> None:
    """Et le cas contraire, y compris quand tout diverge des le premier caractere."""
    assert not codes_match("a" * 64, "b" * 64)
    assert not codes_match("", "b" * 64)


def test_codes_match_uses_a_constant_time_comparison(monkeypatch: pytest.MonkeyPatch) -> None:
    """LE critere du ticket : la comparaison passe par `hmac.compare_digest`.

    Verifie a la source et non par chronometre : mesurer un ecart de quelques
    nanosecondes dans une suite de tests donnerait un test instable qui ne
    prouverait rien. Ce qui compte est qu'un `==` ne puisse pas se glisser ici --
    l'egalite de chaines de Python s'arrete au premier caractere different, et sa
    duree trahit alors le nombre de caracteres corrects.
    """
    calls: list[tuple[str, str]] = []
    # La vraie fonction est capturee AVANT la substitution : `policies.hmac` est
    # le module `hmac` lui-meme, et un `_spy` qui appellerait
    # `hmac.compare_digest` s'appellerait donc lui-meme, indefiniment.
    real_compare = hmac.compare_digest

    def _spy(left: str, right: str) -> bool:
        calls.append((left, right))
        return real_compare(left, right)

    monkeypatch.setattr(policies.hmac, "compare_digest", _spy)

    assert codes_match("a" * 64, "a" * 64)
    assert calls == [("a" * 64, "a" * 64)]


def test_rules_refuse_a_ttl_that_is_not_positive() -> None:
    """Un code eternel n'est plus un code a usage unique."""
    with pytest.raises(ValueError, match="ttl_seconds"):
        otp_rules(ttl_seconds=0)


def test_rules_refuse_a_quota_of_attempts_that_is_not_positive() -> None:
    """Zero tentative rendrait tout code invalide ; une valeur negative n'a pas de sens."""
    with pytest.raises(ValueError, match="max_attempts"):
        otp_rules(max_attempts=0)


def test_rules_accept_a_disabled_minimum_interval() -> None:
    """Zero desactive le delai minimal -- les deux plafonds, eux, restent en place."""
    rules = otp_rules(resend_min_interval_seconds=0)

    assert rules.resend_min_interval_seconds == 0


def test_rules_refuse_a_negative_minimum_interval() -> None:
    """Un delai negatif ne desactive rien : il trahit une soustraction quelque part."""
    with pytest.raises(ValueError, match="resend_min_interval_seconds"):
        otp_rules(resend_min_interval_seconds=-1)
