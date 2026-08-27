"""Couche exterieure du noyau partage : les details techniques, remplacables.

Ce qui vit ici DEPEND du domaine et jamais l'inverse. Trois sous-paquets :

- `db/` -- socle de persistance : la `Base` declarative et sa convention de
  nommage, le moteur, la fabrique de sessions et les mixins (BACK-05), le depot
  generique et l'unite de travail (BACK-06a), le filtre de tenance
  (BACK-06b) ;
- `api/` -- socle HTTP : sondes de sante et routeur racine v1 (BACK-08),
  handlers d'erreur (BACK-09), intergiciels, CORS et identifiant de requete
  (BACK-11) ;
- `clients/` -- adaptateurs des ports techniques vers les services externes : le
  cache Redis (BACK-14) et le stockage objet S3 (BACK-13), chacun avec sa
  convention de nommage de cles ;
- `memory/` -- doublures en memoire des memes ports (BACK-06c) : unite de
  travail, depots, cache, stockage, transport de courriel, controle de fuite.
  Elles ne sont pas rangees sous `tests/`, et l'ADR-0023 dit pourquoi ;
- `security/` -- ce qui signe et verifie (BACK-10a) : l'adaptateur PyJWT du port
  `TokenService`. Distinct de `clients/` parce qu'il ne parle a aucun service
  externe -- il calcule, et n'a donc ni ressource a ouvrir au demarrage ni
  ressource a refermer a l'arret.

Plus `tenancy.py`, qui porte la contextvar du groupe actif. Elle est ici et non
sous `db/` -- ou BACK-04 l'annoncait -- parce que le cache l'a rejointe : deux
lecteurs, aucune raison que l'un importe le socle de l'autre.

L'adaptateur restant rejoindra `audit/` (BACK-27).
"""
