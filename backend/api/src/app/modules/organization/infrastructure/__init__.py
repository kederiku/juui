"""Couche exterieure du module organization : les details remplacables.

Elle DEPEND du domaine, jamais l'inverse. Un seul adaptateur y vit pour
l'instant : `db/` -- les quatre tables du module et les depots qui traduisent
leurs lignes en entites. Les routes arriveront avec BACK-25.

Rien de ce qui est ici n'a le droit d'entrer dans `domain/` ou `application/` :
c'est la seule direction que l'architecture hexagonale interdit, et celle que
les contrats import-linter de BACK-04b verifient.
"""
