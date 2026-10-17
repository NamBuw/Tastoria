"""HTTP layer of substitute: /shopping-items, /shopping-items/{id} (UC18)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from tastoria.core.auth import CurrentUser
from tastoria.core.db import Uow
from tastoria.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from tastoria.modules.substitute import service
from tastoria.modules.substitute.schemas import ShoppingItemCreate, ShoppingItemOut, ShoppingItemPage, ShoppingItemPatch
from tastoria.modules.substitute.service import SubstituteDeps, substitute_deps

router = APIRouter(prefix="/shopping-items", tags=["substitute"])
Deps = Annotated[SubstituteDeps, Depends(substitute_deps)]


@router.get("", operation_id="substitute_list_shopping_items")
def list_items(
    user: CurrentUser,
    uow: Uow,
    status: Annotated[list[Literal["open", "bought", "dropped"]] | None, Query()] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> ShoppingItemPage:
    return service.list_items(uow.session, user, statuses=list(status or []), cursor=cursor, limit=limit)


@router.post(
    "",
    operation_id="substitute_create_shopping_item",
    status_code=201,
    response_model=ShoppingItemOut,
    responses={200: {"model": ShoppingItemOut, "description": "Đã có dòng open cùng nguyên liệu và món: đã cập nhật"}},
)
def create_item(body: ShoppingItemCreate, user: CurrentUser, uow: Uow, deps: Deps) -> JSONResponse:
    item, created = service.create_item(uow.session, deps, user, body)
    headers = {"Location": f"/api/v1/shopping-items/{item.id}"}
    return JSONResponse(jsonable_encoder(item), status_code=201 if created else 200, headers=headers)


@router.patch("/{id}", operation_id="substitute_update_shopping_item")
def update_item(id: uuid.UUID, body: ShoppingItemPatch, user: CurrentUser, uow: Uow) -> ShoppingItemOut:
    return service.update_item(uow.session, user, id, body)
