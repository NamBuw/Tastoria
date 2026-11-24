"""meal_logs public interface (M18): server-synced meal logs, timezone-aware dates, catalog nutrition derivation."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, tuple_
from sqlalchemy.orm import Session

from tastoria.core import pagination
from tastoria.core.auth import AuthUser
from tastoria.core.clock import utcnow
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.catalog import service as catalog
from tastoria.modules.meal_logs.models import MealLog, MealLogItem
from tastoria.modules.meal_logs.schemas import (
    MealLogCreate,
    MealLogItemOut,
    MealLogOut,
    MealLogPage,
    normalize_source_type,
)
from tastoria.modules.profile import service as profile

DEFAULT_PROVENANCE = {
    "scan_calorie": "Ước lượng theo ảnh chụp và bảng thành phần thực phẩm",
    "barcode": "Thông tin dinh dưỡng từ mã vạch sản phẩm",
    "recipe": "Tính từ công thức chuẩn Mỹ Vị",
    "manual": "Tự ghi nhận bữa ăn",
}

DEFAULT_ITEM_KIND = {
    "scan_calorie": "dish",
    "barcode": "barcode_item",
    "manual": "manual_item",
    "recipe": "dish",
}


def _dec(v: float) -> Decimal:
    return Decimal(str(round(v, 1)))


def _num(v: Decimal | None) -> float:
    return float(v) if v is not None else 0.0


def _decode_cursor(cursor: str | None) -> tuple[date, datetime, uuid.UUID] | None:
    key = pagination.decode(cursor)
    if key is None:
        return None
    if len(key) != 3 or not all(isinstance(x, str) for x in key):
        raise ApiError(
            400,
            ProblemCode.validation_error,
            errors=[{"pointer": "#/query/cursor", "code": "invalid_cursor", "message": "Con trỏ trang không hợp lệ."}],
        )
    try:
        d = date.fromisoformat(key[0])
        dt = datetime.fromisoformat(key[1])
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("naive datetime")
        return d, dt, uuid.UUID(key[2])
    except ValueError:
        raise ApiError(
            400,
            ProblemCode.validation_error,
            errors=[{"pointer": "#/query/cursor", "code": "invalid_cursor", "message": "Con trỏ trang không hợp lệ."}],
        ) from None


def _item_out(it: MealLogItem) -> MealLogItemOut:
    return MealLogItemOut(
        id=it.id,
        ordinal=it.ordinal,
        item_kind=it.item_kind,  # type: ignore[arg-type]
        label_vi=it.label_vi,
        dish_slug=it.dish_slug,
        recipe_id=it.recipe_id,
        ingredient_id=it.ingredient_id,
        barcode=it.barcode,
        grams=float(it.grams) if it.grams is not None else None,
        kcal=_num(it.kcal),
        protein_g=_num(it.protein_g),
        carbs_g=_num(it.carbs_g),
        fat_g=_num(it.fat_g),
        fiber_g=_num(it.fiber_g),
        modifiers=list(it.modifiers or []),
        created_at=it.created_at,
    )


def _out(log_row: MealLog, items: list[MealLogItem]) -> MealLogOut:
    return MealLogOut(
        id=log_row.id,
        logged_date=log_row.logged_date,
        logged_at=log_row.logged_at,
        meal_slot=log_row.meal_slot,  # type: ignore[arg-type]
        title=log_row.title,
        source_type=log_row.source_type,  # type: ignore[arg-type]
        source_ref_id=log_row.source_ref_id,
        portion_label=log_row.portion_label,
        portion_scale=float(log_row.portion_scale),
        modifiers=list(log_row.modifiers or []),
        kcal=_num(log_row.kcal),
        kcal_low=_num(log_row.kcal_low),
        kcal_high=_num(log_row.kcal_high),
        protein_g=_num(log_row.protein_g),
        carbs_g=_num(log_row.carbs_g),
        fat_g=_num(log_row.fat_g),
        fiber_g=_num(log_row.fiber_g),
        provenance_label_vi=log_row.provenance_label_vi,
        notes=log_row.notes,
        items=[_item_out(i) for i in items],
        created_at=log_row.created_at,
        updated_at=log_row.updated_at,
    )


def _load_items(session: Session, log_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[MealLogItem]]:
    out: dict[uuid.UUID, list[MealLogItem]] = defaultdict(list)
    if not log_ids:
        return out
    for it in session.scalars(
        select(MealLogItem)
        .where(MealLogItem.meal_log_id.in_(log_ids))
        .order_by(MealLogItem.meal_log_id, MealLogItem.ordinal)
    ):
        out[it.meal_log_id].append(it)
    return out


@dataclass(frozen=True)
class _ResolvedItem:
    item_kind: str
    label_vi: str
    dish_slug: str | None
    recipe_id: uuid.UUID | None
    ingredient_id: uuid.UUID | None
    barcode: str | None
    grams: float | None
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float
    modifiers: list[str]
    derived_from_catalog: bool = False


def _resolve_items(session: Session, body: MealLogCreate, source_type: str) -> list[_ResolvedItem]:
    if not body.items:
        return [
            _ResolvedItem(
                item_kind=DEFAULT_ITEM_KIND[source_type],
                label_vi=body.title,
                dish_slug=None,
                recipe_id=None,
                ingredient_id=None,
                barcode=body.source_ref_id if source_type == "barcode" else None,
                grams=None,
                kcal=round(body.kcal, 1),
                protein_g=round(body.protein_g, 1),
                carbs_g=round(body.carbs_g, 1),
                fat_g=round(body.fat_g, 1),
                fiber_g=round(body.fiber_g, 1),
                modifiers=list(body.modifiers),
            )
        ]

    rec_ids = {it.recipe_id for it in body.items if it.recipe_id is not None}
    ing_ids = {it.ingredient_id for it in body.items if it.ingredient_id is not None}
    recipes = catalog.recipes_by_ids(session, rec_ids) if rec_ids else {}
    rec_macros = catalog.recipe_macros(session, rec_ids) if rec_ids else {}
    ings = catalog.ingredients_by_ids(session, ing_ids) if ing_ids else {}
    ing_nut = catalog.ingredient_nutrition(session, ing_ids) if ing_ids else {}

    resolved: list[_ResolvedItem] = []
    for idx, it in enumerate(body.items):
        if it.recipe_id is not None:
            rec = recipes.get(it.recipe_id)
            if rec is None or rec.status == "draft":
                raise ApiError(
                    422,
                    ProblemCode.validation_error,
                    errors=[
                        {
                            "pointer": f"/items/{idx}/recipe_id",
                            "code": "unknown_recipe",
                            "message": "Công thức không tồn tại hoặc chưa công bố.",
                        }
                    ],
                )
        if it.ingredient_id is not None:
            ing = ings.get(it.ingredient_id)
            if ing is None or not ing.is_active:
                raise ApiError(422, ProblemCode.unknown_ingredient, extra={"ingredient_id": str(it.ingredient_id)})

        label = it.label_vi
        kcal = it.kcal
        protein_g = it.protein_g
        carbs_g = it.carbs_g
        fat_g = it.fat_g
        fiber_g = it.fiber_g
        derived = False

        if it.recipe_id is not None and it.item_kind != "modifier":
            rec = recipes[it.recipe_id]
            label = label or rec.name_vi
            rm = rec_macros.get(it.recipe_id, {})
            if rm:
                scale = body.portion_scale
                kcal = round(rm.get("energy_kcal", 0.0) * scale, 1)
                protein_g = round(rm.get("protein_g", 0.0) * scale, 1)
                carbs_g = round(rm.get("glucid_g", 0.0) * scale, 1)
                fat_g = round(rm.get("lipid_g", 0.0) * scale, 1)
                fiber_g = round(rm.get("fiber_g", 0.0) * scale, 1)
                derived = True
        elif it.ingredient_id is not None:
            ing = ings[it.ingredient_id]
            label = label or ing.name_vi
            nut = ing_nut.get(it.ingredient_id)
            if it.grams is not None and nut is not None and nut.per_100g_purchased:
                factor = it.grams / 100.0
                p100 = nut.per_100g_purchased
                kcal = round(p100.get("energy_kcal", 0.0) * factor, 1)
                protein_g = round(p100.get("protein_g", 0.0) * factor, 1)
                carbs_g = round(p100.get("glucid_g", 0.0) * factor, 1)
                fat_g = round(p100.get("lipid_g", 0.0) * factor, 1)
                fiber_g = round(p100.get("fiber_g", 0.0) * factor, 1)
                derived = True

        assert label is not None
        resolved.append(
            _ResolvedItem(
                item_kind=it.item_kind,
                label_vi=label,
                dish_slug=it.dish_slug,
                recipe_id=it.recipe_id,
                ingredient_id=it.ingredient_id,
                barcode=it.barcode,
                grams=it.grams,
                kcal=round(kcal or 0.0, 1),
                protein_g=round(protein_g or 0.0, 1),
                carbs_g=round(carbs_g or 0.0, 1),
                fat_g=round(fat_g or 0.0, 1),
                fiber_g=round(fiber_g or 0.0, 1),
                modifiers=list(it.modifiers),
                derived_from_catalog=derived,
            )
        )
    return resolved


def create_log(session: Session, user: AuthUser, body: MealLogCreate) -> MealLogOut:
    now = utcnow()
    if body.logged_at is not None:
        if body.logged_at.tzinfo is None or body.logged_at.utcoffset() is None:
            raise ApiError(
                422,
                ProblemCode.validation_error,
                errors=[{"pointer": "/logged_at", "code": "timezone_required", "message": "Cần múi giờ (ISO 8601)."}],
            )
        if body.logged_at > now + timedelta(days=1):
            raise ApiError(
                422,
                ProblemCode.validation_error,
                errors=[{"pointer": "/logged_at", "code": "too_far_in_future", "message": "logged_at ở tương lai."}],
            )
        logged_at = body.logged_at
    else:
        logged_at = now

    tz = profile.get_settings_tz(session, user.id)
    local_today = now.astimezone(ZoneInfo(tz)).date()
    logged_date = body.logged_date or logged_at.astimezone(ZoneInfo(tz)).date()
    if logged_date > local_today + timedelta(days=1):
        raise ApiError(
            422,
            ProblemCode.validation_error,
            errors=[{"pointer": "/logged_date", "code": "too_far_in_future", "message": "logged_date ở tương lai."}],
        )

    source_type = normalize_source_type(body.source_type)
    resolved_items = _resolve_items(session, body, source_type)

    total_kcal = round(sum(it.kcal for it in resolved_items), 1)
    total_protein = round(sum(it.protein_g for it in resolved_items), 1)
    total_carbs = round(sum(it.carbs_g for it in resolved_items), 1)
    total_fat = round(sum(it.fat_g for it in resolved_items), 1)
    total_fiber = round(sum(it.fiber_g for it in resolved_items), 1)

    any_derived = any(it.derived_from_catalog for it in resolved_items)
    if body.kcal_low is None and body.kcal_high is None:
        kcal_low = total_kcal
        kcal_high = total_kcal
    elif any_derived and "kcal_low" not in body.model_fields_set and "kcal_high" not in body.model_fields_set:
        kcal_low = total_kcal
        kcal_high = total_kcal
    else:
        kcal_low = total_kcal if body.kcal_low is None else round(body.kcal_low, 1)
        kcal_high = total_kcal if body.kcal_high is None else round(body.kcal_high, 1)
        if kcal_low > kcal_high or kcal_low > total_kcal or total_kcal > kcal_high:
            raise ApiError(
                422,
                ProblemCode.validation_error,
                errors=[
                    {
                        "pointer": "/kcal_low",
                        "code": "invalid_kcal_range",
                        "message": "Tổng kcal từ các món phải nằm trong [kcal_low, kcal_high].",
                    }
                ],
            )

    provenance = body.provenance_label_vi.strip() or DEFAULT_PROVENANCE[source_type]
    log_row = MealLog(
        id=uuid.uuid4(),
        user_id=user.id,
        logged_date=logged_date,
        logged_at=logged_at,
        meal_slot=body.meal_slot,
        title=body.title,
        source_type=source_type,
        source_ref_id=body.source_ref_id,
        portion_label=body.portion_label,
        portion_scale=Decimal(str(round(body.portion_scale, 3))),
        modifiers=list(body.modifiers),
        kcal=_dec(total_kcal),
        kcal_low=_dec(kcal_low),
        kcal_high=_dec(kcal_high),
        protein_g=_dec(total_protein),
        carbs_g=_dec(total_carbs),
        fat_g=_dec(total_fat),
        fiber_g=_dec(total_fiber),
        provenance_label_vi=provenance,
        notes=body.notes,
        created_at=now,
        updated_at=now,
    )
    session.add(log_row)
    session.flush()

    item_rows: list[MealLogItem] = []
    for ordinal, it in enumerate(resolved_items, 1):
        row = MealLogItem(
            id=uuid.uuid4(),
            meal_log_id=log_row.id,
            ordinal=ordinal,
            item_kind=it.item_kind,
            label_vi=it.label_vi,
            dish_slug=it.dish_slug,
            recipe_id=it.recipe_id,
            ingredient_id=it.ingredient_id,
            barcode=it.barcode,
            grams=_dec(it.grams) if it.grams is not None else None,
            kcal=_dec(it.kcal),
            protein_g=_dec(it.protein_g),
            carbs_g=_dec(it.carbs_g),
            fat_g=_dec(it.fat_g),
            fiber_g=_dec(it.fiber_g),
            modifiers=list(it.modifiers),
            created_at=now,
        )
        session.add(row)
        item_rows.append(row)
    session.flush()
    return _out(log_row, item_rows)


def list_logs(
    session: Session,
    user: AuthUser,
    *,
    date_from: date | None,
    date_to: date | None,
    meal_slot: str | None,
    cursor: str | None,
    limit: int,
) -> MealLogPage:
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ApiError(
            422,
            ProblemCode.validation_error,
            errors=[{"pointer": "#/query/from", "code": "invalid_range", "message": "from phải <= to."}],
        )
    after = _decode_cursor(cursor)
    q = (
        select(MealLog)
        .where(MealLog.user_id == user.id)
        .order_by(MealLog.logged_date.desc(), MealLog.created_at.desc(), MealLog.id.desc())
        .limit(limit + 1)
    )
    if date_from is not None:
        q = q.where(MealLog.logged_date >= date_from)
    if date_to is not None:
        q = q.where(MealLog.logged_date <= date_to)
    if meal_slot is not None:
        q = q.where(MealLog.meal_slot == meal_slot)
    if after is not None:
        q = q.where(tuple_(MealLog.logged_date, MealLog.created_at, MealLog.id) < after)

    rows = list(session.scalars(q))
    page = rows[:limit]
    items_by_log = _load_items(session, [r.id for r in page])
    nxt = (
        pagination.encode([page[-1].logged_date.isoformat(), page[-1].created_at.isoformat(), str(page[-1].id)])
        if len(rows) > limit
        else None
    )
    return MealLogPage(items=[_out(r, items_by_log.get(r.id, [])) for r in page], next_cursor=nxt)


def get_log(session: Session, user: AuthUser, log_id: uuid.UUID) -> MealLogOut:
    row = session.scalars(select(MealLog).where(MealLog.id == log_id, MealLog.user_id == user.id)).one_or_none()
    if row is None:
        raise ApiError(404, ProblemCode.not_found)
    items = _load_items(session, [row.id]).get(row.id, [])
    return _out(row, items)


def delete_log(session: Session, user: AuthUser, log_id: uuid.UUID) -> None:
    deleted = session.execute(
        delete(MealLog).where(MealLog.id == log_id, MealLog.user_id == user.id).returning(MealLog.id)
    ).scalar_one_or_none()
    if deleted is None:
        raise ApiError(404, ProblemCode.not_found)


# ---------------------------------------------------------------- for journal & privacy DSR


def logs_between(session: Session, user_id: uuid.UUID, start_date: date, end_date: date) -> list[MealLogOut]:
    rows = list(
        session.scalars(
            select(MealLog)
            .where(
                MealLog.user_id == user_id,
                MealLog.logged_date >= start_date,
                MealLog.logged_date <= end_date,
            )
            .order_by(MealLog.logged_date.desc(), MealLog.created_at.desc(), MealLog.id.desc())
        )
    )
    items_by_log = _load_items(session, [r.id for r in rows])
    return [_out(r, items_by_log.get(r.id, [])) for r in rows]


class MealLogSubjectData:
    name = "meal_logs"

    def export(self, session: Session, user_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
        logs = list(
            session.scalars(
                select(MealLog)
                .where(MealLog.user_id == user_id)
                .order_by(MealLog.logged_date, MealLog.created_at, MealLog.id)
            )
        )
        items_by_log = _load_items(session, [r.id for r in logs])
        return {
            "meal_logs": [
                {
                    "id": str(r.id),
                    "logged_date": r.logged_date.isoformat(),
                    "logged_at": r.logged_at.isoformat(),
                    "meal_slot": r.meal_slot,
                    "title": r.title,
                    "source_type": r.source_type,
                    "source_ref_id": r.source_ref_id,
                    "portion_label": r.portion_label,
                    "portion_scale": float(r.portion_scale),
                    "modifiers": list(r.modifiers or []),
                    "kcal": _num(r.kcal),
                    "kcal_low": _num(r.kcal_low),
                    "kcal_high": _num(r.kcal_high),
                    "protein_g": _num(r.protein_g),
                    "carbs_g": _num(r.carbs_g),
                    "fat_g": _num(r.fat_g),
                    "fiber_g": _num(r.fiber_g),
                    "provenance_label_vi": r.provenance_label_vi,
                    "notes": r.notes,
                    "created_at": r.created_at.isoformat(),
                    "updated_at": r.updated_at.isoformat(),
                }
                for r in logs
            ],
            "meal_log_items": [
                {
                    "id": str(it.id),
                    "meal_log_id": str(it.meal_log_id),
                    "ordinal": it.ordinal,
                    "item_kind": it.item_kind,
                    "label_vi": it.label_vi,
                    "dish_slug": it.dish_slug,
                    "recipe_id": str(it.recipe_id) if it.recipe_id else None,
                    "ingredient_id": str(it.ingredient_id) if it.ingredient_id else None,
                    "barcode": it.barcode,
                    "grams": float(it.grams) if it.grams is not None else None,
                    "kcal": _num(it.kcal),
                    "protein_g": _num(it.protein_g),
                    "carbs_g": _num(it.carbs_g),
                    "fat_g": _num(it.fat_g),
                    "fiber_g": _num(it.fiber_g),
                    "modifiers": list(it.modifiers or []),
                    "created_at": it.created_at.isoformat(),
                }
                for r in logs
                for it in items_by_log.get(r.id, [])
            ],
        }

    def erase_purpose(self, session: Session, user_id: uuid.UUID, purpose: str) -> None:
        return None  # meal logs are journal/service data deleted on account erasure

    def erase_files(self, user_id: uuid.UUID) -> None:
        return None
