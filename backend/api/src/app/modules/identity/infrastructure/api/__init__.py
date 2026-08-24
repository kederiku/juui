"""Adaptateur HTTP du module identity.

Deux fichiers : les schemas Pydantic, qui valident ce qui entre et mettent en
forme ce qui sort, et le routeur, qui sera assemble par `app.main`.

C'est le SEUL endroit du module ou FastAPI et Pydantic ont le droit d'exister.
Rien de ce qui est ici ne remonte vers `application/` ni `domain/` : un cas
d'usage qui recevrait un schema Pydantic deviendrait inappelable depuis une
tache de fond.

CE QUE LES TICKETS SUIVANTS AJOUTERONT ICI
Les dependances d'authentification (BACK-10c), les routes d'inscription et de
connexion (BACK-28, BACK-29) et un `routes_admin.py` pour les endpoints
d'administration (BACK-26).
"""
