"""Couche exterieure du noyau partage : les details techniques, remplacables.

Ce qui vit ici DEPEND du domaine et jamais l'inverse. Deux sous-paquets :

- `db/` -- socle de persistance : la `Base` declarative, puis le moteur, la
  session, les mixins (BACK-05), le depot generique et l'unite de travail
  (BACK-06a), le contexte de tenance (BACK-06b) ;
- `api/` -- socle HTTP : handlers d'erreur (BACK-09), intergiciels, CORS et
  identifiant de requete (BACK-11).

Les adaptateurs des ports techniques les rejoindront dans `clients/` (BACK-13 et
BACK-14), `security/` (BACK-10a), `memory/` (BACK-06c) et `audit/` (BACK-27).
"""
