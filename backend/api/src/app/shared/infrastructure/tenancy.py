"""Contexte de tenance : quel groupe est actif pour le traitement en cours (BACK-14).

Le SaaS est multi-tenant : un compte peut appartenir a plusieurs groupes, et un
veterinaire remplacant bascule de structure en cours de journee. « Quel groupe
regarde-t-on ? » n'est donc pas une propriete du code appele, c'est une propriete
de l'appel -- exactement ce qu'une `ContextVar` sait porter, sans traverser
chaque signature de fonction jusqu'a la couche qui en a besoin.

POURQUOI CE FICHIER EXISTE DEJA, ALORS QU'IL APPARTIENT A BACK-06b
BACK-14 exige le groupe actif DANS LA CLE DE CACHE, et rien ne le portait. La
surface livree ici est donc volontairement reduite a trois choses : lire, exiger,
et poser le temps d'un bloc. BACK-06b y ajoutera l'intergiciel qui alimente la
contextvar depuis l'authentification (BACK-10c) et, dans `db/`, le filtre
SQLAlchemy applique aux agregats declarant `TenantMixin`.

POURQUOI ICI ET NON DANS `db/`
BACK-04 annoncait ce contexte sous `db/`, du temps ou la persistance devait en
etre le seul lecteur. Le cache l'a rejointe : l'y laisser obligerait
`clients/redis_cache.py` a importer le socle de persistance pour savoir nommer
une cle. Or l'appartenance a un groupe n'est pas une notion de persistance --
c'est une notion de requete, que la persistance et le cache lisent tous deux.

PIEGE A CONNAITRE AVANT D'ECRIRE L'INTERGICIEL DE BACK-06b
`BaseHTTPMiddleware` de Starlette execute l'aval de la chaine dans une TACHE
distincte. Un `current_group_id.set()` fait dans son `dispatch()` n'atteindrait
donc pas l'endpoint : la copie de contexte part avant. L'intergiciel de tenance
devra etre un intergiciel ASGI pur -- une fonction `(scope, receive, send)` --,
ou poser le groupe depuis une DEPENDANCE FastAPI, qui s'execute elle dans le
contexte de l'endpoint.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Final
from uuid import UUID


class MissingTenantContextError(RuntimeError):
    """Un traitement lie a un groupe s'execute hors de tout contexte de groupe.

    C'est un defaut de cablage, pas une panne : une route qui manque sa
    dependance d'authentification, ou une tache de fond lancee sans le `group_id`
    que BACK-15 devra lui transmettre.

    Volontairement distincte des erreurs metier de `DomainError` : aucune regle
    du domaine n'est violee, c'est l'appelant qui ne sait pas de quel groupe il
    parle. Et surtout, elle LEVE au lieu de degrader -- se rabattre en silence
    sur « pas de groupe » produirait des cles de cache partagees entre
    structures, c'est-a-dire la fuite meme que BACK-14 cherche a rendre
    impossible.
    """


# Groupe actif du traitement en cours, ou `None` hors de tout contexte de groupe.
#
# `default=None` et non l'absence de defaut : sans lui, `get()` leverait un
# `LookupError` nu dans tout traitement non tenant -- une inscription, une sonde
# de sante --, la ou l'absence de groupe y est l'etat NORMAL. Les appelants qui
# exigent un groupe passent par `require_current_group_id()`, qui dit pourquoi.
current_group_id: Final[ContextVar[UUID | None]] = ContextVar("current_group_id", default=None)


def require_current_group_id() -> UUID:
    """Retourne le groupe actif, ou echoue en le disant.

    A appeler depuis tout code dont le resultat DEPEND du groupe : composition
    d'une cle de cache tenant (BACK-14), filtre de persistance (BACK-06b).

    Returns:
        L'identifiant du groupe actif.

    Raises:
        MissingTenantContextError: si aucun groupe n'est pose.
    """
    group_id = current_group_id.get()
    if group_id is None:
        message = (
            "Aucun groupe actif dans le contexte : ce traitement est lie a un "
            "groupe mais s'execute hors de tout contexte de tenance."
        )
        raise MissingTenantContextError(message)
    return group_id


@contextmanager
def use_group(group_id: UUID | None) -> Iterator[None]:
    """Pose le groupe actif pour la duree du bloc, puis remet le precedent.

    `reset(token)` et non `set(None)` en sortie : c'est ce qui rend l'imbrication
    correcte. Avec `set(None)`, un bloc imbrique effacerait le groupe du bloc
    englobant a sa sortie au lieu de le restaurer.

    Args:
        group_id: le groupe a poser, ou `None` pour executer le bloc HORS de tout
            contexte de tenance -- ce qui est un usage legitime, et non une
            facon detournee de ne rien faire.

    Yields:
        Rien : le bloc s'execute, le contexte est restaure a sa sortie.
    """
    token = current_group_id.set(group_id)
    try:
        yield
    finally:
        current_group_id.reset(token)
