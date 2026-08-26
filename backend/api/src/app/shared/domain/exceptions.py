"""Hierarchie des erreurs metier et codes namespaces (BACK-04, BACK-09).

Le domaine leve des exceptions METIER, jamais des erreurs de protocole. Une
`HTTPException` levee depuis une entite ou un cas d'usage lierait le coeur du
service a FastAPI, et rendrait le meme code inutilisable depuis une tache de
fond ou une commande en ligne -- ou personne n'attend de code HTTP.

La traduction en reponse HTTP appartient a un seul endroit, l'adaptateur d'API :
`shared/infrastructure/api/error_handlers.py` (BACK-09). C'est lui qui connait
la correspondance entre chaque categorie et son statut :

| Categorie               | Statut HTTP |
| ----------------------- | ----------- |
| `NotFoundError`         | 404         |
| `AlreadyExistsError`    | 409         |
| `ConflictError`         | 409         |
| `ValidationError`       | 422         |
| `PermissionDeniedError` | 403         |
| `TooManyRequestsError`  | 429         |
| `DomainError` non typee | 400         |

LES CODES SE LISENT EN PRODUCTION SANS OUVRIR LE CODE
Chaque classe porte un code namespace `<module>.<ressource>.<erreur>` --
`identity.account.not_found`, `shared.file.too_large`. Le code identifie la
CLASSE de refus, pas l'occurrence : il se pose en attribut de classe, jamais a
la construction, pour rester stable et greppable. Une classe de module le
surcharge par simple reaffectation (`code = "identity.account.not_found"`).

CE MODULE RESTE PUR
Le contrat `domain-purity` (import-linter, BACK-04b) interdit au domaine tout
import de FastAPI, Pydantic ou SQLAlchemy, meme indirect : la hierarchie ne
s'appuie que sur la bibliotheque standard. Le schema Pydantic du corps de
reponse vit cote adaptateur, dans `shared/infrastructure/api/schemas/error.py`.

COLLISION DE NOM AVEC PYDANTIC
`ValidationError` ne masque aucun builtin, mais Pydantic exporte le meme nom.
La convention du depot : dans un fichier qui a besoin des deux, c'est PYDANTIC
qui prend l'alias (`from pydantic import ValidationError as
PydanticValidationError`) -- la classe du domaine garde son nom nu partout.
"""

from collections.abc import Mapping
from typing import ClassVar

__all__ = [
    "AlreadyExistsError",
    "ConflictError",
    "DomainError",
    "NotFoundError",
    "PermissionDeniedError",
    "TooManyRequestsError",
    "ValidationError",
]


class DomainError(Exception):
    """Erreur metier : une regle du domaine n'est pas respectee.

    Classe de base de TOUTES les erreurs metier du service, celles des modules
    comprises. C'est elle que l'adaptateur d'API sait traduire ; une exception
    qui ne descend pas d'ici remontera en 500, ce qui est le comportement
    attendu pour un defaut technique, pas pour un refus metier.

    Une erreur levee sans categorie intermediaire sort en 400 : c'est un signal
    de revue -- toute erreur concrete devrait choisir sa categorie.
    """

    code: ClassVar[str] = "shared.domain.error"

    def __init__(self, message: str, *, details: Mapping[str, object] | None = None) -> None:
        """Construit l'erreur avec son message, et d'eventuels details.

        Args:
            message: la phrase destinee a l'appelant -- elle sort telle quelle
                dans le corps de la reponse HTTP, ne rien y mettre d'interne.
            details: complement structure et serialisable en JSON, copie a la
                construction pour couper tout aliasing. La plupart des erreurs
                n'en portent pas.
        """
        super().__init__(message)
        self.message = message
        self.details: dict[str, object] | None = dict(details) if details is not None else None


class NotFoundError(DomainError):
    """La ressource demandee n'existe pas -- ou n'existe pas POUR CE GROUPE.

    Traduite en 404. C'est la categorie qui porte la regle de non-divulgation
    (BACK-06b, ADR-0013) : une ressource d'un autre groupe leve exactement la
    meme erreur qu'une ressource inexistante, jamais un refus d'acces -- un 403
    confirmerait l'existence de la ressource chez un concurrent.
    """

    code: ClassVar[str] = "shared.resource.not_found"


class AlreadyExistsError(DomainError):
    """Une ressource identique existe deja : l'unicite serait violee.

    Traduite en 409. A ne PAS laisser sortir telle quelle sur un parcours ou
    l'existence est une information sensible -- l'inscription repond la meme
    chose que l'adresse soit libre ou prise (regle posee chez `identity`).
    """

    code: ClassVar[str] = "shared.resource.already_exists"


class ConflictError(DomainError):
    """L'operation est incompatible avec l'etat courant de la ressource.

    Traduite en 409, comme `AlreadyExistsError` -- mais volontairement soeur et
    non parente : un `except ConflictError` ne doit pas attraper des violations
    d'unicite a l'insu du lecteur.
    """

    code: ClassVar[str] = "shared.resource.conflict"


class ValidationError(DomainError):
    """Une valeur fournie ne respecte pas une regle du domaine.

    Traduite en 422. A distinguer de la validation de FORME des corps de
    requete, que Pydantic assure avant meme d'atteindre le domaine : ici, c'est
    une regle METIER qui refuse la valeur (mot de passe hors politique, type de
    fichier interdit...).
    """

    code: ClassVar[str] = "shared.resource.invalid"


class PermissionDeniedError(DomainError):
    """L'appelant est identifie mais n'a pas le droit de faire cela.

    Traduite en 403. Reservee aux refus de DROIT sur une ressource que
    l'appelant a le droit de savoir exister -- pour une ressource d'un autre
    groupe, c'est `NotFoundError` qui s'impose (non-divulgation).
    """

    code: ClassVar[str] = "shared.resource.forbidden"


class TooManyRequestsError(DomainError):
    """L'appelant a demande trop souvent : un quota de cadence est atteint.

    Traduite en 429, statut que BACK-09 n'avait pas eu a poser -- aucun parcours
    livre jusqu'ici n'etait limite en cadence. BACK-17 en apporte le premier :
    les renvois de code de verification sont plafonnes par adresse et par IP,
    faute de quoi le formulaire de renvoi devient un outil de harcelement par
    courriel, aux frais du service.

    A DISTINGUER DE `ConflictError`, qui serait le refuge facile : un 409 dit
    « l'etat de la ressource s'y oppose », alors qu'ici l'etat est bon et c'est le
    RYTHME qui ne l'est pas. Le client n'en tire pas la meme conduite -- sur 429
    il reessaie plus tard, sur 409 il abandonne.

    `retry_after_seconds` PORTE LA SEULE INFORMATION UTILE AU CLIENT : dans combien
    de temps reessayer. L'adaptateur d'API en fait un en-tete `Retry-After`, que
    les clients HTTP et les navigateurs savent lire. Il reste facultatif -- un
    quota sur fenetre glissante ne sait pas toujours dire quand il rouvrira.
    """

    code: ClassVar[str] = "shared.request.too_many"

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        """Construit le refus, avec le delai avant nouvelle tentative s'il est connu.

        Args:
            message: la phrase destinee a l'appelant. NE JAMAIS y faire figurer le
                compteur restant : ce serait dire a un attaquant combien d'essais
                il lui reste avant de changer d'adresse IP.
            details: complement structure et serialisable en JSON.
            retry_after_seconds: delai en secondes avant que l'appel redevienne
                possible. `None` quand le quota ne sait pas le dire.
        """
        super().__init__(message, details=details)
        self.retry_after_seconds = retry_after_seconds
