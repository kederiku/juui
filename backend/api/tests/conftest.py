"""Harnais de la suite de tests : niveaux, base d'integration, garde-fous.

Trois sujets vivent ici, et ce sont les trois que BACK-12 avait a livrer.

LE NIVEAU D'UN TEST SE DEDUIT DE CE QU'IL RECLAME
`pytest_collection_modifyitems` lit la cloture de fixtures -- transitive -- et
pose `unit` ou `integration`. Personne n'a de marqueur a tenir a jour, et un
test qui cesse d'avoir besoin d'une base se reclasse tout seul.

LA BASE D'INTEGRATION RECOIT LES MIGRATIONS, ET CHAQUE TEST ANNULE SA
TRANSACTION
`engine` applique `alembic upgrade head` a la base de test, une fois par
session, sur sa propre connexion et sous le verrou consultatif d'`env.py`. Les
cinq conftests de module qui creaient leurs tables a la main ont disparu avec
elle. `connection` ouvre ensuite une transaction EXTERNE par test, et
`bound_sessionmaker` y inscrit les sessions en `create_savepoint` : un
`commit()` applicatif relache un savepoint, le teardown emporte tout. Plus
aucune purge manuelle.

UN SERVICE ABSENT NE REND PLUS LA SUITE VERTE, ET NE L'ARRETE PLUS NON PLUS
`pytest.exit()` a disparu : il empechait les tests qui ne demandent RIEN de
tourner sans Docker. `require_service` saute et RECENSE ; le recensement
s'affiche en fin d'execution, et `--require-services` le transforme en echec.
C'est ce qui fait d'une CI verte une preuve, la ou une execution locale verte
reste un rapport.

Les quatre garde-fous `autouse` en bas de fichier, eux, sont d'un autre ordre :
ils refusent qu'un test laisse un etat de PROCESSUS derriere lui (BACK-06b pour
la tenance, BACK-11 pour le contexte de requete et la journalisation, BACK-10b
pour le reseau).
"""

import functools
import inspect
import logging
from collections.abc import AsyncIterator, Iterator
from contextvars import ContextVar
from dataclasses import replace
from pathlib import Path
from typing import Final, NoReturn, cast
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from alembic.util import CommandError
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.pool import NullPool

from app.core import get_settings
from app.core.correlation import current_account_id, current_clinic_id, current_request_id
from app.main import build_authentication, create_app
from app.shared.infrastructure.api.dependencies.auth import AUTH_STATE_KEY, Authentication
from app.shared.infrastructure.db.base import Base
from app.shared.infrastructure.db.engine import build_engine
from app.shared.infrastructure.db.session import STATE_KEY, Database, build_sessionmaker
from app.shared.infrastructure.tenancy import current_group_id
from tests.support.api import asgi_client
from tests.support.auth import an_authentication, build_probe_app
from tests.support.tenancy_stubs import PlainNoteModel, TenantNoteModel
from tests.support.tokens import TokenFactory

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


# ---------------------------------------------------------------------------
# Services absents : sauter en le disant, ou echouer si on l'a demande
# ---------------------------------------------------------------------------

# Services de la pile locale qui n'ont pas repondu, et leur remede. Un ENSEMBLE
# et non un compteur : ce qui interesse le lecteur du rapport n'est pas combien
# de tests ont saute -- le resume `-rs` le dit deja -- mais LESQUELS des quatre
# services manquaient, donc quelle part de la suite n'a rien prouve.
_MISSING_SERVICES: Final = pytest.StashKey[dict[str, str]]()


def pytest_addoption(parser: pytest.Parser) -> None:
    """Declare les deux options du harnais, et pas une de plus."""
    parser.addoption(
        "--require-services",
        action="store_true",
        default=False,
        help=(
            "Echoue au lieu de sauter quand un service de la pile locale ne "
            "repond pas. A poser en CI : une execution verte devient une preuve."
        ),
    )
    parser.addoption(
        "--db-reset",
        action="store_true",
        default=False,
        help=(
            "Defait toutes les migrations (`alembic downgrade base`) avant de les "
            "rejouer sur la base de test. A employer apres un changement de branche "
            "qui a fait deriver son schema."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    """Ouvre le recensement des services absents."""
    config.stash[_MISSING_SERVICES] = {}


def require_service(config: pytest.Config, *, name: str, remedy: str) -> NoReturn:
    """Saute le test faute de service -- ou echoue, si on a demande le contraire.

    UN SEUL ENDROIT POUR LES QUATRE SERVICES. Avant BACK-12 ils avaient trois
    comportements pour une meme situation : Redis, MinIO et Mailpit sautaient
    chacun avec son `pytest.skip` muet, et PostgreSQL tuait la SESSION ENTIERE
    par `pytest.exit()` -- y compris les moities en memoire, qui n'ont besoin de
    rien. C'est cet arret-la que le ticket avait a reprendre.

    Le saut est RECENSE, et c'est la piece qui manquait : un `skip` se lit dans
    `-rs`, mais il s'y noie. Le bloc de fin de session dit lesquels des quatre
    services ont manque, juste avant le vert final.

    Args:
        config: la configuration de la session, qui porte le recensement.
        name: le service qui n'a pas repondu.
        remedy: le geste qui le rend joignable, en toutes lettres.

    Raises:
        Failed: sous `--require-services`, ou l'absence est une panne.
        Skipped: sinon.
    """
    message = f"{name} ne repond pas. {remedy}"
    if config.getoption("--require-services"):
        pytest.fail(message, pytrace=False)
    config.stash[_MISSING_SERVICES][name] = remedy
    pytest.skip(message)


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, exitstatus: int, config: pytest.Config
) -> None:
    """Nomme les services absents, donc la part de la suite qui n'a rien prouve.

    Sans ce bloc, une execution verte sur un poste sans Redis ressemble trait
    pour trait a une execution verte sur un poste complet. La page Tests appelait
    cela « le piege de cette suite » ; c'est ici qu'il se referme.
    """
    missing = config.stash.get(_MISSING_SERVICES, {})
    if not missing:
        return
    skipped = len(terminalreporter.stats.get("skipped", []))
    terminalreporter.write_sep("=", "services absents", yellow=True, bold=True)
    for name, remedy in sorted(missing.items()):
        terminalreporter.write_line(f"  {name} -- {remedy}")
    terminalreporter.write_line(
        f"{skipped} test(s) sautes : cette execution NE PROUVE PAS ce qu'ils couvrent. "
        "`--require-services` fait echouer la suite au lieu de sauter."
    )


# ---------------------------------------------------------------------------
# La base d'integration : migrations une fois par session, transaction par test
# ---------------------------------------------------------------------------

# Racine du service, d'ou `alembic.ini` se lit. Derivee de `__file__` et jamais
# du repertoire courant : `uv run pytest` se lance aussi bien depuis la racine
# du depot que depuis `backend/api`.
_ALEMBIC_INI: Final = Path(__file__).resolve().parents[1] / "alembic.ini"

# MEME CLE QUE `alembic/env.py`, et c'est tout l'interet : elle serialise cette
# suite avec un `make migrate` lance en parallele sur le meme cluster, ou avec
# une seconde execution de la suite dans un autre terminal.
_MIGRATION_LOCK_KEY: Final = 0x6A75_7569


def _alembic_config(sync_connection: Connection) -> Config:
    """Compose la configuration Alembic branchee sur une connexion deja ouverte.

    Les deux attributs sont le contrat passe avec `alembic/env.py` :

    - `connection` : la connexion a employer. `env.py` la prefere a celle qu'il
      construirait, et n'appelle donc pas `asyncio.run` -- impossible depuis la
      boucle d'une fixture pytest, et c'est un mur et non une preference.
    - `configure_logger` : `fileConfig` vaut `disable_existing_loggers=True` par
      defaut. En processus, il eteindrait tous les loggers `app.*` deja crees et
      poserait un handler stderr sur la racine.
    """
    config = Config(str(_ALEMBIC_INI))
    config.attributes["connection"] = sync_connection
    config.attributes["configure_logger"] = False
    return config


def _upgrade_to_head(sync_connection: Connection) -> None:
    """Deroule les migrations jusqu'a la tete, sur la connexion du harnais."""
    command.upgrade(_alembic_config(sync_connection), "head")


def _downgrade_to_base(sync_connection: Connection) -> None:
    """Defait toutes les migrations. JAMAIS `DROP SCHEMA public CASCADE`.

    Le schema `public` de la base de test porte `pg_trgm` et `unaccent`, posees
    une seule fois par `docker/postgres/init/02-enable-extensions.sh` a la
    creation du volume -- un script d'initialisation ne rejoue jamais. Les
    detruire rendrait la base irreparable sans `docker compose down -v`.
    """
    command.downgrade(_alembic_config(sync_connection), "base")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine(request: pytest.FixtureRequest) -> AsyncIterator[AsyncEngine]:
    """Moteur vers la base de test, schema a jour, tables stubs creees.

    PORTEE SESSION, BOUCLE SESSION ET `NullPool` VONT ENSEMBLE. Le moteur nait
    dans la boucle de la session et sert des tests qui tournent chacun sur la
    leur ; `NullPool` ouvre une socket par emprunt et la ferme a la restitution,
    si bien qu'aucune file interne n'est liee a une boucle. C'est le parametre
    qu'`engine.py` promettait nommement aux fixtures de ce ticket.

    LE SCHEMA VIENT DES MIGRATIONS, PLUS DE `create_all`. Les cinq conftests de
    module qui creaient leurs propres tables ont disparu : ce qui est teste est
    desormais ce que `alembic upgrade head` pose en production. `upgrade head`
    est idempotent -- la base survit d'une execution a l'autre et le plan est
    alors vide --, et ce que `create_all` achetait au passage, a savoir la
    pression pour qu'un index vive dans le MODELE et pas seulement dans sa
    migration, est rachete par `test_schema_matches_models`.
    """
    settings = get_settings()
    test_engine = build_engine(
        settings,
        url=settings.db.sqlalchemy_test_url,
        poolclass=NullPool,
        application_name="juui-tests",
    )
    try:
        async with test_engine.connect() as connection:
            # Verrou consultatif de SESSION, relache a la deconnexion. Il ne
            # couvre QUE les migrations : le tenir toute la suite empecherait
            # deux executions de cohabiter, ce qui n'a aucune raison d'etre une
            # fois le schema pose.
            await connection.execute(
                text("SELECT pg_advisory_lock(CAST(:lock_key AS bigint))"),
                {"lock_key": _MIGRATION_LOCK_KEY},
            )
            # COMMIT OBLIGATOIRE, exactement pour la raison qu'`env.py`
            # documente : l'execute ci-dessus a ouvert une transaction par
            # autobegin, et Alembic qui en trouve une deja ouverte cesse de gerer
            # la sienne -- tout le DDL serait annule a la deconnexion, SANS LA
            # MOINDRE ERREUR. Le verrou, lui, est de niveau session et survit au
            # commit.
            await connection.commit()
            if request.config.getoption("--db-reset"):
                await connection.run_sync(_downgrade_to_base)
            await connection.run_sync(_upgrade_to_head)
            # Les deux tables stubs ne figurent dans AUCUNE migration, a dessein :
            # `env.py` n'importe jamais `tenancy_stubs`, donc `alembic check` ne
            # les voit pas. Elles se creent donc a la main, APRES les migrations
            # et SOUS LE MEME VERROU -- `create_all` est `checkfirst=True`, mais
            # deux sessions concurrentes le verraient toutes deux absent.
            await connection.run_sync(Base.metadata.create_all, tables=_STUB_TABLES)
            await connection.commit()
    except (OSError, SQLAlchemyError, CommandError) as error:
        await test_engine.dispose()
        require_service(
            request.config,
            name="postgres",
            remedy=(
                f"({error}) `make dev` a la racine demarre la pile, et la base de "
                "test nait au premier demarrage du volume postgres (INFRA-01) ; "
                "un volume anterieur se recree par `docker compose down -v` puis "
                "`make dev`."
            ),
        )
    yield test_engine
    # RIEN N'EST DETRUIT EN SORTIE, ET C'EST UNE CORRECTION. Cette fixture
    # detruisait les deux tables stubs au demontage. Le verrou consultatif ne
    # couvre QUE les migrations -- il tombe avec la connexion ci-dessus, a
    # dessein, pour que deux executions puissent cohabiter une fois le schema
    # pose. Mais alors, la premiere session a se terminer arrachait les tables
    # sous les pieds de la seconde : `UndefinedTableError: relation
    # "plain_notes_test" does not exist`, en plein milieu d'une suite verte
    # ailleurs. Constate en jouant quatre suites en parallele.
    #
    # Les tables stubs ont donc EXACTEMENT le meme cycle de vie que les tables
    # migrees : creees si absentes, jamais detruites. C'est la base de test qui
    # les porte, pas la session -- et cela supprime au passage la ligne la plus
    # dangereuse du harnais, un `drop_all` a une virgule de vaporiser le schema
    # migre. La base se remet a neuf par `--db-reset`, ou par
    # `docker compose down -v`.
    await test_engine.dispose()


@pytest_asyncio.fixture
async def connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """Connexion dediee au test, sous une transaction que la sortie annule.

    C'est la piece qui remplace le rollback de session de BACK-06b ET les purges
    manuelles des suites de conformite. Ce que le test valide atterrit dans un
    SAVEPOINT ; le rollback ci-dessous emporte le savepoint et tout le reste --
    y compris apres un test interrompu, ce que la purge « avant » ne faisait que
    reparer apres coup.

    PORTEE FONCTION, ET C'EST STRUCTUREL. Avec
    `asyncio_default_fixture_loop_scope = "function"`, cette fixture tourne dans
    LA BOUCLE DU TEST : la connexion asyncpg y nait, et c'est la seule facon
    qu'elle y soit utilisable. Une connexion de portee session, nee dans la
    boucle du moteur, serait touchee depuis une autre boucle a chaque test --
    le mode d'echec le plus deroutant d'asyncpg. `NullPool` est ce qui rend
    l'arrangement possible.
    """
    async with engine.connect() as opened:
        transaction = await opened.begin()
        try:
            yield opened
        finally:
            # Inconditionnel : les sessions du test ont pu commiter pour de bon,
            # la transaction EXTERNE est restee ouverte au-dessus de leurs
            # savepoints. Le test n'est pas cense la fermer -- s'il l'a fait,
            # `is_active` le dit et on n'insiste pas.
            if transaction.is_active:
                await transaction.rollback()


@pytest.fixture
def bound_sessionmaker(connection: AsyncConnection) -> async_sessionmaker[AsyncSession]:
    """Fabrique de sessions inscrite dans la transaction du test.

    `create_savepoint` fait exactement une chose : chaque session ouvre un
    SAVEPOINT au lieu de piloter la transaction qu'elle trouve deja ouverte. Un
    `commit()` applicatif RELACHE alors son savepoint -- visible de la suite du
    test, invisible de toute autre connexion -- et le rollback de `connection`
    efface l'ensemble.

    LA LIMITE, ecrite ici parce qu'elle se paie ailleurs : les savepoints se
    relachent EN PILE. Deux sessions imbriquees LIFO cohabitent, et c'est le
    chemin nominal -- les resolveurs d'authentification referment leur bloc avant
    que la route n'ouvre le sien. Deux sessions ENTRELACEES, ce que produit un
    `asyncio.gather` de deux requetes, font echouer le relachement. Un test de
    concurrence prend `engine_sessionmaker` et se nettoie lui-meme.
    """
    return build_sessionmaker(connection, join_transaction_mode="create_savepoint")


@pytest_asyncio.fixture
async def session(
    bound_sessionmaker: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Session neuve par test, inscrite dans la transaction du test.

    Le `rollback` de sortie n'est plus ce qui isole -- c'est `connection` -- il
    n'est plus que l'hygiene du savepoint.
    """
    async with bound_sessionmaker() as opened:
        yield opened


@pytest.fixture
def database(engine: AsyncEngine, bound_sessionmaker: async_sessionmaker[AsyncSession]) -> Database:
    """Les ressources de persistance, telles que le `lifespan` les poserait.

    LE MOTEUR ET NON LA CONNEXION dans le premier champ, et ce n'est pas une
    approximation : `/health/ready` sonde `database.engine` et doit ouvrir sa
    PROPRE connexion, comme en production. Seule la fabrique de sessions est liee
    a la transaction du test -- c'est-a-dire tout ce que les unites de travail
    traversent, donc tout ce qu'une route ouvre.
    """
    return Database(engine=engine, sessionmaker=bound_sessionmaker)


@pytest.fixture
def engine_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Fabrique NON liee, pour les rares tests que le patron ne peut pas servir.

    Deux cas, et deux seulement : un test qui doit prouver qu'un commit est
    visible d'une AUTRE connexion, et un test qui lance deux requetes en
    parallele. Les deux commitent pour de bon et PURGENT EUX-MEMES.
    """
    return build_sessionmaker(engine)


# ---------------------------------------------------------------------------
# Le client HTTP et la fabrique de jetons
# ---------------------------------------------------------------------------


@pytest.fixture
def tokens() -> TokenFactory:
    """La fabrique de jetons du test : celui qui SIGNE est celui qui VERIFIE.

    Sa table d'appartenances est VIVANTE : un test peut declarer un role apres
    que le service est deja pose sur `app.state`, ce qu'un service construit sur
    une table figee ne permettait pas. Son horloge d'emission est figee, mais pas
    reculee -- `now` ne pilote que l'emission, PyJWT verifie sur l'horloge
    murale, et un jeton deja expire se demande par `expired=True`.
    """
    return TokenFactory()


@pytest.fixture
def authentication_double(tokens: TokenFactory) -> Authentication:
    """Montage d'authentification servi par des doublures : AUCUNE base.

    C'est ce qui rend `probe_client` unitaire : les resolveurs sont des closures
    sur des dictionnaires, et le seul objet reel est le service de jetons -- qui
    est aussi celui de `tokens`, sans quoi le verificateur refuserait ce que le
    signataire vient d'emettre.
    """
    return an_authentication(tokens=tokens.service)


@pytest_asyncio.fixture
async def probe_client(authentication_double: Authentication) -> AsyncIterator[AsyncClient]:
    """Client sur l'application de SONDE : les dependances transverses, sans base.

    `override=False` pose le montage sur `app.state` plutot que par surcharge de
    dependance : c'est la seule voie qui prouve `get_authentication`, sa garde
    `isinstance` et la cle d'etat -- la meme que celle qu'`api_client` emprunte.
    """
    async with asgi_client(build_probe_app(authentication_double, override=False)) as opened:
        yield opened


@pytest.fixture
def authentication(
    tokens: TokenFactory, bound_sessionmaker: async_sessionmaker[AsyncSession]
) -> Authentication:
    """Le montage REEL, dont seul le service de jetons vient du harnais.

    `build_authentication` est celle du `lifespan` -- extraite de sa closure par
    BACK-12 pour cette raison precise. Les quatre resolveurs sont donc ceux de la
    production, branches sur la fabrique de sessions LIEE : ils voient le semis
    NON COMMITE du test, ce qui supprime le contournement qu'ont du inventer
    `test_auth_integration.py` et `test_jwt_service_integration.py`, dont les
    resolveurs etaient cables a la main sur la session du test parce qu'« une
    autre connexion ne verrait rien du semis ».

    `replace` echange le SEUL champ que le harnais doit maitriser. Un test qui
    veut au contraire eprouver la chaine d'emission COMPLETE -- le role vient
    vraiment de `MembershipModel` -- ne remplace rien et seme son appartenance.
    """
    return replace(build_authentication(get_settings(), bound_sessionmaker), tokens=tokens.service)


@pytest_asyncio.fixture
async def api_client(
    database: Database, authentication: Authentication
) -> AsyncIterator[AsyncClient]:
    """Client sur l'APPLICATION REELLE, base branchee sur la transaction du test.

    `app.state` SE MONTE A LA MAIN, ET LE `lifespan` NE TOURNE PAS. Quatre
    raisons, toutes dans `main.py` : il appelle `get_settings()` en direct, que
    `dependency_overrides` n'atteint pas ; il appelle `configure_logging()`, ce
    que la garde `_ensure_pristine_logging` mesure et refuse ; il ouvre Redis, S3,
    le magasin d'OTP et demarre le broker, dont un test de route n'a que faire ;
    et il construit un moteur POOLE la ou tout le harnais tient par `NullPool`.
    Les cles d'etat sont publiques et exportees exactement pour ce montage.

    AUCUNE SURCHARGE D'UNITE DE TRAVAIL, ET C'EST LE POINT. `get_identity_uow` et
    `get_organization_uow` lisent `get_database(request).sessionmaker` : poser le
    bon `Database` suffit a ce que les routes ouvrent leurs sessions DANS la
    transaction du test. Elles voient le semis non commite, et le teardown annule
    tout. C'est le signe que le vrai cablage est teste, et non une doublure.
    """
    application = create_app()
    setattr(application.state, STATE_KEY, database)
    setattr(application.state, AUTH_STATE_KEY, authentication)
    async with asgi_client(application) as opened:
        yield opened


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
    collecte. Le remede est `isolated_logging()`, dans `tests/support/logs.py`.
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
