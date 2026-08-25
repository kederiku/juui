"""Schemas Pydantic transverses de l'adaptateur HTTP (BACK-09).

Les corps de reponse qui n'appartiennent a aucun module : aujourd'hui le seul
occupant est `error.py`, le format d'erreur unique du service. Les schemas
METIER, eux, vivent chez leur module (`modules/<nom>/infrastructure/api/`).

Pydantic a sa place ici -- ce paquet est dans `infrastructure` -- alors que le
contrat `domain-purity` (BACK-04b) l'interdit dans `shared/domain` : c'est
exactement pourquoi la hierarchie d'erreurs et son format de sortie vivent
dans deux fichiers separes.

Pas de re-export : chaque schema s'importe depuis son module, comme partout
dans le depot.
"""
