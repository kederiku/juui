"""Tests de la convention de pagination (BACK-24).

Deux volets dans un meme fichier, parce qu'ils prouvent la MEME convention :

- la bordure HTTP, sans base de donnees -- application minimale, routes de
  sonde en memoire, sur le modele de `test_error_handlers.py`. C'est la que se
  verifient les refus (bornes, tri hors liste), l'enveloppe, et les tests de
  SPEC qui tiennent lieu de critere Orval tant que SHARED-03 n'est pas livre :
  les noms de composants OpenAPI doivent rester propres, sans le `Page_X_` que
  Pydantic fabrique pour un generique parametre en signature de route ;
- le depot, sur PostgreSQL -- fenetrage, determinisme des pages, tenance du
  total, sur les doublures de `tenancy_stubs.py`.

Les schemas de sonde du volet HTTP ne portent PAS le prefixe `_` : leur nom
devient le nom du composant OpenAPI, et le test des noms propres les couvre.
"""

import re
from collections.abc import Sequence
from typing import Annotated
from uuid import UUID, uuid4

import pytest
from fastapi import Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import create_app
from app.shared.domain.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    InvalidPageRequestError,
    PageRequest,
    PageResult,
    Sort,
    SortDirection,
    UnknownSortFieldError,
)
from app.shared.infrastructure.api.error_handlers import register_error_handlers
from app.shared.infrastructure.api.pagination import Page, PageParams, sort_param
from app.shared.infrastructure.tenancy import use_all_groups, use_group
from tests.support.api import asgi_client
from tests.support.tenancy_stubs import (
    PlainNoteModel,
    PlainNoteRepository,
    TenantNoteRepository,
    make_tenant_row,
)

pytestmark = pytest.mark.pagination

# Le gabarit d'un nom de composant propre : ce qu'Orval sait typer sans alias.
_CLEAN_COMPONENT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9]*$")

_NOTE_NAMES = ("alpha", "bravo", "charlie", "delta", "echo")


class NoteRead(BaseModel):
    """Element de sonde -- nom SANS prefixe `_` : il devient un composant OpenAPI."""

    name: str


class NotePage(Page[NoteRead]):
    """Enveloppe de sonde, sous-classe nommee comme la convention l'exige."""


def _build_app() -> FastAPI:
    """Construit l'application minimale : handlers enregistres, liste en memoire."""
    application = FastAPI()
    register_error_handlers(application)
    notes = [NoteRead(name=name) for name in _NOTE_NAMES]

    @application.get("/notes")
    async def list_notes(
        params: Annotated[PageParams, Depends()],
        sort: Annotated[Sort | None, sort_param("name")],
    ) -> NotePage:
        """Rejoue le patron d'un vrai endpoint : PageRequest, PageResult, from_result."""
        page = params.to_page_request(sort=sort)
        ordered = notes
        if page.sort is not None:
            ordered = sorted(
                notes,
                key=lambda note: note.name,
                reverse=page.sort.direction is SortDirection.DESC,
            )
        result = PageResult(
            items=ordered[page.offset : page.offset + page.page_size],
            total=len(ordered),
            page=page.page,
            page_size=page.page_size,
        )
        return NotePage.from_result(result, lambda note: note)

    return application


def _build_mangled_app() -> FastAPI:
    """Le contre-exemple : un `Page[...]` parametre en signature de route."""
    application = FastAPI()

    @application.get("/notes")
    async def list_notes() -> Page[NoteRead]:
        """Route HORS convention, presente pour prouver le nom mutile."""
        return Page[NoteRead](items=[], total=0, page=1, page_size=1)

    return application


# ---------------------------------------------------------------------------
# Bordure HTTP : parametres, refus, enveloppe
# ---------------------------------------------------------------------------


async def test_happy_path_returns_the_envelope() -> None:
    async with asgi_client(_build_app()) as client:
        response = await client.get("/notes", params={"page": 2, "page_size": 2})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "page", "page_size"}
    assert body["total"] == 5
    assert body["page"] == 2
    assert body["page_size"] == 2
    assert [item["name"] for item in body["items"]] == ["charlie", "delta"]


async def test_defaults_apply_without_query() -> None:
    async with asgi_client(_build_app()) as client:
        response = await client.get("/notes")
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == DEFAULT_PAGE_SIZE
    assert [item["name"] for item in body["items"]] == list(_NOTE_NAMES)


async def test_page_size_above_max_is_refused_not_truncated() -> None:
    """LE critere du ticket : au-dela du maximum, un refus -- jamais une coupe."""
    async with asgi_client(_build_app()) as client:
        refused = await client.get("/notes", params={"page_size": MAX_PAGE_SIZE + 1})
        witness = await client.get("/notes", params={"page_size": MAX_PAGE_SIZE})
    assert refused.status_code == 422
    body = refused.json()
    assert body["code"] == "http.request.validation_error"
    errors = body["details"]["errors"]
    assert [error["loc"] for error in errors] == [["query", "page_size"]]
    assert errors[0]["type"] == "less_than_equal"
    # Temoin de borne : le maximum lui-meme passe -- la limite est incluse.
    assert witness.status_code == 200
    assert witness.json()["page_size"] == MAX_PAGE_SIZE


@pytest.mark.parametrize(
    "query",
    [{"page": 0}, {"page": -1}, {"page_size": 0}, {"page_size": "abc"}],
)
async def test_out_of_range_params_are_refused(query: dict[str, object]) -> None:
    async with asgi_client(_build_app()) as client:
        response = await client.get("/notes", params=query)
    assert response.status_code == 422
    assert response.json()["code"] == "http.request.validation_error"


async def test_astronomical_page_is_refused_not_a_500() -> None:
    """Un decalage au-dela de l'int8 de PostgreSQL est un refus, pas une panne."""
    async with asgi_client(_build_app()) as client:
        response = await client.get("/notes", params={"page": str(10**18), "page_size": 100})
    assert response.status_code == 422
    assert response.json()["code"] == "shared.pagination.invalid"


async def test_unknown_sort_field_is_refused() -> None:
    async with asgi_client(_build_app()) as client:
        response = await client.get("/notes", params={"sort": "email"})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "shared.pagination.unknown_sort"
    assert body["details"] == {"field": "email", "sortable_fields": ["name"]}


@pytest.mark.parametrize("sort", ["", "-", "--name", "NAME"])
async def test_malformed_sort_is_refused(sort: str) -> None:
    """Correspondance exacte, rien d'autre : vide, double prefixe et casse refuses."""
    async with asgi_client(_build_app()) as client:
        response = await client.get("/notes", params={"sort": sort})
    assert response.status_code == 422
    assert response.json()["code"] == "shared.pagination.unknown_sort"


async def test_sort_prefix_controls_direction() -> None:
    async with asgi_client(_build_app()) as client:
        ascending = await client.get("/notes", params={"sort": "name", "page_size": 5})
        descending = await client.get("/notes", params={"sort": "-name", "page_size": 5})
    names = [item["name"] for item in ascending.json()["items"]]
    assert names == sorted(_NOTE_NAMES)
    reversed_names = [item["name"] for item in descending.json()["items"]]
    assert reversed_names == sorted(_NOTE_NAMES, reverse=True)


async def test_without_sort_the_default_order_holds() -> None:
    async with asgi_client(_build_app()) as client:
        response = await client.get("/notes", params={"page_size": 5})
    assert [item["name"] for item in response.json()["items"]] == list(_NOTE_NAMES)


# ---------------------------------------------------------------------------
# Spec OpenAPI : le critere Orval, verifiable sans Orval
# ---------------------------------------------------------------------------


def test_openapi_component_names_are_clean() -> None:
    """Aucun composant au nom mutile : ce qu'Orval genererait est nommable."""
    spec = _build_app().openapi()
    for name in spec["components"]["schemas"]:
        assert _CLEAN_COMPONENT_NAME.match(name), name


def test_parametrized_page_in_a_route_mangles_the_component_name() -> None:
    """Le contre-exemple qui justifie la regle de la sous-classe nommee."""
    spec = _build_mangled_app().openapi()
    assert "Page_NoteRead_" in spec["components"]["schemas"]
    assert not _CLEAN_COMPONENT_NAME.match("Page_NoteRead_")


def test_envelope_schema_declares_the_four_keys() -> None:
    """Les quatre champs, tous requis : l'enveloppe est un contrat, pas une option."""
    schema = _build_app().openapi()["components"]["schemas"]["NotePage"]
    assert set(schema["properties"]) == {"items", "total", "page", "page_size"}
    assert set(schema["required"]) == {"items", "total", "page", "page_size"}
    items = schema["properties"]["items"]
    assert items["items"] == {"$ref": "#/components/schemas/NoteRead"}


def test_response_is_never_a_bare_array() -> None:
    spec = _build_app().openapi()
    responses = spec["paths"]["/notes"]["get"]["responses"]
    ok_schema = responses["200"]["content"]["application/json"]["schema"]
    assert "$ref" in ok_schema


def test_page_bounds_are_declared_in_the_contract() -> None:
    """Bornes et defauts sont VISIBLES du client genere, pas des surprises serveur."""
    spec = _build_app().openapi()
    parameters = {item["name"]: item for item in spec["paths"]["/notes"]["get"]["parameters"]}
    page_size = parameters["page_size"]["schema"]
    assert page_size["maximum"] == MAX_PAGE_SIZE
    assert page_size["minimum"] == 1
    assert page_size["default"] == DEFAULT_PAGE_SIZE
    assert parameters["page"]["schema"]["minimum"] == 1


def test_real_app_responses_are_never_bare_arrays() -> None:
    """Garde posee sur la vraie application -- `create_app()`, regle du depot."""
    spec = create_app().openapi()
    for path_item in spec["paths"].values():
        for operation in path_item.values():
            for response in operation.get("responses", {}).values():
                content = response.get("content", {})
                schema = content.get("application/json", {}).get("schema")
                if schema is not None:
                    assert schema.get("type") != "array"


def test_real_app_component_names_are_clean() -> None:
    """La meme garde des noms sur la vraie application : tout endpoint futur est tenu."""
    spec = create_app().openapi()
    for name in spec.get("components", {}).get("schemas", {}):
        assert _CLEAN_COMPONENT_NAME.match(name), name


# ---------------------------------------------------------------------------
# Depot : bornes du domaine, fenetrage, determinisme, tenance du total
# ---------------------------------------------------------------------------


def test_page_request_refuses_out_of_bounds_values() -> None:
    """La borne tient hors HTTP : une requete invalide est irrepresentable."""
    with pytest.raises(InvalidPageRequestError):
        PageRequest(page=0)
    with pytest.raises(InvalidPageRequestError):
        PageRequest(page_size=0)
    with pytest.raises(InvalidPageRequestError):
        PageRequest(page_size=MAX_PAGE_SIZE + 1)
    with pytest.raises(InvalidPageRequestError):
        # Decalage au-dela de l'int8 de PostgreSQL : refuse a la construction,
        # jamais laisse partir en erreur technique du pilote.
        PageRequest(page=10**18, page_size=MAX_PAGE_SIZE)
    assert PageRequest(page_size=MAX_PAGE_SIZE).page_size == MAX_PAGE_SIZE


async def _seed_plain(session: AsyncSession, labels: Sequence[str]) -> list[PlainNoteModel]:
    """Seme des notes partagees par la session brute, verite terrain des tests."""
    rows = [PlainNoteModel(id=uuid4(), label=label) for label in labels]
    session.add_all(rows)
    await session.flush()
    return rows


async def test_pages_partition_rows_without_overlap_or_loss(session: AsyncSession) -> None:
    rows = await _seed_plain(session, ["n1", "n2", "n3", "n4", "n5"])
    repository = PlainNoteRepository(session)
    pages = [await repository.list(PageRequest(page=number, page_size=2)) for number in (1, 2, 3)]
    assert [len(page.items) for page in pages] == [2, 2, 1]
    assert all(page.total == 5 for page in pages)
    collected = [note.id for page in pages for note in page.items]
    assert collected == sorted(row.id for row in rows)


async def test_default_order_follows_primary_key(session: AsyncSession) -> None:
    """Sans tri demande, l'ordre est celui de la cle primaire -- et lui seul."""
    rows = await _seed_plain(session, ["premiere", "deuxieme", "troisieme"])
    repository = PlainNoteRepository(session)
    page = await repository.list(PageRequest())
    assert [note.id for note in page.items] == sorted(row.id for row in rows)


async def test_equal_sort_values_fall_back_to_pk_tiebreaker(session: AsyncSession) -> None:
    """LA garantie de determinisme : des valeurs egales ne melangent pas les pages."""
    rows = await _seed_plain(session, ["pareil", "pareil", "pareil", "pareil"])
    repository = PlainNoteRepository(session)
    sort = Sort(field="label")
    pages = [
        await repository.list(PageRequest(page=number, page_size=2, sort=sort)) for number in (1, 2)
    ]
    collected = [note.id for page in pages for note in page.items]
    assert collected == sorted(row.id for row in rows)


async def test_sort_descending_reverses_order_including_tiebreaker(
    session: AsyncSession,
) -> None:
    """Le depart des egalites suit le sens du tri, comme `find_active_role`."""
    rows = await _seed_plain(session, ["a", "b", "b", "c"])
    repository = PlainNoteRepository(session)
    sort = Sort(field="label", direction=SortDirection.DESC)
    page = await repository.list(PageRequest(page_size=4, sort=sort))
    expected = sorted(rows, key=lambda row: (row.label, row.id), reverse=True)
    assert [note.id for note in page.items] == [row.id for row in expected]


async def test_tenancy_column_is_not_sortable(session: AsyncSession, group_a: UUID) -> None:
    """La liste blanche parle en noms publics : la colonne de tenance n'en est pas un."""
    repository = TenantNoteRepository(session)
    with use_group(group_a), pytest.raises(UnknownSortFieldError):
        await repository.list(PageRequest(sort=Sort(field="group_id")))


async def test_page_beyond_the_last_returns_empty_items_and_real_total(
    session: AsyncSession,
) -> None:
    """Une page est une fenetre, pas une ressource : au-dela, vide -- jamais 404."""
    await _seed_plain(session, ["seule", "autre", "encore"])
    repository = PlainNoteRepository(session)
    page = await repository.list(PageRequest(page=5, page_size=2))
    assert page.items == []
    assert page.total == 3
    assert page.page == 5
    assert page.page_size == 2


async def test_empty_table_returns_total_zero(session: AsyncSession) -> None:
    page = await PlainNoteRepository(session).list(PageRequest())
    assert page.items == []
    assert page.total == 0


async def test_total_counts_only_the_active_group(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    """Le compte passe par `_select()` : `total` est celui du groupe actif."""
    for label in ("a1", "a2", "a3"):
        session.add(make_tenant_row(uuid4(), group_a, label))
    for label in ("b1", "b2"):
        session.add(make_tenant_row(uuid4(), group_b, label))
    await session.flush()
    repository = TenantNoteRepository(session)
    with use_group(group_a):
        page_a = await repository.list(PageRequest(page_size=2))
    with use_group(group_b):
        page_b = await repository.list(PageRequest(page_size=2))
    assert page_a.total == 3
    assert page_b.total == 2
    assert {note.label for note in page_a.items} <= {"a1", "a2", "a3"}
    assert {note.label for note in page_b.items} <= {"b1", "b2"}


async def test_use_all_groups_counts_every_group(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    """Sous l'echappatoire nommee, total et pages couvrent tous les groupes."""
    rows = [make_tenant_row(uuid4(), group_a, f"a{index}") for index in range(3)]
    rows += [make_tenant_row(uuid4(), group_b, f"b{index}") for index in range(2)]
    session.add_all(rows)
    await session.flush()
    repository = TenantNoteRepository(session)
    with use_all_groups(reason="test : compte transverse assume"):
        page = await repository.list(PageRequest(page_size=10))
    assert page.total == 5
    assert [note.id for note in page.items] == sorted(row.id for row in rows)


async def test_sorted_pages_stay_disjoint_within_the_active_group(
    session: AsyncSession, group_a: UUID, group_b: UUID
) -> None:
    """Tri et tenance combines : rien de l'autre groupe ne s'invite dans les pages."""
    rows_a = [make_tenant_row(uuid4(), group_a, "meme etiquette") for _ in range(3)]
    rows_b = [make_tenant_row(uuid4(), group_b, "meme etiquette") for _ in range(3)]
    session.add_all([*rows_a, *rows_b])
    await session.flush()
    repository = TenantNoteRepository(session)
    sort = Sort(field="label")
    with use_group(group_a):
        pages = [
            await repository.list(PageRequest(page=number, page_size=2, sort=sort))
            for number in (1, 2)
        ]
    collected = [note.id for page in pages for note in page.items]
    assert collected == sorted(row.id for row in rows_a)
    assert set(collected).isdisjoint({row.id for row in rows_b})
