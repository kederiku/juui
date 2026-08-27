"""Tests de l'adaptateur argon2id du port `PasswordHasher` (BACK-10b).

LES COUTS DE TEST SONT BAS, ET CE N'EST PAS UN RACCOURCI. Un hachage aux couts de
production coute une quinzaine de millisecondes ; une suite qui en fait trente les
paierait toutes. Ce que ces tests verifient -- la correspondance des exceptions,
la remise a niveau, l'absence de fuite -- ne depend pas du cout. Le seul test qui
en depend construit son hacheur depuis la CONFIGURATION, et compare ce que
l'empreinte encode a ce que `Settings` declare : verrouiller le reglage, et pas
seulement constater qu'il existe.

CE QUE CES TESTS VERROUILLENT EN PLUS DU TICKET
La correspondance des exceptions a ete etablie EN EXECUTANT argon2-cffi 25.1, et
deux de ses resultats sont contre-intuitifs au point qu'une relecture les
inverserait :

- `VerifyMismatchError` HERITE de `VerificationError`. Un `except VerificationError`
  place avant elle transformerait le cas nominal -- quelqu'un s'est trompe de mot
  de passe -- en panne technique, donc en 500 sur chaque connexion ratee.
- Une empreinte TRONQUEE mais bien formee leve `VerificationError`, et NON
  `InvalidHashError`. Attraper la seule `InvalidHashError` laisserait donc filer
  un 500 sur le cas le plus probable de corruption de colonne.

Les deux ont leur test, avec l'empreinte litterale qui les produit.
"""

import logging

import argon2
import pytest
from argon2.exceptions import HashingError

from app.core import get_settings
from app.shared.domain.password import Password, PasswordHash
from app.shared.domain.ports.password_hasher import (
    PasswordHasher,
    PasswordHashingFailedError,
    StoredPasswordHashInvalidError,
)
from app.shared.infrastructure.memory.breach_checker import FakeBreachChecker
from app.shared.infrastructure.security.password import (
    ARGON2_PARALLELISM,
    Argon2Parameters,
    Argon2PasswordHasher,
    build_password_hasher,
)

pytestmark = pytest.mark.passwords

_SAIN = "correcte-batterie-agrafe"

# Couts de test : le plancher de la BIBLIOTHEQUE, pas celui de la configuration.
# `PasswordSettings` refuse de descendre sous la recommandation de l'OWASP ; ces
# parametres-ci ne passent pas par elle, et c'est ce qui rend la suite rapide.
_RAPIDE = Argon2Parameters(time_cost=1, memory_cost_kib=8192)
_PLUS_CHER = Argon2Parameters(time_cost=2, memory_cost_kib=16384)

# Empreinte STRUCTURELLEMENT VALIDE mais tronquee : sel et condense trop courts.
# C'est elle qui leve `VerificationError` sans etre une `InvalidHashError` -- le
# piege decrit en tete de fichier. Ne pas la remplacer par du charabia : le
# charabia, lui, leve `InvalidHashError` et masquerait le trou.
_TRONQUEE = "$argon2id$v=19$m=8192,t=1,p=1$AAAAAAAAAAAAAAAAAAAAAA$BBBB"


async def _un_password(valeur: str = _SAIN) -> Password:
    """Fabrique un mot de passe accepte, sans reseau."""
    return await Password.create(valeur, breach_checker=FakeBreachChecker())


def _hasher(parameters: Argon2Parameters = _RAPIDE) -> Argon2PasswordHasher:
    """Un hacheur aux couts donnes."""
    return Argon2PasswordHasher(parameters=parameters)


# ---------------------------------------------------------------------------
# Aller-retour
# ---------------------------------------------------------------------------


async def test_a_password_verifies_against_its_own_hash() -> None:
    """L'aller-retour nominal."""
    hasher = _hasher()

    stored = await hasher.hash(await _un_password())
    outcome = await hasher.verify(stored=stored, candidate=_SAIN)

    assert outcome.verified is True


async def test_another_password_does_not_verify_and_raises_nothing() -> None:
    """Un mot de passe faux est le cas NOMINAL d'un formulaire : il ne leve pas."""
    hasher = _hasher()

    stored = await hasher.hash(await _un_password())
    outcome = await hasher.verify(stored=stored, candidate="ce-n-est-pas-le-bon")

    assert outcome.verified is False
    assert outcome.refreshed_hash is None


async def test_hashing_the_same_password_twice_gives_two_distinct_hashes() -> None:
    """Le sel est tire a chaque fois -- sans quoi deux comptes se trahiraient."""
    hasher = _hasher()
    password = await _un_password()

    premiere = await hasher.hash(password)
    seconde = await hasher.hash(password)

    assert premiere.encoded != seconde.encoded
    assert (await hasher.verify(stored=seconde, candidate=_SAIN)).verified is True


async def test_a_password_with_accents_and_emoji_survives_the_round_trip() -> None:
    """L'encodage UTF-8 est nomme une fois : hachage et verification voient les memes octets."""
    valeur = "clé-à-molette-🔧-et-café"
    hasher = _hasher()

    stored = await hasher.hash(await _un_password(valeur))

    assert (await hasher.verify(stored=stored, candidate=valeur)).verified is True


async def test_the_longest_allowed_password_still_verifies() -> None:
    """Cent vingt-huit emoji, soit 512 octets : la connexion ne doit pas les refuser.

    Le piege que ce test ferme : une borne d'octets ecrite sur la borne de
    CARACTERES rendrait invérifiable a la connexion un mot de passe accepte a
    l'inscription -- et seulement pour les gens qui n'ecrivent pas en ASCII.
    """
    valeur = "🐈" * 128
    hasher = _hasher()

    stored = await hasher.hash(await _un_password(valeur))

    assert (await hasher.verify(stored=stored, candidate=valeur)).verified is True


# ---------------------------------------------------------------------------
# Les couts, et ce que l'empreinte en dit
# ---------------------------------------------------------------------------


async def test_the_hash_announces_the_argon2id_variant() -> None:
    """Ni argon2i ni argon2d : la variante hybride, epinglee dans l'adaptateur."""
    stored = await _hasher().hash(await _un_password())

    assert stored.encoded.startswith("$argon2id$")


async def test_the_configured_costs_are_the_ones_the_hash_encodes() -> None:
    """Le reglage PILOTE, il n'existe pas seulement : l'empreinte le porte."""
    settings = get_settings()

    stored = await build_password_hasher(settings).hash(await _un_password())

    attendu = (
        f"m={settings.password.argon2_memory_cost_kib},"
        f"t={settings.password.argon2_time_cost},"
        f"p={ARGON2_PARALLELISM}"
    )
    assert attendu in stored.encoded


# ---------------------------------------------------------------------------
# La remise a niveau
# ---------------------------------------------------------------------------


async def test_an_up_to_date_hash_is_not_refreshed() -> None:
    """Rien a reecrire quand les couts n'ont pas bouge."""
    hasher = _hasher()

    stored = await hasher.hash(await _un_password())
    outcome = await hasher.verify(stored=stored, candidate=_SAIN)

    assert outcome.refreshed_hash is None


async def test_a_stale_hash_is_refreshed_and_the_new_one_verifies() -> None:
    """LE critere « rehash au login si les couts changent » du ticket."""
    ancienne = await _hasher(_RAPIDE).hash(await _un_password())
    courant = _hasher(_PLUS_CHER)

    outcome = await courant.verify(stored=ancienne, candidate=_SAIN)

    assert outcome.verified is True
    assert outcome.refreshed_hash is not None
    assert f"m={_PLUS_CHER.memory_cost_kib},t={_PLUS_CHER.time_cost}" in (
        outcome.refreshed_hash.encoded
    )
    assert (await courant.verify(stored=outcome.refreshed_hash, candidate=_SAIN)).verified is True


async def test_a_failed_verification_never_refreshes_anything() -> None:
    """On ne rehache pas ce dont on vient de prouver qu'on ne le connait pas."""
    ancienne = await _hasher(_RAPIDE).hash(await _un_password())

    outcome = await _hasher(_PLUS_CHER).verify(stored=ancienne, candidate="mauvais-mot-de-passe")

    assert outcome.verified is False
    assert outcome.refreshed_hash is None


async def test_a_refresh_that_fails_leaves_the_verification_valid(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Une connexion valide ne se perd pas pour une remise a niveau ratee."""
    ancienne = await _hasher(_RAPIDE).hash(await _un_password())
    courant = _hasher(_PLUS_CHER)

    def _echoue(*_args: object, **_kwargs: object) -> str:
        raise HashingError("plus assez de memoire")

    monkeypatch.setattr(argon2.PasswordHasher, "hash", _echoue)

    with caplog.at_level(logging.WARNING):
        outcome = await courant.verify(stored=ancienne, candidate=_SAIN)

    assert outcome.verified is True
    assert outcome.refreshed_hash is None
    assert len(caplog.records) == 1
    assert _SAIN not in caplog.text


# ---------------------------------------------------------------------------
# Les empreintes illisibles : elles LEVENT, elles ne rendent pas « faux »
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "encoded",
    [_TRONQUEE, "pas-une-empreinte", "$argon2id$"],
    ids=["tronquee mais bien formee", "charabia", "prefixe seul"],
)
async def test_an_unreadable_stored_hash_raises_instead_of_refusing(encoded: str) -> None:
    """Rendre « faux » dirait que tout le monde se trompe de mot de passe."""
    with pytest.raises(StoredPasswordHashInvalidError):
        await _hasher().verify(stored=PasswordHash(encoded), candidate=_SAIN)


async def test_no_argon2_exception_crosses_the_port() -> None:
    """Le contrat du port : ce qui en sort est `False` ou l'une de ses trois erreurs."""
    with pytest.raises(StoredPasswordHashInvalidError) as refus:
        await _hasher().verify(stored=PasswordHash(_TRONQUEE), candidate=_SAIN)

    assert not isinstance(refus.value, argon2.exceptions.Argon2Error)
    assert _SAIN not in str(refus.value)
    assert _TRONQUEE not in str(refus.value)


async def test_a_hashing_failure_names_the_configured_memory_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le cas concret est l'allocation refusee : l'exploitant doit savoir quel bouton tourner."""

    def _echoue(*_args: object, **_kwargs: object) -> str:
        raise HashingError("plus assez de memoire")

    monkeypatch.setattr(argon2.PasswordHasher, "hash", _echoue)

    with pytest.raises(PasswordHashingFailedError, match=str(_RAPIDE.memory_cost_kib)):
        await _hasher().hash(await _un_password())


async def test_a_candidate_that_python_cannot_encode_does_not_cross_the_port() -> None:
    """Inatteignable par HTTP, atteignable depuis un script : la regle du port vaut quand meme."""
    hasher = _hasher()
    stored = await hasher.hash(await _un_password())

    with pytest.raises(PasswordHashingFailedError):
        await hasher.verify(stored=stored, candidate="surrogate-isole-\ud800")


def test_an_empty_hash_is_refused_at_construction() -> None:
    """Une empreinte vide est un defaut de programme, pas un refus metier."""
    with pytest.raises(ValueError, match="vide"):
        PasswordHash("")


def test_the_adapter_satisfies_the_port() -> None:
    """La doublure du contrat : l'adaptateur EST un `PasswordHasher`."""
    assert isinstance(_hasher(), PasswordHasher)
