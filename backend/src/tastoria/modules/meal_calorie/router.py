"""HTTP layer of meal_calorie (M17): POST /meal-calorie/estimate, GET /meal-calorie/dishes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile

from tastoria.core.auth import CurrentUser
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.core.ratelimit import enforce_rate_limit
from tastoria.modules.meal_calorie import service
from tastoria.modules.meal_calorie.estimator import MAX_BYTES
from tastoria.modules.meal_calorie.schemas import (
    BarcodeNutritionOut,
    MealCalorieDishListOut,
    MealCalorieEstimateOut,
    PortionSize,
)

router = APIRouter(prefix="/meal-calorie", tags=["meal_calorie"])


def _deps(request: Request) -> service.MealCalorieDeps:
    return request.app.state.meal_calorie


def _read_optional(upload: UploadFile | None) -> bytes | None:
    if upload is None:
        return None
    upload.file.seek(0)
    data = upload.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ApiError(
            413,
            ProblemCode.image_too_large,
            errors=[{"pointer": "/image", "code": "size", "message": "ảnh > 3 MB"}],
        )
    return data


@router.get("/dishes", operation_id="meal_calorie_list_dishes")
def list_dishes(
    request: Request,
    user: CurrentUser,
    include_extended: Annotated[bool, Query()] = False,
) -> MealCalorieDishListOut:
    return service.list_dishes(_deps(request), include_extended=include_extended)


@router.get("/barcode/{barcode}", operation_id="meal_calorie_lookup_barcode")
def lookup_barcode(
    request: Request,
    user: CurrentUser,
    barcode: str,
) -> BarcodeNutritionOut:
    enforce_rate_limit(request, bucket="meal_calorie_barcode", subject=str(user.id), limit=30, window_s=60)
    return service.lookup_barcode(_deps(request), barcode=barcode)


def _limit_estimate(request: Request, user: CurrentUser) -> None:
    enforce_rate_limit(request, bucket="meal_calorie_estimate", subject=str(user.id), limit=30, window_s=60)


@router.post("/estimate", operation_id="meal_calorie_estimate")
def estimate(
    request: Request,
    user: CurrentUser,
    _: Annotated[None, Depends(_limit_estimate)],
    image: Annotated[UploadFile | None, File()] = None,
    dish_slug: Annotated[str | None, Form()] = None,
    dish_name: Annotated[str | None, Form()] = None,
    portion: Annotated[PortionSize, Form()] = "vua",
) -> MealCalorieEstimateOut:
    raw = _read_optional(image)
    return service.estimate_meal_calories(
        _deps(request),
        image_bytes=raw,
        dish_slug=dish_slug,
        dish_name=dish_name,
        portion=portion,
    )
