"""journal public interface (M13): the ISO week of v_journal_days in the user's time zone (UC22).

kcal per person = Σ kcal_per_person of the active dishes (snapshots) + Σ rice bowls × E_bát (BR-TRAY-03). The view
can add E_bát itself through app_param('rice_bowl_kcal'), but that database setting reaches only connections opened
after the catalog import set it, so the dish and rice parts are read separately and E_bát comes from catalog.
"""

from __future__ import annotations

import re
import uuid
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from tastoria.core.clock import utcnow
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.journal.schemas import JournalDay, JournalWeek
from tastoria.modules.meal import service as meal
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
    rows = {
        r.local_date: r for r in session.execute(_DAYS, {"u": user_id, "a": monday, "b": monday + timedelta(days=6)})
    }
    rice = meal.rice_bowl_kcal(session)
    days = []
    for i in range(7):
        d = monday + timedelta(days=i)
        r = rows.get(d)
        if r is None:
            days.append(
                JournalDay(date=d, cooked_trays=0, kcal_per_person=None, e_target_kcal=None, urgent_lots_used=0)
            )
            continue
        kcal = float(r.kcal_dishes_per_person) if r.kcal_dishes_per_person is not None else None
        if kcal is not None and r.rice_bowls_per_person is not None and rice:
            kcal += float(r.rice_bowls_per_person) * rice  # FR-22-04
        days.append(
            JournalDay(
                date=d,
                cooked_trays=int(r.cooked_sessions),
                kcal_per_person=round(kcal, 1) if kcal is not None else None,
                e_target_kcal=float(r.e_target_kcal) if r.e_target_kcal is not None else None,
                urgent_lots_used=int(r.urgent_lots_used),
            )
        )
    status = "calibrated" if meal.kcal_half_width(session) is not None else "calibrating"  # BR-NUT-06
    return JournalWeek(week=week, timezone=tz, days=days, kcal_range_status=status)
