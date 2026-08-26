"""Cas d'usage du module notifications -- un fichier par intention.

UN FICHIER PAR CAS D'USAGE, et non un « service » qui les rassemblerait tous : la
liste des fichiers de ce dossier est la liste de ce que le module sait faire.

`deliver_notification.py` est le seul a ce stade, et c'est lui qui porte la regle
du ticket : lire les preferences, en deduire les canaux, rendre le message, le
remettre, journaliser.

CE QUE LES TICKETS SUIVANTS AJOUTERONT ICI
La lecture et la mise a jour des preferences depuis l'espace personnel, quand
BACK-10c aura livre la dependance d'authentification et BACK-23 la surface de
composition. Les faire naitre sans elles obligerait a prendre l'identifiant de
compte dans une URL, ce que BACK-17 a deja refuse comme oracle d'existence.
"""
