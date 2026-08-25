"""Contexte de tenance : quel perimetre est actif pour le traitement en cours (BACK-14, BACK-06b).

Le SaaS est multi-tenant : un compte peut appartenir a plusieurs groupes, et un
veterinaire remplacant bascule de structure en cours de journee. « Quel groupe
regarde-t-on ? » n'est donc pas une propriete du code appele, c'est une propriete
de l'appel -- exactement ce qu'une `ContextVar` sait porter, sans traverser
chaque signature de fonction jusqu'a la couche qui en a besoin.

TROIS ETATS, ET PAS UN DE PLUS
La contextvar porte soit un groupe (`UUID`), soit le mode assume « tous
groupes » (`AllGroups`), soit rien (`None`). `None` est l'etat NORMAL d'un
traitement non tenant -- une inscription, une sonde de sante -- et tout acces a
un agregat tenant y echoue bruyamment. `AllGroups` est l'echappatoire nommee de
BACK-06b : elle ne se pose que par `use_all_groups(reason=...)`, jamais par
defaut, jamais par oubli. Une seule contextvar pour les trois : deux variables
se desynchroniseraient, la ou une seule valeur rend l'imbrication correcte par
`reset(token)` et le `match` exhaustif chez ses lecteurs.

POURQUOI ICI ET NON DANS `db/`
BACK-04 annoncait ce contexte sous `db/`, du temps ou la persistance devait en
etre le seul lecteur. Le cache l'a rejointe : l'y laisser obligerait
`clients/redis_cache.py` a importer le socle de persistance pour savoir nommer
une cle. Or l'appartenance a un groupe n'est pas une notion de persistance --
c'est une notion de requete, que la persistance et le cache lisent tous deux.
Le filtre SQLAlchemy de BACK-06b vit, lui, dans `db/repositories/tenant.py` :
la mecanique aupres du depot qu'elle complete, le contexte au-dessus des deux
lecteurs.

PIEGE A CONNAITRE AVANT D'ECRIRE L'INTERGICIEL DE BACK-10c
C'est la dependance d'authentification (BACK-10c) qui posera le groupe actif a
partir du claim `active_group_id`. Si elle devait passer par un intergiciel :
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
from dataclasses import dataclass
from typing import Final, assert_never
from uuid import UUID


class MissingTenantContextError(RuntimeError):
    """Un traitement lie a un groupe s'execute hors de tout contexte de groupe.

    C'est un defaut de cablage, pas une panne : une route qui manque sa
    dependance d'authentification, ou une tache de fond lancee sans le `group_id`
    que BACK-15 lui transmet. Elle se leve aussi sous le mode « tous groupes »
    quand le geste exige UN groupe -- estampiller une insertion, composer une
    cle de cache tenant : lire partout n'est pas ecrire n'importe ou.

    Volontairement distincte des erreurs metier de `DomainError` : aucune regle
    du domaine n'est violee, c'est l'appelant qui ne sait pas de quel groupe il
    parle. Et surtout, elle LEVE au lieu de degrader -- se rabattre en silence
    sur « pas de groupe » produirait des cles de cache partagees entre
    structures (BACK-14) ou des requetes rendant les donnees de tous les
    groupes (BACK-06b), c'est-a-dire la fuite meme que ce contexte cherche a
    rendre impossible.
    """


@dataclass(frozen=True, slots=True)
class AllGroups:
    """Mode assume « tous groupes », porteur de sa raison.

    Ce n'est ni un etat par defaut ni un repli : cette valeur ne se construit
    que par `use_all_groups(reason=...)`, et la raison, obligatoire, est ce qui
    rend l'echappatoire visible en revue comme dans les messages d'erreur.
    """

    reason: str


# Perimetre de tenance du traitement en cours : un groupe, le mode assume
# « tous groupes », ou `None` hors de tout contexte de groupe.
#
# `default=None` et non l'absence de defaut : sans lui, `get()` leverait un
# `LookupError` nu dans tout traitement non tenant -- une inscription, une sonde
# de sante --, la ou l'absence de groupe y est l'etat NORMAL. Les appelants qui
# exigent un groupe passent par `require_current_group_id()`, qui dit pourquoi.
current_group_id: Final[ContextVar[UUID | AllGroups | None]] = ContextVar(
    "current_group_id", default=None
)


def require_current_group_id() -> UUID:
    """Retourne le groupe actif, ou echoue en le disant.

    A appeler depuis tout code dont le resultat depend d'UN groupe precis :
    composition d'une cle de cache tenant (BACK-14), estampillage d'une ligne a
    l'insertion (BACK-06b). Le mode « tous groupes » echoue ici aussi : ces
    gestes n'ont pas de sens sans groupe unique, et l'echappatoire de lecture
    n'autorise pas a ecrire n'importe ou.

    Returns:
        L'identifiant du groupe actif.

    Raises:
        MissingTenantContextError: si aucun groupe n'est pose, ou si le mode
            « tous groupes » est actif.
    """
    scope = current_group_id.get()
    match scope:
        case UUID():
            return scope
        case AllGroups(reason=reason):
            message = (
                f"Le mode « tous groupes » est actif (raison : {reason}), mais ce "
                "traitement exige UN groupe : ouvrir un bloc `use_group(group_id)` "
                "imbrique pour designer lequel."
            )
            raise MissingTenantContextError(message)
        case None:
            message = (
                "Aucun groupe actif dans le contexte : ce traitement est lie a un "
                "groupe mais s'execute hors de tout contexte de tenance."
            )
            raise MissingTenantContextError(message)
        case _:
            assert_never(scope)


@contextmanager
def use_group(group_id: UUID | None) -> Iterator[None]:
    """Pose le groupe actif pour la duree du bloc, puis remet le precedent.

    `reset(token)` et non `set(None)` en sortie : c'est ce qui rend l'imbrication
    correcte. Avec `set(None)`, un bloc imbrique effacerait le groupe du bloc
    englobant a sa sortie au lieu de le restaurer.

    `None` execute le bloc HORS de tout contexte de tenance -- usage legitime,
    et non une facon detournee de ne rien faire : tout acces a un agregat
    tenant y echoue en `MissingTenantContextError`. Pour voir TOUS les groupes,
    c'est `use_all_groups` qui se declare, avec sa raison.

    Args:
        group_id: le groupe a poser, ou `None` pour executer le bloc hors de
            tout contexte de tenance.

    Yields:
        Rien : le bloc s'execute, le contexte est restaure a sa sortie.
    """
    token = current_group_id.set(group_id)
    try:
        yield
    finally:
        current_group_id.reset(token)


@contextmanager
def use_all_groups(*, reason: str) -> Iterator[None]:
    """Leve le cloisonnement de tenance pour la duree du bloc, en le disant.

    L'ECHAPPATOIRE EST UN GESTE, PAS UN ETAT
    Rien ne pose ce mode par defaut, et aucun oubli ne peut y mener : il faut
    ecrire l'appel ET sa raison. C'est le pendant de `CacheScope.SHARED`
    (BACK-14) : le hors-norme se declare, il ne s'omet pas. Les usages
    legitimes sont rares et nommes -- CLI superadmin, jeu de donnees de
    demonstration (INFRA-08), endpoints d'administration (BACK-25).

    LIRE PARTOUT N'EST PAS ECRIRE PARTOUT
    Sous ce mode, les lectures tenant voient tous les groupes, mais tout geste
    qui exige UN groupe -- estampiller une insertion, composer une cle de cache
    tenant -- continue d'echouer. Ecrire dans un groupe donne se fait par un
    bloc `use_group(group_id)` imbrique : c'est le patron du seed (INFRA-08),
    qui lit partout et ecrit groupe par groupe.

    Args:
        reason: ce qui justifie de voir tous les groupes, en toutes lettres.
            Reprise dans les messages d'erreur du bloc.

    Yields:
        Rien : le bloc s'execute, le contexte est restaure a sa sortie.

    Raises:
        ValueError: si la raison est vide ou blanche.
    """
    if not reason.strip():
        message = (
            "Le mode « tous groupes » exige une raison en toutes lettres : "
            "c'est elle qui rend l'echappatoire visible en revue."
        )
        raise ValueError(message)
    token = current_group_id.set(AllGroups(reason=reason))
    try:
        yield
    finally:
        current_group_id.reset(token)
