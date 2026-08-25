"""Regles metier pures du module organization (BACK-16).

Meme doctrine que chez identity : une politique est une regle qui ne tient
DANS AUCUNE ENTITE en particulier -- elle s'exprime sur des valeurs, se teste
sans rien construire, et se reutilise d'un cas d'usage a l'autre. Ce qui n'est
vrai que d'une appartenance donnee reste dans `entities.py`, ou c'est l'entite
elle-meme qui le fait respecter.

Ce module n'importe RIEN du reste du module organization, `entities.py`
compris. C'est ce qui permet aux entites d'appeler ces regles sans creer de
cycle d'import, et ce n'est pas un hasard : une politique qui aurait besoin de
connaitre l'entite serait un comportement de l'entite.
"""

from datetime import datetime


def is_window_active(start_at: datetime, end_at: datetime | None, at: datetime) -> bool:
    """Dit si la fenetre `[start_at, end_at)` couvre l'instant donne.

    L'intervalle est DEMI-OUVERT : la borne de debut est incluse, la borne de
    fin exclue. C'est ce qui rend deux periodes raccordees -- l'une finissant
    quand l'autre commence -- exemptes de tout instant partage : a la borne, la
    seconde a deja pris le relais.

    Args:
        start_at: le debut de la fenetre, inclus.
        end_at: la fin de la fenetre, exclue -- None pour une fenetre ouverte,
            sans terme connu.
        at: l'instant interroge.

    Returns:
        Vrai si l'instant tombe dans la fenetre.
    """
    return start_at <= at and (end_at is None or at < end_at)
