"""catalog public interface (M04) — the lookups profile needs in this slice."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from tastoria.modules.catalog.models import AllergenGroup, Diet, Recipe


def unknown_allergen_codes(session: Session, codes: Iterable[str]) -> list[str]:
    wanted = set(codes)
    if not wanted:
        return []
    known = set(session.scalars(select(AllergenGroup.code).where(AllergenGroup.code.in_(wanted))).all())
    return sorted(wanted - known)


def diet_exists(session: Session, code: str) -> bool:
    return session.get(Diet, code) is not None


def not_published_recipe_ids(session: Session, recipe_ids: Iterable[uuid.UUID]) -> list[uuid.UUID]:
    """Ids that do not exist or are not `published` (draft, retired)."""
    wanted = list(dict.fromkeys(recipe_ids))
    if not wanted:
        return []
    ok = set(session.scalars(select(Recipe.id).where(Recipe.id.in_(wanted), Recipe.status == "published")).all())
    return [r for r in wanted if r not in ok]
