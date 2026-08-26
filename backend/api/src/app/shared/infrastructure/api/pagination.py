"""Pagination a la bordure HTTP : parametres normalises et enveloppe (BACK-24).

L'adaptateur de la convention posee par `shared/domain/pagination.py` : les
routes de liste recoivent `PageParams` (parametres `page` et `page_size`,
bornes visibles dans l'OpenAPI), un tri valide par `sort_param(...)` contre la
liste blanche de l'endpoint, et repondent par une sous-classe nommee de `Page`
-- l'enveloppe unique `{ items, total, page, page_size }`, jamais un tableau
nu : un objet s'etend sans casser le contrat, et Orval (SHARED-03) le type
proprement, la ou ajouter un `total` a un tableau apres coup casserait tous
les appelants et tout le code genere.

LE REFUS DES BORNES EST CELUI DE PYDANTIC
`page_size` au-dela du maximum sort en 422 `http.request.validation_error`
par les contraintes de champ -- validation de FORME, chemin BACK-09 -- avant
meme que `PageRequest` existe. La meme borne, importee du domaine, refuse
aussi sur les chemins qui ne passent pas par HTTP : une seule constante,
deux gardiens.

LE NOM DES COMPOSANTS OPENAPI EST UNE DECISION
`Page` est generique, mais une route qui declarerait `Page[AccountRead]` en
reponse sortirait dans l'OpenAPI sous le nom mutile `Page_AccountRead_` --
et Orval genererait ce nom-la. La convention : chaque endpoint declare sa
sous-classe nommee (`class AccountPage(Page[AccountRead])`), qui sort en
`AccountPage`, a cote d'`AccountRead`. Le test de spec de BACK-24 refuse
mecaniquement tout nom de composant hors gabarit.

LA LISTE BLANCHE DU TRI EST CELLE DE L'ENDPOINT
`sort_param("email", "last_name")` n'accepte que ces noms publics, en clair ou
prefixes de `-` ; tout autre champ sort en 422 `shared.pagination.unknown_sort`.
Le nom valide ne touche jamais le SQL : le depot du module porte sa propre
correspondance nom -> colonne et refuse a son tour -- deux listes qu'un test
de l'endpoint garde alignees (BACK-25).
"""

from collections.abc import Callable
from typing import Annotated, Self

from fastapi import Query, params
from pydantic import BaseModel, Field

from app.shared.domain.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    PageRequest,
    PageResult,
    Sort,
    SortDirection,
    UnknownSortFieldError,
)

__all__ = [
    "Page",
    "PageParams",
    "sort_param",
]


class PageParams(BaseModel):
    """Parametres de pagination de toute route de liste.

    S'utilise en dependance : `params: Annotated[PageParams, Depends()]` --
    FastAPI l'aplatit en deux parametres de query, bornes et defauts visibles
    dans l'OpenAPI. PAS la forme `Query()` des modeles de query : sur cette
    version de FastAPI elle sort dans le spec un unique parametre `params` en
    `$ref`, objet que le client genere enverrait imbrique quand le serveur
    attend `?page=&page_size=` -- verifie par le test de spec des bornes. Le
    `le=` du champ `page_size` EST le refus explicite du ticket : Pydantic
    rejette en 422, jamais ne tronque.

    PAS de `extra="forbid"` ici, et c'est voulu : sur un modele de QUERY, la
    consigne rejetterait toute cle de query etrangere au modele -- donc les
    parametres voisins de la meme route (`sort`, `search`, filtres nommes).
    La regle du depot vise les corps de requete.
    """

    page: int = Field(default=1, ge=1, description="Numero de page, a partir de 1.")
    page_size: int = Field(
        default=DEFAULT_PAGE_SIZE,
        ge=1,
        le=MAX_PAGE_SIZE,
        description=f"Taille de page, entre 1 et {MAX_PAGE_SIZE}.",
    )

    def to_page_request(self, *, sort: Sort | None = None) -> PageRequest:
        """Traduit les parametres HTTP en requete de page du domaine.

        Mapping a la main, comme `to_command` chez identity : un
        `PageRequest(**self.model_dump())` lierait les deux formes en douce.

        Args:
            sort: le tri deja valide par la dependance de `sort_param`.

        Returns:
            La requete de page, prete pour `Repository.list`.
        """
        return PageRequest(page=self.page, page_size=self.page_size, sort=sort)


class Page[ItemT](BaseModel):
    """Enveloppe unique des listes : { items, total, page, page_size }.

    A SOUS-CLASSER, JAMAIS A UTILISER PARAMETREE DANS UNE SIGNATURE DE ROUTE :
    `Page[AccountRead]` en annotation de reponse sort dans l'OpenAPI sous le
    nom mutile `Page_AccountRead_`, que le test de spec refuse. La forme juste,
    deux lignes chez le module : `class AccountPage(Page[AccountRead]): ...`,
    qui sort en `AccountPage`.
    """

    items: list[ItemT]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)

    @classmethod
    def from_result[EntityT](
        cls, result: PageResult[EntityT], map_item: Callable[[EntityT], ItemT]
    ) -> Self:
        """Met en forme une page d'entites du domaine pour la reponse HTTP.

        Les champs de compte sont recopies une fois pour toutes ici ; le
        mapping d'un element reste celui du module -- son `from_entity`,
        ecrit a la main.

        Args:
            result: la page rendue par le depot.
            map_item: la mise en forme d'UN element, `AccountRead.from_entity`
                typiquement.

        Returns:
            L'enveloppe prete a sortir.
        """
        return cls(
            items=[map_item(item) for item in result.items],
            total=result.total,
            page=result.page,
            page_size=result.page_size,
        )


def sort_param(*allowed_fields: str) -> params.Depends:
    """Fabrique la dependance de tri d'un endpoint, sa liste blanche a l'appui.

    S'utilise en metadonnee d'annotation :
    `sort: Annotated[Sort | None, sort_param("email", "last_name")]`. Un seul
    champ, `-` en prefixe pour descendre (`sort=email`, `sort=-email`) : une
    forme que TanStack Table traduit en une ligne et qu'Orval type en un
    simple champ optionnel. Le multi-champs attendra un besoin reel.

    Args:
        allowed_fields: les noms PUBLICS triables sur cet endpoint -- le
            sous-ensemble expose de la liste blanche du depot.

    Returns:
        La dependance FastAPI a poser sur le parametre `sort` de la route.
    """
    tokens = ", ".join(f"`{field}`" for field in allowed_fields)
    description = f"Champ de tri, prefixe de `-` pour l'ordre decroissant. Champs : {tokens}."

    def resolve_sort(
        sort: Annotated[str | None, Query(description=description)] = None,
    ) -> Sort | None:
        """Valide le parametre `sort` contre la liste blanche de l'endpoint.

        Raises:
            UnknownSortFieldError: si le champ n'est pas dans la liste --
                traduit en 422 par le handler de BACK-09.
        """
        if sort is None:
            return None
        field = sort.removeprefix("-")
        if field not in allowed_fields:
            raise UnknownSortFieldError(
                f"Le champ de tri « {field} » n'est pas triable sur cette ressource.",
                details={"field": field, "sortable_fields": sorted(allowed_fields)},
            )
        direction = SortDirection.DESC if sort.startswith("-") else SortDirection.ASC
        return Sort(field=field, direction=direction)

    # La classe `params.Depends` plutot que l'usine `fastapi.Depends` : cette
    # derniere est annotee `Any` pour se glisser en valeur par defaut, et un
    # `Any` en retour est refuse par mypy strict.
    return params.Depends(resolve_sort)
