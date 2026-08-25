"""Decouverte des taches declarees par les modules metier (BACK-15).

MOTIF -- POURQUOI UN IMPORT DYNAMIQUE, ICI ET NULLE PART AILLEURS
Le point d'entree du worker est fige par l'infrastructure livree (INFRA-04,
INFRA-05b) : `taskiq worker app.shared.infrastructure.tasks.broker:broker`,
sans argument de modules. Or le contrat `service-spaces` interdit a `shared`
d'importer `app.modules.*` : le broker ne peut pas connaitre statiquement les
taches des modules. Ce fichier est le POINT D'ASSEMBLAGE qui resout la
contradiction : au demarrage du worker -- et jamais a l'import du paquet --, il
importe `app.modules.<module>.infrastructure.tasks` partout ou ce sous-paquet
existe, ce qui enregistre leurs taches aupres du broker. BACK-17 et BACK-22
n'auront qu'a creer le sous-paquet, sans toucher ni Dockerfile ni compose.

C'est une entorse a l'ESPRIT du contrat, assumee et confinee : elle est
invisible d'import-linter, donc elle n'existe QU'ICI, ou ce commentaire la
declare. En ecrire une seconde ailleurs serait le debut de la fin du contrat.
"""

import importlib
import importlib.util
import logging
import pkgutil
from typing import Final

_LOGGER: Final = logging.getLogger(__name__)

# Paquet racine des modules metier, et suffixe du sous-paquet de taches que la
# portee du ticket assigne a chaque module.
_MODULES_PACKAGE: Final = "app.modules"
_TASKS_SUBPACKAGE: Final = "infrastructure.tasks"


def discover_module_tasks() -> tuple[str, ...]:
    """Importe `app.modules.<m>.infrastructure.tasks` partout ou il existe.

    Appelee par le demarrage du worker (`WORKER_STARTUP`). L'importation
    enregistre les taches decorees `@broker.task` aupres du broker, deja
    construit a ce stade.

    Returns:
        Les noms des sous-paquets importes, pour la journalisation et les
        sondes.

    Raises:
        ModuleNotFoundError: si un sous-paquet de taches existe mais echoue a
            importer l'une de SES dependances -- un vrai defaut, qui doit tuer
            le worker plutot que de faire silencieusement tourner une flotte
            sans les taches concernees.
    """
    spec = importlib.util.find_spec(_MODULES_PACKAGE)
    if spec is None or spec.submodule_search_locations is None:
        message = f"Le paquet {_MODULES_PACKAGE} est introuvable ou n'est pas un paquet."
        raise ModuleNotFoundError(message)

    imported: list[str] = []
    modules = pkgutil.iter_modules(spec.submodule_search_locations, prefix=f"{_MODULES_PACKAGE}.")
    for info in modules:
        if not info.ispkg:
            continue
        candidate = f"{info.name}.{_TASKS_SUBPACKAGE}"
        try:
            importlib.import_module(candidate)
        except ModuleNotFoundError as error:
            # N'avaler QUE l'absence du sous-paquet lui-meme ou d'un de ses
            # intermediaires (`organization` n'a pas encore d'`infrastructure/`).
            # Le test porte sur des NOMS DE PAQUETS, d'ou le point ajoute :
            # `a.b.orga` ne doit pas passer pour un prefixe de `a.b.organization`.
            missing = error.name
            if missing is None:
                raise
            if candidate != missing and not candidate.startswith(f"{missing}."):
                raise
            continue
        imported.append(candidate)

    if imported:
        _LOGGER.info("Taches de modules decouvertes : %s.", ", ".join(imported))
    else:
        _LOGGER.info("Aucun module ne declare de taches -- seules celles de shared/ tournent.")
    return tuple(imported)
