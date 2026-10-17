"""Pure pantry rules: urgency/labels at the BR-FRESH-04 boundaries and interval deduction (BR-PANTRY-02)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from tastoria.modules.pantry.service import round_up_to_unit, split_need
from tastoria.modules.pantry.urgency import assess, urgency

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def _label(u_days: float, L: float = 10.0, **kw) -> tuple[str, bool]:  # noqa: N803
    f = assess(now=NOW, acquired_at=NOW - timedelta(days=u_days * L), basis="purchase_date_entered",
               shelf_life_days=L, probs=None, user_checked_at=None, observed_at=None, status="in_stock", **kw)  # fmt: skip
    return f.label, f.available


@pytest.mark.parametrize(
    ("u", "label"),
    [(0.0, "tuoi"), (0.49, "tuoi"), (0.5, "dung_som"), (0.79, "dung_som"), (0.8, "dung_ngay"), (1.0, "dung_ngay"),
     (1.01, "kiem_tra")],
)  # fmt: skip
def test_label_boundaries(u: float, label: str) -> None:
    assert _label(u)[0] == label
    assert _label(u)[1] is (label != "kiem_tra")


def test_u_time_is_read_time() -> None:  # FR-14-06
    acquired = NOW - timedelta(days=1)
    assert urgency(now=NOW, acquired_at=acquired, basis="first_seen", shelf_life_days=5, probs=None) == pytest.approx(
        0.2
    )
    later = NOW + timedelta(days=3)
    assert urgency(now=later, acquired_at=acquired, basis="first_seen", shelf_life_days=5, probs=None) == pytest.approx(
        0.8
    )


def test_trusted_image_wins_only_without_a_purchase_date() -> None:
    probs = {"tuoi": 0.6, "dung_som": 0.4, "dung_ngay": 0.0, "kiem_tra": 0.0}  # u_img = 0.41, max P = 0.6
    old = NOW - timedelta(days=9)
    assert urgency(now=NOW, acquired_at=old, basis="first_seen", shelf_life_days=10, probs=probs) == pytest.approx(0.41)
    assert urgency(now=NOW, acquired_at=old, basis="purchase_date_entered", shelf_life_days=10,
                   probs=probs) == pytest.approx(0.9)  # fmt: skip


def test_not_seen_lots_are_not_available() -> None:
    f = assess(now=NOW, acquired_at=NOW, basis="first_seen", shelf_life_days=5, probs=None, user_checked_at=None,
               observed_at=None, status="not_seen")  # fmt: skip
    assert f.label == "tuoi" and f.available is False


bounds = st.lists(
    st.tuples(st.floats(0, 2000, allow_nan=False), st.floats(0, 2000, allow_nan=False)).map(lambda t: tuple(sorted(t))),
    max_size=6,
)


@given(need=st.floats(0, 5000, allow_nan=False), lots=bounds)
def test_split_need_is_interval_arithmetic(need: float, lots: list[tuple[float, float]]) -> None:
    out = split_need(need, lots)
    assert len(out) == len(lots)
    for (lo, hi), (nlo, nhi) in zip(lots, out, strict=True):
        assert 0 <= nlo <= lo + 1e-9 and 0 <= nhi <= hi + 1e-9 and nlo <= nhi + 1e-9
    removed_lo = sum(lo - nlo for (lo, _), (nlo, _) in zip(lots, out, strict=True))
    removed_hi = sum(hi - nhi for (_, hi), (_, nhi) in zip(lots, out, strict=True))
    assert removed_lo == pytest.approx(min(need, sum(lo for lo, _ in lots)), abs=1e-6)
    assert removed_hi == pytest.approx(min(need, sum(hi for _, hi in lots)), abs=1e-6)


def test_split_need_examples() -> None:
    assert split_need(150, [(100, 100), (200, 200)]) == [(0, 0), (150, 150)]  # FR-20-07
    assert split_need(150, [(100, 200)]) == [(0, 50)]


def test_round_up_to_unit() -> None:
    assert round_up_to_unit(110, 50) == 150 and round_up_to_unit(100, 50) == 100 and round_up_to_unit(70, None) == 70
