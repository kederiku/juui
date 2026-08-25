"""Point d'entree HTTP du service d'API Juui.

Ce module ne porte aucune logique metier : c'est le fichier d'assemblage de
l'application. Il expose deux choses, et rien d'autre :

- `create_app()`, la factory qui construit une instance neuve de l'application ;
- `app`, l'instance que sert uvicorn (et, a partir d'INFRA-04, le conteneur).

C'est aussi le POINT D'ASSEMBLAGE des modules metier (BACK-04) : le seul endroit
du service qui ait le droit de connaitre plus d'un module a la fois. Chaque
module publie son routeur, ce fichier les monte, et c'est tout -- les modules,
eux, restent etanches les uns aux autres.

L'application ne sert encore AUCUNE route : le routeur d'`identity` est monte
mais vide, ses routes venant avec BACK-28 et BACK-29, et la sonde de sante avec
BACK-08. `/docs` s'affiche donc vide, ce qui est attendu.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.core import get_settings
from app.modules.identity import router as identity_router
from app.shared.infrastructure.clients.redis_cache import CACHE_STATE_KEY, build_cache
from app.shared.infrastructure.clients.s3_storage import STORAGE_STATE_KEY, build_file_storage
from app.shared.infrastructure.db.base import Base, check_schema
from app.shared.infrastructure.db.engine import build_engine, verify_connectivity
from app.shared.infrastructure.db.session import STATE_KEY, Database, build_sessionmaker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Cycle de vie du processus : ouvre les ressources partagees, puis les ferme.

    Tout ce qui doit vivre aussi longtemps que le serveur -- et non le temps
    d'une requete -- se cree ici : le pool de connexions PostgreSQL (BACK-05),
    le client Redis (BACK-14), le client S3 (BACK-13), le broker TaskIQ
    (BACK-15). Ces ressources se rangent ensuite dans `app.state`, d'ou les
    dependances FastAPI les recuperent via `request.app.state`.

    Le point d'accroche fixe une contrainte que le reste du code doit respecter :
    aucune connexion ne s'ouvre a l'import du module, tout passe par ici. Ce qui
    precede le `yield` s'execute au demarrage, ce qui le suit a l'arret -- et
    l'ordre de fermeture est l'inverse exact de l'ordre d'ouverture.
    """
    # Premier occupant du point d'accroche : la configuration (BACK-03) se valide
    # AVANT que la moindre ressource ne s'ouvre. Une variable obligatoire absente
    # doit arreter le processus ici, avec le nom de la variable, et non produire
    # une panne au premier appel HTTP.
    #
    # Ici et non dans `create_app()` : ce module doit rester importable sans
    # effet de bord, et un `import app.main` -- ce que font Mypy et les futurs
    # exports d'OpenAPI -- ne doit pas exiger un fichier .env.
    settings = get_settings()

    # Seconde ressource : le moteur PostgreSQL (BACK-05). Le construire n'ouvre
    # aucune connexion ; `verify_connectivity` en ouvre une et la referme.
    engine = build_engine(settings)
    try:
        await verify_connectivity(engine, settings)

        # Controle du schema declare, une fois les modeles importes. Surtout
        # PAS de `Base.metadata.create_all()` : le schema existerait alors avant
        # la premiere migration, et `alembic upgrade head` (BACK-07) echouerait
        # sur une table deja creee.
        check_schema(Base.metadata)

        setattr(
            app.state,
            STATE_KEY,
            Database(engine=engine, sessionmaker=build_sessionmaker(engine)),
        )

        # Troisieme ressource : le cache Redis (BACK-14), base 0. Comme le
        # moteur, le construire n'ouvre aucune connexion.
        cache = build_cache(settings)
        try:
            setattr(app.state, CACHE_STATE_KEY, cache)

            # NE PAS transformer ceci en garde bloquante. L'asymetrie avec
            # `verify_connectivity` est deliberee : sans base de donnees aucune
            # route ne peut repondre juste, donc echouer vite est correct ; sans
            # cache toutes repondent, plus lentement. Un demarrage qui echoue
            # parce qu'un CACHE est absent rendrait par ailleurs inatteignable le
            # critere « si Redis est arrete, l'application continue de repondre ».
            # `ping()` sonde et journalise, elle ne leve jamais.
            await cache.ping()

            # Quatrieme ressource : le stockage objet (BACK-13). Construire le
            # client n'ouvre aucune connexion, comme pour les deux precedentes.
            storage = build_file_storage(settings)
            try:
                setattr(app.state, STORAGE_STATE_KEY, storage)

                # MEME GESTE QUE POUR LE CACHE, POUR UNE RAISON DIFFERENTE, et
                # c'est ce qu'il faut avoir en tete avant de toucher a ces deux
                # lignes. Le cache ne bloque pas le demarrage parce qu'il ne
                # bloquera rien ensuite : sans lui, tout repond plus lentement.
                # Le stockage, lui, ne bloque pas le demarrage parce qu'aucune
                # route n'en depend encore -- mais ses operations LEVENT. Refuser
                # de partir priverait le service de tout ce qui n'a rien a voir
                # avec les fichiers ; se taire a l'appel ferait perdre des
                # fichiers en silence. `ping()` journalise, les operations levent.
                await storage.ping()

                yield
            finally:
                # Toujours en ordre inverse : le stockage, puis le cache, puis le
                # moteur. `aclose()` n'echoue pas -- une exception levee ici
                # sauterait les deux fermetures qui suivent.
                await storage.aclose()
        finally:
            # Fermeture en ordre INVERSE de l'ouverture : le cache avant le
            # moteur. `aclose()` ferme le client et le pool, et n'echoue pas --
            # une exception levee ici sauterait le `dispose()` ci-dessous.
            await cache.aclose()
    finally:
        # `finally` et non simplement apres le `yield` : un moteur construit
        # avant un `SELECT 1` en echec doit etre libere lui aussi, sans quoi une
        # boucle de redemarrage de conteneur fuit un pool a chaque tour.
        #
        # `dispose()` sans argument : `close=True` est deja le defaut, et ne se
        # discute que dans un processus qui aurait forke apres la creation du
        # moteur -- ce que ni uvicorn ni TaskIQ ne font ici.
        await engine.dispose()


# Routeurs publies par les modules metier, dans leur ordre de montage.
#
# Un TUPLE plutot qu'une suite d'appels a `include_router` : ajouter un module
# revient alors a ajouter une ligne ici, et la liste des contextes servis par
# l'API se lit d'un coup d'oeil. Chaque routeur porte son propre prefixe et sa
# propre etiquette -- c'est le module qui decide de sa surface publique, pas ce
# fichier.
#
# `organization` (BACK-16) et les modules suivants viendront s'y ajouter.
_MODULE_ROUTERS: Sequence[APIRouter] = (identity_router,)


def create_app() -> FastAPI:
    """Construit une instance neuve et independante de l'application.

    Passer par une factory plutot que de configurer un objet global est ce qui
    rendra les tests de BACK-12 possibles : chaque test construit son
    application, avec ses propres surcharges de dependances, sans heriter de
    l'etat laisse par le test precedent.

    Returns:
        L'application FastAPI, routeurs des modules deja montes.
    """
    application = FastAPI(
        title="Juui API",
        version="0.1.0",
        lifespan=lifespan,
    )

    for module_router in _MODULE_ROUTERS:
        application.include_router(module_router)

    return application


# Instance servie par uvicorn (`uvicorn app.main:app`), et plus tard par le
# conteneur d'INFRA-04.
#
# Ce n'est PAS une entorse a la factory. Un serveur ASGI a besoin d'un objet, pas
# d'une fonction : cette ligne est l'adaptateur entre les deux, et `create_app()`
# reste l'unique endroit ou l'application se construit. L'anti-pattern que le
# ticket ecarte est different : un `app = FastAPI()` nu sur lequel des
# decorateurs enregistreraient les routes a l'import, ce qui interdirait toute
# isolation en test.
#
# Deux regles en decoulent, a tenir dans la duree : ce module doit rester
# importable sans effet de bord, et les tests doivent appeler `create_app()`
# plutot qu'importer `app`.
app = create_app()
