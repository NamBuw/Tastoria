"""cooking public interface (M12): cook sessions with the CP-SAT schedule (BR-COOK-01), "nấu xong" in one Unit of
Work (BR-COOK-02), undo within 10 minutes (BR-PANTRY-02), abandon.

complete = one transaction (the request's UoW): session in_progress → completed, pantry deducted most urgent first,
plan → cooked, `cooked`/`liked`/`disliked` interactions with consent. A repeat with the same Idempotency-Key gets
the stored response; a repeat with a new key finds the session completed and answers the first completion's
summary without touching the pantry again (FR-20-04).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tastoria.core.auth import AuthUser
from tastoria.core.clock import utcnow
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.catalog import service as catalog
from tastoria.modules.cooking.models import CookScheduleEntry, CookSession
from tastoria.modules.cooking.schemas import (
    CookCompleteRequest,
    CookCompletion,
    CookSessionCreate,
    CookSessionOut,
    PantryDeductionOut,
    ScheduleEntryOut,
    ShortfallOut,
)
from tastoria.modules.events import service as events
from tastoria.modules.events.schemas import Event
from tastoria.modules.meal import service as meal
from tastoria.modules.meal.service import MealDeps
from tastoria.modules.pantry import service as pantry
from tastoria.modules.pantry.schemas import Deduction

UNDO_WINDOW = timedelta(minutes=10)  # BR-PANTRY-02
CLOCK_SKEW = timedelta(minutes=5)


def has_live_cook_session(session: Session, meal_plan_id: uuid.UUID) -> bool:
    """Installed into meal (MealDeps): a plan being cooked is neither abandoned nor superseded (FR-15-38, FR-15-41)."""
    return (
        session.scalar(
            select(CookSession.id).where(CookSession.meal_plan_id == meal_plan_id, CookSession.status == "in_progress")
        )
        is not None
    )


def _owned(session: Session, user_id: uuid.UUID, cook_session_id: uuid.UUID, *, lock: bool = False) -> CookSession:
    q = select(CookSession).where(CookSession.id == cook_session_id)
    cs = session.scalars(q.with_for_update() if lock else q).one_or_none()
    if cs is None or not meal.plan_owned(session, user_id, cs.meal_plan_id):
        raise ApiError(404, ProblemCode.not_found)  # BOLA: the owner is the plan's
    return cs


def _out(session: Session, cs: CookSession) -> CookSessionOut:
    rows = list(
        session.scalars(
            select(CookScheduleEntry)
            .where(CookScheduleEntry.cook_session_id == cs.id)
            .order_by(CookScheduleEntry.start_offset_s, CookScheduleEntry.recipe_id, CookScheduleEntry.step_no)
        )
    )
    recipes = catalog.recipes_by_ids(session, {r.recipe_id for r in rows})
    steps = {(rid, s.step_no): s for rid, v in recipes.items() for s in v.steps}
    return CookSessionOut(
        id=cs.id,
        meal_plan_id=cs.meal_plan_id,
        status=cs.status,  # type: ignore[arg-type]
        serve_at=cs.serve_at,
        burners=cs.burners,
        started_at=cs.started_at,
        completed_at=cs.completed_at,
        reverted_at=cs.reverted_at,
        created_at=cs.created_at,
        makespan_s=max((r.end_offset_s for r in rows), default=0),
        undo_deadline=cs.completed_at + UNDO_WINDOW if cs.completed_at and cs.status == "completed" else None,
        schedule=[
            ScheduleEntryOut(
                recipe_id=r.recipe_id,
                step_no=r.step_no,
                start_offset_s=r.start_offset_s,
                end_offset_s=r.end_offset_s,
                text_vi=steps[(r.recipe_id, r.step_no)].text_vi,
                kind=steps[(r.recipe_id, r.step_no)].kind,  # type: ignore[arg-type]
                uses_burner=steps[(r.recipe_id, r.step_no)].uses_burner,
            )
            for r in rows
        ],
    )


# ---------------------------------------------------------------- UC19: start, read, abandon


def create_session(session: Session, deps: MealDeps, user: AuthUser, body: CookSessionCreate) -> CookSessionOut:
    if body.serve_at.tzinfo is None:
        raise ApiError(
            422,
            ProblemCode.validation_error,
            errors=[{"pointer": "/serve_at", "code": "timezone_required", "message": "Cần múi giờ (ISO 8601)."}],
        )
    plan = meal.plan_for_cooking(session, deps, user.id, body.meal_plan_id)
    if plan.status == "proposed":
        raise ApiError(409, ProblemCode.meal_plan_not_accepted)  # FR-19-01
    if plan.status != "accepted":
        raise ApiError(409, ProblemCode.meal_plan_not_cookable, extra={"status": plan.status})
    live = session.scalar(
        select(CookSession.id).where(CookSession.meal_plan_id == plan.id, CookSession.status == "in_progress")
    )
    if live is not None:  # FR-19-02
        raise ApiError(409, ProblemCode.cook_session_in_progress, extra={"cook_session_id": str(live)})
    empty = [str(d.recipe.id) for d in plan.dishes if not d.recipe.steps]
    if empty:
        raise ApiError(422, ProblemCode.recipe_without_steps, extra={"recipe_ids": empty})
    sched, dishes = meal.schedule_plan(plan, plan.burners)
    over = sched.makespan - plan.max_minutes
    if over > 0 and not body.confirm_over_time:  # FR-19-10: say how much, create nothing
        raise ApiError(
            409,
            ProblemCode.conflict_state,
            f"Lịch cần {sched.makespan} phút, quá {over} phút đã chọn; gửi lại với confirm_over_time = true.",
            extra={"over_time_minutes": over, "makespan_s": sched.makespan * 60, "solver_status": sched.status},
        )
    now = utcnow()
    serve_at = max(body.serve_at, now + timedelta(minutes=sched.makespan))  # UC19 1a: the earliest possible
    lead = int((serve_at - now).total_seconds()) - sched.makespan * 60
    cs = CookSession(
        id=uuid.uuid4(),
        meal_plan_id=plan.id,
        status="in_progress",
        serve_at=serve_at,
        burners=plan.burners,
        started_at=now,
        created_at=now,
    )
    session.add(cs)
    session.flush()
    session.add_all(
        CookScheduleEntry(
            cook_session_id=cs.id,
            recipe_id=dishes[e.dish].recipe.id,
            step_no=e.step_no,
            start_offset_s=lead + e.start * 60,
            end_offset_s=lead + e.end * 60,
        )
        for e in sched.entries
    )
    session.flush()
    return _out(session, cs)


def get_session(session: Session, user: AuthUser, cook_session_id: uuid.UUID) -> CookSessionOut:
    return _out(session, _owned(session, user.id, cook_session_id))


def abandon_session(session: Session, user: AuthUser, cook_session_id: uuid.UUID) -> CookSessionOut:
    cs = _owned(session, user.id, cook_session_id, lock=True)
    if cs.status == "in_progress":
        cs.status = "abandoned"  # FR-19-12: the pantry is untouched, the plan stays accepted
    elif cs.status != "abandoned":
        raise ApiError(409, ProblemCode.cook_session_not_in_progress, extra={"status": cs.status})
    session.flush()
    return _out(session, cs)


# ---------------------------------------------------------------- UC20: complete


def _deduction_out(d: Deduction) -> PantryDeductionOut:
    return PantryDeductionOut(
        transaction_id=d.transaction_id,
        lot_id=d.lot_id,
        ingredient_id=d.ingredient_id,
        delta_g_min=d.delta_g_min,
        delta_g_max=d.delta_g_max,
        urgency_at_event=d.urgency_at_event,
    )


def _summary(session: Session, user_id: uuid.UUID, cs: CookSession) -> CookCompletion:
    return CookCompletion(
        cook_session=_out(session, cs),
        deductions=[_deduction_out(d) for d in pantry.deductions_of(session, cs.id)],
        interactions_recorded=events.count(session, user_id, meal_plan_id=cs.meal_plan_id, types=("cooked",)) > 0,
    )


def complete_session(
    session: Session, deps: MealDeps, user: AuthUser, cook_session_id: uuid.UUID, body: CookCompleteRequest
) -> CookCompletion:
    cs = _owned(session, user.id, cook_session_id, lock=True)
    if cs.status == "completed":
        return _summary(session, user.id, cs)  # FR-20-04: completed already, nothing deducted twice
    if cs.status != "in_progress":
        raise ApiError(409, ProblemCode.cook_session_not_in_progress, extra={"status": cs.status})
    plan = meal.plan_for_cooking(session, deps, user.id, cs.meal_plan_id)
    items = {d.item_id: d for d in plan.dishes}
    for f in body.feedback:
        if f.meal_plan_item_id not in items:
            raise ApiError(
                422,
                ProblemCode.validation_error,
                errors=[{"pointer": "/feedback", "code": "unknown_item", "message": "Món không thuộc mâm này."}],
            )
    now = utcnow()
    occurred = (
        body.completed_at if body.completed_at and cs.started_at <= body.completed_at <= now + CLOCK_SKEW else now
    )
    deds, short = pantry.deduct(
        session, user.id, cs.id, meal.consumption(session, plan), priority_lot_ids=plan.pinned_lot_ids
    )
    cs.status, cs.completed_at = "completed", now  # server time decides the undo window (UC20 3a)
    session.flush()
    meal.set_cooked(session, plan.id, True)
    evts = [Event("cooked", d.recipe.id, occurred, plan.id, d.item_id) for d in plan.dishes]
    evts += [
        Event(
            "liked" if f.liked else "disliked",
            items[f.meal_plan_item_id].recipe.id,
            occurred,
            plan.id,
            f.meal_plan_item_id,
        )
        for f in body.feedback
        if f.liked is not None
    ]
    recorded = events.record(session, user.id, evts)
    session.flush()
    return CookCompletion(
        cook_session=_out(session, cs),
        deductions=[_deduction_out(d) for d in deds],
        interactions_recorded=recorded,
        shortfalls=[
            ShortfallOut(
                ingredient_id=s.ingredient_id, need_g=s.need_g, available_g_min=s.available_g_min, short_g=s.short_g
            )
            for s in short
        ],
    )


# ---------------------------------------------------------------- UC21: undo


def undo_session(session: Session, user: AuthUser, cook_session_id: uuid.UUID) -> CookSessionOut:
    cs = _owned(session, user.id, cook_session_id, lock=True)
    if cs.status == "reverted":
        return _out(session, cs)  # FR-21-06
    if cs.status != "completed":
        raise ApiError(409, ProblemCode.cook_session_not_completed, extra={"status": cs.status})
    now = utcnow()
    assert cs.completed_at is not None
    if now > cs.completed_at + UNDO_WINDOW:  # FR-21-02
        raise ApiError(
            409, ProblemCode.undo_window_expired, extra={"undo_deadline": (cs.completed_at + UNDO_WINDOW).isoformat()}
        )
    pantry.reverse(session, user.id, cs.id)
    cs.status, cs.reverted_at = "reverted", now
    session.flush()
    meal.set_cooked(session, cs.meal_plan_id, False)
    undone = [
        Event("undone", r, now, cs.meal_plan_id, i) for r, i in events.cooked_items(session, user.id, cs.meal_plan_id)
    ]
    events.record(session, user.id, undone)  # FR-21-08: `cooked` rows stay, `undone` rows are added
    session.flush()
    return _out(session, cs)


# ---------------------------------------------------------------- data-subject requests


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


class CookingSubjectData:
    name = "cooking"

    def export(self, session: Session, user_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
        plan_ids = meal.plan_ids_of(session, user_id)
        rows = session.scalars(
            select(CookSession).where(CookSession.meal_plan_id.in_(plan_ids)).order_by(CookSession.created_at)
        )
        return {
            "cook_sessions": [
                {
                    "id": str(r.id),
                    "meal_plan_id": str(r.meal_plan_id),
                    "status": r.status,
                    "serve_at": _iso(r.serve_at),
                    "started_at": _iso(r.started_at),
                    "completed_at": _iso(r.completed_at),
                    "reverted_at": _iso(r.reverted_at),
                }
                for r in rows
            ]
        }

    def erase_purpose(self, session: Session, user_id: uuid.UUID, purpose: str) -> None:
        return None

    def erase_files(self, user_id: uuid.UUID) -> None:
        return None
