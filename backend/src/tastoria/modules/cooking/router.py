"""HTTP layer of cooking: /cook-sessions (UC19), complete (UC20), undo (UC21), abandon."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse

from tastoria.core import idempotency
from tastoria.core.auth import CurrentUser
from tastoria.core.db import Uow
from tastoria.core.idempotency import IdempotencyKeyDep
from tastoria.modules.cooking import service
from tastoria.modules.cooking.schemas import CookCompleteRequest, CookCompletion, CookSessionCreate, CookSessionOut
from tastoria.modules.meal.service import MealDeps, meal_deps

router = APIRouter(prefix="/cook-sessions", tags=["cooking"])
Deps = Annotated[MealDeps, Depends(meal_deps)]


@router.post("", operation_id="cooking_create_session", status_code=201, response_model=CookSessionOut)
def create_session(
    body: CookSessionCreate, user: CurrentUser, uow: Uow, deps: Deps, idem: IdempotencyKeyDep
) -> JSONResponse:
    if (replayed := idempotency.begin(uow.session, user.id, idem)) is not None:
        return replayed
    cs = service.create_session(uow.session, deps, user, body)
    return idempotency.finish(
        uow.session, user.id, idem, 201, cs, headers={"Location": f"/api/v1/cook-sessions/{cs.id}"}
    )


@router.get("/{id}", operation_id="cooking_get_session")
def get_session(id: uuid.UUID, user: CurrentUser, uow: Uow) -> CookSessionOut:
    return service.get_session(uow.session, user, id)


@router.post("/{id}/complete", operation_id="cooking_complete_session", response_model=CookCompletion)
def complete_session(
    id: uuid.UUID,
    user: CurrentUser,
    uow: Uow,
    deps: Deps,
    idem: IdempotencyKeyDep,
    body: Annotated[CookCompleteRequest | None, Body()] = None,
) -> JSONResponse:
    if (replayed := idempotency.begin(uow.session, user.id, idem)) is not None:
        return replayed
    res = service.complete_session(uow.session, deps, user, id, body or CookCompleteRequest())
    return idempotency.finish(uow.session, user.id, idem, 200, res)


@router.post("/{id}/undo", operation_id="cooking_undo_session")
def undo_session(id: uuid.UUID, user: CurrentUser, uow: Uow) -> CookSessionOut:
    return service.undo_session(uow.session, user, id)


@router.post("/{id}/abandon", operation_id="cooking_abandon_session")
def abandon_session(id: uuid.UUID, user: CurrentUser, uow: Uow) -> CookSessionOut:
    return service.abandon_session(uow.session, user, id)
