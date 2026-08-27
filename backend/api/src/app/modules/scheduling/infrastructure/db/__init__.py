"""Persistance du module scheduling -- interne, et strictement interne.

Aucun autre module n'importe ce qui se trouve ici. Un `JOIN` depuis un autre
contexte sur `practitioner_profiles`, `practitioner_hours` ou
`practitioner_species` serait une dependance invisible, que rien ne signalerait
le jour ou scheduling change son schema. Les echanges passent par les deux
lectures publiques du module.
"""
