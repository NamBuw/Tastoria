"""meal public interface (M11): hard filter, taste ranking, tray composition, swap, substitutions (UC15–UC17), and the
plan view cooking uses (UC19–UC21).

Order of work for POST /meal-plans (AD02, SD03):
  constraints (profile) → usable lots and urgency (pantry) → published recipes (catalog) → hard filter with the
  allergens of the user and of the co-eaters and the diet's excluded food groups (BR-ALG-01, BR-DIET-01) → ŝ and the
  per-slot percentile ŝ' (ranker) → composer (top-K, pooled stock, pins, makespan bound) → exact CP-SAT makespan of
  the best trays (schedule.py, the same solver cooking uses) → persist + `served` interactions with consent.
No feasible tray: a 2-dish tray for n ≥ 2 (BR-TRAY-06), then 422 `pin_unsatisfiable` (pins are the cause) or
`no_feasible_tray` with the missing ingredients of the 3 best trays without the stock constraint.

meal may not import cooking (cooking depends on meal): whether a plan has a live cook session comes from a check
installed by tastoria.app (MealDeps.has_live_cook_session).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Request
from sqlalchemy import delete, select, tuple_
from sqlalchemy.orm import Session

from tastoria.core import pagination
from tastoria.core.auth import AuthUser
from tastoria.core.clock import utcnow
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.catalog import service as catalog
from tastoria.modules.catalog.schemas import IngredientView, RecipeView
from tastoria.modules.events import service as events
from tastoria.modules.events.schemas import Event
from tastoria.modules.meal import composer as cmp
from tastoria.modules.meal import schedule as sch
from tastoria.modules.meal.models import (
    MealPlan,
    MealPlanCoeaterAllergen,
    MealPlanItem,
    MealPlanItemSubstitution,
    MealPlanPin,
)
from tastoria.modules.meal.ranker import BaselineRanker, RankContext, Ranker, percentiles
from tastoria.modules.meal.schemas import (
    CookPlan,
    MealPlanCreate,
    MealPlanItemOut,
    MealPlanOut,
    MealPlanSummary,
    MealPlanSummaryPage,
    MissingIngredientOut,
    PlanDish,
    SubstituteCandidateOut,
    SubstituteListOut,
    SubstitutionCreate,
    SubstitutionOut,
)
from tastoria.modules.pantry import service as pantry
from tastoria.modules.pantry.schemas import LotView, Need
from tastoria.modules.profile import service as profile
from tastoria.modules.substitute import service as substitute

STRUCTURE_3 = (("man", "rau", "canh"),)
STRUCTURE_2 = (("man", "rau"), ("man", "canh"))
MEAL_END = {"lunch": time(15, 0), "dinner": None}  # FR-15-39: 15:00 / 24:00 local time of the creation day
STIR_FRY = catalog.STIR_FRY_METHOD
VERIFY_MAX = 30  # trays whose exact schedule is tried before giving up on time
KCAL_HALF_WIDTH: float | None = None  # BR-NUT-06: not calibrated yet → kcal_low/high NULL ("đang hiệu chỉnh")


@dataclass(frozen=True)
class MealDeps:
    ranker: Ranker = field(default_factory=BaselineRanker)
    has_live_cook_session: Callable[[Session, uuid.UUID], bool] = lambda s, plan_id: False
    params: cmp.Params = field(default_factory=cmp.Params)


def meal_deps(request: Request) -> MealDeps:
    return request.app.state.meal


# ---------------------------------------------------------------- needs (BR-TRAY-02)


@dataclass(frozen=True)
class _Sub:
    substitute: IngredientView
    grams: float  # for the plan's persons


def line_need(grams: float, ing: IngredientView, persons: int, servings: int) -> float:
    return pantry.round_up_to_unit(grams * persons / servings, ing.rounding_unit_g)


def _needs(recipe: RecipeView, persons: int, subs: dict[uuid.UUID, _Sub] | None = None) -> tuple[dict, dict, float]:
    """(stock-checked needs, consumption needs, made-ahead item grams) for `persons`.

    Stock check (BR-TRAY-04) skips staples and optional lines; consumption (UC20) covers every line, pantry only
    deducts what has lots. A whole make-ahead dish needs its item instead of the raw lines (data/kb/make_ahead.yaml)."""
    subs = subs or {}
    stock: dict[uuid.UUID, float] = defaultdict(float)
    use: dict[uuid.UUID, float] = defaultdict(float)
    ma = recipe.make_ahead
    if ma is not None and ma.whole_dish:
        raw = sum(
            line_need(ln.grams, ln.ingredient, persons, recipe.servings)
            for ln in recipe.lines
            if not ln.ingredient.is_staple and not ln.is_optional
        )
        use[ma.item.id] = raw
        return {}, dict(use), raw
    for ln in recipe.lines:
        sub = subs.get(ln.ingredient.id)
        ing, g = (
            (sub.substitute, sub.grams)
            if sub
            else (ln.ingredient, line_need(ln.grams, ln.ingredient, persons, recipe.servings))
        )
        use[ing.id] += g
        if not ing.is_staple and not ln.is_optional:
            stock[ing.id] += g
    return dict(stock), dict(use), 0.0


def _sched_dish(recipe: RecipeView) -> sch.Dish:
    steps = tuple(sch.Step(s.step_no, s.minutes, s.kind == "active", s.uses_burner) for s in recipe.cook_steps)
    return sch.Dish(recipe.id, steps, recipe.method_code == STIR_FRY)


def _option(
    recipe: RecipeView,
    s_prime: float,
    persons: int,
    subs: dict[uuid.UUID, _Sub] | None = None,
    kcal_pp: float | None = None,
) -> cmp.Option:
    stock, _, item_g = _needs(recipe, persons, subs)
    item = recipe.make_ahead.item.id if recipe.make_ahead and recipe.make_ahead.whole_dish else None
    kcal = kcal_pp if kcal_pp is not None else recipe.kcal_per_serving
    return cmp.Option(recipe, s_prime, stock, item, kcal, _sched_dish(recipe), item_g)


# ---------------------------------------------------------------- planning context


@dataclass
class _Plan:
    user_id: uuid.UUID
    meal: str
    persons: int
    max_minutes: int
    banned: frozenset[str]
    excluded_groups: frozenset[str]
    e_target: float | None
    burners: int
    tz: str
    consented: bool
    lots: list[LotView]
    rice_kcal: float | None
    favorites: list[uuid.UUID]


def _context(
    session: Session, user_id: uuid.UUID, meal: str, persons: int | None, max_minutes: int, coeaters: Iterable[str]
) -> _Plan:
    c = profile.get_meal_constraints(session, user_id)
    return _Plan(
        user_id=user_id,
        meal=meal,
        persons=persons or c.default_persons,
        max_minutes=max_minutes,
        banned=frozenset(c.allergen_codes) | frozenset(coeaters),
        excluded_groups=catalog.excluded_food_groups(session, c.diet_code),
        e_target=float(c.e_meal_kcal[meal]) if c.e_meal_kcal else None,
        burners=c.burners,
        tz=c.timezone,
        consented=events.personalization_allowed(session, user_id),
        lots=pantry.lot_views(session, user_id),
        rice_kcal=catalog.rice_bowl_kcal(session),
        favorites=list(c.favorite_recipe_ids),
    )


def _scores(session: Session, deps: MealDeps, ctx: _Plan, recipes: Sequence[RecipeView]) -> dict[uuid.UUID, float]:
    """ŝ' per slot (design v2 §6.1): the ranker's scores turned into the user's percentile within each slot."""
    favs = list(catalog.recipes_by_ids(session, ctx.favorites).values())
    rank_ctx = RankContext(
        user_id=ctx.user_id,
        favorites=favs,
        popularity=events.popularity(session),
        personal=events.personal_signals(session, ctx.user_id) if ctx.consented else None,  # FR-15-17
    )
    raw = deps.ranker.score(rank_ctx, recipes)
    out: dict[uuid.UUID, float] = {}
    for slot in ("man", "rau", "canh"):
        out.update(percentiles({r.id: raw[r.id] for r in recipes if r.slot == slot}))
    return out


def _lots(ctx: _Plan) -> list[cmp.Lot]:
    return [cmp.Lot(x.id, x.ingredient_id, x.g_min, x.urgency, x.rewarded) for x in ctx.lots if x.available]


def _problem(ctx: _Plan, deps: MealDeps, options: dict[str, list[cmp.Option]], pins: Sequence[LotView]) -> cmp.Problem:
    pin_lots = [cmp.Lot(x.id, x.ingredient_id, x.g_min if x.available else 0.0, x.urgency, x.rewarded) for x in pins]
    return cmp.Problem(
        options, _lots(ctx), pin_lots, ctx.burners, ctx.max_minutes, ctx.e_target, ctx.rice_kcal, deps.params
    )


def _verify(trays: list[cmp.Tray], burners: int, max_minutes: int) -> tuple[cmp.Tray | None, cmp.Tray | None]:
    """First tray (by objective) whose exact CP-SAT makespan fits (BR-TRAY-05), and the next one for the reason line."""
    for i, t in enumerate(trays[:VERIFY_MAX]):
        s = sch.solve([d.sched for d in t.dishes], burners)
        if s.makespan <= max_minutes:
            return t, next(iter(trays[i + 1 :]), None)
    return None, None


# ---------------------------------------------------------------- reason line (design v2 §6.2)


def _reason(session: Session, ctx: _Plan, best: cmp.Tray, second: cmp.Tray | None, two_dish: bool) -> str:
    def parts(t: cmp.Tray) -> dict[str, float]:
        return {
            "urgency": t.urgency,
            "taste": t.taste,
            "kcal": 1 - min(1.0, t.kcal_dev) if ctx.e_target else 0.0,
            "diversity": 1 - t.diversity,
        }

    mine = parts(best)
    if second is not None:
        theirs = parts(second)
        key = max(mine, key=lambda k: (mine[k] - theirs[k], mine[k]))
    else:
        key = max(mine, key=lambda k: mine[k])
    prefix = "Mâm 2 món vì thiếu nguyên liệu. " if two_dish else ""
    if key == "urgency" and best.urgency > 0:
        lots = {x.id: x for x in ctx.lots}
        used = sorted(
            (lots[i] for i in best.used_lots if i in lots and lots[i].rewarded), key=lambda x: -(x.urgency or 0)
        )[:2]
        names = catalog.ingredients_by_ids(session, [x.ingredient_id for x in used])
        listed = ", ".join(dict.fromkeys(names[x.ingredient_id].name_vi for x in used))
        return f"{prefix}Dùng kịp đồ sắp hỏng: {listed}."
    if key == "kcal" and ctx.e_target:
        return f"{prefix}Sát mục tiêu năng lượng của bữa (khoảng {round(ctx.e_target)} kcal mỗi người)."
    if key == "diversity" and best.diversity == 0 and len(best.dishes) > 1:
        return f"{prefix}Các món khác cách nấu và khác nguyên liệu chính."
    top = max(best.dishes, key=lambda d: d.s_prime)
    return f"{prefix}Hợp gu của bạn: {top.recipe.name_vi}."


# ---------------------------------------------------------------- plan lifecycle (FR-15-37 … FR-15-41)


def meal_end(meal_: str, created_at: datetime, tz: str) -> datetime:
    """End of the meal a plan is for: the first lunch end (15:00) or dinner end (24:00) local time after it was made.
    A lunch plan made at 16:00 is for tomorrow's lunch, not an already expired one."""
    z = ZoneInfo(tz)
    day = created_at.astimezone(z).date()
    end = MEAL_END[meal_]
    local = datetime.combine(day, end, z) if end else datetime.combine(day + timedelta(days=1), time(0, 0), z)
    return local if local > created_at else local + timedelta(days=1)


def _meal_end(plan: MealPlan, tz: str) -> datetime:
    return meal_end(plan.meal, plan.created_at, tz)


def _settle(session: Session, deps: MealDeps, plans: Iterable[MealPlan], tz: str) -> None:
    """Past the meal's end a proposed plan is expired and an accepted one without a live cook session is abandoned."""
    now = utcnow()
    for p in plans:
        if p.status not in ("proposed", "accepted") or now < _meal_end(p, tz):
            continue
        if p.status == "proposed":
            p.status, p.updated_at = "expired", now
        elif not deps.has_live_cook_session(session, p.id):
            p.status, p.updated_at = "abandoned", now
    session.flush()


def _sweep(session: Session, deps: MealDeps, user_id: uuid.UUID, tz: str) -> None:
    _settle(
        session,
        deps,
        session.scalars(
            select(MealPlan)
            .where(MealPlan.user_id == user_id, MealPlan.status.in_(("proposed", "accepted")))
            .with_for_update()
        ),
        tz,
    )


def _supersede(session: Session, deps: MealDeps, user_id: uuid.UUID, meal: str, tz: str, keep: uuid.UUID) -> None:
    """A new plan for the same meal (same day's lunch or dinner) replaces the open one (FR-15-37, FR-15-38)."""
    now = utcnow()
    target = meal_end(meal, now, tz)
    for p in session.scalars(
        select(MealPlan)
        .where(
            MealPlan.user_id == user_id,
            MealPlan.meal == meal,
            MealPlan.id != keep,
            MealPlan.status.in_(("proposed", "accepted")),
        )
        .with_for_update()
    ):
        if _meal_end(p, tz) != target:
            continue
        if p.status == "proposed":
            p.status, p.updated_at = "expired", now
        elif not deps.has_live_cook_session(session, p.id):
            p.status, p.updated_at = "abandoned", now
    session.flush()


def _owned_plan(session: Session, user_id: uuid.UUID, plan_id: uuid.UUID, *, lock: bool = False) -> MealPlan:
    q = select(MealPlan).where(MealPlan.id == plan_id, MealPlan.user_id == user_id)
    plan = session.scalars(q.with_for_update() if lock else q).one_or_none()
    if plan is None:
        raise ApiError(404, ProblemCode.not_found)  # BOLA: someone else's plan looks missing
    return plan


def _tz(session: Session, user_id: uuid.UUID) -> str:
    return profile.get_settings_tz(session, user_id)


# ---------------------------------------------------------------- output


def _items(session: Session, plan_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[MealPlanItem]]:
    out: dict[uuid.UUID, list[MealPlanItem]] = defaultdict(list)
    for it in session.scalars(
        select(MealPlanItem)
        .where(MealPlanItem.meal_plan_id.in_(list(plan_ids)))
        .order_by(MealPlanItem.created_at, MealPlanItem.id)
    ):
        out[it.meal_plan_id].append(it)
    return out


def _subs_of(session: Session, item_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[MealPlanItemSubstitution]]:
    out: dict[uuid.UUID, list[MealPlanItemSubstitution]] = defaultdict(list)
    if item_ids:
        for s in session.scalars(
            select(MealPlanItemSubstitution).where(MealPlanItemSubstitution.item_id.in_(list(item_ids)))
        ):
            out[s.item_id].append(s)
    return out


def _item_out(it: MealPlanItem, name: str, subs: list[MealPlanItemSubstitution]) -> MealPlanItemOut:
    return MealPlanItemOut(
        id=it.id,
        slot=it.slot,
        recipe_id=it.recipe_id,
        recipe_name_vi=name,
        status=it.status,  # type: ignore[arg-type]
        replaced_item_id=it.replaced_item_id,
        swap_reason=it.swap_reason,  # type: ignore[arg-type]
        rank_score=float(it.rank_score),
        servings_scale=float(it.servings_scale),
        kcal_per_person=float(it.kcal_per_person) if it.kcal_per_person is not None else None,
        substitutions=[
            SubstitutionOut(
                original_ingredient_id=s.original_ingredient_id,
                substitute_ingredient_id=s.substitute_ingredient_id,
                grams=float(s.grams),
                origin=s.origin,
                created_at=s.created_at,
            )
            for s in subs
        ],  # type: ignore[arg-type]
        created_at=it.created_at,
    )


def _num(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


def plan_out(session: Session, plan: MealPlan) -> MealPlanOut:
    items = _items(session, [plan.id]).get(plan.id, [])
    subs = _subs_of(session, [i.id for i in items])
    names = {r.id: r.name_vi for r in catalog.recipes_by_ids(session, [i.recipe_id for i in items]).values()}
    coeaters = sorted(
        session.scalars(
            select(MealPlanCoeaterAllergen.allergen_code).where(MealPlanCoeaterAllergen.meal_plan_id == plan.id)
        )
    )
    pins = list(session.scalars(select(MealPlanPin.lot_id).where(MealPlanPin.meal_plan_id == plan.id)))
    return MealPlanOut(
        id=plan.id,
        meal=plan.meal,
        persons=plan.persons,
        max_minutes=plan.max_minutes,
        status=plan.status,  # type: ignore[arg-type]
        e_target_kcal=_num(plan.e_target_kcal),
        kcal_low=_num(plan.kcal_low),
        kcal_high=_num(plan.kcal_high),
        rice_bowls_per_person=_num(plan.rice_bowls_per_person),
        reason_vi=plan.reason_vi,
        ranker_version_id=plan.ranker_version_id,
        params_version=plan.params_version,
        coeater_allergen_codes=coeaters,
        pinned_lot_ids=pins,
        items=[_item_out(i, names.get(i.recipe_id, ""), subs.get(i.id, [])) for i in items],
        created_at=plan.created_at,
        updated_at=plan.updated_at,
    )


# ---------------------------------------------------------------- UC15: create


@dataclass(frozen=True)
class Created:
    """A new plan (201) or the infeasible answer (422), which the router stores under the Idempotency-Key too (SD03)."""

    plan: MealPlanOut | None = None
    error: ApiError | None = None


def _infeasible(session: Session, ctx: _Plan, problem: cmp.Problem, structures, code: ProblemCode) -> ApiError:  # noqa: ANN001
    if code == ProblemCode.pin_unsatisfiable:
        unmet = cmp.unmet_pins(problem, structures)
        return ApiError(
            422,
            code,
            "Không mâm nào dùng được ít nhất 50% lô ghim; thử bỏ ghim.",
            extra={"unmet_pinned_lot_ids": [str(i) for i in unmet], "shortfalls": []},
        )
    ignoring = cmp.compose(problem, structures, use_stock=False, use_pins=False, expand=False)[:3]
    names = {
        k: v.name_vi
        for k, v in catalog.ingredients_by_ids(
            session, {i for t in ignoring for i, _, _ in cmp.shortfall(problem, t)}
        ).items()
    }
    shortfalls = [
        {
            "rank": n,
            "recipe_ids": [str(r) for r in t.recipe_ids],
            "missing": [
                {
                    "ingredient_id": str(i),
                    "name_vi": names.get(i, ""),
                    "need_g": round(g, 1),
                    "available_g_min": round(a, 1),
                }
                for i, g, a in cmp.shortfall(problem, t)
            ],
        }
        for n, t in enumerate(ignoring, 1)
    ]
    detail = "Không có mâm khả thi với đồ đang có" + ("" if ignoring else " trong thời gian đã chọn") + "."
    return ApiError(422, code, detail, extra={"shortfalls": shortfalls, "unmet_pinned_lot_ids": []})


def create_plan(session: Session, deps: MealDeps, user: AuthUser, body: MealPlanCreate) -> Created:
    if len(set(body.pinned_lot_ids)) != len(body.pinned_lot_ids) or len(set(body.coeater_allergen_codes)) != len(
        body.coeater_allergen_codes
    ):
        raise ApiError(
            422,
            ProblemCode.validation_error,
            errors=[{"pointer": "/pinned_lot_ids", "code": "unique_items", "message": "Phần tử lặp."}],
        )
    unknown = catalog.unknown_allergen_codes(session, body.coeater_allergen_codes)
    if unknown:
        raise ApiError(422, ProblemCode.unknown_code, extra={"unknown": unknown})  # FR-15-03
    pins = pantry.owned_lots(session, user.id, body.pinned_lot_ids)
    bad = [str(i) for i in body.pinned_lot_ids if i not in pins or pins[i].status != "in_stock"]
    if bad:  # FR-15-02
        raise ApiError(
            422,
            ProblemCode.validation_error,
            extra={"lot_ids": bad},
            errors=[
                {
                    "pointer": "/pinned_lot_ids",
                    "code": "lot_not_usable",
                    "message": "Lô không có hoặc không còn trong kho.",
                }
            ],
        )
    ctx = _context(session, user.id, body.meal, body.persons, body.max_minutes, body.coeater_allergen_codes)
    _sweep(session, deps, user.id, ctx.tz)

    allowed = [
        r for r in catalog.published_recipes(session) if catalog.recipe_allowed(r, ctx.banned, ctx.excluded_groups)
    ]
    s_prime = _scores(session, deps, ctx, allowed)
    options: dict[str, list[cmp.Option]] = defaultdict(list)
    for r in allowed:
        options[r.slot].append(_option(r, s_prime[r.id], ctx.persons))
    pin_views = [pins[i] for i in body.pinned_lot_ids]
    problem = _problem(ctx, deps, options, pin_views)
    structures = STRUCTURE_3 if ctx.persons >= 2 else STRUCTURE_2
    best, second = _verify(cmp.compose(problem, structures), ctx.burners, ctx.max_minutes)
    two_dish = False
    if best is None and ctx.persons >= 2:  # BR-TRAY-06: a 2-dish tray before giving up
        best, second = _verify(cmp.compose(problem, STRUCTURE_2), ctx.burners, ctx.max_minutes)
        two_dish = best is not None
    if best is None:
        every = (*structures, *(STRUCTURE_2 if ctx.persons >= 2 else ()))
        no_pins = cmp.compose(problem, every, use_pins=False) if pin_views else []
        code = ProblemCode.pin_unsatisfiable if no_pins else ProblemCode.no_feasible_tray
        return Created(error=_infeasible(session, ctx, problem, every, code))

    now = utcnow()
    plan = MealPlan(
        id=uuid.uuid4(),
        user_id=user.id,
        meal=ctx.meal,
        persons=ctx.persons,
        max_minutes=ctx.max_minutes,
        status="proposed",
        e_target_kcal=Decimal(str(round(ctx.e_target, 1))) if ctx.e_target else None,
        kcal_low=None,
        kcal_high=None,
        rice_bowls_per_person=Decimal(str(best.bowls)) if best.bowls is not None else None,
        reason_vi=_reason(session, ctx, best, second, two_dish),
        ranker_version_id=deps.ranker.version_id,
        params_version=deps.params.version,
        created_at=now,
        updated_at=now,
    )
    session.add(plan)
    session.flush()
    _set_kcal_range(plan, best)
    session.add_all(
        MealPlanCoeaterAllergen(meal_plan_id=plan.id, allergen_code=c) for c in sorted(set(body.coeater_allergen_codes))
    )
    session.add_all(MealPlanPin(meal_plan_id=plan.id, lot_id=i) for i in body.pinned_lot_ids)
    items = []
    for d in sorted(best.dishes, key=lambda d: ("man", "rau", "canh").index(d.slot)):
        it = MealPlanItem(
            id=uuid.uuid4(),
            meal_plan_id=plan.id,
            slot=d.slot,
            recipe_id=d.recipe.id,
            status="active",
            rank_score=d.s_prime,
            servings_scale=Decimal(str(round(ctx.persons / d.recipe.servings, 4))),
            kcal_per_person=Decimal(str(round(d.kcal_pp, 1))) if d.kcal_pp is not None else None,
            created_at=now,
        )
        items.append(it)
    session.add_all(items)
    session.flush()
    _supersede(session, deps, user.id, ctx.meal, ctx.tz, keep=plan.id)
    events.record(
        session,
        user.id,
        [
            Event(
                "served",
                it.recipe_id,
                now,
                plan.id,
                it.id,
                position=n,
                ranker_version_id=plan.ranker_version_id,
                propensity=1.0,
            )
            for n, it in enumerate(items)
        ],
        consented=ctx.consented,
    )  # FR-15-26
    return Created(plan=plan_out(session, plan))


def _set_kcal_range(plan: MealPlan, tray: cmp.Tray | None, e_pp: float | None = None) -> None:
    e = e_pp if e_pp is not None else (tray.e_pp if tray else None)
    if KCAL_HALF_WIDTH is None or e is None:
        plan.kcal_low = plan.kcal_high = None
    else:
        plan.kcal_low = Decimal(str(round(e * (1 - KCAL_HALF_WIDTH), 1)))
        plan.kcal_high = Decimal(str(round(e * (1 + KCAL_HALF_WIDTH), 1)))


# ---------------------------------------------------------------- UC15: read, accept


def get_plan(session: Session, deps: MealDeps, user: AuthUser, plan_id: uuid.UUID) -> MealPlanOut:
    plan = _owned_plan(session, user.id, plan_id)
    _settle(session, deps, [plan], _tz(session, user.id))
    return plan_out(session, plan)


def latest_plan(session: Session, deps: MealDeps, user: AuthUser, meal: str | None) -> MealPlanOut:
    tz = _tz(session, user.id)
    _sweep(session, deps, user.id, tz)
    z = ZoneInfo(tz)
    start = datetime.combine(utcnow().astimezone(z).date(), time(0, 0), z)
    q = select(MealPlan).where(
        MealPlan.user_id == user.id, MealPlan.status.in_(("proposed", "accepted")), MealPlan.created_at >= start
    )
    if meal:
        q = q.where(MealPlan.meal == meal)
    plan = session.scalars(q.order_by(MealPlan.created_at.desc(), MealPlan.id.desc()).limit(1)).first()
    if plan is None:
        raise ApiError(404, ProblemCode.not_found)
    return plan_out(session, plan)


def list_plans(
    session: Session,
    deps: MealDeps,
    user: AuthUser,
    *,
    statuses: list[str],
    date_from: date | None,
    date_to: date | None,
    cursor: str | None,
    limit: int,
) -> MealPlanSummaryPage:
    tz = _tz(session, user.id)
    _sweep(session, deps, user.id, tz)
    z = ZoneInfo(tz)
    q = select(MealPlan).where(MealPlan.user_id == user.id)
    if statuses:
        q = q.where(MealPlan.status.in_(statuses))
    if date_from:
        q = q.where(MealPlan.created_at >= datetime.combine(date_from, time(0, 0), z))
    if date_to:
        q = q.where(MealPlan.created_at < datetime.combine(date_to + timedelta(days=1), time(0, 0), z))
    after = pagination.decode_created(cursor)
    if after is not None:
        q = q.where(tuple_(MealPlan.created_at, MealPlan.id) < after)
    rows = list(session.scalars(q.order_by(MealPlan.created_at.desc(), MealPlan.id.desc()).limit(limit + 1)))
    page = rows[:limit]
    items = _items(session, [p.id for p in page])
    names = {
        r.id: r.name_vi
        for r in catalog.recipes_by_ids(session, [i.recipe_id for v in items.values() for i in v]).values()
    }
    out = [
        MealPlanSummary(
            id=p.id,
            meal=p.meal,
            persons=p.persons,
            status=p.status,  # type: ignore[arg-type]
            recipe_names_vi=[names[i.recipe_id] for i in items.get(p.id, []) if i.status == "active"],
            created_at=p.created_at,
        )
        for p in page
    ]
    nxt = pagination.encode_created(page[-1].created_at, page[-1].id) if len(rows) > limit else None
    return MealPlanSummaryPage(items=out, next_cursor=nxt)


def accept_plan(session: Session, deps: MealDeps, user: AuthUser, plan_id: uuid.UUID) -> MealPlanOut:
    plan = _owned_plan(session, user.id, plan_id, lock=True)
    _settle(session, deps, [plan], _tz(session, user.id))
    if plan.status == "proposed":
        plan.status, plan.updated_at = "accepted", utcnow()
    elif plan.status != "accepted":  # FR-15-32 / FR-15-33
        raise ApiError(409, ProblemCode.conflict_state, extra={"status": plan.status})
    session.flush()
    return plan_out(session, plan)


# ---------------------------------------------------------------- UC16: swap


def _open_item(
    session: Session,
    deps: MealDeps,
    user: AuthUser,
    plan_id: uuid.UUID,
    item_id: uuid.UUID,
    *,
    allow_cooking: bool = False,
) -> tuple[MealPlan, MealPlanItem]:
    plan = _owned_plan(session, user.id, plan_id, lock=True)
    item = session.scalars(
        select(MealPlanItem).where(MealPlanItem.id == item_id, MealPlanItem.meal_plan_id == plan.id).with_for_update()
    ).one_or_none()
    if item is None:
        raise ApiError(404, ProblemCode.not_found)
    _settle(session, deps, [plan], _tz(session, user.id))
    if plan.status not in ("proposed", "accepted") or item.status != "active":
        raise ApiError(409, ProblemCode.conflict_state, extra={"status": plan.status, "item_status": item.status})
    if not allow_cooking and plan.status == "accepted" and deps.has_live_cook_session(session, plan.id):
        raise ApiError(409, ProblemCode.conflict_state, "Đang nấu mâm này.")
    return plan, item


def _plan_subs(session: Session, items: Sequence[MealPlanItem]) -> dict[uuid.UUID, dict[uuid.UUID, _Sub]]:
    rows = _subs_of(session, [i.id for i in items])
    views = catalog.ingredients_by_ids(session, [s.substitute_ingredient_id for v in rows.values() for s in v])
    return {
        it: {s.original_ingredient_id: _Sub(views[s.substitute_ingredient_id], float(s.grams)) for s in v}
        for it, v in rows.items()
    }


def _plan_ctx(session: Session, plan: MealPlan) -> _Plan:
    coeaters = list(
        session.scalars(
            select(MealPlanCoeaterAllergen.allergen_code).where(MealPlanCoeaterAllergen.meal_plan_id == plan.id)
        )
    )
    ctx = _context(session, plan.user_id, plan.meal, plan.persons, plan.max_minutes, coeaters)
    ctx.e_target = float(plan.e_target_kcal) if plan.e_target_kcal is not None else None  # the snapshot of creation
    return ctx


def swap_item(
    session: Session, deps: MealDeps, user: AuthUser, plan_id: uuid.UUID, item_id: uuid.UUID, reason: str
) -> MealPlanOut:
    plan, item = _open_item(session, deps, user, plan_id, item_id)
    ctx = _plan_ctx(session, plan)
    all_items = _items(session, [plan.id])[plan.id]
    active = [i for i in all_items if i.status == "active"]
    excluded = {i.recipe_id for i in all_items if i.status == "swapped_out"} | {item.recipe_id}  # BR-SWAP-01
    recipes = catalog.recipes_by_ids(session, [i.recipe_id for i in active])
    allowed = [
        r for r in catalog.published_recipes(session) if catalog.recipe_allowed(r, ctx.banned, ctx.excluded_groups)
    ]
    s_prime = _scores(session, deps, ctx, allowed)
    subs = _plan_subs(session, active)
    fixed = [
        _option(
            recipes[i.recipe_id],
            float(i.rank_score),
            plan.persons,
            subs.get(i.id),
            float(i.kcal_per_person) if i.kcal_per_person is not None else None,
        )
        for i in active
        if i.id != item.id
    ]
    cands = [_option(r, s_prime[r.id], plan.persons) for r in allowed if r.slot == item.slot and r.id not in excluded]
    pins = list(
        pantry.owned_lots(
            session, user.id, session.scalars(select(MealPlanPin.lot_id).where(MealPlanPin.meal_plan_id == plan.id))
        ).values()
    )
    problem = _problem(ctx, deps, {item.slot: cands}, pins)
    structure = (tuple(i.slot for i in active),)
    best, second = _verify(cmp.compose(problem, structure, fixed=fixed), ctx.burners, plan.max_minutes)
    if best is None:  # FR-16-14
        raise ApiError(
            422,
            ProblemCode.no_alternative,
            "Không còn món khác phù hợp với đồ đang có.",
            extra={"shortfalls": [], "unmet_pinned_lot_ids": []},
        )
    new_opt = next(d for d in best.dishes if d.slot == item.slot and d.recipe.id not in {f.recipe.id for f in fixed})
    now = utcnow()
    item.status, item.swap_reason = "swapped_out", reason
    session.flush()
    new = MealPlanItem(
        id=uuid.uuid4(),
        meal_plan_id=plan.id,
        slot=item.slot,
        recipe_id=new_opt.recipe.id,
        status="active",
        replaced_item_id=item.id,
        rank_score=new_opt.s_prime,
        servings_scale=Decimal(str(round(plan.persons / new_opt.recipe.servings, 4))),
        kcal_per_person=Decimal(str(round(new_opt.kcal_pp, 1))) if new_opt.kcal_pp is not None else None,
        created_at=now,
    )
    session.add(new)
    session.flush()
    plan.rice_bowls_per_person = Decimal(str(best.bowls)) if best.bowls is not None else None
    _set_kcal_range(plan, best)
    plan.reason_vi = _reason(session, ctx, best, second, two_dish=len(active) == 2 and plan.persons >= 2)
    plan.updated_at = now
    position = [i.id for i in active].index(item.id)
    events.record(
        session,
        user.id,
        [  # FR-16-12, FR-16-13: no `disliked`; khong_hop_gu is the negative signal
            Event("swapped", item.recipe_id, now, plan.id, item.id, swap_reason=reason),
            Event(
                "served",
                new.recipe_id,
                now,
                plan.id,
                new.id,
                position=position,
                ranker_version_id=plan.ranker_version_id,
                propensity=1.0,
            ),
        ],
        consented=ctx.consented,
    )
    session.flush()
    return plan_out(session, plan)


# ---------------------------------------------------------------- UC17: substitutes


def _availability(lots: Iterable[LotView]) -> dict[uuid.UUID, tuple[float, float]]:
    out: dict[uuid.UUID, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for x in lots:
        if x.available:
            out[x.ingredient_id][0] += x.g_min
            out[x.ingredient_id][1] += x.g_max
    return {k: (v[0], v[1]) for k, v in out.items()}


def list_substitutes(
    session: Session,
    deps: MealDeps,
    user: AuthUser,
    plan_id: uuid.UUID,
    item_id: uuid.UUID,
    ingredient_id: uuid.UUID | None,
) -> SubstituteListOut:
    plan, item = _open_item(session, deps, user, plan_id, item_id, allow_cooking=True)
    ctx = _plan_ctx(session, plan)
    active = [i for i in _items(session, [plan.id])[plan.id] if i.status == "active"]
    recipes = catalog.recipes_by_ids(session, [i.recipe_id for i in active])
    subs = _plan_subs(session, active)
    totals: dict[uuid.UUID, float] = defaultdict(float)
    for i in active:
        for k, g in _needs(recipes[i.recipe_id], plan.persons, subs.get(i.id))[0].items():
            totals[k] += g
    avail = _availability(ctx.lots)
    recipe = recipes[item.recipe_id]
    mine = {ln.ingredient.id: ln for ln in recipe.lines}
    if ingredient_id is not None and ingredient_id not in mine:
        raise ApiError(
            422,
            ProblemCode.validation_error,
            errors=[
                {
                    "pointer": "#/query/ingredient_id",
                    "code": "not_in_recipe",
                    "message": "Nguyên liệu không có trong món.",
                }
            ],
        )
    wanted: list[tuple[IngredientView, float, float]] = []  # (ingredient, need, available)
    item_subs = subs.get(item.id, {})
    for iid, ln in mine.items():
        if iid in item_subs:
            continue  # already replaced
        need = line_need(ln.grams, ln.ingredient, plan.persons, recipe.servings)
        have = avail.get(iid, (0.0, 0.0))[0]
        if ingredient_id is not None:
            if iid == ingredient_id:
                wanted.append((ln.ingredient, need, have))
        elif not ln.ingredient.is_staple and not ln.is_optional and totals.get(iid, 0.0) > have + cmp.EPS:
            wanted.append((ln.ingredient, need, have))  # FR-17-01: missing after sharing with the other dishes
    out = []
    for ing, need, have in wanted:
        cands = substitute.candidates(
            session,
            ing.id,
            slot=recipe.slot,
            method=recipe.method_code,
            allergens=ctx.banned,
            excluded_groups=ctx.excluded_groups,
        )
        out.append(
            MissingIngredientOut(
                original_ingredient_id=ing.id,
                name_vi=ing.name_vi,
                need_g=round(need, 1),
                available_g_min=round(have, 1),
                candidates=[
                    SubstituteCandidateOut(
                        substitute_ingredient_id=c.substitute.id,
                        name_vi=c.substitute.name_vi,
                        ratio=c.ratio,
                        grams=round(pantry.round_up_to_unit(need * c.ratio, c.substitute.rounding_unit_g), 1),
                        score=c.score,
                        origin=c.origin,
                        in_pantry=avail.get(c.substitute.id, (0.0, 0.0))[0] > 0,  # type: ignore[arg-type]
                        available_g_min=round(avail.get(c.substitute.id, (0.0, 0.0))[0], 1),
                        available_g_max=round(avail.get(c.substitute.id, (0.0, 0.0))[1], 1),
                    )
                    for c in cands
                ],
            )
        )
    return SubstituteListOut(items=out)


def _item_kcal(
    session: Session, recipe: RecipeView, persons: int, rows: Sequence[MealPlanItemSubstitution]
) -> float | None:
    """BR-NUT-05 after substitutions: the dish's kcal per serving, minus each original, plus its substitute."""
    if recipe.kcal_per_serving is None:
        return None
    lines = {ln.ingredient.id: ln for ln in recipe.lines}
    nut = catalog.ingredient_nutrition(
        session, [r.original_ingredient_id for r in rows] + [r.substitute_ingredient_id for r in rows]
    )
    kcal = recipe.kcal_per_serving
    for r in rows:
        ln = lines.get(r.original_ingredient_id)
        if ln is None or ln.is_optional:
            continue
        e_orig = nut[r.original_ingredient_id].per_100g_purchased.get("energy_kcal", 0.0)
        e_sub = nut[r.substitute_ingredient_id].per_100g_purchased.get("energy_kcal", 0.0)
        kcal += (float(r.grams) / persons * e_sub - ln.grams / recipe.servings * e_orig) / 100
    return max(0.0, kcal)


def apply_substitution(
    session: Session, deps: MealDeps, user: AuthUser, plan_id: uuid.UUID, item_id: uuid.UUID, body: SubstitutionCreate
) -> MealPlanItemOut:
    plan, item = _open_item(session, deps, user, plan_id, item_id, allow_cooking=True)
    ctx = _plan_ctx(session, plan)
    recipe = catalog.recipes_by_ids(session, [item.recipe_id])[item.recipe_id]
    lines = {ln.ingredient.id: ln for ln in recipe.lines}
    orig = lines.get(body.original_ingredient_id)

    def bad(code: str, msg: str) -> ApiError:
        return ApiError(
            422,
            ProblemCode.validation_error,
            errors=[{"pointer": "/substitute_ingredient_id", "code": code, "message": msg}],
        )

    if orig is None:
        raise ApiError(
            422,
            ProblemCode.validation_error,
            errors=[
                {
                    "pointer": "/original_ingredient_id",
                    "code": "not_in_recipe",
                    "message": "Nguyên liệu không có trong món.",
                }
            ],
        )
    sub = catalog.ingredients_by_ids(session, [body.substitute_ingredient_id]).get(body.substitute_ingredient_id)
    if sub is None or not sub.is_active:
        raise bad("inactive", "Nguyên liệu thay không dùng được.")
    if sub.id == orig.ingredient.id:
        raise bad("same_ingredient", "Đồ thay trùng nguyên liệu gốc.")
    if sub.food_group_code != orig.ingredient.food_group_code:
        raise bad("other_food_group", "Đồ thay phải cùng nhóm thực phẩm (FR-17-05).")
    if sub.allergen_codes & ctx.banned:
        raise bad("allergen", f"Thuộc nhóm dị ứng: {', '.join(sorted(sub.allergen_codes & ctx.banned))} (BR-ALG-01).")
    if sub.food_group_code in ctx.excluded_groups:
        raise bad("diet", "Trái chế độ ăn (BR-DIET-01).")
    ratio = substitute.pair_ratio(session, orig.ingredient.id, sub.id, slot=recipe.slot, method=recipe.method_code)
    need = line_need(orig.grams, orig.ingredient, plan.persons, recipe.servings)
    grams = pantry.round_up_to_unit(need * ratio, sub.rounding_unit_g)
    now = utcnow()
    grams_d = Decimal(str(round(grams, 1)))
    cur = session.get(MealPlanItemSubstitution, (item.id, orig.ingredient.id))
    if cur is None or (cur.substitute_ingredient_id, cur.grams, cur.origin) != (sub.id, grams_d, body.origin):
        if cur is not None:  # choosing again replaces the row of (item, original) (FR-17-11)
            session.execute(
                delete(MealPlanItemSubstitution).where(
                    MealPlanItemSubstitution.item_id == item.id,
                    MealPlanItemSubstitution.original_ingredient_id == orig.ingredient.id,
                )
            )
            session.expunge(cur)
        session.add(
            MealPlanItemSubstitution(
                item_id=item.id,
                original_ingredient_id=orig.ingredient.id,
                substitute_ingredient_id=sub.id,
                grams=grams_d,
                origin=body.origin,
                created_at=now,
            )
        )
    session.flush()
    rows = _subs_of(session, [item.id]).get(item.id, [])
    kcal = _item_kcal(session, recipe, plan.persons, rows)
    item.kcal_per_person = Decimal(str(round(kcal, 1))) if kcal is not None else None
    _refresh_energy(session, plan)
    session.flush()
    return _item_out(item, recipe.name_vi, rows)


def _refresh_energy(session: Session, plan: MealPlan) -> None:
    active = [i for i in _items(session, [plan.id])[plan.id] if i.status == "active"]
    dish = sum(float(i.kcal_per_person or 0) for i in active)
    rice = catalog.rice_bowl_kcal(session)
    e_pp = dish
    if plan.e_target_kcal is not None and rice:
        bowls = min(3.0, max(0.5, cmp.round_half((float(plan.e_target_kcal) - dish) / rice)))
        plan.rice_bowls_per_person = Decimal(str(bowls))
        e_pp = dish + bowls * rice
    _set_kcal_range(plan, None, e_pp)
    plan.updated_at = utcnow()


# ---------------------------------------------------------------- for substitute, cooking, journal


def plan_owned(session: Session, user_id: uuid.UUID, plan_id: uuid.UUID) -> bool:
    return session.scalar(select(MealPlan.id).where(MealPlan.id == plan_id, MealPlan.user_id == user_id)) is not None


def plan_ids_of(session: Session, user_id: uuid.UUID) -> list[uuid.UUID]:
    return list(session.scalars(select(MealPlan.id).where(MealPlan.user_id == user_id)))


def item_owned(session: Session, user_id: uuid.UUID, item_id: uuid.UUID) -> bool:
    return (
        session.scalar(
            select(MealPlanItem.id)
            .join(MealPlan, MealPlan.id == MealPlanItem.meal_plan_id)
            .where(MealPlanItem.id == item_id, MealPlan.user_id == user_id)
        )
        is not None
    )


def plan_for_cooking(session: Session, deps: MealDeps, user_id: uuid.UUID, plan_id: uuid.UUID) -> CookPlan:
    plan = _owned_plan(session, user_id, plan_id, lock=True)
    tz = _tz(session, user_id)
    _settle(session, deps, [plan], tz)
    active = [i for i in _items(session, [plan.id])[plan.id] if i.status == "active"]
    recipes = catalog.recipes_by_ids(session, [i.recipe_id for i in active])
    pins = tuple(session.scalars(select(MealPlanPin.lot_id).where(MealPlanPin.meal_plan_id == plan.id)))
    return CookPlan(
        plan.id,
        plan.user_id,
        plan.status,
        plan.persons,
        plan.max_minutes,
        profile.get_meal_constraints(session, user_id).burners,
        tuple(PlanDish(i.id, recipes[i.recipe_id], float(i.servings_scale)) for i in active),
        pins,
    )


def schedule_plan(plan: CookPlan, burners: int) -> tuple[sch.Schedule, list[PlanDish]]:
    dishes = list(plan.dishes)
    return sch.solve([_sched_dish(d.recipe) for d in dishes], burners), dishes


def consumption(session: Session, plan: CookPlan) -> list[Need]:
    """What cooking the plan uses (FR-20-05): every line for the plan's persons, substitutions applied."""
    items = session.scalars(select(MealPlanItem).where(MealPlanItem.id.in_([d.item_id for d in plan.dishes])))
    subs = _plan_subs(session, list(items))
    total: dict[uuid.UUID, float] = defaultdict(float)
    checked: set[uuid.UUID] = set()
    for d in plan.dishes:
        stock, use, _ = _needs(d.recipe, plan.persons, subs.get(d.item_id))
        checked |= set(stock) | (
            {d.recipe.make_ahead.item.id} if d.recipe.make_ahead and d.recipe.make_ahead.whole_dish else set()
        )
        for k, g in use.items():
            total[k] += g
    return [Need(k, g, report_short=k in checked) for k, g in total.items()]


def set_cooked(session: Session, plan_id: uuid.UUID, cooked: bool) -> None:
    """accepted → cooked when a session completes (FR-20-01); back to accepted on undo (FR-21-07), unless the plan
    has moved on (expired / abandoned stay, UC21 5a)."""
    plan = session.get(MealPlan, plan_id, with_for_update=True)
    assert plan is not None
    if cooked and plan.status in ("proposed", "accepted"):
        plan.status, plan.updated_at = "cooked", utcnow()
    elif not cooked and plan.status == "cooked":
        plan.status, plan.updated_at = "accepted", utcnow()
    session.flush()


def plan_status(session: Session, plan_id: uuid.UUID) -> str | None:
    return session.scalar(select(MealPlan.status).where(MealPlan.id == plan_id))


def rice_bowl_kcal(session: Session) -> float | None:
    return catalog.rice_bowl_kcal(session)


class MealSubjectData:
    name = "meal"

    def export(self, session: Session, user_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
        plans = list(session.scalars(select(MealPlan).where(MealPlan.user_id == user_id).order_by(MealPlan.created_at)))
        items = _items(session, [p.id for p in plans])
        return {
            "meal_plans": [
                {
                    "id": str(p.id),
                    "meal": p.meal,
                    "persons": p.persons,
                    "status": p.status,
                    "e_target_kcal": _num(p.e_target_kcal),
                    "reason_vi": p.reason_vi,
                    "created_at": p.created_at.isoformat(),
                }
                for p in plans
            ],
            "meal_plan_items": [
                {
                    "id": str(i.id),
                    "meal_plan_id": str(i.meal_plan_id),
                    "slot": i.slot,
                    "recipe_id": str(i.recipe_id),
                    "status": i.status,
                    "swap_reason": i.swap_reason,
                }
                for p in plans
                for i in items.get(p.id, [])
            ],
        }

    def erase_purpose(self, session: Session, user_id: uuid.UUID, purpose: str) -> None:
        return None

    def erase_files(self, user_id: uuid.UUID) -> None:
        return None
