"""Unit tests for M4-3 domain hardening: events validation/caching, cooking bounds, meal_logs schemas, copy hygiene."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from tastoria.core.clock import utcnow
from tastoria.core.errors import ApiError
from tastoria.modules.cooking import service as cooking_service
from tastoria.modules.cooking.schemas import CookCompleteRequest, CookSessionCreate
from tastoria.modules.events import service as events_service
from tastoria.modules.events.schemas import (
    SERVER_ONLY_INTERACTION_TYPES,
    Event,
    InteractionEventIn,
    RecipeSignal,
)
from tastoria.modules.journal.schemas import JournalDay, JournalWeek
from tastoria.modules.meal_logs.schemas import MealLogCreate, MealLogItemIn, normalize_source_type
from tastoria.modules.privacy import service as privacy_service


@pytest.mark.parametrize("bad_type", sorted(SERVER_ONLY_INTERACTION_TYPES))
def test_events_reject_server_only_types(bad_type: str) -> None:
    with pytest.raises(ValidationError):
        InteractionEventIn(
            event_id=uuid.uuid4(),
            type=bad_type,  # type: ignore[arg-type]
            recipe_id=uuid.uuid4(),
            meal_plan_id=uuid.uuid4(),
            occurred_at=datetime.now(UTC),
            swap_reason="khac" if bad_type == "swapped" else None,
        )


@pytest.mark.parametrize("ok_type", ["viewed", "liked", "disliked"])
def test_events_allow_client_types(ok_type: str) -> None:
    ev = InteractionEventIn(
        event_id=uuid.uuid4(),
        type=ok_type,  # type: ignore[arg-type]
        recipe_id=uuid.uuid4(),
        occurred_at=datetime.now(UTC),
    )
    assert ev.type == ok_type


def test_events_popularity_cache_and_invalidation(monkeypatch: pytest.MonkeyPatch) -> None:
    events_service.invalidate_popularity_cache()
    calls = 0
    rid = uuid.uuid4()

    def fake_signals(_session, _uid):
        nonlocal calls
        calls += 1
        return {rid: RecipeSignal(positive=3, negative=1)}

    monkeypatch.setattr(events_service, "_signals", fake_signals)
    fake_session = MagicMock()
    fake_session.get_bind.return_value = SimpleNamespace(url="sqlite:///unit-pop")
    fake_session.execute.return_value.scalar.return_value = True

    first = events_service.popularity(fake_session)
    second = events_service.popularity(fake_session)
    assert calls == 1
    assert first == second == {rid: RecipeSignal(positive=3, negative=1)}

    events_service.invalidate_popularity_cache(fake_session)
    third = events_service.popularity(fake_session)
    assert calls == 2
    assert third == {rid: RecipeSignal(positive=3, negative=1)}

    # Also resets when an empty DB truncation probe returns False
    fake_session.execute.return_value.scalar.return_value = False
    _ = events_service.popularity(fake_session)
    assert calls == 3


def test_events_record_invalidates_popularity_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    events_service.invalidate_popularity_cache()
    inv_calls = 0
    monkeypatch.setattr(events_service, "_insert", lambda *_a, **_kw: 1)
    real_invalidate = events_service.invalidate_popularity_cache

    def track_inv(sess=None):
        nonlocal inv_calls
        inv_calls += 1
        real_invalidate(sess)

    monkeypatch.setattr(events_service, "invalidate_popularity_cache", track_inv)
    fake_session = MagicMock()
    events_service.record(
        fake_session,
        uuid.uuid4(),
        [Event("viewed", uuid.uuid4(), datetime.now(UTC))],
        consented=True,
    )
    assert inv_calls == 0  # viewed does not alter taste signals
    events_service.record(
        fake_session,
        uuid.uuid4(),
        [Event("cooked", uuid.uuid4(), datetime.now(UTC))],
        consented=True,
    )
    assert inv_calls == 1


def test_cooking_rejects_naive_completed_at_and_far_future_serve_at() -> None:
    with pytest.raises(ValidationError):
        CookCompleteRequest(completed_at=datetime(2026, 11, 24, 12, 0))
    ok = CookCompleteRequest(completed_at=datetime(2026, 11, 24, 12, 0, tzinfo=UTC))
    assert ok.completed_at is not None and ok.completed_at.tzinfo is not None

    fake_session = MagicMock()
    fake_deps = MagicMock()
    user = SimpleNamespace(id=uuid.uuid4())

    with pytest.raises(ApiError) as naive_err:
        cooking_service.create_session(
            fake_session,
            fake_deps,
            user,  # type: ignore[arg-type]
            CookSessionCreate(meal_plan_id=uuid.uuid4(), serve_at=datetime(2026, 11, 24, 12, 0)),
        )
    assert naive_err.value.status == 422

    with pytest.raises(ApiError) as far_err:
        cooking_service.create_session(
            fake_session,
            fake_deps,
            user,  # type: ignore[arg-type]
            CookSessionCreate(meal_plan_id=uuid.uuid4(), serve_at=utcnow() + timedelta(days=8)),
        )
    assert far_err.value.status == 422
    assert far_err.value.errors and far_err.value.errors[0]["code"] == "too_far_in_future"


def test_meal_logs_schema_validation_and_normalization() -> None:
    assert normalize_source_type("calorie_scan") == "scan_calorie"
    assert normalize_source_type("scan_calorie") == "scan_calorie"
    assert normalize_source_type("barcode") == "barcode"

    created = MealLogCreate(
        meal_slot="trua",
        title="  Cơm tấm sườn  ",
        source_type="calorie_scan",
        kcal=650,
        kcal_low=580,
        kcal_high=720,
        protein_g=30,
        carbs_g=80,
        fat_g=22,
        fiber_g=4,
    )
    assert created.title == "Cơm tấm sườn"
    assert normalize_source_type(created.source_type) == "scan_calorie"

    for bad_num in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            MealLogCreate(meal_slot="trua", title="Phở", source_type="manual", kcal=bad_num)

    with pytest.raises(ValidationError):
        MealLogCreate(meal_slot="trua", title="Phở", source_type="manual", kcal=900, kcal_low=400, kcal_high=600)

    with pytest.raises(ValidationError):
        MealLogItemIn(label_vi="   ")

    day = JournalDay(
        date=datetime(2026, 11, 24, tzinfo=UTC).date(),
        cooked_trays=0,
        kcal_per_person=None,
        e_target_kcal=None,
        urgent_lots_used=0,
    )
    assert day.meal_logs_count == 0 and day.meal_logs_kcal == 0.0
    wk = JournalWeek(
        week="2026-W48",
        timezone="Asia/Ho_Chi_Minh",
        days=[day],
        kcal_range_status="calibrated",
        macros={"protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0, "fiber_g": 0.0},
        cooked_history=[],
    )
    assert wk.meal_logs == []


def test_privacy_copy_and_dsr_descriptions_are_clean() -> None:
    assert "meal_logs" in privacy_service._DESCRIPTIONS
    assert "meal_log_items" in privacy_service._DESCRIPTIONS
    for desc in privacy_service._DESCRIPTIONS.values():
        assert "ứng dụng" not in desc.lower()
        assert "tastoria" not in desc.lower()
        assert "—" not in desc and "·" not in desc and "–" not in desc
