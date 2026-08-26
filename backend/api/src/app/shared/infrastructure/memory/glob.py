r"""Motifs de cles a la maniere de Redis, pour la doublure de cache (BACK-06c).

POURQUOI PAS `fnmatch`, ET C'EST LA SUITE DE CONFORMITE QUI L'A TRANCHE
Les deux syntaxes se ressemblent -- `*`, `?`, `[...]` -- et divergent sur quatre
points, dont une INVERSION complete :

| Motif        | Redis                        | `fnmatch`                     |
| ------------ | ---------------------------- | ----------------------------- |
| `[^a]`       | nie                          | classe litterale `^` ou `a`   |
| `[!a]`       | classe litterale `!` ou `a`  | nie                           |
| `a\*b`        | `*` litteral (echappement)   | pas d'echappement             |
| `[abc`       | classe non refermee, litt.   | motif invalide, ne filtre pas |
| `?`          | UN OCTET                     | UN CARACTERE                  |

La derniere n'est pas un cas de laboratoire dans un service francophone : une
seule cle accentuee suffit a faire diverger n'importe quel motif a `?`. Les deux
premieres sont pires -- chaque syntaxe purge d'un cote et ne purge RIEN de
l'autre, donc un test vert « l'invalidation retire exactement les entrees
concernees » n'affirmerait rien.

CE MODULE EST UN PORTAGE DE `stringmatchlen()` de Redis, algorithme compris :
recursion avec retour arriere sur `*`, et comparaison OCTET par OCTET. Le prix
est une soixantaine de lignes ; ce qu'il achete est qu'une purge se comporte en
test comme en production.

`nocase` n'est PAS porte : le service n'emet aucun motif insensible a la casse,
et `SCAN MATCH` ne l'offre pas.
"""


def matches(pattern: str, key: str) -> bool:
    """Dit si une cle correspond a un motif, selon la syntaxe de Redis.

    Args:
        pattern: le motif, tel qu'il serait passe a `SCAN MATCH`.
        key: la cle physique a confronter.

    Returns:
        Vrai si Redis ferait correspondre les deux.
    """
    return _match(pattern.encode("utf-8"), key.encode("utf-8"))


def _match(pattern: bytes, string: bytes) -> bool:
    """Confronte motif et chaine en OCTETS, comme le fait Redis.

    Args:
        pattern: le motif encode.
        string: la chaine encodee.

    Returns:
        Vrai si les deux correspondent.
    """
    while pattern and string:
        head = pattern[0]
        if head == _STAR:
            # Les `*` consecutifs valent un seul, et un `*` final accepte tout.
            while len(pattern) >= 2 and pattern[1] == _STAR:
                pattern = pattern[1:]
            if len(pattern) == 1:
                return True
            # Retour arriere : on essaie chaque point de coupe possible.
            return any(_match(pattern[1:], string[index:]) for index in range(len(string) + 1))
        if head == _QUESTION:
            string = string[1:]
        elif head == _OPEN_BRACKET:
            pattern, matched = _match_class(pattern, string[0])
            if not matched:
                return False
            string = string[1:]
        else:
            if head == _BACKSLASH and len(pattern) >= 2:
                pattern = pattern[1:]
            if pattern[0] != string[0]:
                return False
            string = string[1:]
        pattern = pattern[1:]
        if not string:
            break
    # Une chaine epuisee laisse passer les `*` restants du motif -- y compris
    # quand elle etait VIDE des le depart, cas que la boucle ci-dessus n'atteint
    # jamais. Verifie contre Redis 8.1, dont le moteur de motifs iteratif fait
    # correspondre `*` a la chaine vide.
    while pattern and pattern[0] == _STAR:
        pattern = pattern[1:]
    return not pattern and not string


def _match_class(pattern: bytes, char: int) -> tuple[bytes, bool]:
    """Consomme une classe `[...]` et dit si l'octet courant lui appartient.

    Une classe NON REFERMEE est consommee jusqu'a la fin du motif, comme chez
    Redis : elle ne rend pas le motif invalide, elle se comporte comme si le
    crochet fermant suivait.

    Args:
        pattern: le motif, positionne sur le crochet ouvrant.
        char: l'octet de la chaine a confronter.

    Returns:
        Le motif positionne sur le crochet fermant (ou sur son dernier octet),
        et le verdict.
    """
    pattern = pattern[1:]
    negated = bool(pattern) and pattern[0] == _CARET
    if negated:
        pattern = pattern[1:]
    matched = False
    while True:
        if pattern[:1] == b"\\" and len(pattern) >= 2:
            pattern = pattern[1:]
            matched = matched or pattern[0] == char
        elif not pattern:
            # Classe non refermee : on recule d'un cran pour que l'appelant
            # consomme le dernier octet lu, comme le fait Redis.
            return b"\x00", matched != negated
        elif pattern[0] == _CLOSE_BRACKET:
            break
        elif len(pattern) >= 3 and pattern[1] == _DASH:
            start, end = pattern[0], pattern[2]
            if start > end:
                start, end = end, start
            pattern = pattern[2:]
            matched = matched or start <= char <= end
        else:
            matched = matched or pattern[0] == char
        pattern = pattern[1:]
    return pattern, matched != negated


_STAR = ord("*")
_QUESTION = ord("?")
_OPEN_BRACKET = ord("[")
_CLOSE_BRACKET = ord("]")
_BACKSLASH = ord("\\")
_CARET = ord("^")
_DASH = ord("-")
