"""La categorie obligatoire du ticket, rendue mecanique (BACK-12).

CE QUE CE TEST GARDE, ET CE QU'IL NE PEUT PAS GARDER
Le ticket exige que « tout module portant des agregats tenant ait des tests
marques `tenant_isolation` ». Verifier qu'un tel test EXISTE est hors de portee
d'un test : la collecte pytest ne voit que la selection courante, et un
`pytest -k autre_chose` ferait passer au vert une garde qui n'aurait rien garde.

Ce test prend donc le probleme par l'autre bout, et c'est le seul qui tienne :
il verifie que la LISTE des modules tenant est a jour. Un agregat qui gagne
`TenantMixin` fait echouer la collecte tant que personne n'a inscrit son module
ici -- et l'inscrire est le moment ou la question « ou sont ses tests
d'isolation ? » se pose, avec le message qui la pose.

IL AURAIT ATTRAPE LE CAS REEL. `scheduling` a livre `PractitionerProfileModel`
en BACK-21, avec ses tests d'isolation, et SANS le marqueur. Rien ne l'a
signale ; c'est BACK-12 qui l'a decouvert en relisant. Ce test est ce qui fait
que cela n'arrivera plus en silence.
"""

import pkgutil
from contextlib import suppress
from importlib import import_module
from typing import Final

from app import modules as app_modules
from app.shared.infrastructure.db.base import Base
from app.shared.infrastructure.db.mixins import TenantMixin

# Modules metier dont au moins un agregat porte `TenantMixin`, et qui doivent
# donc porter des tests marques `tenant_isolation`, joues par `make test-tenancy`.
#
# `shared` n'y figure pas : ses deux modeles tenant sont les stubs de
# `tests/support/tenancy_stubs.py`, dont l'isolation est prouvee par
# `tests/shared/test_tenant_isolation.py` et la suite de conformite.
_TENANT_MODULES: Final = frozenset({"organization", "scheduling"})

# Message d'echec : il nomme le geste, pas seulement la faute.
_UNDECLARED = (
    "Le module « {module} » porte un agregat tenant ({model}) mais n'est pas "
    "declare ici. Ecrire ses tests d'isolation entre groupes, les marquer "
    "`tenant_isolation`, puis l'inscrire dans _TENANT_MODULES. C'est une "
    "categorie OBLIGATOIRE (BACK-12) : elle est la seule preuve que l'isolation "
    "entre groupes tient."
)

_STALE = (
    "Le module « {module} » est declare tenant mais aucun de ses modeles ne "
    "porte plus `TenantMixin`. Un marqueur qui ne designe rien est un marqueur "
    "qu'on cessera de croire : retirer la ligne."
)


def _tenant_modules() -> dict[str, str]:
    """Rend les modules metier dont un modele porte `TenantMixin`, et le modele temoin.

    LES MODULES SE DECOUVRENT, ILS NE SE RECOPIENT PAS. Une liste ecrite ici
    serait une TROISIEME copie de celle d'`alembic/env.py` et de `_MODULE_ROUTERS`
    -- et elle vieillirait exactement comme celle qu'on cherche a garder. On
    parcourt donc le paquet `app.modules` et l'on importe le `models.py` de
    chacun, a l'emplacement que le depot impose : `<module>/infrastructure/db/`.

    Ne pas s'en remettre a ce que `Base.registry` contient deja : il ne recense
    que les modeles IMPORTES, et cette liste depend de la selection de tests
    courante -- ce qui rendrait la garde verte a l'usage precis ou elle doit
    mordre.
    """
    for module in _business_modules():
        with suppress(ModuleNotFoundError):
            import_module(f"app.modules.{module}.infrastructure.db.models")

    found: dict[str, str] = {}
    for mapper in Base.registry.mappers:
        model = mapper.class_
        if not issubclass(model, TenantMixin):
            continue
        parts = model.__module__.split(".")
        if len(parts) > 2 and parts[:2] == ["app", "modules"]:
            found.setdefault(parts[2], model.__name__)
    return found


def _business_modules() -> list[str]:
    """Rend le nom de chaque sous-paquet de `app.modules`."""
    return sorted(found.name for found in pkgutil.iter_modules(app_modules.__path__) if found.ispkg)


def test_every_module_with_a_tenant_aggregate_is_declared() -> None:
    """Un agregat tenant neuf ne peut pas naitre sans que la question soit posee."""
    for module, model in sorted(_tenant_modules().items()):
        assert module in _TENANT_MODULES, _UNDECLARED.format(module=module, model=model)


def test_no_module_is_declared_tenant_without_a_tenant_aggregate() -> None:
    """L'autre sens : une declaration qui ne designe plus rien doit disparaitre."""
    carriers = _tenant_modules()
    for module in sorted(_TENANT_MODULES):
        assert module in carriers, _STALE.format(module=module)
