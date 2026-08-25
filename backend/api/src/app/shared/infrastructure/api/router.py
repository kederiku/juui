"""Routeur racine de la v1 de l'API (BACK-08).

Toutes les routes METIER vivent sous `/api/v1` : le prefixe de version se pose
ici, UNE fois, et jamais dans les modules. La repartition est celle-ci : la
VERSION est un choix du service, le chemin de la ressource (`/auth`, ...) reste
celui du module -- chacun maitre de sa moitie de l'URL (BACK-04).

UNE FONCTION, ET NON UN ROUTEUR PRE-ASSEMBLE. Ce fichier appartient a
`app.shared`, que le contrat « Sens des dependances entre les espaces du
service » (import-linter) place SOUS `app.modules` : il ne peut pas importer
les routeurs des modules pour les monter lui-meme. C'est `app.main`, seul
point d'assemblage, qui possede la liste et la passe en argument.

Les sondes de sante (`health.py`) ne passent PAS par ici : leur URL est un
contrat d'exploitation, stable a travers les versions de l'API.
"""

from collections.abc import Sequence
from typing import Final

from fastapi import APIRouter

# Prefixe de version. Une constante exportee et non un litteral repete : les
# messages, la documentation et les tests de BACK-12 doivent parler du meme nom.
API_V1_PREFIX: Final = "/api/v1"


def build_api_router(module_routers: Sequence[APIRouter]) -> APIRouter:
    """Assemble le routeur racine v1 a partir des routeurs publies par les modules.

    Args:
        module_routers: les routeurs des modules, dans leur ordre de montage --
            la liste vit dans `app.main`, qui seul a le droit de la connaitre.

    Returns:
        Le routeur unique, prefixe `/api/v1`, a monter sur l'application.
    """
    api_router = APIRouter(prefix=API_V1_PREFIX)
    for module_router in module_routers:
        api_router.include_router(module_router)
    return api_router
