"""Reponse a la panne et inspecteurs des doublures de ports techniques (BACK-06c).

CE FICHIER EPROUVE LA MOITIE DU CONTRAT QUE LA CONFORMITE NE PEUT PAS COMPARER :
ce que chaque port fait quand le service qu'il masque ne repond plus. Les trois
reponses sont DIFFERENTES, et c'est tout le sujet -- `Cache` degrade,
`FileStorage` leve, `BreachChecker` accepte. Une doublure qui les confondrait
ferait passer en test un service qui tombe la ou il devait tenir, ou l'inverse.
"""

import logging
from uuid import uuid4

import pytest

from app.core import get_settings
from app.shared.domain.ports.cache import MISSING, CacheScope
from app.shared.domain.ports.email import EmailDeliveryError
from app.shared.domain.ports.file_storage import (
    FileStorageUnavailableError,
    InvalidStorageKeyError,
)
from app.shared.infrastructure.clients.storage_keys import build_storage_key
from app.shared.infrastructure.memory.breach_checker import FakeBreachChecker
from app.shared.infrastructure.memory.cache import build_in_memory_cache
from app.shared.infrastructure.memory.clock import FakeClock
from app.shared.infrastructure.memory.email import FakeEmailTransport
from app.shared.infrastructure.memory.file_storage import InMemoryFileStorage
from app.shared.infrastructure.tenancy import use_group

_PNG = b"\x89PNG\r\n\x1a\n"


# --- InMemoryCache : la degradation, l'horloge, le prefixage ----------------


async def test_an_unavailable_cache_degrades_on_every_operation() -> None:
    """« Si Redis est arrete, l'application continue de repondre », prouve sans arreter Redis."""
    cache = build_in_memory_cache(get_settings())
    cache.unavailable = True
    with use_group(uuid4()):
        assert await cache.get("dossier") is MISSING
        await cache.set("dossier", 1, ttl=60)
        assert await cache.exists("dossier") is False
        assert await cache.delete("dossier") is False
        assert await cache.invalidate_pattern("dossier*") == 0
    assert await cache.ping() is False


async def test_an_unavailable_cache_still_refuses_an_invalid_call() -> None:
    """La panne relache le STOCKAGE, jamais la validation : les deux sont distinctes."""
    cache = build_in_memory_cache(get_settings())
    cache.unavailable = True
    with use_group(uuid4()):
        with pytest.raises(ValueError, match="vide"):
            await cache.get("")
        with pytest.raises(ValueError, match="strictement positif"):
            await cache.set("dossier", 1, ttl=0)


async def test_the_physical_key_carries_the_environment_and_the_group() -> None:
    """La doublure compose ses cles avec le VRAI compositeur : elle prouve la production."""
    cache = build_in_memory_cache(get_settings())
    group = uuid4()
    with use_group(group):
        await cache.set("dossier:42", "vu", ttl=60)
        await cache.set("catalogue", "commun", ttl=60, scope=CacheScope.SHARED)
    keys = cache.physical_keys()
    assert any(key.endswith(f"g-{group}:dossier:42") for key in keys)
    assert any(key.endswith("shared:catalogue") for key in keys)


async def test_a_piloted_clock_expires_an_entry_without_waiting() -> None:
    """L'interet de l'horloge injectee : dix minutes de TTL en zero seconde de test."""
    clock = FakeClock()
    cache = build_in_memory_cache(get_settings(), clock=clock)
    with use_group(uuid4()):
        await cache.set("code", "123456", ttl=600)
        clock.advance(599)
        assert await cache.get("code") == "123456"
        clock.advance(2)
        assert await cache.get("code") is MISSING


async def test_an_expired_entry_is_not_listed_and_deletes_to_false() -> None:
    """Expiree, l'entree n'est plus la pour personne -- pas meme pour `delete`."""
    clock = FakeClock()
    cache = build_in_memory_cache(get_settings(), clock=clock)
    with use_group(uuid4()):
        await cache.set("ephemere", 1, ttl=10)
        clock.advance(11)
        assert cache.physical_keys() == []
        assert await cache.delete("ephemere") is False


# --- InMemoryFileStorage : la panne LEVE, elle ne degrade pas ---------------


async def test_an_unavailable_storage_raises_on_every_operation() -> None:
    """L'inverse exact du cache, et c'est la dissymetrie des ports qu'on eprouve."""
    storage = InMemoryFileStorage(unavailable=True)
    key = build_storage_key("conformance", uuid4(), "radio.png")
    with pytest.raises(FileStorageUnavailableError):
        await storage.upload(key, _PNG, "image/png")
    with pytest.raises(FileStorageUnavailableError):
        await storage.download(key)
    with pytest.raises(FileStorageUnavailableError):
        await storage.exists(key)
    with pytest.raises(FileStorageUnavailableError):
        await storage.delete(key)
    assert await storage.ping() is False


async def test_an_unavailable_storage_still_signs_a_url() -> None:
    """Signer n'appelle personne : vrai en production, donc vrai ici."""
    storage = InMemoryFileStorage(unavailable=True)
    key = build_storage_key("conformance", uuid4(), "radio.png")
    assert key.rsplit("/", maxsplit=1)[-1] in storage.generate_presigned_url(key)


async def test_an_unavailable_storage_still_refuses_an_invalid_key() -> None:
    """La cle est validee AVANT le stockage : une panne ne relache pas la traversee.

    Le pendant exact de la validation du cache sous indisponibilite, et il faut
    les deux : c'est precisement quand tout va mal qu'une cle `..` ne doit pas
    devenir soudain acceptable.
    """
    storage = InMemoryFileStorage(unavailable=True)
    with pytest.raises(InvalidStorageKeyError):
        await storage.exists("conformance/a/../../autre/dossier.pdf")


async def test_the_content_type_is_kept_on_the_object() -> None:
    """Sans equivalent reel a comparer -- mais une doublure qui l'oublierait mentirait."""
    storage = InMemoryFileStorage()
    key = build_storage_key("conformance", uuid4(), "compte-rendu.pdf")
    await storage.upload(key, b"%PDF-1.7", "application/pdf")
    assert storage.stored_content_type(key) == "application/pdf"
    assert storage.keys() == [key]


# --- FakeBreachChecker : la panne ACCEPTE, et le dit ------------------------


async def test_a_known_breached_password_is_reported() -> None:
    checker = FakeBreachChecker({"motdepasse-fuite"})
    assert await checker.is_breached("motdepasse-fuite") is True
    assert await checker.is_breached("un-mot-de-passe-inconnu") is False
    assert checker.calls == 2


async def test_an_unavailable_checker_accepts_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """LA regle du port, et celle qu'on oublie de verifier.

    Refuser une inscription parce qu'un service tiers ne repond pas coute plus
    cher que le risque couvert -- mais une degradation SILENCIEUSE serait une
    regle de securite qui cesse de s'appliquer sans que personne l'apprenne.
    """
    checker = FakeBreachChecker({"motdepasse-fuite"}, unavailable=True)
    with caplog.at_level(logging.WARNING):
        assert await checker.is_breached("motdepasse-fuite") is False
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert checker.calls == 1


# --- FakeEmailTransport : la panne LEVE, et ne retient rien -----------------


async def test_the_transport_keeps_what_it_was_given() -> None:
    transport = FakeEmailTransport()
    await transport.send(
        recipient="jean@exemple.fr", recipient_name="Jean", subject="Objet", body="Corps"
    )
    assert transport.last.recipient == "jean@exemple.fr"
    assert transport.last.body == "Corps"


async def test_a_failing_transport_raises_and_keeps_nothing() -> None:
    """Le port promet qu'un envoi en echec n'est PAS parti : rien ne doit rester."""
    transport = FakeEmailTransport(fails=True)
    with pytest.raises(EmailDeliveryError):
        await transport.send(
            recipient="jean@exemple.fr", recipient_name="Jean", subject="Objet", body="Corps"
        )
    assert transport.sent == []


async def test_reading_the_last_message_of_an_idle_transport_is_a_test_error() -> None:
    with pytest.raises(AssertionError, match="Aucun courriel"):
        _ = FakeEmailTransport().last
