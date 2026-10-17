"""HTTP layer of pantry: /pantry/lots, /pantry/lots/{id}, /pantry/lots/{id}/discard (UC14)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Response

from tastoria.core.auth import CurrentUser
from tastoria.core.db import Uow
from tastoria.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from tastoria.modules.pantry import service
from tastoria.modules.pantry.schemas import LotStatus, PantryLotCreate, PantryLotOut, PantryLotPage, PantryLotPatch

router = APIRouter(prefix="/pantry", tags=["pantry"])


@router.get("/lots", operation_id="pantry_list_lots")
def list_lots(
    user: CurrentUser,
    uow: Uow,
    status: Annotated[list[LotStatus] | None, Query()] = None,
    sort: Literal["urgency", "created_at"] = "urgency",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> PantryLotPage:
    return service.list_lots(uow.session, user, statuses=list(status or []), sort=sort, cursor=cursor, limit=limit)


@router.post("/lots", operation_id="pantry_create_lot", status_code=201)
def create_lot(body: PantryLotCreate, user: CurrentUser, uow: Uow, response: Response) -> PantryLotOut:
    lot = service.create_lot(uow.session, user, body)
    response.headers["Location"] = f"/api/v1/pantry/lots/{lot.id}"
    return lot


@router.patch("/lots/{id}", operation_id="pantry_update_lot")
def update_lot(id: uuid.UUID, body: PantryLotPatch, user: CurrentUser, uow: Uow) -> PantryLotOut:
    return service.update_lot(uow.session, user, id, body)


@router.post("/lots/{id}/discard", operation_id="pantry_discard_lot")
def discard_lot(id: uuid.UUID, user: CurrentUser, uow: Uow) -> PantryLotOut:
    return service.discard_lot(uow.session, user, id)
