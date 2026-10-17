"""HTTP layer of catalog: /reference (public), /recipes, /recipes/{id}, /ingredients, /catalog/snapshot."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Query, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from tastoria.core.auth import CurrentUser
from tastoria.core.db import Uow
from tastoria.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from tastoria.modules.catalog import service
from tastoria.modules.catalog.schemas import (
    CatalogSnapshot,
    IngredientPage,
    RecipeOut,
    RecipeSummaryPage,
    ReferenceData,
)
from tastoria.modules.catalog.service import CatalogDeps, catalog_deps

router = APIRouter(tags=["catalog"])
Deps = Annotated[CatalogDeps, Depends(catalog_deps)]
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]


def _matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    tags = {t.strip().removeprefix("W/") for t in if_none_match.split(",")}
    return "*" in tags or etag in tags


def _cached(body: object, version: str, if_none_match: str | None) -> Response:
    etag = f'"{version}"'
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    if _matches(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    return JSONResponse(jsonable_encoder(body), headers=headers)


@router.get(
    "/reference",
    operation_id="catalog_get_reference",
    response_model=ReferenceData,
    responses={304: {"description": "Không đổi so với ETag client giữ"}},
)
def get_reference(uow: Uow, deps: Deps, if_none_match: Annotated[str | None, Header()] = None) -> Response:
    ref = service.get_reference(uow.session, deps)
    return _cached(ref, ref.data_version, if_none_match)


@router.get("/recipes", operation_id="catalog_list_recipes")
def list_recipes(
    user: CurrentUser,
    uow: Uow,
    q: Annotated[str | None, Query(max_length=100)] = None,
    slot: Literal["man", "rau", "canh"] | None = None,
    tag: str | None = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> RecipeSummaryPage:
    return service.list_recipes(uow.session, q=q, slot=slot, tag=tag, cursor=cursor, limit=limit)


@router.get("/recipes/{id}", operation_id="catalog_get_recipe")
def get_recipe(id: uuid.UUID, user: CurrentUser, uow: Uow) -> RecipeOut:
    return service.get_recipe(uow.session, id)


@router.get("/ingredients", operation_id="catalog_list_ingredients")
def list_ingredients(
    user: CurrentUser,
    uow: Uow,
    q: Annotated[str | None, Query(max_length=100)] = None,
    food_group_code: str | None = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> IngredientPage:
    return service.list_ingredients(uow.session, q=q, food_group_code=food_group_code, cursor=cursor, limit=limit)


@router.get(
    "/catalog/snapshot",
    operation_id="catalog_get_snapshot",
    response_model=CatalogSnapshot,
    responses={304: {"description": "Không đổi"}},
)
def get_snapshot(user: CurrentUser, uow: Uow, if_none_match: Annotated[str | None, Header()] = None) -> Response:
    snap = service.snapshot(uow.session)
    return _cached(snap, snap.data_version, if_none_match)
