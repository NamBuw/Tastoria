"""events public interface (M09): interactions behind the `personalization` consent gate (BR-CONSENT-03).

`record` is called by meal and cooking inside their Unit of Work and by POST /events; without a current consent
nothing is written. Event ids make writes idempotent (INSERT … ON CONFLICT (id) DO NOTHING). Only "khong_hop_gu"
swaps count as a negative taste signal (BR-SWAP-01).
"""

from __future__ import annotations

import threading
import time as pytime
import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tastoria.core.clock import utcnow
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.events.models import Interaction
from tastoria.modules.events.schemas import Event, EventBatch, EventBatchResult, RecipeSignal, TrainingInteractionRow
from tastoria.modules.privacy import service as privacy

PURPOSE = "personalization"
POPULARITY_TTL_S = 60.0
_SIGNAL_TYPES = frozenset({"liked", "cooked", "disliked", "swapped"})
_pop_lock = threading.Lock()
_pop_cache: dict[str, tuple[float, dict[uuid.UUID, RecipeSignal]]] = {}


def _cache_db_key(session: Session) -> str:
    bind = session.get_bind()
    return f"{id(bind)}:{bind.url}"


def invalidate_popularity_cache(session: Session | None = None) -> None:
    with _pop_lock:
        if session is None:
            _pop_cache.clear()
        else:
            _pop_cache.pop(_cache_db_key(session), None)


def personalization_allowed(session: Session, user_id: uuid.UUID) -> bool:
    return privacy.has_consent(session, user_id, PURPOSE)


def _insert(session: Session, user_id: uuid.UUID, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    stmt = insert(Interaction).values(rows).on_conflict_do_nothing(index_elements=["id"]).returning(Interaction.id)
    return len(session.execute(stmt).all())


def record(session: Session, user_id: uuid.UUID, events: Iterable[Event], *, consented: bool | None = None) -> bool:
    """Write the events when the user has a current personalization consent; returns whether anything may be written."""
    if consented is None:
        consented = personalization_allowed(session, user_id)
    if not consented:
        return False
    now = utcnow()
    rows = [
        {
            "id": e.event_id or uuid.uuid4(),
            "user_id": user_id,
            "recipe_id": e.recipe_id,
            "meal_plan_id": e.meal_plan_id,
            "meal_plan_item_id": e.meal_plan_item_id,
            "type": e.type,
            "position": e.position,
            "swap_reason": e.swap_reason,
            "ranker_version_id": e.ranker_version_id,
            "propensity": e.propensity,
            "occurred_at": e.occurred_at,
            "received_at": now,
        }
        for e in events
    ]
    if not rows:
        return True
    _insert(session, user_id, rows)
    if any(r["type"] in _SIGNAL_TYPES for r in rows):
        invalidate_popularity_cache(session)
    return True


def record_batch(session: Session, user_id: uuid.UUID, batch: EventBatch) -> EventBatchResult:
    """POST /events: dedupe by event_id; a plan or item that is not the caller's is a 422 (composite FKs)."""
    ids = [e.event_id for e in batch.events]
    if len(set(ids)) != len(ids):
        raise ApiError(
            422,
            ProblemCode.validation_error,
            errors=[{"pointer": "/events", "code": "duplicate_event_id", "message": "event_id lặp trong cùng lô"}],
        )
    if not personalization_allowed(session, user_id):
        return EventBatchResult(accepted=0, duplicates=0, skipped_no_consent=len(batch.events))
    now = utcnow()
    rows = [
        {
            "id": e.event_id,
            "user_id": user_id,
            "recipe_id": e.recipe_id,
            "meal_plan_id": e.meal_plan_id,
            "meal_plan_item_id": e.meal_plan_item_id,
            "type": e.type,
            "position": e.position,
            "swap_reason": e.swap_reason,
            "occurred_at": e.occurred_at,
            "received_at": now,
        }
        for e in batch.events
    ]
    try:
        with session.begin_nested():
            accepted = _insert(session, user_id, rows)
    except IntegrityError:
        raise ApiError(
            422,
            ProblemCode.validation_error,
            errors=[
                {
                    "pointer": "/events",
                    "code": "unknown_reference",
                    "message": "recipe_id, meal_plan_id hoặc meal_plan_item_id không tồn tại hoặc không thuộc bạn",
                }
            ],
        ) from None
    if accepted and any(e.type in _SIGNAL_TYPES for e in batch.events):
        invalidate_popularity_cache(session)
    return EventBatchResult(accepted=accepted, duplicates=len(rows) - accepted, skipped_no_consent=0)


def count(session: Session, user_id: uuid.UUID, *, meal_plan_id: uuid.UUID, types: Iterable[str]) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(Interaction)
            .where(
                Interaction.user_id == user_id,
                Interaction.meal_plan_id == meal_plan_id,
                Interaction.type.in_(list(types)),
            )
        )
        or 0
    )


def cooked_items(
    session: Session, user_id: uuid.UUID, meal_plan_id: uuid.UUID
) -> list[tuple[uuid.UUID, uuid.UUID | None]]:
    """(recipe_id, meal_plan_item_id) of the plan's `cooked` events, for the `undone` events of UC21."""
    return [
        (r, i)
        for r, i in session.execute(
            select(Interaction.recipe_id, Interaction.meal_plan_item_id).where(
                Interaction.user_id == user_id, Interaction.meal_plan_id == meal_plan_id, Interaction.type == "cooked"
            )
        )
    ]


def _signals(session: Session, user_id: uuid.UUID | None) -> dict[uuid.UUID, RecipeSignal]:
    q = select(Interaction.recipe_id, Interaction.type, Interaction.swap_reason, func.count()).group_by(
        Interaction.recipe_id, Interaction.type, Interaction.swap_reason
    )
    if user_id is not None:
        q = q.where(Interaction.user_id == user_id)
    pos: dict[uuid.UUID, int] = defaultdict(int)
    neg: dict[uuid.UUID, int] = defaultdict(int)
    for rid, typ, reason, n in session.execute(q):
        if typ in ("liked", "cooked"):
            pos[rid] += n
        elif typ == "disliked" or (typ == "swapped" and reason == "khong_hop_gu"):
            neg[rid] += n
    return {rid: RecipeSignal(pos.get(rid, 0), neg.get(rid, 0)) for rid in set(pos) | set(neg)}


def popularity(session: Session) -> dict[uuid.UUID, RecipeSignal]:
    """Aggregate over every user who consented (only they have rows): the item-average signal of BR-CONSENT-03.
    Cached with a short TTL and invalidated on signal writes/erasure to avoid full-table scans per plan."""
    key = _cache_db_key(session)
    now = pytime.monotonic()
    with _pop_lock:
        cached = _pop_cache.get(key)
    if cached is not None and now < cached[0]:
        if not cached[1] or bool(session.execute(text("SELECT EXISTS (SELECT 1 FROM interactions LIMIT 1)")).scalar()):
            return dict(cached[1])
    fresh = _signals(session, None)
    with _pop_lock:
        _pop_cache[key] = (pytime.monotonic() + POPULARITY_TTL_S, fresh)
    return dict(fresh)


def personal_signals(session: Session, user_id: uuid.UUID) -> dict[uuid.UUID, RecipeSignal]:
    """The user's own history; callers read it only with a current consent (FR-15-17)."""
    return _signals(session, user_id)


def export_interactions_since(
    session: Session, *, user_ids: set[uuid.UUID], since_utc: datetime
) -> list[TrainingInteractionRow]:
    if not user_ids:
        return []
    rows = session.scalars(
        select(Interaction)
        .where(Interaction.user_id.in_(user_ids), Interaction.occurred_at >= since_utc)
        .order_by(Interaction.occurred_at, Interaction.id)
    )
    return [
        TrainingInteractionRow(
            user_id=r.user_id,
            recipe_id=r.recipe_id,
            meal_plan_id=r.meal_plan_id,
            meal_plan_item_id=r.meal_plan_item_id,
            type=r.type,
            position=r.position,
            swap_reason=r.swap_reason,
            ranker_version_id=r.ranker_version_id,
            propensity=float(r.propensity) if r.propensity is not None else None,
            occurred_at=r.occurred_at,
        )
        for r in rows
    ]


class EventsSubjectData:
    name = "events"

    def export(self, session: Session, user_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
        rows = session.scalars(
            select(Interaction).where(Interaction.user_id == user_id).order_by(Interaction.occurred_at)
        )
        return {
            "interactions": [
                {
                    "id": str(r.id),
                    "type": r.type,
                    "recipe_id": str(r.recipe_id),
                    "meal_plan_id": str(r.meal_plan_id) if r.meal_plan_id else None,
                    "swap_reason": r.swap_reason,
                    "occurred_at": r.occurred_at.isoformat(),
                }
                for r in rows
            ]
        }

    def erase_purpose(self, session: Session, user_id: uuid.UUID, purpose: str) -> None:
        if purpose == PURPOSE:  # BR-CONSENT-04: withdrawing personalization deletes the behaviour data
            session.execute(text("SELECT public.erase_user_interactions(:u)"), {"u": user_id})
            invalidate_popularity_cache(session)

    def erase_files(self, user_id: uuid.UUID) -> None:
        return None
