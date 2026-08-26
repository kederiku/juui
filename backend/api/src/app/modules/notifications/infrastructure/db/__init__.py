"""Persistance du module notifications -- interne, et strictement interne.

Aucun autre module n'importe ce qui se trouve ici. Un `JOIN` depuis un autre
contexte sur `notification_preferences` serait une dependance invisible, que rien
ne signalerait le jour ou notifications change son schema. Les echanges passent
par les ports publics du module -- et pour l'ecrasante majorite d'entre eux, par
le seul `NotificationDispatcher` : un emetteur emet un evenement, il ne lit
jamais les preferences de quelqu'un.
"""
