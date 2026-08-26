"""Horloge injectable des doublures (BACK-06c).

Tester une expiration ne doit pas demander d'attendre. Le cache en memoire et le
magasin d'OTP en memoire recoivent donc leur horloge plutot que d'appeler
`time.monotonic()` de l'interieur : un test avance le temps d'un appel de methode
au lieu de dormir dix minutes.

POURQUOI `monotonic` ET NON `time()` PAR DEFAUT
Une duree de vie se compte en temps ECOULE. `time.time()` suit l'horloge murale,
que NTP peut reculer -- une entree de cache y deviendrait valide a nouveau apres
avoir expire. `monotonic()` n'a pas cette propriete, et c'est la meme raison qui
la fait choisir partout ou une echeance se calcule.
"""

import time
from collections.abc import Callable
from typing import Final

# Ce qu'une doublure attend d'une horloge : un appel, des secondes.
#
# Un alias et non un protocole : il n'y a rien a nommer de plus qu'une fonction
# sans argument, et `time.monotonic` le satisfait tel quel.
type Clock = Callable[[], float]

# Horloge par defaut des doublures, quand le test ne veut pas piloter le temps.
DEFAULT_CLOCK: Final[Clock] = time.monotonic


class FakeClock:
    """Horloge que le test avance a la main.

    S'utilise partout ou un `Clock` est attendu -- elle est appelable. Le test
    qui veut prouver qu'un code expire au bout de dix minutes ecrit
    `clock.advance(601)`, et la suite tourne en quelques microsecondes.
    """

    def __init__(self, start: float = 1_000.0) -> None:
        """Pose l'instant initial.

        Args:
            start: l'instant de depart, en secondes. La valeur par defaut n'est
                pas zero a dessein : une doublure qui compare une echeance a
                `0.0` passerait par accident sur une horloge partant de zero.
        """
        self._now = start

    def __call__(self) -> float:
        """Rend l'instant courant, en secondes.

        Returns:
            L'instant courant.
        """
        return self._now

    def advance(self, seconds: float) -> None:
        """Avance l'horloge.

        Args:
            seconds: la duree ecoulee, en secondes.
        """
        self._now += seconds
