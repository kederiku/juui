"""Taches de demonstration : le patron de reference des taches de fond (BACK-15).

Toute tache ecrite pour BACK-17, BACK-22 ou les suivants part de `record_ping` :
elle en reprend la signature -- des IDENTIFIANTS SERIALISABLES, le `group_id`
en tete, les dependances en fin --, le `use_group` en premiere instruction, et
l'idempotence. `fail_on_purpose` n'est pas un patron : elle n'existe que pour
rendre observables la politique de reprise et la file de rejets.

CE QUE « IDEMPOTENTE » VEUT DIRE ICI, ET POURQUOI C'EST EXIGE
La politique de reprise REJOUE les taches en echec, et le stream represente un
message dont l'acquittement s'est perdu : toute tache doit pouvoir s'executer
deux fois sans effet cumulatif. `record_ping` l'obtient en derivant sa valeur
des SEULS arguments et en l'ecrivant par un SET absolu : rejouee, elle reecrit
le meme etat. Les anti-patrons a ne pas reproduire : incrementer un compteur,
ecrire un horodatage, dependre d'un etat lu puis reecrit sans verrou.
"""

from typing import Annotated, Final
from uuid import UUID

from taskiq import TaskiqDepends

from app.shared.domain.ports.cache import Cache
from app.shared.infrastructure.tasks.broker import broker
from app.shared.infrastructure.tasks.lifecycle import get_task_cache
from app.shared.infrastructure.tenancy import use_group

# Duree de vie des empreintes de demonstration : cinq minutes, le temps de les
# constater dans une sonde -- rien de tout cela n'est une donnee.
_PING_TTL_SECONDS: Final = 300


class DemoFailureError(RuntimeError):
    """Echec volontaire, leve par `fail_on_purpose` et par elle seule."""


@broker.task(task_name="shared.demo.record_ping")
async def record_ping(
    group_id: UUID,
    ping_id: str,
    cache: Annotated[Cache, TaskiqDepends(get_task_cache)],
) -> str:
    """Ecrit une empreinte deterministe dans le cache du groupe, et la retourne.

    LE `group_id` EN ARGUMENT, ET EN PREMIER : une tache s'execute hors de tout
    contexte de requete, le groupe actif ne traverse pas la file tout seul
    (ADR-0008). L'argument est type `UUID` -- serialise en chaine sur le fil,
    re-type par le receiver -- et `use_group` le repose dans la contextvar en
    PREMIERE instruction : la composition de la cle TENANT, et le futur filtre
    de persistance (BACK-06b), le lisent la. Une tache lancee sans lui echoue
    en `MissingTenantContextError`, bruyamment, au lieu d'ecrire hors groupe.

    Args:
        group_id: le groupe actif au moment ou la tache a ete demandee.
        ping_id: discriminant de l'empreinte, choisi par l'appelant.
        cache: le cache du worker, injecte -- jamais construit dans la tache.

    Returns:
        La valeur ecrite, relisible par l'appelant via `wait_result`.
    """
    with use_group(group_id):
        value = f"pong:{ping_id}"
        await cache.set(f"demo:ping:{ping_id}", value, ttl=_PING_TTL_SECONDS)
        return value


@broker.task(task_name="shared.demo.fail_on_purpose")
async def fail_on_purpose(reason: str) -> None:
    """Echoue systematiquement, pour observer relances, replis et rejets.

    Args:
        reason: motif rejoue dans l'exception, pour se retrouver dans les
            journaux et dans le document de rejet.

    Raises:
        DemoFailureError: toujours -- c'est sa seule raison d'etre.
    """
    raise DemoFailureError(reason)
