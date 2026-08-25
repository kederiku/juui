"""Couche exterieure du noyau partage : les details techniques, remplacables.

Ce qui vit ici DEPEND du domaine et jamais l'inverse. Trois sous-paquets :

- `db/` -- socle de persistance : la `Base` declarative et sa convention de
  nommage, le moteur, la fabrique de sessions et les mixins (BACK-05) ; puis le
  depot generique et l'unite de travail (BACK-06a), et le filtre de tenance
  (BACK-06b) ;
- `api/` -- socle HTTP : handlers d'erreur (BACK-09), intergiciels, CORS et
  identifiant de requete (BACK-11) ;
- `clients/` -- adaptateurs des ports techniques vers les services externes : le
  cache Redis (BACK-14), puis le stockage objet (BACK-13).

Plus `tenancy.py`, qui porte la contextvar du groupe actif. Elle est ici et non
sous `db/` -- ou BACK-04 l'annoncait -- parce que le cache l'a rejointe : deux
lecteurs, aucune raison que l'un importe le socle de l'autre.

Les adaptateurs restants rejoindront `security/` (BACK-10a), `memory/` (BACK-06c)
et `audit/` (BACK-27).
"""
