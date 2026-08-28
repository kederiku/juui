"""Fixtures minimales des tests d'isolation de tenance et garde-fous de contexte.

Deux sujets cohabitent ici, et c'est assume tant que BACK-12 n'a pas hisse le
harnais complet : les fixtures de base de donnees des tests d'isolation
(BACK-06b) et les trois garde-fous `autouse` qui refusent qu'un test laisse un
etat de PROCESSUS derriere lui (BACK-06b pour la tenance, BACK-11 pour le
contexte de requete et la journalisation).

HARNAIS TIRE EN AVANT SUR BACK-12
Le harnais complet -- fixtures generales, fabrique de jetons, client HTTP,
migrations appliquees a la base de test -- appartient a BACK-12. Ce conftest ne
porte que le strict necessaire aux tests d'isolation : un moteur NullPool vers
la base de test, les deux tables stubs, une session par test annulee en sortie.
Chaque emprunt sur BACK-12 est consigne au registre des ecarts.

LA BASE DE TEST, SANS TOUCHER `DatabaseSettings`
L'URL derive de la configuration reelle en remplacant le nom de la base par
`POSTGRES_TEST_DB` (defaut `app_test`, creee par INFRA-01 au premier demarrage
du cluster docker). Le champ dedie de `DatabaseSettings` et la decommentation
de `.env.example` restent a BACK-12 -- meme geste que `alembic/env.py`, qui
construit son moteur sans passer par `build_engine`.

POURQUOI NullPool
Le moteur nait sur la boucle d'evenements de la session pytest et sert des
tests qui tournent chacun sur la leur : un pool ordinaire lierait sa file a la
premiere boucle venue. NullPool ouvre une connexion par emprunt et la ferme a
la restitution -- la raison meme pour laquelle `engine.py` promet ce parametre
aux fixtures de BACK-12.

ISOLATION ENTRE TESTS PAR ROLLBACK
Les tests ne committent jamais : semis et ecritures restent dans la
transaction de LEUR session, que le teardown annule. Ni savepoints ni
truncate -- cette machinerie appartient a BACK-12.
"""

import functools
import inspect
import logging
import os
from collections.abc import AsyncIterator, Iterator
from contextvars import ContextVar
from typing import Final, cast
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import URL, make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import DatabaseSettings
from app.core.correlation import current_account_id, current_clinic_id, current_request_id
from app.shared.infrastructure.db.base import Base
from app.shared.infrastructure.db.session import build_sessionmaker
from app.shared.infrastructure.tenancy import current_group_id
from tests.shared.tenancy_stubs import PlainNoteModel, TenantNoteModel

# Les deux seules tables que ces tests creent et detruisent : jamais un
# create_all/drop_all sans cible, qui toucherait aux tables sous migrations.
_STUB_TABLES = [TenantNoteModel.__table__, PlainNoteModel.__table__]


# Fixtures qui ouvrent un SERVICE REEL, et qui suffisent donc a classer un test.
#
# La cloture de fixtures que pytest calcule a la collecte est TRANSITIVE :
# `session`, `connection`, `bound_sessionmaker` et `database` tirent toutes
# `engine`, si bien qu'un test qui demande l'une d'elles est vu ici sans avoir
# rien a declarer. C'est ce qui rend le classement gratuit a maintenir -- un
# test qui cesse d'avoir besoin d'une base est reclasse tout seul.
#
# POURQUOI PAS LE CHEMIN. Deduire le niveau de `.../infrastructure/` classerait
# faux des le premier jour : `test_channel_adapters.py` et les tests des
# doublures en memoire sont de l'infrastructure qui ne demande aucun service, et
# `test_species_vocabulary.py` compare deux vocabulaires sans toucher a rien.
# Ce que le test RECLAME est la seule chose qui ne puisse pas mentir.
#
# Redis et MinIO n'y figurent pas, et c'est structurel : dans les suites de
# conformite, la moitie reelle et la doublure demandent une fixture du MEME NOM
# (`cache`, `storage`, `store`). Un nom ne peut pas les departager -- ces
# quatre endroits portent donc `pytest.mark.integration` a la main, SUR LA
# CLASSE reelle et jamais sur le module, sans quoi la moitie en memoire
# cesserait d'etre jouee par `-m "not integration"`.
_SERVICE_FIXTURES: Final = frozenset({"engine", "mailpit"})

# Les marqueurs de niveau deja poses a la main, que le hook ne doit pas doubler.
_LEVEL_MARKERS: Final = frozenset({"unit", "integration"})


# `tryfirst` : la deselection par `-m` se fait elle aussi dans ce hook, cote
# greffon integre. Les conftests passent avant les greffons, mais on ne se repose
# pas sur un ordre implicite quand `make test-unit` en depend.
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Pose sur chaque test le niveau que sa cloture de fixtures revele.

    Ni `pytestmark` recopie dans cinquante fichiers -- cinquante lignes a tenir
    vraies, dont l'oubli est SILENCIEUX puisque le test tourne quand meme, il
    devient seulement invisible aux filtres --, ni deduction du chemin, qui
    classerait faux (voir `_SERVICE_FIXTURES`). Ce qu'un test demande est la
    seule source de verite qui se maintienne toute seule.

    Un test qui porte deja `unit` ou `integration` n'est pas retouche : la
    surcharge a la main reste possible, et elle est meme obligatoire aux quatre
    endroits ou deux implementations partagent un nom de fixture.

    Args:
        items: les tests collectes, dans l'ordre de la selection courante.
    """
    for item in items:
        if _LEVEL_MARKERS & {mark.name for mark in item.iter_markers()}:
            continue
        requested = frozenset(getattr(item, "fixturenames", ()))
        level = "integration" if requested & _SERVICE_FIXTURES else "unit"
        item.add_marker(getattr(pytest.mark, level))


def _test_database_url() -> URL:
    """Compose l'URL de la base de test a partir de la configuration reelle."""
    settings = DatabaseSettings()
    test_db = os.environ.get("POSTGRES_TEST_DB", "app_test")
    if test_db == settings.db:
        message = (
            f"La base de test « {test_db} » est la base applicative : les tests "
            "creent et detruisent des tables, ils ne tournent jamais contre elle. "
            "Renseigner POSTGRES_TEST_DB avec une base dediee."
        )
        pytest.exit(message)
    return make_url(settings.sqlalchemy_url).set(database=test_db)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    """Moteur vers la base de test, tables stubs creees puis detruites."""
    test_engine = create_async_engine(
        _test_database_url(),
        poolclass=NullPool,
        connect_args={"timeout": 10, "server_settings": {"application_name": "juui-tests"}},
    )
    try:
        async with test_engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all, tables=_STUB_TABLES)
    except (OSError, SQLAlchemyError) as error:
        await test_engine.dispose()
        message = (
            f"Connexion a la base de test impossible : {error}\n"
            "PostgreSQL docker doit tourner (`make dev` a la racine) et la base "
            "`app_test` exister -- elle nait au premier demarrage du volume "
            "postgres (INFRA-01) ; un volume anterieur se recree par "
            "`docker compose down -v` puis `make dev`."
        )
        pytest.exit(message)
    yield test_engine
    async with test_engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all, tables=_STUB_TABLES)
    await test_engine.dispose()


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Session neuve par test, annulee puis fermee en sortie."""
    test_session = build_sessionmaker(engine)()
    try:
        yield test_session
    finally:
        await test_session.rollback()
        await test_session.close()


@pytest.fixture
def group_a() -> UUID:
    """Premier groupe de la paire concurrente."""
    return uuid4()


@pytest.fixture
def group_b() -> UUID:
    """Second groupe de la paire concurrente."""
    return uuid4()


@pytest.fixture(autouse=True)
def _ensure_clean_tenant_context() -> Iterator[None]:
    """Refuse un contexte de groupe qui fuirait d'un test vers le suivant.

    NE COUVRE QUE LES TESTS SYNCHRONES, et ce n'est pas un defaut de cette
    fixture : un test async tourne dans une `asyncio.Task`, qui recoit une COPIE
    du contexte. Ce qu'il y pose meurt avec elle et n'atteint jamais le test
    suivant -- mesure -- mais reste invisible d'ici. Le pendant asynchrone est le
    hook `pytest_pyfunc_call` plus bas, qui verifie DANS la tache.
    """
    assert current_group_id.get() is None, "Un contexte de tenance precede le test."
    yield
    assert current_group_id.get() is None, "Le test a laisse fuir son contexte de tenance."


# Contextvars de PORTEE REQUETE (BACK-11). Une table plutot que six assertions :
# le message nomme la coupable. Elles sont desormais posees pour de bon par la
# dependance d'authentification de BACK-10c -- ce qui n'a rien change ici, les
# trois y figurant deja : c'est le hook asynchrone plus bas qui les surveille
# dans la tache ou une requete les pose.
#
# `current_group_id` n'y figure pas : elle a sa fixture, celle de BACK-06b
# ci-dessus, dont le message parle de tenance et non de requete.
_REQUEST_CONTEXT: Final[dict[str, ContextVar[str | None] | ContextVar[UUID | None]]] = {
    "current_request_id": current_request_id,
    "current_account_id": current_account_id,
    "current_clinic_id": current_clinic_id,
}


@pytest.fixture(autouse=True)
def _ensure_clean_request_context() -> Iterator[None]:
    """Refuse un contexte de requete qui fuirait d'un test vers le suivant.

    MEME PORTEE QUE LA GARDE DE TENANCE : les tests synchrones. Sa docstring
    promettait le cas ASGI -- un intergiciel qui oublie son `reset(token)` --, et
    elle avait raison sur le mecanisme : sous `httpx.ASGITransport` l'application
    tourne bien dans le contexte de l'APPELANT, donc la fuite atterrit dans celui
    du test. Elle se trompait sur l'endroit ou la voir : ce contexte est celui de
    la TACHE du test, que cette fixture-ci ne partage pas. C'est le hook
    `pytest_pyfunc_call` plus bas qui l'attrape.
    """
    for name, variable in _REQUEST_CONTEXT.items():
        assert variable.get() is None, f"Un contexte de requete precede le test : {name}."
    yield
    for name, variable in _REQUEST_CONTEXT.items():
        assert variable.get() is None, f"Le test a laisse fuir son contexte de requete : {name}."


# Toutes les contextvars de PORTEE REQUETE OU TENANCE, avec le mot qui les
# nomme. Le hook asynchrone les verifie d'un seul geste, la ou les deux fixtures
# ci-dessus gardent chacune la sienne : dans une tache, la distinction n'apporte
# rien -- ce qui compte est de dire LAQUELLE a fui.
_TASK_SCOPED_CONTEXT: Final[
    tuple[tuple[str, ContextVar[str | None] | ContextVar[UUID | None] | ContextVar[object]], ...]
] = (
    ("current_group_id", cast("ContextVar[object]", current_group_id)),
    *((name, variable) for name, variable in _REQUEST_CONTEXT.items()),
)


# Marque posee sur l'enveloppe, pour ne jamais l'appliquer deux fois -- un
# greffon de reprise (pytest-rerunfailures) rejoue la phase de preparation.
_GUARDED = "_juui_context_guarded"


@pytest.hookimpl(trylast=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    """Enveloppe un test asynchrone pour verifier le contexte DANS sa tache.

    POURQUOI LES DEUX FIXTURES CI-DESSUS NE SUFFISENT PAS
    `asyncio_mode = "auto"` fait tourner chaque test async dans une
    `asyncio.Task`, et une tache recoit une COPIE du contexte. Un `set()` fait a
    l'interieur n'atteint jamais le contexte ou tournent les fixtures : leurs
    assertions passent toujours, sur la quasi-totalite de la suite.

    CE QUE CELA CACHAIT, ET CE QUE CELA NE CACHAIT PAS -- les deux sont mesures.
    Une fuite d'un test async ne CONTAMINE PAS le test suivant : la copie meurt
    avec la tache, et c'est ce qui a rendu le trou indolore assez longtemps pour
    qu'il traverse deux tickets. Mais une fuite DANS un test reste parfaitement
    reelle : sous `httpx.ASGITransport`, un intergiciel qui oublie son
    `reset(token)` la depose dans le contexte de la tache, ou tout ce qui suit
    dans le test la lit -- une seconde requete du meme test verrait le groupe de
    la premiere. C'est le cas que la docstring de BACK-11 revendiquait, et que
    rien n'attrapait.

    POURQUOI ICI, ET PAS DANS `pytest_pyfunc_call` -- verifie plutot que suppose.
    A `pytest_pyfunc_call`, `item.obj` N'EST DEJA PLUS une coroutine :
    pytest-asyncio l'a remplacee par un appelable synchrone qui fait tourner la
    boucle, et une enveloppe posee la s'executerait donc HORS de la tache, sans
    rien voir de plus que les fixtures. A `pytest_runtest_setup`, elle en est
    encore une -- c'est le dernier point de la chaine ou elle l'est.

    PAS DE CONTROLE A L'ENTREE, a dessein : le contexte de la tache est copie de
    celui des fixtures, que les deux gardes ci-dessus viennent de verifier.

    Args:
        item: le test que pytest s'apprete a preparer. Ceux qui ne portent pas
            de fonction -- un `DoctestItem`, par exemple -- sont ignores.
    """
    original = getattr(item, "obj", None)
    if not inspect.iscoroutinefunction(original) or getattr(original, _GUARDED, False):
        return

    @functools.wraps(original)
    async def guarded(*args: object, **kwargs: object) -> object:
        """Appelle le test, puis verifie le contexte de sa propre tache."""
        try:
            return await original(*args, **kwargs)
        finally:
            _assert_task_context_is_clean()

    setattr(guarded, _GUARDED, True)
    item.obj = guarded  # type: ignore[attr-defined]


def _assert_task_context_is_clean() -> None:
    """Refuse une contextvar laissee posee dans la tache du test.

    Raises:
        AssertionError: si une contextvar de requete ou de tenance est posee.
    """
    for name, variable in _TASK_SCOPED_CONTEXT:
        assert variable.get() is None, (
            f"Le test a laisse fuir une contextvar dans sa tache : {name}. "
            "Une contextvar se pose par un bloc (`use_group`, `use_all_groups`) "
            "ou se remet par `reset(token)` en sortie -- y compris dans un "
            "intergiciel sonde par httpx.ASGITransport, qui tourne dans le "
            "contexte du test et non dans le sien."
        )


@pytest.fixture(autouse=True)
def _ensure_pristine_logging() -> Iterator[None]:
    """Refuse qu'un test laisse la journalisation du processus configuree.

    `logging` est un etat GLOBAL de processus : un test qui appelle
    `configure_logging()` sans le refermer arrache le handler de `caplog` et
    detourne la sortie de TOUS les tests suivants -- une panne qui se manifeste
    a distance, dans un fichier innocent, et seulement selon l'ordre de
    collecte. Le remede est `isolated_logging()`, dans `tests/core/logging_probes.py`.
    """
    root = logging.getLogger()
    before = list(root.handlers)
    yield
    assert root.handlers == before, (
        "Le test a laisse une configuration de journalisation derriere lui : "
        "envelopper l'appel a `configure_logging` dans `isolated_logging()`."
    )


# Hotes que la suite a le droit de joindre : ceux de la pile de developpement.
# Mailpit (BACK-17) y repond, et ses tests se sautent d'eux-memes quand la boite
# est arretee. Tout le reste est un TIERS, et un tiers ne se joint pas depuis une
# suite de tests.
_LOCAL_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "::1", "mailpit"})

# Message de refus du garde-fou reseau. Il nomme le remede, pas seulement la
# faute -- un test qui sort sur le reseau le fait presque toujours en oubliant
# d'injecter un transport. Il ne porte que l'HOTE : le chemin d'un appel a Have I
# Been Pwned contient un prefixe d'empreinte, qui n'a rien a faire dans une sortie
# de test plus que dans un journal.
_NO_NETWORK = (
    "Un test a tente de joindre l'hote tiers {host} par httpx. Passer "
    "`transport=httpx.MockTransport(...)` a l'adaptateur, ou sa doublure en memoire."
)


@pytest.fixture(autouse=True)
def _forbid_outbound_http(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse toute requete HTTPX vers un hote tiers, dans toute la suite (BACK-10b).

    CE QU'IL GARANTIT, EXACTEMENT : aucune requete passant par `httpx` ne joint un
    hote absent de `_LOCAL_HOSTS`. Ni plus, ni moins -- `smtplib`, `socket` et
    `urllib` ne sont pas gardes, et la pile locale reste joignable. Le dire
    precisement importe : un garde-fou dont on croit qu'il ferme tout est un
    garde-fou sur lequel on se repose a tort.

    Le critere du ticket -- « aucun test n'appelle le vrai service de fuites » --
    ne tenait que par une convention : passer un transport de doublure. Une
    convention se tient jusqu'au jour ou quelqu'un appelle la fabrique de
    production depuis un test de configuration, et la suite se met a envoyer des
    prefixes d'empreintes de mots de passe a un tiers, depuis la CI, sans que rien
    ne le signale. Ceci le rend MECANIQUE.

    LE TRANSPORT ASGI N'EST PAS TOUCHE, et c'est tout l'interet de mordre sur le
    transport plutot que sur `AsyncClient` : `httpx.ASGITransport` sert le trafic
    ENTRANT des tests d'API (BACK-09, BACK-11, BACK-24) et n'ouvre aucune socket.
    Seuls les deux transports qui en ouvrent une sont gardes -- l'asynchrone et le
    synchrone.

    LA PILE LOCALE RESTE JOIGNABLE. Interdire `localhost` ferait echouer les tests
    de remise de courriel (BACK-17) au lieu de les faire se sauter, et rendrait ce
    garde-fou insupportable donc contourne. Ce qu'on refuse, ce n'est pas le
    reseau : c'est le TIERS.

    Cout mesure : 0,27 microseconde par test, soit 0,2 ms sur la suite entiere.
    """
    original_async = httpx.AsyncHTTPTransport.handle_async_request
    original_sync = httpx.HTTPTransport.handle_request

    def _refuse(request: httpx.Request) -> None:
        if request.url.host not in _LOCAL_HOSTS:
            raise RuntimeError(_NO_NETWORK.format(host=request.url.host))

    @functools.wraps(original_async)
    async def guarded_async(
        self: httpx.AsyncHTTPTransport, request: httpx.Request
    ) -> httpx.Response:
        _refuse(request)
        return await original_async(self, request)

    @functools.wraps(original_sync)
    def guarded_sync(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        _refuse(request)
        return original_sync(self, request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", guarded_async)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", guarded_sync)
