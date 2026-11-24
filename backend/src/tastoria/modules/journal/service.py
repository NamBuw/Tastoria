"""journal public interface (M13): the ISO week of v_journal_days in the user's time zone (UC22).

kcal per person = Σ kcal_per_person of the active dishes (snapshots) + Σ rice bowls × E_bát (BR-TRAY-03). The view
can add E_bát itself through app_param('rice_bowl_kcal'), but that database setting reaches only connections opened
after the catalog import set it, so the dish and rice parts are read separately and E_bát comes from catalog.
"""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from tastoria.core.clock import utcnow
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.cooking import service as cooking
from tastoria.modules.journal.schemas import CookedDishOut, CookedMealOut, JournalDay, JournalMacros, JournalWeek
from tastoria.modules.meal import service as meal
from tastoria.modules.meal_logs import service as meal_logs
from tastoria.modules.profile import service as profile

WEEK = re.compile(r"^(\d{4})-W(\d{2})$")
_DAYS = text(
    "SELECT local_date, cooked_sessions, kcal_dishes_per_person, rice_bowls_per_person, e_target_kcal, "
    "urgent_lots_used FROM v_journal_days WHERE user_id = :u AND local_date BETWEEN :a AND :b"
)


def parse_week(week: str) -> date:
    """Monday of an ISO 8601 week; 2026-W54 or "abc" → 422 invalid_iso_week (FR-22-08)."""
    m = WEEK.match(week)
    if not m:
        raise ApiError(422, ProblemCode.invalid_iso_week)
    try:
        return date.fromisocalendar(int(m[1]), int(m[2]), 1)
    except ValueError:
        raise ApiError(422, ProblemCode.invalid_iso_week) from None


def get_week(session: Session, user_id: uuid.UUID, week: str | None) -> JournalWeek:
    tz = profile.get_settings_tz(session, user_id)
    if week is None:
        y, w, _ = utcnow().astimezone(ZoneInfo(tz)).date().isocalendar()
        week = f"{y}-W{w:02d}"
    monday = parse_week(week)
    sunday = monday + timedelta(days=6)
    rows = {r.local_date: r for r in session.execute(_DAYS, {"u": user_id, "a": monday, "b": sunday})}
    rice = meal.rice_bowl_kcal(session)

    sessions = cooking.completed_sessions_between(session, user_id, tz, monday, sunday)
    details = meal.cooked_meal_details(session, [s.meal_plan_id for s in sessions])
    week_logs = meal_logs.logs_between(session, user_id, monday, sunday)

    day_macros: dict[date, list[float]] = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0])
    wk_p = wk_c = wk_f = wk_fib = 0.0
    history: list[CookedMealOut] = []
    for s in sessions:
        det = details.get(s.meal_plan_id)
        if det is None:
            continue
        dm = day_macros[s.local_date]
        dm[0] += det.protein_g
        dm[1] += det.carbs_g
        dm[2] += det.fat_g
        dm[3] += det.fiber_g
        wk_p += det.protein_g
        wk_c += det.carbs_g
        wk_f += det.fat_g
        wk_fib += det.fiber_g
        history.append(
            CookedMealOut(
                cook_session_id=s.cook_session_id,
                meal_plan_id=s.meal_plan_id,
                date=s.local_date,
                completed_at=s.completed_at,
                meal=det.meal,
                persons=det.persons,
                kcal_per_person=det.kcal_per_person,
                rice_bowls_per_person=det.rice_bowls_per_person,
                macros=JournalMacros(
                    protein_g=det.protein_g,
                    carbs_g=det.carbs_g,
                    fat_g=det.fat_g,
                    fiber_g=det.fiber_g,
                ),
                dishes=[
                    CookedDishOut(
                        recipe_id=d.recipe_id,
                        name_vi=d.name_vi,
                        slot=d.slot,
                        kcal_per_person=d.kcal_per_person,
                    )
                    for d in det.dishes
                ],
            )
        )

    logs_by_day: dict[date, list] = defaultdict(list)
    for lg in week_logs:
        logs_by_day[lg.logged_date].append(lg)
        dm = day_macros[lg.logged_date]
        dm[0] += lg.protein_g
        dm[1] += lg.carbs_g
        dm[2] += lg.fat_g
        dm[3] += lg.fiber_g
        wk_p += lg.protein_g
        wk_c += lg.carbs_g
        wk_f += lg.fat_g
        wk_fib += lg.fiber_g

    days = []
    for i in range(7):
        d = monday + timedelta(days=i)
        r = rows.get(d)
        day_logs = logs_by_day.get(d, [])
        logs_kcal = sum(lg.kcal for lg in day_logs)
        cooked_kcal = float(r.kcal_dishes_per_person) if (r is not None and r.kcal_dishes_per_person is not None) else None
        if cooked_kcal is not None and r is not None and r.rice_bowls_per_person is not None and rice:
            cooked_kcal += float(r.rice_bowls_per_person) * rice  # FR-22-04
        if cooked_kcal is not None or day_logs:
            day_kcal = round((cooked_kcal or 0.0) + logs_kcal, 1)
        else:
            day_kcal = None
        dm = day_macros.get(d)
        days.append(
            JournalDay(
                date=d,
                cooked_trays=int(r.cooked_sessions) if r is not None else 0,
                meal_logs_count=len(day_logs),
                meal_logs_kcal=round(logs_kcal, 1),
                kcal_per_person=day_kcal,
                e_target_kcal=float(r.e_target_kcal) if (r is not None and r.e_target_kcal is not None) else None,
                urgent_lots_used=int(r.urgent_lots_used) if r is not None else 0,
                protein_g=round(dm[0], 1) if dm is not None else None,
                carbs_g=round(dm[1], 1) if dm is not None else None,
                fat_g=round(dm[2], 1) if dm is not None else None,
                fiber_g=round(dm[3], 1) if dm is not None else None,
            )
        )
    status = "calibrated" if meal.kcal_half_width(session) is not None else "calibrating"  # BR-NUT-06
    return JournalWeek(
        week=week,
        timezone=tz,
        days=days,
        kcal_range_status=status,
        macros=JournalMacros(
            protein_g=round(wk_p, 1),
            carbs_g=round(wk_c, 1),
            fat_g=round(wk_f, 1),
            fiber_g=round(wk_fib, 1),
        ),
        cooked_history=history,
        meal_logs=week_logs,
    )
