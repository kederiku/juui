"""Persistance du module medical_records -- interne, et strictement interne.

Aucun autre module n'importe ce qui se trouve ici. Un `JOIN` depuis un autre
contexte sur `animals` ou `custodies` serait une dependance invisible, que
rien ne signalerait le jour ou medical_records change son schema. Les
echanges passent par les ports publics du module -- le compteur d'animaux de
l'administration (BACK-26) consommera le cas d'usage public de BACK-30,
jamais ces tables.
"""
