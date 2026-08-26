"""Doublure en memoire du port `BreachChecker` (BACK-06c).

Aucun test ne doit appeler le vrai service de fuites : c'est une dependance
reseau, elle est lente, elle est hors du controle du projet, et l'interroger
depuis une suite de tests reviendrait a lui envoyer des mots de passe de test en
continu. Cette doublure repond a partir d'une liste que le test fournit.

ELLE SAIT AUSSI ETRE MUETTE, ET C'EST SON USAGE LE PLUS UTILE. La regle du port
-- une indisponibilite ACCEPTE le mot de passe -- est exactement le genre de
regle qu'on ecrit une fois et qui cesse de s'appliquer sans que personne s'en
apercoive. `unavailable=True` la rend testable : l'inscription doit aboutir, et
un avertissement doit avoir ete journalise.
"""

import logging
from collections.abc import Iterable
from typing import Final

from app.shared.domain.ports.breach_checker import BreachChecker

_LOGGER: Final = logging.getLogger(__name__)


class FakeBreachChecker(BreachChecker):
    """Verificateur adosse a une liste de mots de passe reputes fuites."""

    def __init__(self, breached: Iterable[str] = (), *, unavailable: bool = False) -> None:
        """Construit le verificateur avec ce que le test veut lui faire dire.

        Args:
            breached: les mots de passe que la doublure declarera fuites. La
                comparaison est faite sur la chaine EXACTE : le port ne promet
                aucune normalisation, et un mot de passe ne se normalise pas.
            unavailable: si vrai, la doublure se comporte comme un service
                injoignable -- elle accepte tout, en le journalisant.
        """
        self._breached = frozenset(breached)
        self.unavailable = unavailable
        self.calls = 0
        """Nombre d'appels recus. Il permet a un test d'assurer que la
        verification a bien EU LIEU : un port qui n'est jamais appele passe tous
        les tests permissifs."""

    async def is_breached(self, password: str) -> bool:
        """Dit si ce mot de passe est dans la liste. Voir le port pour le contrat."""
        self.calls += 1
        if self.unavailable:
            _LOGGER.warning("Controle de fuite simule indisponible : le mot de passe est accepte.")
            return False
        return password in self._breached
