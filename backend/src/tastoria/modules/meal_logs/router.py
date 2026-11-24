"""HTTP layer of meal_logs: GET/POST /meal-logs, GET/DELETE /meal-logs/{id}."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse

from tastoria.core import idempotency
from tastoria.core.auth import CurrentUser
from tastoria.core.db import Uow
from tastoria.core.idempotency import IdempotencyRequest
from tastoria.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from tastoria.core.ratelimit import enforce_rate_limit
from tastoria.modules.meal_logs import service
from tastoria.modules.meal_logs.schemas import MealLogCreate, MealLogOut, MealLogPage, MealSlot

router = APIRouter(prefix="/meal-logs", tags=["meal_logs"])


async def _optional_idempotency(request: Request) -> IdempotencyRequest | None:
    if "idempotency-key" not in request.headers:
        return None
    return await idempotency.idempotency_key(request)


OptionalIdempotencyDep = Annotated[IdempotencyRequest | None, Depends(_optional_idempotency)]


@router.get("", operation_id="meal_logs_list")
def list_logs(
    user: CurrentUser,
    uow: Uow,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    meal_slot: MealSlot | None = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> MealLogPage:
    return service.list_logs(
        uow.session, user, date_from=from_, date_to=to, meal_slot=meal_slot, cursor=cursor, limit=limit
    )


@router.post("", operation_id="meal_logs_create", status_code=201, response_model=MealLogOut)
def create_log(
    body: MealLogCreate,
    request: Request,
    user: CurrentUser,
    uow: Uow,
    idem: OptionalIdempotencyDep,
) -> JSONResponse:
    enforce_rate_limit(request, bucket="meal_logs_create", subject=str(user.id), limit=60, window_s=60)
    if idem is not None and (replayed := idempotency.begin(uow.session, user.id, idem)) is not None:
        return replayed
    out = service.create_log(uow.session, user, body)
    headers = {"Location": f"/api/v1/meal-logs/{out.id}"}
    if idem is not None:
        return idempotency.finish(uow.session, user.id, idem, 201, out, headers=headers)
    return JSONResponse(out.model_dump(mode="json"), status_code=201, headers=headers)


@router.get("/{id}", operation_id="meal_logs_get")
def get_log(id: uuid.UUID, user: CurrentUser, uow: Uow) -> MealLogOut:
    return service.get_log(uow.session, user, id)


@router.delete("/{id}", operation_id="meal_logs_delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_log(id: uuid.UUID, user: CurrentUser, uow: Uow) -> Response:
    service.delete_log(uow.session, user, id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
