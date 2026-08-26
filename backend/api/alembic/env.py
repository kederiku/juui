"""Environnement d'execution des migrations Alembic (BACK-07).

Ce module tourne HORS de l'application : la commande `alembic` l'importe, jamais
le serveur. Il ne partage avec elle que deux verites, lues a la meme source
qu'elle : l'URL de connexion vient de `Settings` (app.core) -- rien n'est ecrit
dans alembic.ini -- et `Base.metadata` sert de cible a l'autogeneration.

LES MODELES DOIVENT ETRE IMPORTES
`Base.metadata` ne recense que les tables des modeles effectivement importes.
Tout nouveau module metier qui gagne un `infrastructure/db/models.py` DOIT
s'ajouter a `_MODEL_MODULES`, sans quoi l'autogeneration proposera de SUPPRIMER
ses tables. Le filet est `alembic check` (make migrate-check) : sur une base a
jour, il echoue des que modeles et migrations divergent.

UN SEUL MIGRATEUR A LA FOIS
Les conteneurs `api` et `worker` partagent l'entrypoint d'INFRA-04, qui lance
`alembic upgrade head` a chaque demarrage -- et le worker est `--scale`-able.
Un verrou consultatif PostgreSQL serialise les executions : le second migrateur
ATTEND le premier, puis rejoue un plan devenu vide. Voir
`run_async_migrations`, dont le commit qui suit la prise du verrou n'est pas
decoratif.

PAS DE MODE HORS LIGNE
`alembic upgrade head --sql` est refuse explicitement : personne ne consomme de
script SQL genere, et le verrou ci-dessus ne peut rien serialiser sans
connexion. Le jour ou un exploitant en aura besoin, ce refus est l'endroit a
rouvrir (BACK-07).
"""

import asyncio
from importlib import import_module
from logging.config import fileConfig
from typing import Final

from alembic import context
from alembic.util import CommandError
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.core import get_settings
from app.shared.infrastructure.db.base import Base, check_schema

# Journalisation d'Alembic, configuree par les sections [loggers] et compagnie
# d'alembic.ini. C'est le SEUL usage que ce module fait de ce fichier.
if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

# Modules de modeles a importer pour peupler `Base.metadata`. MEME GESTE que le
# tuple `_MODULE_ROUTERS` de main.py : ajouter un module metier, c'est ajouter
# une ligne ici, et la liste des tables sous controle de version se lit d'un
# coup d'oeil.
_MODEL_MODULES: Final[tuple[str, ...]] = (
    "app.modules.identity.infrastructure.db.models",
    "app.modules.medical_records.infrastructure.db.models",
    "app.modules.notifications.infrastructure.db.models",
    "app.modules.organization.infrastructure.db.models",
)

for _module_name in _MODEL_MODULES:
    import_module(_module_name)

# Un schema qui enfreint les conventions (identifiant au-dela de 63 octets) doit
# empecher la generation d'une migration autant que le demarrage de l'API : meme
# garde, meme moment. Elle court des que ce module s'execute -- toute commande
# qui touche la base (upgrade, downgrade, current, check, revision
# --autogenerate) ; les commandes purement informatives (history, heads) ne
# chargent pas cet environnement et passent au travers, sans consequence : elles
# ne generent rien et n'ecrivent rien.
check_schema(Base.metadata)

# Cle du verrou consultatif, arbitraire mais FIGEE : « juui » en ASCII
# (0x6A 0x75 0x75 0x69). L'espace de cles est propre a la base ; aucun autre
# verrou consultatif n'existe dans le service a ce jour.
_MIGRATION_LOCK_KEY: Final = 0x6A75_7569

# Meme delai et meme raison que le moteur de l'application (engine.py) : un
# hote muet doit echouer en le disant.
_CONNECT_TIMEOUT_SECONDS: Final = 10


def do_run_migrations(connection: Connection) -> None:
    """Configure le contexte Alembic sur une connexion et deroule les migrations.

    Args:
        connection: la connexion synchrone fournie par `run_sync` -- celle-la
            meme qui detient deja le verrou consultatif.
    """
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        # `compare_type` est le defaut depuis Alembic 1.12 ; redeclare pour que
        # la promesse du ticket se lise ici. `compare_server_default` ne l'est
        # pas : sans lui, un `server_default=func.now()` ajoute ou retire ne
        # produirait aucune migration.
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Ouvre une connexion dediee, prend le verrou de migration, puis deroule.

    Le moteur est construit ICI et non par `build_engine` (engine.py) : un
    processus de migration vit le temps d'une commande, son pool est donc
    `NullPool` -- incompatible avec les `pool_size`/`max_overflow` que
    `build_engine` transmet toujours -- et sa connexion s'annonce sous son
    propre nom dans `pg_stat_activity`, la ou reutiliser le moteur de l'API
    rendrait une migration indiscernable de l'API elle-meme.
    """
    settings = get_settings()
    engine = create_async_engine(
        settings.db.sqlalchemy_url,
        poolclass=NullPool,
        connect_args={
            "timeout": _CONNECT_TIMEOUT_SECONDS,
            "server_settings": {
                "application_name": f"juui-alembic/{settings.app.environment}",
            },
        },
    )
    try:
        async with engine.connect() as connection:
            # Verrou consultatif de SESSION : plusieurs `alembic upgrade head`
            # simultanes se serialisent ici. Pas de deverrouillage explicite :
            # la session se ferme avec le moteur et PostgreSQL libere le verrou
            # avec elle. Le CAST fixe la surcharge bigint de la fonction, quel
            # que soit le type que le pilote infere pour le parametre.
            await connection.execute(
                text("SELECT pg_advisory_lock(CAST(:lock_key AS bigint))"),
                {"lock_key": _MIGRATION_LOCK_KEY},
            )
            # COMMIT OBLIGATOIRE, ET CE N'EST PAS UN DETAIL. L'execute ci-dessus
            # a ouvert une transaction (autobegin). Si elle restait ouverte,
            # Alembic la detecterait et cesserait de gerer la sienne -- charge a
            # l'appelant de committer, ce que la fermeture du bloc `async with`
            # ne fait pas : tout le DDL serait DEROULE EN ARRIERE a la
            # deconnexion, sans erreur. Le verrou, lui, est de niveau session et
            # survit au commit.
            await connection.commit()
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    """Point d'entree du mode en ligne, le seul que ce projet accepte."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    _message = (
        "Le mode hors ligne (--sql) n'est pas pris en charge : l'URL vient de "
        "Settings et les migrations s'executent sous verrou consultatif, ce "
        "qu'un script SQL genere ne peut pas garantir. Relire la migration "
        "Python, ou rouvrir cet arbitrage (BACK-07) si un besoin reel apparait."
    )
    raise CommandError(_message)

run_migrations_online()
