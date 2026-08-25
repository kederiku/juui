"""Depots generiques du socle de persistance (BACK-06a).

Un seul fichier aujourd'hui : `base.py`, le depot generique dont les depots
concrets des modules heritent. C'est aussi ici que BACK-06b appliquera le
filtre de tenance, aux seuls agregats declarant `TenantMixin` -- raison d'etre
du sous-paquet : le filtre aura sa place a cote de la classe qu'il complete.
"""
