"""Convention de pagination des listes -- parametres, enveloppe, bornes (BACK-24).

Le vocabulaire que TOUTE liste du service partage : une requete de page
(`PageRequest`), un resultat de page (`PageResult`), un tri nomme (`Sort`).
Le protocole generique des depots (BACK-06a) l'exprime, le depot SQLAlchemy
l'applique, et l'adaptateur HTTP (`shared/infrastructure/api/pagination.py`) le
traduit en parametres de requete et en enveloppe de reponse. La convention
raisonne sur le vocabulaire commun, jamais sur un depot particulier -- comme le
filtre de tenance (BACK-06b) avant elle.

OFFSET, ET C'EST UN CHOIX ECRIT (ADR-0017)
La pagination est par decalage -- `page`, `page_size` -- et non par curseur :
les ecrans d'administration veulent « page 7 » et un total, ce qu'un curseur ne
sait pas donner. Le flux a fort volume qui exigerait un curseur fera l'objet
d'une decision dediee le jour ou il existera -- les deux formes ne se melangent
pas sans motif.

REFUSER, JAMAIS TRONQUER
Un `page_size` hors bornes est REFUSE a la construction de `PageRequest`,
jamais ramene en douce au maximum : un client qui demande 10 000 lignes et en
recoit 100 sans le savoir produit des pages incompletes sans erreur. La borne
vit ici, en une seule constante, pour que la bordure HTTP et les chemins qui ne
la traversent pas (cas d'usage, taches de fond) refusent d'une seule voix.

LE TRI EST UN NOM PUBLIC, JAMAIS UNE COLONNE
`Sort.field` porte le nom expose par l'API, pas un nom de colonne : la
correspondance nom -> colonne appartient au depot concret, qui la declare en
liste blanche (`_sortable`). Rien de ce que le client envoie n'approche donc le
SQL, et la doublure en memoire (BACK-06c) saura trier par nom d'attribut sans
rien connaitre de SQLAlchemy.

Comme tout le domaine, ce module ne s'appuie que sur la bibliotheque standard
(contrat `domain-purity`) : l'enveloppe Pydantic exposee par l'API vit cote
adaptateur, dans `shared/infrastructure/api/pagination.py`.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Final

from app.shared.domain.exceptions import ValidationError

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "InvalidPageRequestError",
    "PageRequest",
    "PageResult",
    "Sort",
    "SortDirection",
    "UnknownSortFieldError",
]

DEFAULT_PAGE_SIZE: Final = 20
MAX_PAGE_SIZE: Final = 100

# Borne de l'offset : OFFSET est un int8 chez PostgreSQL, et asyncpg refuse
# d'encoder au-dela. Sans cette garde, une page astronomique sortirait en 500
# technique au lieu du refus explicite que la convention promet.
_MAX_OFFSET: Final = 2**63 - 1


class InvalidPageRequestError(ValidationError):
    """Parametres de page hors bornes -- refuses, jamais tronques.

    A la bordure HTTP, les contraintes des parametres de requete refusent avant
    meme la construction ; cette erreur couvre les chemins qui ne passent pas
    par la bordure, pour que la borne tienne partout.
    """

    code: ClassVar[str] = "shared.pagination.invalid"


class UnknownSortFieldError(ValidationError):
    """Champ de tri absent de la liste blanche de la ressource.

    Levee a la bordure HTTP par la dependance de tri, et par le depot en
    defense en profondeur : un nom hors liste n'atteint jamais une requete.
    """

    code: ClassVar[str] = "shared.pagination.unknown_sort"


class SortDirection(Enum):
    """Sens d'un tri : croissant ou decroissant."""

    ASC = "asc"
    DESC = "desc"


@dataclass(frozen=True, slots=True, kw_only=True)
class Sort:
    """Tri demande : un nom PUBLIC de champ et un sens.

    `field` est le nom que l'API expose, jamais un nom de colonne -- la
    correspondance vers la persistance appartient au depot concret, qui refuse
    tout nom hors de sa liste blanche.
    """

    field: str
    direction: SortDirection = SortDirection.ASC


@dataclass(frozen=True, slots=True, kw_only=True)
class PageRequest:
    """Requete de page : quelle fenetre de la liste, dans quel ordre.

    Les defauts vivent ICI et nulle part ailleurs : le protocole des depots
    n'a pas de valeur par defaut a repeter, et la bordure HTTP importe les
    memes constantes -- une seule source pour une seule borne.
    """

    page: int = 1
    page_size: int = DEFAULT_PAGE_SIZE
    sort: Sort | None = None

    def __post_init__(self) -> None:
        """Refuse toute borne violee -- une requete invalide est irrepresentable.

        Raises:
            InvalidPageRequestError: si `page` ou `page_size` sort des bornes.
        """
        if self.page < 1:
            raise InvalidPageRequestError(
                f"La page demandee doit valoir au moins 1, pas {self.page}.",
                details={"page": self.page},
            )
        if self.page_size < 1 or self.page_size > MAX_PAGE_SIZE:
            raise InvalidPageRequestError(
                f"La taille de page doit tenir entre 1 et {MAX_PAGE_SIZE}, pas {self.page_size}.",
                details={"page_size": self.page_size, "max_page_size": MAX_PAGE_SIZE},
            )
        if self.offset > _MAX_OFFSET:
            raise InvalidPageRequestError(
                "La page demandee est hors de portee : le decalage depasse ce que "
                "la persistance sait adresser.",
                details={"page": self.page, "page_size": self.page_size},
            )

    @property
    def offset(self) -> int:
        """Decalage de la fenetre : nombre de lignes a sauter avant la page."""
        return (self.page - 1) * self.page_size


@dataclass(frozen=True, slots=True, kw_only=True)
class PageResult[ItemT]:
    """Une page de resultats et son compte total -- jamais une liste nue.

    `total` compte les elements du PERIMETRE COURANT -- filtre de tenance
    compris : un depot tenant compte le groupe actif, jamais la table. Une page
    au-dela de la fin est une page vide portant le total reel, pas une absence :
    une page est une fenetre, pas une ressource.

    L'enveloppe HTTP `{ items, total, page, page_size }` reprend ces champs un
    pour un ; `page` et `page_size` sont rappeles ici pour que la mise en forme
    n'ait pas a transporter la requete a cote du resultat.
    """

    items: Sequence[ItemT]
    total: int
    page: int
    page_size: int
