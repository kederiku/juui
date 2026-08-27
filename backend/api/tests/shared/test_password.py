"""Tests de l'objet-valeur `Password` et de la politique (BACK-10b).

CE QUE CES TESTS VERROUILLENT EN PLUS DU TICKET

Trois d'entre eux protegent des regressions qu'aucune relecture n'attraperait,
parce qu'elles se presentent comme des ameliorations :

- `test_a_password_of_identical_lowercase_letters_is_accepted` refuse par avance
  la « contrainte de composition » qu'un relecteur bien intentionne voudra
  ajouter. La politique NIST est un choix, pas un oubli.
- Les trois tests de representation refusent le pire defaut possible de ce
  ticket : un mot de passe en clair qui atterrit dans une trace, un diff
  d'assertion pytest ou une ligne de journal.
- `test_a_too_short_password_never_reaches_the_breach_checker` epingle un ORDRE.
  Rien dans les types ne l'impose : c'est le compteur de la doublure qui le prouve.

LES BORNES SONT LUES INCLUSES, contrairement a la lettre du ticket (« strictement
comprise entre 14 et 128 »). Le registre des ecarts porte le raisonnement ; les
tests, eux, epinglent les quatre valeurs qui font la difference.
"""

import copy
import dataclasses
import logging
import pickle
from collections.abc import Callable

import pytest

from app.shared.domain.password import (
    DECOY_PASSWORD,
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    Password,
    PasswordBreachedError,
    PasswordHash,
    PasswordPolicyError,
    PasswordTooLongError,
    PasswordTooShortError,
)
from app.shared.infrastructure.memory.breach_checker import FakeBreachChecker

pytestmark = pytest.mark.passwords

# Un mot de passe honnete, plus long que la borne basse, et qui ne ressemble a
# aucun des mots de passe de test que la doublure declarera fuites.
_SAIN = "correcte-batterie-agrafe"


# ---------------------------------------------------------------------------
# Les bornes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "length",
    [PASSWORD_MIN_LENGTH, PASSWORD_MIN_LENGTH + 1, PASSWORD_MAX_LENGTH - 1, PASSWORD_MAX_LENGTH],
    ids=["borne basse", "juste au-dessus", "juste en dessous", "borne haute"],
)
async def test_a_length_inside_the_bounds_is_accepted(length: int) -> None:
    """Les deux bornes sont INCLUSES : 14 et 128 passent."""
    password = await Password.create("a" * length, breach_checker=FakeBreachChecker())

    assert len(password.value) == length


async def test_a_password_one_character_too_short_is_refused() -> None:
    """Treize caracteres : le refus nomme la borne, jamais la saisie."""
    with pytest.raises(PasswordTooShortError) as refus:
        await Password.create("a" * (PASSWORD_MIN_LENGTH - 1), breach_checker=FakeBreachChecker())

    assert refus.value.code == "shared.password.too_short"
    assert refus.value.details == {
        "min_length": PASSWORD_MIN_LENGTH,
        "max_length": PASSWORD_MAX_LENGTH,
    }


async def test_a_password_one_character_too_long_is_refused() -> None:
    """Cent vingt-neuf caracteres."""
    with pytest.raises(PasswordTooLongError) as refus:
        await Password.create("a" * (PASSWORD_MAX_LENGTH + 1), breach_checker=FakeBreachChecker())

    assert refus.value.code == "shared.password.too_long"


async def test_no_refusal_carries_the_password_in_its_message_or_details() -> None:
    """`details` sort au client sans redaction : il ne porte que les BORNES."""
    trop_court = "s" * (PASSWORD_MIN_LENGTH - 1)

    with pytest.raises(PasswordPolicyError) as refus:
        await Password.create(trop_court, breach_checker=FakeBreachChecker())

    assert trop_court not in refus.value.message
    assert trop_court not in str(refus.value.details)
    # `details` ne porte QUE les bornes, et rien qui mesure la saisie : une mesure
    # du secret n'a rien a faire dans un corps de reponse que tous les journaux
    # clients recopient. Le jeu de cles est donc fige, pas seulement son contenu.
    assert refus.value.details is not None
    assert set(refus.value.details) == {"min_length", "max_length"}
    assert len(trop_court) not in refus.value.details.values()


async def test_a_password_of_identical_lowercase_letters_is_accepted() -> None:
    """AUCUNE contrainte de composition : « aaaaaaaaaaaaaa » passe (NIST SP 800-63B)."""
    password = await Password.create("a" * PASSWORD_MIN_LENGTH, breach_checker=FakeBreachChecker())

    assert password.value == "a" * PASSWORD_MIN_LENGTH


async def test_the_length_is_counted_in_code_points_and_not_in_bytes() -> None:
    """Quatorze emoji font quatorze caracteres -- et cinquante-six octets."""
    password = await Password.create("🐈" * PASSWORD_MIN_LENGTH, breach_checker=FakeBreachChecker())

    assert len(password.utf8) == PASSWORD_MIN_LENGTH * 4


async def test_a_password_is_never_trimmed_normalised_or_recased() -> None:
    """La chaine est conservee telle quelle -- normaliser d'un cote seulement enferme dehors."""
    saisie = f"  {_SAIN}  "

    password = await Password.create(saisie, breach_checker=FakeBreachChecker())

    assert password.value == saisie


# ---------------------------------------------------------------------------
# Le controle de fuite, et ce qui l'empeche d'etre oublie
# ---------------------------------------------------------------------------


def test_a_password_cannot_be_built_without_going_through_the_policy() -> None:
    """LE test du ticket : `Password(...)` echoue, la fabrique est le seul chemin."""
    with pytest.raises(TypeError, match=r"Password\.create"):
        Password(_SAIN)


async def test_replacing_a_field_does_not_smuggle_a_password_past_the_policy() -> None:
    """La voie de contournement trouvee EN REVUE : `replace` rejoue `__init__`.

    La premiere version portait le jeton de fabrique dans un CHAMP de la dataclass.
    `dataclasses.replace` le recopiait avec les autres, si bien qu'une seule ligne
    fabriquait un `Password` portant une valeur connue fuitee, sans un appel au
    controle. Le drapeau vit desormais dans le contexte d'appel, que `replace` n'a
    aucun moyen de reproduire.
    """
    checker = FakeBreachChecker({"motdepasse1234"})
    password = await Password.create(_SAIN, breach_checker=checker)

    with pytest.raises(TypeError):
        dataclasses.replace(password, value="motdepasse1234")

    assert checker.calls == 1


def _round_trip_pickle(password: Password) -> Password:
    """Serialise puis deserialise -- ou plutot : essaie, et doit echouer des le `dumps`.

    Le `noqa` est justifie et non subi : la donnee desserialisee est celle que la
    ligne du dessus vient de produire, et `dumps` leve de toute facon avant que
    `loads` ait quoi que ce soit a lire.
    """
    return pickle.loads(pickle.dumps(password))  # noqa: S301


@pytest.mark.parametrize(
    "contournement",
    [copy.copy, copy.deepcopy, _round_trip_pickle],
    ids=["copy", "deepcopy", "pickle"],
)
async def test_no_copy_or_serialisation_rebuilds_a_password_behind_the_policy(
    contournement: Callable[[Password], Password],
) -> None:
    """Les trois voies qui reconstruisent un objet SANS passer par `__init__`."""
    password = await Password.create(_SAIN, breach_checker=FakeBreachChecker())

    with pytest.raises(TypeError):
        contournement(password)


async def test_a_breached_password_is_refused_with_its_own_code() -> None:
    """Le code dedie qu'attend FRONT-13, distinct des refus de longueur."""
    checker = FakeBreachChecker({_SAIN})

    with pytest.raises(PasswordBreachedError) as refus:
        await Password.create(_SAIN, breach_checker=checker)

    assert refus.value.code == "shared.password.breached"
    assert refus.value.details is None
    assert _SAIN not in refus.value.message
    assert checker.calls == 1


async def test_the_refusal_never_says_how_many_times_the_password_leaked() -> None:
    """Un nombre d'occurrences ferait de l'inscription un oracle sur le corpus."""
    with pytest.raises(PasswordBreachedError) as refus:
        await Password.create(_SAIN, breach_checker=FakeBreachChecker({_SAIN}))

    assert not any(caractere.isdigit() for caractere in refus.value.message)


async def test_a_too_short_password_never_reaches_the_breach_checker() -> None:
    """La longueur mord AVANT le reseau : une saisie de trois lettres ne part pas."""
    checker = FakeBreachChecker()

    with pytest.raises(PasswordTooShortError):
        await Password.create("court", breach_checker=checker)

    assert checker.calls == 0


async def test_an_unavailable_breach_checker_accepts_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """La degradation permissive du port : muet vaut accepte, mais jamais en silence."""
    checker = FakeBreachChecker({_SAIN}, unavailable=True)

    with caplog.at_level(logging.WARNING):
        password = await Password.create(_SAIN, breach_checker=checker)

    assert password.value == _SAIN
    assert checker.calls == 1
    assert len(caplog.records) == 1


async def test_the_comparison_of_the_breach_checker_is_case_sensitive() -> None:
    """Un mot de passe ne se normalise pas : la casse change le secret."""
    password = await Password.create(_SAIN.upper(), breach_checker=FakeBreachChecker({_SAIN}))

    assert password.value == _SAIN.upper()


# ---------------------------------------------------------------------------
# Ce qui ne doit jamais sortir : la valeur
# ---------------------------------------------------------------------------


async def test_no_representation_of_a_password_reveals_its_value() -> None:
    """`repr`, `str`, f-string et `%s` -- les quatre chemins, une seule ligne de code."""
    password = await Password.create(_SAIN, breach_checker=FakeBreachChecker())

    representations = [repr(password), str(password), f"{password}", "%s" % password]  # noqa: UP031

    assert all(_SAIN not in rendu for rendu in representations)
    assert set(representations) == {"Password(***)"}


async def test_a_password_logged_as_a_value_does_not_leak(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Le cas reel : quelqu'un journalise l'objet par megarde, la valeur ne suit pas."""
    password = await Password.create(_SAIN, breach_checker=FakeBreachChecker())

    with caplog.at_level(logging.INFO):
        logging.getLogger(__name__).info("mot de passe recu : %s", password)

    assert _SAIN not in caplog.text


@pytest.mark.parametrize(
    ("encoded", "secret"),
    [
        (
            "$argon2id$v=19$m=19456,t=2,p=1$U6T+V3RwIrGYHKFJpc9dRw$Y29uZGVuc2U",
            "U6T+V3RwIrGYHKFJpc9dRw",
        ),
        ("$argon2id$m=19456,t=2,p=1$U6T+V3RwIrGYHKFJpc9dRw$Y29uZGVuc2U", "U6T+V3RwIrGYHKFJpc9dRw"),
        ("$scrypt$ln=16,r=8,p=1$U2VsU2VsU2Vs$Y29uZGVuc2U", "U2VsU2VsU2Vs"),
    ],
    ids=["avec segment de version", "sans segment de version", "scrypt"],
)
def test_the_hash_representation_never_reveals_the_salt(encoded: str, secret: str) -> None:
    """Le defaut trouve en revue : compter quatre champs depuis le DEBUT.

    Une empreinte a cinq champs -- argon2 sans `v=`, scrypt, pbkdf2 -- voyait alors
    son sel passer pour un parametre et sortir en clair. Le decoupage se fait
    desormais par la fin, ou le format PHC place toujours `$<sel>$<condense>`.
    """
    rendu = repr(PasswordHash(encoded))

    assert secret not in rendu
    assert rendu.endswith("$***)")


def test_the_decoy_password_is_usable_without_any_breach_checker() -> None:
    """Ce que BACK-29 doit pouvoir ecrire en une ligne, et qui n'en tenait pas une.

    La vérification factice sur compte inconnu demande un `Password` jete. Sans
    cette constante, BACK-29 devrait importer une doublure de test dans du code de
    production, ou forcer le drapeau de fabrique.
    """
    assert PASSWORD_MIN_LENGTH <= len(DECOY_PASSWORD.value) <= PASSWORD_MAX_LENGTH
    assert repr(DECOY_PASSWORD) == "Password(***)"


async def test_two_equal_passwords_are_not_equal_objects() -> None:
    """`eq=False` : pas de comparaison de clairs en temps variable, pas de cle de dict."""
    checker = FakeBreachChecker()
    un = await Password.create(_SAIN, breach_checker=checker)
    deux = await Password.create(_SAIN, breach_checker=checker)

    assert un != deux
    assert un == un
