"""Paquet racine du service d'API Juui.

Trois espaces s'y partagent le code, et la distinction compte :

- `core/`    -- reglages du PROCESSUS : configuration (BACK-03), puis
               journalisation (BACK-11). Ni domaine, ni infrastructure.
- `shared/`  -- noyau partage par les modules metier : racine des erreurs, ports
               techniques, socles de persistance et d'API.
- `modules/` -- les contextes metier, etanches les uns aux autres, chacun
               portant ses trois couches hexagonales.

Plus `main.py`, seul fichier autorise a connaitre plusieurs modules a la fois :
c'est lui qui assemble leurs routeurs.

CE DECOUPAGE EST UN CONTRAT, PAS UNE INTENTION. Le sens des dependances entre
ces quatre espaces -- `main` au-dessus de `modules`, au-dessus de `shared`,
au-dessus de `core` -- est verifie par le contrat `service-spaces` de BACK-04b
(pyproject.toml, section [tool.importlinter]). Il est declare `exhaustive` : un
cinquieme espace ajoute ici fait echouer `make lint` tant que sa place dans la
hierarchie n'est pas ecrite.
"""
