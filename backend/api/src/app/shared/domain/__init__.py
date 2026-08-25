"""Couche interieure du noyau partage : ce que le metier connait de commun.

Deux choses y vivent, et rien d'autre :

- `exceptions` -- la racine `DomainError`, ses categories intermediaires
  (`NotFoundError`, `AlreadyExistsError`, `ConflictError`, `ValidationError`,
  `PermissionDeniedError`) et les codes namespaces dont heritent les erreurs
  metier de tous les modules (BACK-09) ;
- `ports` -- les contrats techniques que les modules expriment et que
  l'infrastructure remplit.

Comme tout `domain/` du projet, ce paquet n'importe ni fastapi, ni sqlalchemy,
ni pydantic. La verification est mecanisee par les contrats import-linter de
BACK-04b.
"""
