"""Persistance du module identity -- interne, et strictement interne.

Aucun autre module n'importe ce qui se trouve ici. Un `JOIN` depuis un autre
contexte sur la table `accounts` serait une dependance invisible, que rien ne
signalerait le jour ou identity change son schema. Les echanges passent par les
cas d'usage publics du module.
"""
