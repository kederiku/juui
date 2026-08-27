"""Couche exterieure du module scheduling : les details remplacables.

Elle DEPEND du domaine, jamais l'inverse. Un seul adaptateur y vit : `db/` --
les trois tables du module et le depot qui traduit leurs lignes en entites. Les
routes appartiennent au ticket qui livrera l'ecran « mon compte » ; ce socle
n'en pose aucune, et `main.py` reste donc intact.

Rien de ce qui est ici n'a le droit d'entrer dans `domain/` : c'est la seule
direction que l'architecture hexagonale interdit, et celle que le contrat
`module-layers` de BACK-04b verifie.
"""
