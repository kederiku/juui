"""Persistance du module organization -- interne, et strictement interne.

Aucun autre module n'importe ce qui se trouve ici. Un `JOIN` depuis un autre
contexte sur `groups`, `clinics`, `memberships` ou `assignments` serait une
dependance invisible, que rien ne signalerait le jour ou organization change
son schema. Les echanges passent par les trois requetes publiques du module.
"""
