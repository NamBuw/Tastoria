"""Urgency u and freshness label of a lot, computed at read time and never stored (BR-FRESH-01 … BR-FRESH-05).

    u_time = d / L          d = days (decimal) since acquired_at, L = ingredients.shelf_life_days
    u_img  = Σ_c P(c)·m(c)  m = 0.25 tươi, 0.65 dùng sớm, 0.9 dùng ngay, 1.2 kiểm tra
    u      = u_img                    when acquired_basis = first_seen and max P ≥ 0.6
           = max(u_time, u_img)       otherwise; a lot without freshness probabilities has u = u_time
    label  = tươi (u < 0.5) | dùng sớm [0.5, 0.8) | dùng ngay [0.8, 1.0] | kiểm tra (u > 1.0 or P(kiểm tra) largest)
           | chưa rõ (no L and no probabilities: counted as available, never rewarded — FR-14-05)

"Kiểm tra trước khi dùng" lots are not available until the user confirms them ("vẫn dùng được"): a confirmation newer
than the last freshness observation shows the lot as "dùng ngay" and available again (FR-14-15). The thresholds equal
the database GUCs tastoria.fresh_u_soon / fresh_u_check that v_journal_days reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

M = {"tuoi": 0.25, "dung_som": 0.65, "dung_ngay": 0.9, "kiem_tra": 1.2}
U_SOON = 0.5  # fresh_u_soon
U_NOW = 0.8
U_CHECK = 1.0  # fresh_u_check
P_TRUST_IMAGE = 0.6  # BR-FRESH-03


@dataclass(frozen=True)
class Freshness:
    urgency: float | None
    label: str  # tuoi | dung_som | dung_ngay | kiem_tra | chua_ro
    available: bool
    check_level: bool  # the lot is at "kiểm tra" before any user confirmation


def probabilities(p_tuoi, p_dung_som, p_dung_ngay, p_kiem_tra) -> dict[str, float] | None:  # noqa: ANN001
    if p_tuoi is None:
        return None
    return {"tuoi": p_tuoi, "dung_som": p_dung_som, "dung_ngay": p_dung_ngay, "kiem_tra": p_kiem_tra}


def urgency(
    *, now: datetime, acquired_at: datetime, basis: str, shelf_life_days: float | None, probs: dict[str, float] | None
) -> float | None:
    u_time = None
    if shelf_life_days:
        u_time = max(0.0, (now - acquired_at).total_seconds() / 86400) / shelf_life_days
    if probs is None:
        return u_time
    u_img = sum(probs[c] * M[c] for c in M)
    if u_time is None or (basis == "first_seen" and max(probs.values()) >= P_TRUST_IMAGE):
        return u_img
    return max(u_time, u_img)


def assess(
    *,
    now: datetime,
    acquired_at: datetime,
    basis: str,
    shelf_life_days: float | None,
    probs: dict[str, float] | None,
    user_checked_at: datetime | None,
    observed_at: datetime | None,
    status: str,
) -> Freshness:
    u = urgency(now=now, acquired_at=acquired_at, basis=basis, shelf_life_days=shelf_life_days, probs=probs)
    check = (u is not None and u > U_CHECK) or (probs is not None and probs["kiem_tra"] >= max(probs.values()))
    if check:
        confirmed = user_checked_at is not None and (observed_at is None or user_checked_at > observed_at)
        label, available = ("dung_ngay", True) if confirmed else ("kiem_tra", False)
    elif u is None:
        label, available = "chua_ro", True
    elif u < U_SOON:
        label, available = "tuoi", True
    elif u < U_NOW:
        label, available = "dung_som", True
    else:
        label, available = "dung_ngay", True
    if status != "in_stock":  # not_seen: waiting for "còn không?" (BR-PANTRY-03); closed lots hold nothing
        available = False
    return Freshness(u, label, available, check)


def rewarded(u: float | None, f: Freshness) -> bool:
    """U(m) counts only lots with a known u in [0.5, 1.0] that are not at check level (design v2 §6.2, FR-15-16)."""
    return u is not None and U_SOON <= u <= U_CHECK and not f.check_level
