"""HTTP layer of meal: /meal-plans (UC15), swap (UC16), substitutes and substitutions (UC17)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from tastoria.core import idempotency
from tastoria.core.auth import CurrentUser
from tastoria.core.db import Uow
from tastoria.core.errors import problem_body
from tastoria.core.idempotency import IdempotencyKeyDep
from tastoria.core.pagination import DEFAULT_LIMIT, MAX_LIMIT
from tastoria.modules.meal import service
from tastoria.modules.meal.schemas import (
    MealPlanCreate,
    MealPlanItemOut,
    MealPlanOut,
    MealPlanSummaryPage,
    PlanStatus,
    SubstituteListOut,
    SubstitutionCreate,
    SwapRequest,
)
from tastoria.modules.meal.service import MealDeps, meal_deps

router = APIRouter(prefix="/meal-plans", tags=["meal"])
Deps = Annotated[MealDeps, Depends(meal_deps)]


@router.post(
    "",
    operation_id="meal_create_plan",
    status_code=201,
    response_model=MealPlanOut,
    responses={422: {"description": "no_feasible_tray / pin_unsatisfiable (InfeasibleTrayProblem)"}},
)
def create_plan(
    body: MealPlanCreate, request: Request, user: CurrentUser, uow: Uow, deps: Deps, idem: IdempotencyKeyDep
) -> JSONResponse:
    if (replayed := idempotency.begin(uow.session, user.id, idem)) is not None:
        return replayed
    res = service.create_plan(uow.session, deps, user, body)
    if res.error is not None:  # stored as well: a resend with the same key gets the same answer (SD03)
        e = res.error
        payload = problem_body(e.status, e.code, detail=e.detail, instance=request.url.path, extra=e.extra)
        return idempotency.finish(uow.session, user.id, idem, e.status, payload)
    assert res.plan is not None
    return idempotency.finish(
        uow.session, user.id, idem, 201, res.plan, headers={"Location": f"/api/v1/meal-plans/{res.plan.id}"}
    )


@router.get("", operation_id="meal_list_plans")
def list_plans(
    user: CurrentUser,
    uow: Uow,
    deps: Deps,
    status: Annotated[list[PlanStatus] | None, Query()] = None,
    from_: Annotated[date | None, Query(alias="from")] = None,
    to: date | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> MealPlanSummaryPage:
    return service.list_plans(
        uow.session, deps, user, statuses=list(status or []), date_from=from_, date_to=to, cursor=cursor, limit=limit
    )


@router.get("/latest", operation_id="meal_get_latest_plan")
def latest_plan(user: CurrentUser, uow: Uow, deps: Deps, meal: Literal["lunch", "dinner"] | None = None) -> MealPlanOut:
    return service.latest_plan(uow.session, deps, user, meal)


@router.get("/{id}", operation_id="meal_get_plan")
def get_plan(id: uuid.UUID, user: CurrentUser, uow: Uow, deps: Deps) -> MealPlanOut:
    return service.get_plan(uow.session, deps, user, id)


@router.post("/{id}/accept", operation_id="meal_accept_plan")
def accept_plan(id: uuid.UUID, user: CurrentUser, uow: Uow, deps: Deps) -> MealPlanOut:
    return service.accept_plan(uow.session, deps, user, id)


@router.post("/{id}/items/{itemId}/swap", operation_id="meal_swap_item", response_model=MealPlanOut)
def swap_item(
    id: uuid.UUID,
    itemId: uuid.UUID,  # noqa: N803 (path parameter name of the contract)
    body: SwapRequest,
    user: CurrentUser,
    uow: Uow,
    deps: Deps,
    idem: IdempotencyKeyDep,
) -> JSONResponse:
    if (replayed := idempotency.begin(uow.session, user.id, idem)) is not None:
        return replayed
    plan = service.swap_item(uow.session, deps, user, id, itemId, body.swap_reason)
    return idempotency.finish(uow.session, user.id, idem, 200, plan)


@router.get("/{id}/items/{itemId}/substitutes", operation_id="meal_list_substitutes")
def list_substitutes(
    id: uuid.UUID,
    itemId: uuid.UUID,  # noqa: N803
    user: CurrentUser,
    uow: Uow,
    deps: Deps,
    ingredient_id: uuid.UUID | None = None,
) -> SubstituteListOut:
    return service.list_substitutes(uow.session, deps, user, id, itemId, ingredient_id)


@router.post("/{id}/items/{itemId}/substitutions", operation_id="meal_apply_substitution")
def apply_substitution(
    id: uuid.UUID,
    itemId: uuid.UUID,  # noqa: N803
    body: SubstitutionCreate,
    user: CurrentUser,
    uow: Uow,
    deps: Deps,
) -> MealPlanItemOut:
    return service.apply_substitution(uow.session, deps, user, id, itemId, body)
