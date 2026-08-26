"""Couche d'orchestration du module identity.

Elle ne contient AUCUNE regle metier -- celles-ci vivent dans `domain/` -- et
aucun detail technique : ni session, ni requete HTTP, ni client Redis. Son
travail tient en une phrase : enchainer des appels aux ports et aux entites pour
realiser un cas d'usage, et rien de plus.

C'est ce qui permet de la tester sur les doublures en memoire de BACK-06c, sans
Docker ni base de donnees.
"""
