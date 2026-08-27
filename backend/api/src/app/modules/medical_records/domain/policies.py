"""Regles metier pures du module medical_records (BACK-19).

Meme doctrine que chez identity et organization : une politique est une regle
qui ne tient DANS AUCUNE ENTITE en particulier -- elle s'exprime sur des
valeurs, se teste sans rien construire, et se reutilise d'un cas d'usage a
l'autre. Ce qui n'est vrai que d'une detention donnee reste dans
`entities.py`, ou c'est l'entite elle-meme qui le fait respecter.

Ce module n'importe RIEN du reste du module medical_records, `entities.py`
compris.

`is_window_active` est la COPIE de celle d'organization, jamais son import :
le contrat `module-independence` interdit toute dependance entre modules,
meme pour quinze lignes pures. La remontee en `shared/domain` reste due, mais
son declencheur a change : elle etait annoncee « au troisieme module date
(BACK-21) », et scheduling n'en est pas un -- sa fiche technique ne porte ni
`start_at` ni `end_at`, aucun de ses ports ne prend d'instant, et ses seules
bornes sont des minutes d'horloge murale, dont la garde est l'INVERSE
d'`ensure_aware_instant`. Le declencheur passe au moteur de rendez-vous, qui
sera le premier a manipuler de vraies fenetres datees ; l'ecart est consigne au
registre.
"""

from datetime import datetime


def is_window_active(start_at: datetime, end_at: datetime | None, at: datetime) -> bool:
    """Dit si la fenetre `[start_at, end_at)` couvre l'instant donne.

    L'intervalle est DEMI-OUVERT : la borne de debut est incluse, la borne de
    fin exclue. C'est ce qui rend deux periodes raccordees -- l'une finissant
    quand l'autre commence -- exemptes de tout instant partage : a la borne,
    la seconde a deja pris le relais. Pour deux detentions successives, aucun
    instant n'a deux detenteurs.

    Args:
        start_at: le debut de la fenetre, inclus.
        end_at: la fin de la fenetre, exclue -- None pour une fenetre ouverte,
            sans terme connu.
        at: l'instant interroge.

    Returns:
        Vrai si l'instant tombe dans la fenetre.
    """
    return start_at <= at and (end_at is None or at < end_at)
