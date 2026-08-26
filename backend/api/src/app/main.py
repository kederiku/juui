"""Point d'entree HTTP du service d'API Juui.

Ce module ne porte aucune logique metier : c'est le fichier d'assemblage de
l'application. Il expose deux choses, et rien d'autre :

- `create_app()`, la factory qui construit une instance neuve de l'application ;
- `app`, l'instance que sert uvicorn (et, a partir d'INFRA-04, le conteneur).

C'est aussi le POINT D'ASSEMBLAGE des modules metier (BACK-04) : le seul endroit
du service qui ait le droit de connaitre plus d'un module a la fois. Chaque
module publie son routeur, ce fichier les monte, et c'est tout -- les modules,
eux, restent etanches les uns aux autres. C'est a ce titre, et a ce titre seul,
qu'il ouvre le magasin d'OTP d'`identity` (BACK-17) : une ressource de module que
`shared` n'a pas le droit de nommer.

L'application sert les sondes de sante (`/health/live`, `/health/ready`,
BACK-08) ; les routes METIER, elles, vivront sous `/api/v1` -- le routeur
d'`identity` y est monte mais reste vide, ses routes venant avec BACK-28 et
BACK-29. `/docs` n'affiche donc que le groupe `health`, ce qui est attendu.
"""

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI

from app.core import AppSettings, configure_logging, get_settings
from app.modules.identity import router as identity_router
from app.modules.identity.infrastructure.clients.redis_otp_store import (
    OTP_STORE_STATE_KEY,
    build_otp_store,
)
from app.shared.infrastructure.api.error_handlers import register_error_handlers
from app.shared.infrastructure.api.health import router as health_router
from app.shared.infrastructure.api.middlewares import register_middlewares
from app.shared.infrastructure.api.router import build_api_router
from app.shared.infrastructure.clients.redis_cache import CACHE_STATE_KEY, build_cache
from app.shared.infrastructure.clients.s3_storage import STORAGE_STATE_KEY, build_file_storage
from app.shared.infrastructure.db.base import Base, check_schema
from app.shared.infrastructure.db.engine import build_engine, verify_connectivity
from app.shared.infrastructure.db.session import STATE_KEY, Database, build_sessionmaker
from app.shared.infrastructure.tenancy import current_group_label


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Cycle de vie du processus : ouvre les ressources partagees, puis les ferme.

    Tout ce qui doit vivre aussi longtemps que le serveur -- et non le temps
    d'une requete -- se cree ici : le pool de connexions PostgreSQL (BACK-05),
    le client Redis (BACK-14), le client S3 (BACK-13), le magasin des codes de
    verification (BACK-17). Le transport de courriel (BACK-22) n'y figure PAS, et
    ce n'est pas un oubli : une session SMTP nait et meurt avec chaque message, il
    n'y a rien a ouvrir ni a refermer. Ces ressources se rangent dans `app.state`,
    d'ou les dependances FastAPI les recuperent via `request.app.state`. Le
    broker TaskIQ (BACK-15) est a part : il demarre et s'arrete ici aussi, mais
    les routes qui declenchent une tache importent la tache elle-meme -- rien a
    ranger dans `app.state`.

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

    # Second geste, et avant toute ressource : la journalisation (BACK-11).
    # Ici plutot que dans `create_app()` pour deux raisons. `import app.main`
    # doit rester sans effet de bord, et reconfigurer la racine de `logging` en
    # est un -- en test, il arracherait le handler de `caplog` en plein cas. Et
    # a cette place, TOUTES les lignes d'ouverture des ressources ci-dessous
    # sortent deja au bon format.
    #
    # `current_group_label` passe en argument parce que `core` ne peut pas
    # importer `shared` (contrat `service-spaces`) : ce fichier est l'un des deux
    # points d'entree du processus, avec `worker_startup()`, et c'est a lui de
    # faire le pont. Une seule source de verite -- la contextvar de `tenancy.py`
    # --, et tout ce qui pose un groupe apparait des lors dans les journaux.
    configure_logging(settings.app, context_providers={"group_id": current_group_label})

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

                # Cinquieme ressource : le magasin des codes de verification
                # (BACK-17), sur la meme instance Redis que le cache mais avec
                # son propre pool. Deux pools et non un seul, parce que les deux
                # contrats sont opposes : le cache degrade en silence, ce magasin
                # echoue ferme. Les melanger reviendrait a choisir l'un des deux.
                otp_store = build_otp_store(settings)
                try:
                    setattr(app.state, OTP_STORE_STATE_KEY, otp_store)

                    # `ping()` journalise et ne leve pas, comme pour le cache --
                    # mais pour une raison de plus : un Redis absent au demarrage
                    # ne doit pas priver le service de TOUT ce qui ne touche pas
                    # a la verification d'adresse. Les operations du magasin,
                    # elles, LEVENT : l'asymetrie est le sujet de son module.
                    await otp_store.ping()

                    # Sixieme ressource : le broker TaskIQ (BACK-15). Import
                    # LOCAL et non en tete de module : importer `tasks.broker`
                    # construit le broker, donc lit la configuration -- or `import
                    # app.main` doit rester possible sans fichier .env (voir plus
                    # haut). Construire n'ouvre aucune connexion, comme partout.
                    from app.shared.infrastructure.tasks.broker import broker

                    # Cote API, seul le versant CLIENT demarre : le backend de
                    # resultats, necessaire au `kiq`. Le worker -- qui IMPORTE ce
                    # module -- a son propre cycle de vie (WORKER_STARTUP) : la
                    # garde `is_worker_process` evite le double demarrage.
                    if not broker.is_worker_process:
                        await broker.startup()
                    try:
                        yield
                    finally:
                        # Ferme en premier : le broker est ouvert en dernier.
                        if not broker.is_worker_process:
                            await broker.shutdown()
                finally:
                    # Toujours en ordre inverse : le magasin d'OTP, puis le
                    # stockage, puis le cache, puis le moteur.
                    await otp_store.aclose()
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
# `organization` (BACK-16) n'a pas de routeur : son premier arrivera avec les
# routes d'administration de BACK-25. Meme silence pour `medical_records`
# (BACK-19) : ses routes arriveront avec BACK-30, et pour `notifications`
# (BACK-22), dont la lecture et l'ecriture des preferences supposent
# `get_current_active_account` (BACK-10c) et la surface de composition de
# BACK-23. Les suivants s'ajouteront ici.
_MODULE_ROUTERS: Sequence[APIRouter] = (identity_router,)


# Descriptions des etiquettes OpenAPI, dans l'ordre d'affichage de /docs.
#
# La cle `name` doit valoir EXACTEMENT le `tags=[...]` du routeur concerne :
# une etiquette mal appariee produirait un groupe sans description ET un groupe
# fantome. Orval (SHARED-03) decoupe ses clients par etiquette -- une par
# module, plus `health`. Ajouter un module = une ligne ici, une ligne dans
# `_MODULE_ROUTERS`.
_OPENAPI_TAGS: Sequence[dict[str, str]] = (
    {
        "name": "health",
        "description": "Sondes de vie et de disponibilite du service, hors /api/v1.",
    },
    {
        "name": "identity",
        "description": "Comptes et authentification : qui etes-vous, pouvez-vous le prouver.",
    },
)


def create_app(*, app_settings: AppSettings | None = None) -> FastAPI:
    """Construit une instance neuve et independante de l'application.

    Passer par une factory plutot que de configurer un objet global est ce qui
    rendra les tests de BACK-12 possibles : chaque test construit son
    application, avec ses propres surcharges de dependances, sans heriter de
    l'etat laisse par le test precedent.

    Args:
        app_settings: reglages generaux employes A LA CONSTRUCTION -- fermeture
            de /docs comprise. `None` les lit de l'environnement ; les tests de
            BACK-12 passeront les leurs sans manipuler de variables.

    Returns:
        L'application FastAPI, sondes et routeur v1 deja montes.
    """
    # `AppSettings()` et non `get_settings()`, et la nuance compte : cette
    # fonction s'execute a l'import du module (`app = create_app()`), qui doit
    # rester importable sans configuration complete -- voir la docstring du
    # lifespan. `AppSettings` n'a que des champs a defaut, sa construction
    # n'exige rien ; `Settings` reclamerait POSTGRES_USER et consorts.
    settings = AppSettings() if app_settings is None else app_settings

    # En production la surface de documentation se ferme ENTIEREMENT : /docs et
    # /redoc (le ticket), et aussi /openapi.json -- ecart assume au registre des
    # ecarts du site de documentation. Le
    # healthcheck du conteneur vise desormais /health/live et Orval (SHARED-03)
    # genere depuis un poste de developpement : plus aucun consommateur
    # legitime, et un plan complet de l'API servi sans authentification est de
    # la reconnaissance offerte.
    application = FastAPI(
        title="Juui API",
        version="0.1.0",
        description=(
            "API du SaaS veterinaire Juui. Les routes metier vivent sous "
            "`/api/v1` ; les sondes de sante sous `/health`, hors versionnage."
        ),
        # Nom et depot : aucune adresse de support n'existe encore, et en
        # inventer une serait pire que ce vide -- a completer quand elle existera.
        contact={"name": "Equipe Juui", "url": "https://github.com/kederiku/juui"},
        openapi_tags=list(_OPENAPI_TAGS),
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )

    # Avant les routes : l'application sait repondre en erreur (BACK-09) avant
    # de savoir repondre tout court. Fonctionnellement l'ordre est indifferent,
    # la lecture ne l'est pas.
    register_error_handlers(application)

    # Puis les intergiciels (BACK-11) : identifiant de requete, journal d'acces
    # et CORS. Leur ORDRE compte et s'explique dans `middlewares.py` -- ce
    # fichier n'en connait que le point d'entree, comme pour les handlers.
    register_middlewares(application, settings=settings)

    # Les sondes se montent SUR l'application, hors du routeur v1 : leur URL
    # est un contrat d'exploitation, pas un contrat d'API.
    application.include_router(health_router)
    application.include_router(build_api_router(_MODULE_ROUTERS))

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
