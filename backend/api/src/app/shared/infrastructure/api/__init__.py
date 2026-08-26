"""Socle HTTP partage : ce que toute route recoit sans avoir a le demander.

Paquet cree par BACK-04 pour fixer la place de ces briques -- au NIVEAU DU
NOYAU et non dans un module : un handler d'erreur ou un identifiant de requete
qui vivraient dans `identity` obligeraient tous les autres modules a en
dependre. BACK-08 y pose les deux premieres briques -- les sondes de sante et
le routeur racine versionne --, BACK-09 la traduction des erreurs et BACK-11
les intergiciels que toute requete traverse.

CE QUE CHAQUE TICKET APPORTE ICI

| Fichier                    | Contenu                                        | Ticket  |
| -------------------------- | ---------------------------------------------- | ------- |
| `health.py`                | sondes `/health/live` et `/health/ready`       | BACK-08 |
| `router.py`                | routeur racine `/api/v1`, assemble par `app.main` | BACK-08 |
| `error_handlers.py`        | traduction `DomainError` -> reponse HTTP       | BACK-09 |
| `schemas/error.py`         | format unique { code, message, details, ... }  | BACK-09 |
| `pagination.py`            | parametres page/page_size/sort, enveloppe Page | BACK-24 |
| `middlewares.py`           | CORS, journal d'acces, identifiant de requete  | BACK-11 |
| `dependencies/audit.py`    | tracage des acces aux donnees personnelles     | BACK-27 |

Le contexte de tenance, lui, est pose par la dependance d'authentification
(BACK-10c) dans la contextvar de `tenancy.py` : le filtre de BACK-06b le lit
cote persistance, pas ici.
"""
