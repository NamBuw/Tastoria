"""Valkey client (RQ queue later, login-failure counters now). Valkey is never the source of truth (ADR 0003)."""

from __future__ import annotations

import valkey


def make_valkey(url: str) -> valkey.Valkey:
    return valkey.Valkey.from_url(url, socket_timeout=2, socket_connect_timeout=2, decode_responses=True)
