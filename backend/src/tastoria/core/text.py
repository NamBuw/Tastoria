"""Vietnamese text folding for search: "Đậu phụ" and "dau phu" match (openapi: tìm không dấu cũng khớp)."""

from __future__ import annotations

import unicodedata


def fold(s: str) -> str:
    """Lower case, no diacritics, đ → d, single spaces."""
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return " ".join(s.casefold().split())
