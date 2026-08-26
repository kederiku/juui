"""Suites de conformite du module identity (BACK-06c).

MEME DISPOSITIF QUE `tests/shared/conformance/`, applique aux ports METIER.
La conformite partagee eprouve le socle -- depot generique, unite de travail,
cache, stockage. Elle ne dit rien des doublures de module, qui portent pourtant
ce qu'un socle ne peut pas porter : le finder maison d'`AccountRepository`, et
les trois quotas d'`OtpStore`.

POURQUOI CES DEUX-LA ET PAS D'AUTRES
Parce que ce sont les seules doublures de module dont la contrepartie reelle est
COMPARABLE aujourd'hui. `find_by_email` compare une adresse en base ;
`InMemoryOtpStore` est la doublure la plus dense du ticket -- TTL, compteur de
tentatives, fenetre glissante, trois plafonds -- et `RedisOtpStore` fait la meme
chose contre un vrai Redis. La regle du dispositif ne souffre pas d'exception :
un comportement qui peut se comparer aux deux implementations DOIT y etre.
"""
