"""Contexte de correlation : quel identifiant de requete a declenche le traitement (BACK-15).

Une tache de fond s'execute dans un autre processus que la requete HTTP qui l'a
demandee. Pour relire un incident de bout en bout -- « cet e-mail n'est jamais
parti » --, il faut pouvoir suivre l'identifiant de la requete d'origine jusque
dans les journaux du worker. « Quelle requete a demande ce traitement ? » n'est
pas une propriete du code appele mais de l'appel : une `ContextVar`, comme le
groupe actif de `tenancy.py`.

POURQUOI CE FICHIER EXISTE DEJA, ALORS QU'IL APPARTIENT A BACK-11
BACK-15 doit propager l'identifiant de requete vers le worker, et rien ne le
portait. La surface livree ici est volontairement reduite a deux choses : lire,
et poser le temps d'un bloc. BACK-11 y branchera l'intergiciel HTTP qui pose
l'identifiant a l'entree de chaque requete, et le filtre de journalisation qui
l'ecrit dans chaque ligne. Meme precedent que `tenancy.py`, livre par BACK-14
en anticipation de BACK-06b.

POURQUOI DANS `core/` ET NON DANS `shared/`
Le futur `core/logging.py` (BACK-11) lira cette contextvar pour enrichir chaque
ligne de journal, et le contrat `service-spaces` interdit a `core` d'importer
`shared`. Les intergiciels -- HTTP (BACK-11) comme TaskIQ (BACK-15) -- vivent
en `shared/infrastructure/` et peuvent importer `core` : la fleche pointe dans
le bon sens.

UNE `str` OPAQUE, PAS UN `UUID`
L'identifiant de requete est un jeton de correlation, pas une cle metier : il se
compare, il ne se decompose pas. Le typer `UUID` imposerait un format a BACK-11
sans aucun gain -- et les labels TaskIQ qui le transportent sont des chaines.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Final

# Identifiant de la requete d'origine, ou `None` hors de tout contexte de
# correlation.
#
# `default=None` et non l'absence de defaut, pour la raison ecrite sur
# `current_group_id` : un traitement sans requete d'origine -- une sonde, un
# script -- est un etat NORMAL, pas une erreur a lever.
current_request_id: Final[ContextVar[str | None]] = ContextVar("current_request_id", default=None)


@contextmanager
def use_request_id(request_id: str | None) -> Iterator[None]:
    """Pose l'identifiant de requete pour la duree du bloc, puis remet le precedent.

    `reset(token)` et non `set(None)` en sortie : c'est ce qui rend l'imbrication
    correcte -- meme geste que `use_group` dans `tenancy.py`.

    Args:
        request_id: l'identifiant a poser, ou `None` pour executer le bloc hors
            de tout contexte de correlation.

    Yields:
        Rien : le bloc s'execute, le contexte est restaure a sa sortie.
    """
    token = current_request_id.set(request_id)
    try:
        yield
    finally:
        current_request_id.reset(token)
