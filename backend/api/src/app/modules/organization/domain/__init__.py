"""Couche domaine du module organization (BACK-16).

Entites, regles pures, refus metier et ports : tout ce qui se teste sans
Docker. Aucun import de FastAPI, SQLAlchemy ou Pydantic n'entre ici -- le
contrat `domain-purity` de BACK-04b le verifie a chaque `make lint`.
"""
