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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Cycle de vie du processus : ouvre les ressources partagees, puis les ferme.

    Tout ce qui doit vivre aussi longtemps que le serveur -- et non le temps
    d'une requete -- se cree ici : le pool de connexions PostgreSQL (BACK-05),
    le client Redis (BACK-14), le broker TaskIQ (BACK-15). Ces ressources se
    rangent ensuite dans `app.state`, d'ou les dependances FastAPI les
    recuperent via `request.app.state`.

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
    get_settings()

    yield


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
