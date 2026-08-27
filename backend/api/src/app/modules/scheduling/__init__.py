"""Module scheduling : « quand, avec qui, pour quel acte ».

`identity` prouve qui vous etes, `organization` dit ou vous travaillez,
`medical_records` porte le dossier de l'animal ; celui-ci porte la fiche
technique du praticien -- ses horaires d'intervention et les especes qu'il prend
en charge.

POURQUOI CETTE FICHE N'EST PAS DANS `identity`
L'ecran « mon compte » du cahier des charges l'y pousse, parce qu'il affiche
tout au meme endroit. Mais des horaires sont une DISPONIBILITE et des especes
une COMPETENCE : les deux sont consommees par la prise de rendez-vous, jamais
par l'authentification. Le formulaire est dans « mon compte » par commodite
d'IHM ; c'est une decision d'ecran, pas une decision de modele.

CE QUE BACK-21 A LIVRE ICI
L'agregat `PractitionerProfile` -- porte par le couple (compte, clinique) a
l'interieur d'un groupe, et non par le compte : un remplacant n'a pas les memes
horaires selon la structure --, l'objet-valeur `WeeklyTimeRange` qui dit une
plage d'intervention hebdomadaire en minutes d'horloge murale, le catalogue
d'especes, leur persistance en trois tables, et les DEUX lectures qui prouvent
le modele : les praticiens disponibles pour une clinique, un creneau et une
espece ; la fiche d'un compte dans une clinique.

Aucun autre module n'accede a ses tables. PAS de cas d'usage, pas de routes, pas
de moteur de rendez-vous, pas de gestion des conges et exceptions, pas de regles
de duree d'acte : la portee du ticket les exclut nommement.

DEUX HOMONYMIES A CONNAITRE, ET AUCUNE N'EST UN ACCIDENT
`Species` porte ici le meme nom et les memes valeurs que celui de
`medical_records` : le contrat `module-independence` interdit l'import, le
depot recopie plutot que de faire descendre le vocabulaire dans `shared/`
(precedent BACK-10a), et un test de non-derive tient les deux catalogues
ensemble. Et `PractitionerProfile` emploie le mot « profile » que le futur
module `profile` (BACK-32) portera aussi : celui-la parlera de l'adresse d'un
particulier, et devra nommer son agregat autrement -- ADR-0026 le dit.

SURFACE PUBLIQUE
Le port de depot et l'unite de travail, les entites et le catalogue qui forment
leur contrat, les refus metier QU'UNE OPERATION PUBLIEE PEUT LEVER, et la
dependance FastAPI que le point de composition consommera.
`PractitionerProfileNotFoundError` n'en est pas : seul le `get()` herite du depot
generique la leve, et le port ne l'expose pas -- l'exporter donnerait un nom que
personne ne peut attraper. Le re-export est EXPLICITE parce que Mypy tourne avec
`no_implicit_reexport` (implique par `strict`).
"""

from app.modules.scheduling.domain.entities import (
    PractitionerProfile,
    Species,
    WeeklyTimeRange,
    ensure_hours_disjoint,
)
from app.modules.scheduling.domain.exceptions import (
    InvalidTimeRangeError,
    OverlappingTimeRangesError,
    UnknownSpeciesError,
)
from app.modules.scheduling.domain.policies import MINUTES_PER_DAY
from app.modules.scheduling.domain.ports import (
    PractitionerProfileRepository,
    SchedulingUnitOfWork,
)
from app.modules.scheduling.unit_of_work import SchedulingUowDep, get_scheduling_uow

__all__ = [
    "MINUTES_PER_DAY",
    "InvalidTimeRangeError",
    "OverlappingTimeRangesError",
    "PractitionerProfile",
    "PractitionerProfileRepository",
    "SchedulingUnitOfWork",
    "SchedulingUowDep",
    "Species",
    "UnknownSpeciesError",
    "WeeklyTimeRange",
    "ensure_hours_disjoint",
    "get_scheduling_uow",
]
