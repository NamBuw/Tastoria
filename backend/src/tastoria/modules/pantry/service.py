"""pantry public interface (M06): lots, the append-only transaction ledger, quantity conversion and urgency.

Every change of amount is a new pantry_transactions row; the current amount is v_pantry_lot_balance (initial + Σ delta,
floored at 0). Urgency u and the freshness label are computed at read time (BR-FRESH-05, urgency.py).

Amounts are intervals [g_min, g_max] of grams as purchased (BR-QTY-01). Deducting `need` grams from lots taken in
order works on both bounds: after lots 1..i-1, lot i loses at most max(0, need − Σ_{j<i} g_min_j) and at least
max(0, need − Σ_{j<i} g_max_j), so its remaining interval is
    [max(0, g_min_i − max(0, need − Σ_{j<i} g_min_j)),  max(0, g_max_i − max(0, need − Σ_{j<i} g_max_j))].
A lot whose upper bound reaches 0 is used up.
"""

from __future__ import annotations

import math
import uuid
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from tastoria.core import pagination
from tastoria.core.auth import AuthUser
from tastoria.core.clock import utcnow
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.catalog import service as catalog
from tastoria.modules.catalog.schemas import IngredientView
from tastoria.modules.pantry import urgency as fresh
from tastoria.modules.pantry.models import PantryLot, PantryTransaction
from tastoria.modules.pantry.schemas import (
    CountQty,
    Deduction,
    GramsQty,
    LevelQty,
    LotView,
    Need,
    PantryLotCreate,
    PantryLotOut,
    PantryLotPage,
    PantryLotPatch,
    Shortfall,
)

FUTURE_SKEW = timedelta(minutes=5)  # client clocks run a little ahead
OPEN_STATUSES = ("in_stock", "not_seen")

_BALANCE = text("SELECT lot_id, g_min, g_max FROM v_pantry_lot_balance WHERE user_id = :u AND lot_id = ANY(:ids)")


# ---------------------------------------------------------------- quantity conversion (BR-QTY-02)


def to_grams(session: Session, ing: IngredientView, qty: GramsQty | CountQty | LevelQty) -> tuple[float, float]:
    if isinstance(qty, GramsQty):
        return qty.g_min, qty.g_max
    if isinstance(qty, CountQty):
        gpu = ing.units.get(qty.unit_code)  # a unit row is enough: "2 bó rau muống" (ingredient_units, BR-QTY-02)
        if gpu is None and not ing.countable and not ing.units:
            raise ApiError(422, ProblemCode.qty_kind_mismatch, "Nguyên liệu này không đếm được; nhập gam hoặc mức.")
        if gpu is None:
            raise ApiError(422, ProblemCode.unit_conversion_missing, extra={"unit_code": qty.unit_code})
        return qty.count * gpu, qty.count * gpu
    if ing.countable:
        raise ApiError(422, ProblemCode.qty_kind_mismatch, "Đồ đếm được: nhập số lượng hoặc gam.")
    rng = catalog.qty_level_grams(session, ing.food_group_code, qty.qty_level)
    if rng is None:
        raise ApiError(422, ProblemCode.unit_conversion_missing, extra={"qty_level": qty.qty_level})
    return rng


# ---------------------------------------------------------------- reading lots


@dataclass
class _Lot:
    row: PantryLot
    g_min: float
    g_max: float
    f: fresh.Freshness


def _load(session: Session, user_id: uuid.UUID, rows: list[PantryLot], now: datetime) -> list[_Lot]:
    if not rows:
        return []
    bal = {
        r.lot_id: (float(r.g_min), float(r.g_max))
        for r in session.execute(_BALANCE, {"u": user_id, "ids": [x.id for x in rows]})
    }
    ings = catalog.ingredients_by_ids(session, [r.ingredient_id for r in rows])
    out = []
    for r in rows:
        f = fresh.assess(
            now=now,
            acquired_at=r.acquired_at,
            basis=r.acquired_basis,
            shelf_life_days=ings[r.ingredient_id].shelf_life_days,
            probs=fresh.probabilities(r.p_tuoi, r.p_dung_som, r.p_dung_ngay, r.p_kiem_tra),
            user_checked_at=r.user_checked_at,
            observed_at=r.freshness_observed_at,
            status=r.status,
        )
        g_min, g_max = bal.get(r.id, (float(r.initial_g_min), float(r.initial_g_max)))
        out.append(_Lot(r, g_min, g_max, f))
    return out


def _view(x: _Lot) -> LotView:
    return LotView(
        id=x.row.id,
        ingredient_id=x.row.ingredient_id,
        status=x.row.status,
        g_min=x.g_min,
        g_max=x.g_max,
        urgency=x.f.urgency,
        label=x.f.label,
        available=x.f.available and x.g_min > 0,
        rewarded=fresh.rewarded(x.f.urgency, x.f) and x.f.available,
        acquired_at=x.row.acquired_at,
    )


def _out(session: Session, x: _Lot, names: dict[uuid.UUID, str] | None = None) -> PantryLotOut:
    r = x.row
    if names is None:
        names = {k: v.name_vi for k, v in catalog.ingredients_by_ids(session, [r.ingredient_id]).items()}
    return PantryLotOut(
        id=r.id,
        ingredient_id=r.ingredient_id,
        ingredient_name_vi=names[r.ingredient_id],
        initial_g_min=float(r.initial_g_min),
        initial_g_max=float(r.initial_g_max),
        balance_g_min=x.g_min,
        balance_g_max=x.g_max,
        acquired_at=r.acquired_at,
        acquired_basis=r.acquired_basis,  # type: ignore[arg-type]
        status=r.status,  # type: ignore[arg-type]
        p_tuoi=r.p_tuoi,
        p_dung_som=r.p_dung_som,
        p_dung_ngay=r.p_dung_ngay,
        p_kiem_tra=r.p_kiem_tra,
        freshness_observed_at=r.freshness_observed_at,
        user_checked_at=r.user_checked_at,
        urgency=round(x.f.urgency, 4) if x.f.urgency is not None else None,
        freshness_label=x.f.label,  # type: ignore[arg-type]
        available=x.f.available,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


def _sort_key(x: _Lot) -> tuple[float, str, str]:
    """u descending, unknown u last (FR-14-05), then oldest first."""
    u = x.f.urgency
    return (-(u if u is not None else -1.0), x.row.created_at.isoformat(), str(x.row.id))


def list_lots(
    session: Session, user: AuthUser, *, statuses: list[str], sort: str, cursor: str | None, limit: int
) -> PantryLotPage:
    rows = list(
        session.scalars(
            select(PantryLot).where(PantryLot.user_id == user.id, PantryLot.status.in_(statuses or OPEN_STATUSES))
        )
    )
    lots = _load(session, user.id, rows, utcnow())
    after = pagination.decode(cursor)
    if sort == "urgency":
        lots.sort(key=_sort_key)
        keys = [list(_sort_key(x)) for x in lots]
    else:
        lots.sort(key=lambda x: (x.row.created_at, x.row.id))
        keys = [[x.row.created_at.isoformat(), str(x.row.id)] for x in lots]
    if after is not None:
        start = next((i for i, k in enumerate(keys) if k > after), len(keys))
        lots, keys = lots[start:], keys[start:]
    page = lots[:limit]
    names = {k: v.name_vi for k, v in catalog.ingredients_by_ids(session, [x.row.ingredient_id for x in page]).items()}
    nxt = pagination.encode(keys[limit - 1]) if len(lots) > limit else None
    return PantryLotPage(items=[_out(session, x, names) for x in page], next_cursor=nxt)


def lot_views(session: Session, user_id: uuid.UUID, *, statuses: Iterable[str] = OPEN_STATUSES) -> list[LotView]:
    """The user's lots as of now (BR-FRESH-05); meal planning keeps those with `available` (FR-14-07)."""
    rows = list(
        session.scalars(select(PantryLot).where(PantryLot.user_id == user_id, PantryLot.status.in_(list(statuses))))
    )
    return [_view(x) for x in _load(session, user_id, rows, utcnow())]


def owned_lots(session: Session, user_id: uuid.UUID, ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, LotView]:
    wanted = list(set(ids))
    if not wanted:
        return {}
    rows = list(session.scalars(select(PantryLot).where(PantryLot.user_id == user_id, PantryLot.id.in_(wanted))))
    return {x.row.id: _view(x) for x in _load(session, user_id, rows, utcnow())}


# ---------------------------------------------------------------- UC14 writes


def _owned(session: Session, user_id: uuid.UUID, lot_id: uuid.UUID) -> PantryLot:
    lot = session.scalars(
        select(PantryLot).where(PantryLot.id == lot_id, PantryLot.user_id == user_id).with_for_update()
    ).one_or_none()
    if lot is None:
        raise ApiError(404, ProblemCode.not_found)  # FR-14-16: someone else's lot looks missing
    return lot


def _one(session: Session, user_id: uuid.UUID, lot: PantryLot) -> _Lot:
    session.flush()
    return _load(session, user_id, [lot], utcnow())[0]


def _check_acquired(at: datetime) -> datetime:
    if at.tzinfo is None:
        raise ApiError(
            422,
            ProblemCode.validation_error,
            errors=[{"pointer": "/acquired_at", "code": "timezone_required", "message": "Cần múi giờ (ISO 8601)."}],
        )
    if at > utcnow() + FUTURE_SKEW:
        raise ApiError(422, ProblemCode.acquired_at_in_future)
    return at


def _tx(
    session: Session,
    lot: PantryLot,
    dmin: float,
    dmax: float,
    reason: str,
    *,
    ref_type: str | None,
    ref_id: uuid.UUID | None,
    urgency: float | None = None,
    reverses: int | None = None,
) -> PantryTransaction:
    tx = PantryTransaction(
        lot_id=lot.id,
        delta_g_min=Decimal(str(round(dmin, 3))),
        delta_g_max=Decimal(str(round(dmax, 3))),
        reason=reason,
        ref_type=ref_type,
        ref_id=ref_id,
        reverses_id=reverses,
        urgency_at_event=round(urgency, 4) if urgency is not None else None,
        created_at=utcnow(),
    )
    session.add(tx)
    session.flush()
    return tx


def create_lot(session: Session, user: AuthUser, body: PantryLotCreate) -> PantryLotOut:
    ing = catalog.ingredients_by_ids(session, [body.ingredient_id]).get(body.ingredient_id)
    if ing is None or not ing.is_active:
        raise ApiError(422, ProblemCode.unknown_ingredient)
    g_min, g_max = to_grams(session, ing, body.quantity)
    now = utcnow()
    if body.acquired_at is not None:
        acquired, basis = _check_acquired(body.acquired_at), "purchase_date_entered"
    else:
        acquired, basis = now, "first_seen"  # BR-PANTRY-01
    lot = PantryLot(
        id=uuid.uuid4(),
        user_id=user.id,
        ingredient_id=ing.id,
        initial_g_min=Decimal(str(g_min)),
        initial_g_max=Decimal(str(g_max)),
        acquired_at=acquired,
        acquired_basis=basis,
        status="in_stock",
        created_at=now,
        updated_at=now,
    )
    session.add(lot)
    return _out(session, _one(session, user.id, lot))


def update_lot(session: Session, user: AuthUser, lot_id: uuid.UUID, body: PantryLotPatch) -> PantryLotOut:
    lot = _owned(session, user.id, lot_id)
    fields = body.model_fields_set
    cur = _one(session, user.id, lot)
    if lot.status in ("discarded", "used_up"):
        if "status" in fields and body.status is not None and body.status != lot.status:
            raise ApiError(409, ProblemCode.invalid_lot_transition, extra={"from": lot.status, "to": body.status})
        if fields - {"status"}:
            raise ApiError(409, ProblemCode.lot_closed)
        return _out(session, cur)
    changed = False
    now = utcnow()
    if "balance" in fields and body.balance is not None:
        ing = catalog.ingredients_by_ids(session, [lot.ingredient_id])[lot.ingredient_id]
        g_min, g_max = to_grams(session, ing, body.balance)
        dmin, dmax = g_min - cur.g_min, g_max - cur.g_max
        if dmin or dmax:  # FR-14-10: an unchanged amount writes nothing
            _tx(session, lot, dmin, dmax, "manual_edit", ref_type="user", ref_id=user.id, urgency=cur.f.urgency)
            changed = True
    if "acquired_at" in fields and body.acquired_at is not None:
        lot.acquired_at = _check_acquired(body.acquired_at)
        lot.acquired_basis = "purchase_date_entered"  # FR-14-12
        changed = True
    if "acquired_basis" in fields and body.acquired_basis is not None and lot.acquired_basis != body.acquired_basis:
        lot.acquired_basis = body.acquired_basis
        changed = True
    if "user_checked" in fields and body.user_checked:
        if not cur.f.check_level:
            raise ApiError(409, ProblemCode.lot_not_check_level)
        lot.user_checked_at = now  # FR-14-14
        changed = True
    if "status" in fields and body.status is not None and body.status != lot.status:
        if (lot.status, body.status) not in {
            ("not_seen", "in_stock"),
            ("not_seen", "used_up"),
            ("in_stock", "used_up"),
        }:
            raise ApiError(409, ProblemCode.invalid_lot_transition, extra={"from": lot.status, "to": body.status})
        if body.status == "used_up":
            now_bal = _one(session, user.id, lot)
            if now_bal.g_min or now_bal.g_max:  # FR-14-13: used up = a manual_edit to 0
                _tx(
                    session,
                    lot,
                    -now_bal.g_min,
                    -now_bal.g_max,
                    "manual_edit",
                    ref_type="user",
                    ref_id=user.id,
                    urgency=now_bal.f.urgency,
                )
        lot.status = body.status
        changed = True
    if changed:
        lot.updated_at = now
    return _out(session, _one(session, user.id, lot))


def discard_lot(session: Session, user: AuthUser, lot_id: uuid.UUID) -> PantryLotOut:
    lot = _owned(session, user.id, lot_id)
    cur = _one(session, user.id, lot)
    if lot.status == "discarded":
        return _out(session, cur)  # FR-14-19: a resend writes nothing
    if lot.status == "used_up":
        raise ApiError(409, ProblemCode.invalid_lot_transition, extra={"from": "used_up", "to": "discarded"})
    _tx(session, lot, -cur.g_min, -cur.g_max, "discard", ref_type="user", ref_id=user.id, urgency=cur.f.urgency)
    lot.status = "discarded"
    lot.updated_at = utcnow()
    return _out(session, _one(session, user.id, lot))


# ---------------------------------------------------------------- cooking (UC20, UC21)


def split_need(need: float, lots: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Remaining [g_min, g_max] of each lot, taken in order, after using `need` grams (interval arithmetic, see the
    module docstring). Removed from the lower bounds: min(need, Σ g_min); from the upper ones: min(need, Σ g_max)."""
    out = []
    used_lo = used_hi = 0.0
    for lo, hi in lots:
        new_lo = max(0.0, lo - max(0.0, need - used_lo))  # the lot loses at most need − Σ previous lower bounds …
        new_hi = max(0.0, hi - max(0.0, need - used_hi))  # … and at least need − Σ previous upper bounds
        used_lo += lo
        used_hi += hi
        out.append((new_lo, new_hi))
    return out


def deduct(
    session: Session,
    user_id: uuid.UUID,
    cook_session_id: uuid.UUID,
    needs: Iterable[Need],
    *,
    priority_lot_ids: Iterable[uuid.UUID] = (),
) -> tuple[list[Deduction], list[Shortfall]]:
    """Take each need from the user's usable lots, most urgent first (BR-PANTRY-02); pinned lots of the plan go first
    so a pin really gets used (BR-TRAY-08). Check-level lots are skipped (BR-FRESH-04); a shortage is reported, not an
    error (FR-20-10). One cook_deduct row per touched lot with the urgency at that moment (FR-20-09)."""
    wanted: dict[uuid.UUID, float] = defaultdict(float)
    reported: set[uuid.UUID] = set()
    for n in needs:
        if n.grams > 0:
            wanted[n.ingredient_id] += n.grams
            if n.report_short:
                reported.add(n.ingredient_id)
    if not wanted:
        return [], []
    rows = list(
        session.scalars(
            select(PantryLot)
            .where(
                PantryLot.user_id == user_id,
                PantryLot.ingredient_id.in_(list(wanted)),
                PantryLot.status.in_(OPEN_STATUSES),
            )
            .order_by(PantryLot.id)
            .with_for_update()
        )
    )
    lots = _load(session, user_id, rows, utcnow())
    prio = set(priority_lot_ids)
    by_ing: dict[uuid.UUID, list[_Lot]] = defaultdict(list)
    for x in lots:
        if x.f.label != "kiem_tra" and x.g_max > 0:
            by_ing[x.row.ingredient_id].append(x)
    deductions: list[Deduction] = []
    shortfalls: list[Shortfall] = []
    for iid, need in wanted.items():
        cands = sorted(by_ing.get(iid, []), key=lambda x: (x.row.id not in prio, *_sort_key(x)))
        for x, (new_lo, new_hi) in zip(cands, split_need(need, [(x.g_min, x.g_max) for x in cands]), strict=True):
            dmin, dmax = new_lo - x.g_min, new_hi - x.g_max
            if dmin or dmax:
                tx = _tx(
                    session,
                    x.row,
                    dmin,
                    dmax,
                    "cook_deduct",
                    ref_type="cook_session",
                    ref_id=cook_session_id,
                    urgency=x.f.urgency,
                )
                deductions.append(Deduction(tx.id, x.row.id, iid, dmin, dmax, tx.urgency_at_event))
                if new_hi <= 0:
                    x.row.status = "used_up"
                x.row.updated_at = utcnow()
        avail = sum(x.g_min for x in cands)
        if iid in reported and need > avail + 1e-9:  # staples / optional lines without lots are not "missing" (8b, 8c)
            shortfalls.append(Shortfall(iid, round(need, 1), round(avail, 1), round(need - avail, 1)))
    session.flush()
    return deductions, shortfalls


def deductions_of(session: Session, cook_session_id: uuid.UUID) -> list[Deduction]:
    rows = session.execute(
        select(PantryTransaction, PantryLot.ingredient_id)
        .join(PantryLot, PantryLot.id == PantryTransaction.lot_id)
        .where(
            PantryTransaction.ref_type == "cook_session",
            PantryTransaction.ref_id == cook_session_id,
            PantryTransaction.reason == "cook_deduct",
        )
        .order_by(PantryTransaction.id)
    ).all()
    return [
        Deduction(t.id, t.lot_id, iid, float(t.delta_g_min), float(t.delta_g_max), t.urgency_at_event)
        for t, iid in rows
    ]


def reverse(session: Session, user_id: uuid.UUID, cook_session_id: uuid.UUID) -> list[Deduction]:
    """UC21: one `undo` row per not yet reversed cook_deduct of the session; used-up lots with stock again return to
    in_stock (FR-21-05); discarded lots stay discarded (4a)."""
    originals = [d for d in deductions_of(session, cook_session_id)]
    done = set(
        session.scalars(
            select(PantryTransaction.reverses_id).where(
                PantryTransaction.reverses_id.in_([d.transaction_id for d in originals])
            )
        )
    )
    lots = {
        lot.id: lot
        for lot in session.scalars(
            select(PantryLot)
            .where(PantryLot.user_id == user_id, PantryLot.id.in_([d.lot_id for d in originals]))
            .with_for_update()
        )
    }
    out = []
    for d in originals:
        if d.transaction_id in done or d.lot_id not in lots:
            continue
        lot = lots[d.lot_id]
        tx = _tx(
            session,
            lot,
            -d.delta_g_min,
            -d.delta_g_max,
            "undo",
            ref_type="cook_session",
            ref_id=cook_session_id,
            reverses=d.transaction_id,
        )
        out.append(Deduction(tx.id, lot.id, d.ingredient_id, -d.delta_g_min, -d.delta_g_max, None))
    session.flush()
    for x in _load(session, user_id, list(lots.values()), utcnow()):
        if x.row.status == "used_up" and x.g_max > 0:
            x.row.status = "in_stock"
            x.row.updated_at = utcnow()
    session.flush()
    return out


def round_up_to_unit(grams: float, unit_g: float | None) -> float:
    """Countable needs round up to whole units (BR-TRAY-02, FR-15-09)."""
    if not unit_g or grams <= 0:
        return grams
    return math.ceil(grams / unit_g - 1e-9) * unit_g


# ---------------------------------------------------------------- data-subject requests


class PantrySubjectData:
    name = "pantry"

    def export(self, session: Session, user_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
        lots = list(
            session.scalars(select(PantryLot).where(PantryLot.user_id == user_id).order_by(PantryLot.created_at))
        )
        txs = session.scalars(
            select(PantryTransaction)
            .where(PantryTransaction.lot_id.in_([lt.id for lt in lots]))
            .order_by(PantryTransaction.id)
        )
        return {
            "pantry_lots": [
                {
                    "id": str(x.id),
                    "ingredient_id": str(x.ingredient_id),
                    "initial_g_min": float(x.initial_g_min),
                    "initial_g_max": float(x.initial_g_max),
                    "acquired_at": x.acquired_at.isoformat(),
                    "acquired_basis": x.acquired_basis,
                    "status": x.status,
                    "created_at": x.created_at.isoformat(),
                }
                for x in lots
            ],
            "pantry_transactions": [
                {
                    "id": t.id,
                    "lot_id": str(t.lot_id),
                    "delta_g_min": float(t.delta_g_min),
                    "delta_g_max": float(t.delta_g_max),
                    "reason": t.reason,
                    "created_at": t.created_at.isoformat(),
                }
                for t in txs
            ],
        }

    def erase_purpose(self, session: Session, user_id: uuid.UUID, purpose: str) -> None:
        return None  # the pantry is service data, not tied to a consent purpose

    def erase_files(self, user_id: uuid.UUID) -> None:
        return None
