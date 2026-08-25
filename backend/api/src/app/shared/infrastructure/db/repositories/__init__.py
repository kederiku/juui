"""Depots generiques du socle de persistance (BACK-06a, BACK-06b).

Deux fichiers : `base.py`, le depot generique dont tous les depots concrets
heritent, et `tenant.py`, sa variante filtree par groupe pour les agregats
declarant `TenantMixin` -- la promesse de BACK-06b, tenue a cote de la classe
qu'elle complete. La convention qui lie les deux : toute requete SELECT d'un
depot commence par `self._select()`, jamais par un `select(...)` importe --
c'est ce qui etend le filtre aux requetes ecrites a la main. L'echappatoire
« tous groupes » vit au-dessus de `db/`, dans `tenancy.py` (`use_all_groups`).

Pas de re-export : les modules importent `repositories.base` ou
`repositories.tenant` directement, comme identity le fait depuis BACK-06a.
"""
