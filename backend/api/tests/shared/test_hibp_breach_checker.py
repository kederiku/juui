"""Tests de l'adaptateur Have I Been Pwned du port `BreachChecker` (BACK-10b).

AUCUN DE CES TESTS NE SORT SUR LE RESEAU. Le pilote est `httpx.MockTransport`,
publie par httpx lui-meme : aucune dependance de developpement n'a ete ajoutee,
et rien n'est remplace par `monkeypatch` -- on passe un transport, ce qui est la
couture prevue par la bibliotheque. Le garde-fou `_forbid_outbound_http` du
conftest racine rend la regle mecanique plutot que conventionnelle, et un test
ci-dessous le prouve.

CE QUE CES TESTS VERROUILLENT EN PLUS DU TICKET

- `test_a_padding_entry_with_a_zero_count_is_not_a_breach` : avec `Add-Padding`,
  le service ajoute des suffixes FACTICES au compte nul. Un analyseur qui
  demanderait « mon suffixe est-il dans le corps ? » rendrait un faux positif, et
  refuserait au hasard des mots de passe parfaitement sains.
- `test_a_slow_server_is_cut_off_within_the_budget` : le delai d'httpx borne
  chaque PHASE et se rearme a chaque fragment recu. Mesure sur ce depot : 30,1 s
  pour un delai annonce a 2 s. C'est l'enveloppe `asyncio.timeout` que ce test
  epingle, et sans elle une inscription -- non authentifiee -- devient un
  amplificateur de deni de service.
- `test_a_broken_content_encoding_degrades_instead_of_raising` : `DecodingError`
  n'est PAS une `httpx.TransportError` (verifie). Un intermediaire qui annonce
  `gzip` sur un corps abime ferait un 500 sur l'inscription, c'est-a-dire
  l'exact contraire de la degradation que le port promet.
- Le test de non-divulgation balaie les enregistrements de journalisation en
  cherchant le mot de passe, l'empreinte ET LE PREFIXE. Les cinq caracteres du
  prefixe croises avec le corpus public reduisent le mot de passe d'un
  utilisateur a un millionieme de ce corpus : un journal est precisement le
  « systeme de quelqu'un d'autre » que la k-anonymity protege.
"""

import asyncio
import hashlib
import logging
import time
from collections.abc import AsyncIterator, Callable

import httpx
import pytest

from app.core import get_settings
from app.core.config import AppSettings
from app.shared.infrastructure.clients.hibp import (
    HIBP_PREFIX_LENGTH,
    HibpBreachChecker,
    build_breach_checker,
)
from tests.support.logs import isolated_logging

pytestmark = pytest.mark.passwords

_MDP = "correcte-batterie-agrafe"
_EMPREINTE = hashlib.sha1(_MDP.encode("utf-8"), usedforsecurity=False).hexdigest().upper()
_PREFIXE, _SUFFIXE = _EMPREINTE[:HIBP_PREFIX_LENGTH], _EMPREINTE[HIBP_PREFIX_LENGTH:]

_BASE = "https://api.pwnedpasswords.com"

# Un autre suffixe, de meme forme, pour peupler les seaux sans declencher le
# verdict. Trente-cinq caracteres hexadecimaux, comme le vrai.
_AUTRE_SUFFIXE = "0" * 34 + "F"


def _seau(*lignes: str) -> str:
    """Assemble un corps de reponse, avec les fins de ligne du vrai service."""
    return "\r\n".join(lignes)


def _checker(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    timeout_seconds: float = 2.0,
) -> HibpBreachChecker:
    """Un verificateur adosse a un transport de doublure."""
    return HibpBreachChecker(
        base_url=_BASE,
        timeout_seconds=timeout_seconds,
        transport=httpx.MockTransport(handler),
    )


def _rendant(response: httpx.Response) -> Callable[[httpx.Request], httpx.Response]:
    """Un gestionnaire qui rend toujours la meme reponse."""
    return lambda _request: response


def _levant(error: Exception) -> Callable[[httpx.Request], httpx.Response]:
    """Un gestionnaire qui leve toujours la meme erreur de transport."""

    def handler(_request: httpx.Request) -> httpx.Response:
        raise error

    return handler


# ---------------------------------------------------------------------------
# Ce qui part sur le fil : la k-anonymity
# ---------------------------------------------------------------------------


async def test_only_the_first_five_characters_of_the_digest_leave_the_process() -> None:
    """LE critere de securite du ticket, verifie sur la requete elle-meme."""
    vue: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        vue["requete"] = request
        return httpx.Response(200, text=_seau(f"{_AUTRE_SUFFIXE}:1"))

    await _checker(handler).is_breached(_MDP)

    requete = vue["requete"]
    dernier_segment = str(requete.url).rsplit("/", 1)[-1]
    assert dernier_segment == _PREFIXE
    assert len(dernier_segment) == HIBP_PREFIX_LENGTH

    # Ni le mot de passe, ni l'empreinte complete, ni le suffixe, nulle part.
    emis = str(requete.url) + "".join(f"{cle}{valeur}" for cle, valeur in requete.headers.items())
    assert _MDP not in emis
    assert _EMPREINTE not in emis
    assert _SUFFIXE not in emis


async def test_the_request_carries_the_padding_and_agent_headers() -> None:
    """Sans rembourrage, la TAILLE de la reponse trahit le seau et vide la k-anonymity."""
    vue: dict[str, httpx.Headers] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        vue["headers"] = request.headers
        return httpx.Response(200, text=_seau(f"{_AUTRE_SUFFIXE}:1"))

    await _checker(handler).is_breached(_MDP)

    assert vue["headers"]["add-padding"] == "true"
    # Le service repond 403 a un client anonyme, et notre propre degradation
    # avalerait ce 403 en silence : le controle serait desactive pour toujours.
    assert vue["headers"]["user-agent"] == "juui-api"


# ---------------------------------------------------------------------------
# Le verdict
# ---------------------------------------------------------------------------


async def test_a_suffix_present_with_a_positive_count_is_a_breach() -> None:
    """Le cas nominal."""
    handler = _rendant(httpx.Response(200, text=_seau(f"{_AUTRE_SUFFIXE}:3", f"{_SUFFIXE}:42")))

    assert await _checker(handler).is_breached(_MDP) is True


async def test_a_suffix_absent_from_the_bucket_is_not_a_breach() -> None:
    """Le seau existe, le suffixe n'y est pas."""
    handler = _rendant(httpx.Response(200, text=_seau(f"{_AUTRE_SUFFIXE}:9")))

    assert await _checker(handler).is_breached(_MDP) is False


async def test_a_padding_entry_with_a_zero_count_is_not_a_breach() -> None:
    """Le piege du rembourrage : present ne suffit pas, il faut un compte non nul."""
    handler = _rendant(httpx.Response(200, text=_seau(f"{_SUFFIXE}:0", f"{_AUTRE_SUFFIXE}:4")))

    assert await _checker(handler).is_breached(_MDP) is False


async def test_a_lowercase_answer_is_recognised_all_the_same() -> None:
    """S'y tromper desactiverait le controle en silence, jamais bruyamment."""
    handler = _rendant(httpx.Response(200, text=_seau(f"{_SUFFIXE.lower()}:7")))

    assert await _checker(handler).is_breached(_MDP) is True


async def test_unreadable_lines_are_ignored_and_the_good_one_still_counts() -> None:
    """Une ligne abimee ne doit ni lever, ni faire perdre le verdict des autres."""
    handler = _rendant(
        httpx.Response(
            200,
            text=_seau("sans-deux-points", f"{_AUTRE_SUFFIXE}:pas-un-nombre", f"{_SUFFIXE}:5"),
        )
    )

    assert await _checker(handler).is_breached(_MDP) is True


# ---------------------------------------------------------------------------
# La degradation : muet vaut accepte, jamais en silence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403),
        httpx.Response(404),
        httpx.Response(429, headers={"Retry-After": "12"}),
        httpx.Response(500),
        httpx.Response(503),
        httpx.Response(301, headers={"Location": "https://ailleurs.example/range/ABCDE"}),
        httpx.Response(200, text=""),
        httpx.Response(200, text="<html><body>maintenance</body></html>"),
    ],
    ids=["403", "404", "429", "500", "503", "redirection", "corps vide", "corps HTML"],
)
async def test_an_unusable_answer_accepts_the_password_and_warns(
    response: httpx.Response,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Toute reponse inexploitable degrade -- et le dit, exactement une fois."""
    with caplog.at_level(logging.WARNING):
        breached = await _checker(_rendant(response)).is_breached(_MDP)

    assert breached is False
    assert len(caplog.records) == 1


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("injoignable"),
        httpx.ConnectTimeout("trop lent a repondre"),
        httpx.ReadTimeout("silence"),
        httpx.RemoteProtocolError("reponse tronquee"),
        httpx.DecodingError("gzip abime"),
        OSError("resolution impossible"),
    ],
    ids=["connexion", "delai de connexion", "delai de lecture", "protocole", "decodage", "OSError"],
)
async def test_a_transport_failure_accepts_the_password_and_warns(
    error: Exception,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`DecodingError` n'est pas une `TransportError` : elle est nommee a part."""
    with caplog.at_level(logging.WARNING):
        breached = await _checker(_levant(error)).is_breached(_MDP)

    assert breached is False
    assert len(caplog.records) == 1


async def test_a_broken_content_encoding_degrades_instead_of_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Le cas reel : un intermediaire annonce gzip sur un corps qui n'en est pas.

    Le corps passe par un VRAI flux et non par `content=` : httpx ne decode que ce
    qu'il lit, et une reponse au corps deja constitue ne leverait jamais -- le test
    passerait alors sans rien prouver.
    """

    class _CorpsAbime(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b"ceci-n-est-pas-du-gzip"

    handler = _rendant(
        httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=_CorpsAbime())
    )

    with caplog.at_level(logging.WARNING):
        breached = await _checker(handler).is_breached(_MDP)

    assert breached is False
    assert "DecodingError" in caplog.text


async def test_a_realistic_padded_bucket_still_yields_a_verdict() -> None:
    """LE test que le plafond d'octets manquait, et qui a trouve le defaut.

    Le rembourrage ajoute ses entrees PAR-DESSUS les vraies : un seau reel monte a
    1500-1800 lignes, soit une soixantaine de kibioctets. Le premier plafond, pose
    a 64 KiB sur une arithmetique fausse, coupait donc des seaux legitimes -- et
    couper vaut ACCEPTER : le controle de fuite s'eteignait par prefixes entiers,
    de facon permanente, sans que rien n'echoue. Le seul test de plafond visait
    4000 lignes, trop loin de la bordure pour le voir.
    """
    seau = _seau(*[f"{numero:035X}:1" for numero in range(1799)], f"{_SUFFIXE}:42")

    assert len(seau) > 64 * 1024
    assert await _checker(_rendant(httpx.Response(200, text=seau))).is_breached(_MDP) is True


async def test_an_oversized_answer_is_cut_off_and_degrades(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`HIBP_API_URL` est reglable : l'hote au bout n'est pas de confiance."""
    enorme = _seau(*[f"{_AUTRE_SUFFIXE}:1"] * 20000)

    assert len(enorme) > 512 * 1024
    with caplog.at_level(logging.WARNING):
        breached = await _checker(_rendant(httpx.Response(200, text=enorme))).is_breached(_MDP)

    assert breached is False
    assert "octets" in caplog.text


async def test_the_request_refuses_a_compressed_answer() -> None:
    """Sans cela, le plafond d'octets ne borne rien du tout.

    `aiter_bytes()` rend des octets DEJA DECOMPRESSES : un corps de 199 KiB qui se
    detend en 200 MiB est entierement materialise avant que la moindre comparaison
    de budget s'execute. Mesure : 437 MiB de pic memoire pour une requete.
    """
    vue: dict[str, httpx.Headers] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        vue["headers"] = request.headers
        return httpx.Response(200, text=_seau(f"{_AUTRE_SUFFIXE}:1"))

    await _checker(handler).is_breached(_MDP)

    assert vue["headers"]["accept-encoding"] == "identity"


@pytest.mark.parametrize(
    "corps",
    ["<html>Maintenance. Retry:30</html>", "upstream:8080 unreachable", "cle: 12"],
    ids=["page de maintenance", "erreur de mandataire", "cle deux-points valeur"],
)
async def test_an_error_page_that_happens_to_contain_a_colon_still_warns(
    corps: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Le garde de silence exige la FORME du suffixe, pas seulement un deux-points.

    Sans cela, « Retry:30 » comptait pour une ligne exploitable et la degradation
    devenait muette -- exactement ce que le port interdit nommement. Mesure sur la
    premiere version : deux corps HTML sur trois passaient sans un mot.
    """
    with caplog.at_level(logging.WARNING):
        breached = await _checker(_rendant(httpx.Response(200, text=corps))).is_breached(_MDP)

    assert breached is False
    assert len(caplog.records) == 1


async def test_the_logged_host_never_carries_credentials(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un miroir interne derriere une authentification basique ne fuite pas son mot de passe.

    C'est le cas d'usage meme pour lequel `HIBP_API_URL` est reglable, et
    `urlsplit(...).netloc` conserve les identifiants -- `hostname` non.
    """
    checker = HibpBreachChecker(
        base_url="https://compte:motdepasse@hibp.interne.example",
        timeout_seconds=2.0,
        transport=httpx.MockTransport(_rendant(httpx.Response(503))),
    )

    with caplog.at_level(logging.WARNING):
        await checker.is_breached(_MDP)

    assert "motdepasse" not in caplog.text
    assert "hibp.interne.example" in caplog.text


async def test_a_slow_server_is_cut_off_within_the_budget(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Le delai d'httpx se rearme a chaque fragment ; l'enveloppe borne le TOTAL."""

    class _FluxSansFin(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            while True:  # pragma: no cover - interrompu par l'enveloppe
                await asyncio.sleep(0.1)
                yield f"{_AUTRE_SUFFIXE}:1\r\n".encode("ascii")

    handler = _rendant(httpx.Response(200, stream=_FluxSansFin()))
    depart = time.perf_counter()

    with caplog.at_level(logging.WARNING):
        breached = await _checker(handler, timeout_seconds=0.3).is_breached(_MDP)

    assert breached is False
    assert time.perf_counter() - depart < 1.0
    assert "TimeoutError" in caplog.text


@pytest.mark.parametrize(
    "handler_factory",
    [
        lambda: _rendant(httpx.Response(503)),
        lambda: _levant(httpx.ConnectError("injoignable")),
        lambda: _rendant(httpx.Response(200, text="<html>maintenance</html>")),
    ],
    ids=["statut", "transport", "corps illisible"],
)
async def test_no_log_record_ever_carries_the_password_the_digest_or_the_prefix(
    handler_factory: Callable[[], Callable[[httpx.Request], httpx.Response]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cinq caracteres de SHA-1 dans un journal reduisent le corpus d'un facteur un million.

    Le balayage porte sur les enregistrements de NOTRE adaptateur. Ceux d'httpx
    sont exclus ici et traites par le test suivant, qui est celui qui compte : la
    fuite ne venait pas de notre code mais de la bibliotheque, et c'est le genre de
    defaut qu'on ne trouve qu'en regardant la sortie reelle.
    """
    with caplog.at_level(logging.DEBUG):
        await _checker(handler_factory()).is_breached(_MDP)

    notres = [record for record in caplog.records if record.name.startswith("app.")]
    assert notres, "L'adaptateur n'a rien journalise : le test ne prouve rien."
    trace = "".join(record.getMessage() + str(record.__dict__) for record in notres)
    assert _MDP not in trace
    assert _EMPREINTE not in trace
    assert _SUFFIXE not in trace
    assert _PREFIXE not in trace


async def test_the_real_logging_configuration_never_lets_the_prefix_through() -> None:
    """La fuite trouvee EN EXECUTANT cette suite : httpx journalise l'URL complete.

    « HTTP Request: GET https://api.pwnedpasswords.com/range/2EA84 » a INFO, soit
    le prefixe d'empreinte depose dans les journaux du service par une
    bibliotheque, quoi que fasse l'adaptateur.

    Ce test applique la VRAIE configuration de journalisation, au niveau le plus
    bavard qu'un exploitant puisse demander, et lit le flux de sortie reel. Un
    test qui se contenterait de comparer une constante a `WARNING` ne prouverait
    que la presence d'une ligne dans un dictionnaire -- pas que le prefixe reste
    dehors.
    """
    settings = AppSettings(environment="development", log_level="DEBUG")
    handler = _rendant(httpx.Response(200, text=_seau(f"{_AUTRE_SUFFIXE}:1")))

    with isolated_logging(settings) as sortie:
        await _checker(handler).is_breached(_MDP)
        journal = sortie.getvalue()

    assert _PREFIXE not in journal
    assert _EMPREINTE not in journal
    assert _MDP not in journal


async def test_the_prefix_would_leak_without_that_floor(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Le contre-exemple, qui donne sa valeur au test precedent.

    Il DEMONTRE la fuite au lieu de l'affirmer : le logger d'httpx remis a INFO
    depose bien le prefixe. Sans ce test, personne ne saurait dans deux ans si la
    ligne de `core/logging.py` sert encore a quelque chose -- et le premier
    relecteur qui la trouverait « bavarde » la retirerait.
    """
    handler = _rendant(httpx.Response(200, text=_seau(f"{_AUTRE_SUFFIXE}:1")))

    with caplog.at_level(logging.INFO, logger="httpx"):
        await _checker(handler).is_breached(_MDP)

    assert _PREFIXE in caplog.text


# ---------------------------------------------------------------------------
# Les deux garde-fous qui rendent le critere 5 du ticket mecanique
# ---------------------------------------------------------------------------


def test_a_checker_cannot_be_built_without_naming_its_transport() -> None:
    """`transport` n'a pas de defaut : l'oublier est une erreur, pas un appel reseau."""
    with pytest.raises(TypeError):
        HibpBreachChecker(base_url=_BASE, timeout_seconds=2.0)  # type: ignore[call-arg]


async def test_the_production_factory_is_stopped_by_the_suite_wide_network_guard() -> None:
    """La ceinture par-dessus les bretelles : meme la vraie fabrique ne sort pas."""
    with pytest.raises(RuntimeError, match="hote tiers"):
        await build_breach_checker(get_settings()).is_breached(_MDP)
