"""Single source of "now" (UTC, timezone-aware) so tests can move application time without sleeping."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

_offset = timedelta(0)


def utcnow() -> datetime:
    return datetime.now(UTC) + _offset


def local_year(tz: str = "Asia/Ho_Chi_Minh") -> int:
    return utcnow().astimezone(ZoneInfo(tz)).year


def shift_for_tests(seconds: float) -> None:
    """Tests only: move the application clock (PostgreSQL now() is not affected)."""
    global _offset
    _offset = timedelta(seconds=seconds)
