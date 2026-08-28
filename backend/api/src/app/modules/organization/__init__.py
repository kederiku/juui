"""Module organization : « dans quelle structure travailles-tu, et affecte ou ».

`identity` repond a « peux-tu prouver qui tu es » ; celui-ci repond a l'autre
question. Deux questions distinctes, donc deux modules -- les fondre
reviendrait a coller au compte un `group_id` immuable, ce qu'un veterinaire
remplacant intervenant dans plusieurs groupes contredit des le premier jour.

CE QUE BACK-16 A LIVRE ICI
Les entites `Group` (LE tenant, frontiere d'isolation, ADR-0004), `Clinic`
(perimetre de travail, pas frontiere de securite), `Membership` et
`Assignment` (deux relations N:M DATEES, ADR-0005), leur persistance, et les
REQUETES DE L'AUTHENTIFICATION qui sont sa seule surface publique :

1. les appartenances actives d'un compte -- l'emission du jeton (BACK-10a) ;
2. le role d'un compte dans un groupe donne ;
3. les affectations d'un compte dans le groupe actif -- `require_role`
   scope="clinic" (BACK-10c) ;
4. le groupe proprietaire d'une clinique -- `get_active_clinic` (BACK-10c),
   ajoutee par la bordure et NON tenant, pour que sa verification soit
   independante de celle des affectations.

Aucun autre module n'accede a ses tables. PAS de CRUD, pas de parcours
d'invitation, pas de contrat de remplacement : cas d'usage et routes
appartiennent a BACK-25.

SURFACE PUBLIQUE
Les trois ports de depot et l'unite de travail qui portent ces requetes,
les entites et les enums de roles qui forment leur contrat, et la dependance
FastAPI que le point de composition consommera. `identity` ne peut PAS
importer ce paquet (contrat `module-independence`) : le cablage de l'emission
de jeton se fera au niveau de `main`, seul espace autorise a connaitre
plusieurs modules.

Le re-export est EXPLICITE parce que Mypy tourne avec `no_implicit_reexport`
(implique par `strict`) : un simple import ne suffirait pas a rendre les noms
importables depuis `app.modules.organization`.
"""

from app.modules.organization.domain.entities import (
    Assignment,
    ClinicRole,
    GroupRole,
    Membership,
)
from app.modules.organization.domain.ports import (
    AssignmentRepository,
    ClinicRepository,
    MembershipRepository,
    OrganizationUnitOfWork,
)
from app.modules.organization.unit_of_work import OrganizationUowDep, get_organization_uow

__all__ = [
    "Assignment",
    "AssignmentRepository",
    "ClinicRepository",
    "ClinicRole",
    "GroupRole",
    "Membership",
    "MembershipRepository",
    "OrganizationUnitOfWork",
    "OrganizationUowDep",
    "get_organization_uow",
]
