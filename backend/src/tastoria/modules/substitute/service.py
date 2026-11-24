"""substitute public interface (M10): substitution candidates from the curated lookup table and the shopping list.

Candidates (design v2 §6.3, FR-17-04 … FR-17-06): pairs of `substitution_pairs` for the missing ingredient whose
context (slot, cooking method) matches the dish — exact context first, then slot-only, method-only, context-free —
by score; hard filter: same food group, active, not the original, and no allergen group or diet-excluded food group
of the user and the co-eaters (BR-ALG-01, BR-DIET-01). Embedding neighbours need a deployed substitution model and
are not served yet (FR-17-07: the lookup table alone answers).

Shopping items (UC18): FR-18-05 merges a repeated add of the same ingredient from the same plan item; the plan item
must belong to the caller, which only meal can tell — the check is installed by tastoria.app (no import of meal here,
meal depends on substitute).
"""

from __future__ import annotations

import unicodedata
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import Request
from sqlalchemy import delete, select, text, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from tastoria.core import pagination
from tastoria.core.auth import AuthUser
from tastoria.core.clock import utcnow
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.catalog import service as catalog
from tastoria.modules.mlops import service as mlops
from tastoria.modules.pantry import service as pantry
from tastoria.modules.substitute.models import ShoppingItem, SubstitutionPair
from tastoria.modules.substitute.schemas import (
    Candidate,
    CuratedPair,
    ShoppingItemCreate,
    ShoppingItemOut,
    ShoppingItemPage,
    ShoppingItemPatch,
    ShoppingItemToPantryOut,
    ShoppingItemToPantryRequest,
)

MAX_CANDIDATES = 3
TRANSITIONS = {("open", "bought"), ("open", "dropped"), ("bought", "open"), ("dropped", "open")}  # FR-18-07


@dataclass(frozen=True)
class SubstituteDeps:
    item_owned: Callable[[Session, uuid.UUID, uuid.UUID], bool]  # (session, user_id, meal_plan_item_id)


def substitute_deps(request: Request) -> SubstituteDeps:
    return request.app.state.substitute


# ---------------------------------------------------------------- candidates


def _context_rank(p: SubstitutionPair, slot: str, method: str) -> int | None:
    if p.context_slot not in (None, slot) or p.context_method_code not in (None, method):
        return None  # a pair for another context does not apply here
    return {(True, True): 0, (True, False): 1, (False, True): 2, (False, False): 3}[
        (p.context_slot is not None, p.context_method_code is not None)
    ]


def candidates(
    session: Session,
    original_id: uuid.UUID,
    *,
    slot: str,
    method: str,
    allergens: Iterable[str],
    excluded_groups: Iterable[str],
    limit: int = MAX_CANDIDATES,
) -> list[Candidate]:
    original = catalog.ingredients_by_ids(session, [original_id]).get(original_id)
    if original is None:
        return []
    pairs = [
        (rank, p)
        for p in session.scalars(select(SubstitutionPair).where(SubstitutionPair.ingredient_id == original_id))
        if (rank := _context_rank(p, slot, method)) is not None
    ]
    subs = catalog.ingredients_by_ids(session, [p.substitute_id for _, p in pairs])
    banned, excl = set(allergens), set(excluded_groups)
    out: list[Candidate] = []
    seen: set[uuid.UUID] = set()
    for _, p in sorted(pairs, key=lambda x: (x[0], -x[1].score, str(x[1].substitute_id))):
        sub = subs.get(p.substitute_id)
        if (
            sub is None
            or sub.id in seen
            or sub.id == original.id
            or not sub.is_active
            or sub.food_group_code != original.food_group_code
            or not catalog.ingredient_allowed(sub, banned, excl)
        ):
            continue
        seen.add(sub.id)
        out.append(Candidate(sub, float(p.ratio), float(p.score), "lookup"))
        if len(out) >= limit:
            break
    if len(out) < limit and (sub_ver := mlops.active_version(session, "substitution")) is not None:
        rows = session.execute(
            text(
                "SELECT e2.ingredient_id, 1.0 - (e2.vector <=> e1.vector) AS sim "
                "FROM ingredient_embeddings e1 "
                "JOIN ingredient_embeddings e2 "
                "  ON e2.model_version_id = e1.model_version_id "
                " AND e2.ingredient_id <> e1.ingredient_id "
                "JOIN ingredients i ON i.id = e2.ingredient_id "
                "WHERE e1.model_version_id = :vid "
                "  AND e1.ingredient_id = :orig_id "
                "  AND i.is_active "
                "  AND i.food_group_code = :fg "
                "ORDER BY e2.vector <=> e1.vector ASC, e2.ingredient_id ASC "
                "LIMIT :fetch_limit"
            ),
            {
                "vid": sub_ver.id,
                "orig_id": original.id,
                "fg": original.food_group_code,
                "fetch_limit": max(25, limit * 5),
            },
        ).all()
        if rows:
            emb_subs = catalog.ingredients_by_ids(session, [r.ingredient_id for r in rows])
            for r in rows:
                sub = emb_subs.get(r.ingredient_id)
                if (
                    sub is None
                    or sub.id in seen
                    or sub.id == original.id
                    or not sub.is_active
                    or sub.food_group_code != original.food_group_code
                    or not catalog.ingredient_allowed(sub, banned, excl)
                ):
                    continue
                seen.add(sub.id)
                score = round(max(0.0, min(1.0, float(r.sim))), 4)
                out.append(Candidate(sub, 1.0, score, "embedding"))
                if len(out) >= limit:
                    break
    return out


def sync_embeddings(session: Session, *, model_version_id: uuid.UUID, npz_path: Path) -> dict[str, int]:
    """Load (N, 100) float vectors from `.npz` and upsert into `ingredient_embeddings` for `model_version_id`."""
    import numpy as np

    with np.load(npz_path, allow_pickle=False) as z:
        vectors = np.asarray(z["vectors"], dtype=np.float32)
        names_vi = [unicodedata.normalize("NFC", str(n)) for n in z["names_vi"]]
    if vectors.ndim != 2 or vectors.shape[1] != 100:
        raise ValueError(f"vectors shape {vectors.shape} must be (N, 100)")
    if not np.all(np.isfinite(vectors)):
        raise ValueError("vectors contain NaN or Inf")

    by_name = {
        unicodedata.normalize("NFC", v.name_vi): v.id for v in catalog.active_ingredients(session).values()
    }
    matched_ids: list[uuid.UUID] = []
    unmatched = 0
    upsert_sql = text(
        "INSERT INTO ingredient_embeddings (ingredient_id, model_version_id, vector) "
        "VALUES (:iid, :vid, CAST(:vec AS vector)) "
        "ON CONFLICT (ingredient_id, model_version_id) DO UPDATE SET vector = EXCLUDED.vector"
    )
    for name, row in zip(names_vi, vectors, strict=True):
        iid = by_name.get(name)
        if iid is None:
            unmatched += 1
            continue
        matched_ids.append(iid)
        vec_str = "[" + ",".join(f"{float(x):.8f}" for x in row) + "]"
        session.execute(upsert_sql, {"iid": iid, "vid": model_version_id, "vec": vec_str})
    if matched_ids:
        session.execute(
            text(
                "DELETE FROM ingredient_embeddings "
                "WHERE model_version_id = :vid AND NOT (ingredient_id = ANY(:ids))"
            ),
            {"vid": model_version_id, "ids": matched_ids},
        )
    else:
        session.execute(
            text("DELETE FROM ingredient_embeddings WHERE model_version_id = :vid"),
            {"vid": model_version_id},
        )
    session.flush()
    return {"upserted": len(matched_ids), "unmatched": unmatched}


def pair_ratio(session: Session, original_id: uuid.UUID, substitute_id: uuid.UUID, *, slot: str, method: str) -> float:
    """Ratio of the best matching pair (FR-17-08), 1 when the pair is not in the table (origin = user)."""
    best = None
    for p in session.scalars(
        select(SubstitutionPair).where(
            SubstitutionPair.ingredient_id == original_id, SubstitutionPair.substitute_id == substitute_id
        )
    ):
        rank = _context_rank(p, slot, method)
        if rank is not None and (best is None or rank < best[0]):
            best = (rank, float(p.ratio))
    return best[1] if best else 1.0


# ---------------------------------------------------------------- curated table import (UC26 data, via admin)


def sync_curated_pairs(session: Session, pairs: list[CuratedPair]) -> dict[str, int]:
    """Make the curated rows of `substitution_pairs` equal to `pairs` (idempotent): insert new keys, update changed
    ratio/score/source, delete curated rows whose key is gone. Rows proposed by a model (curated = false) are kept,
    unless the file now holds the same key — then the curated row replaces them."""
    existing = {
        (p.ingredient_id, p.substitute_id, p.context_slot, p.context_method_code): p
        for p in session.scalars(select(SubstitutionPair).with_for_update())
    }
    counts = {"inserted": 0, "updated": 0, "unchanged": 0, "removed": 0}
    wanted = set()
    for c in pairs:
        wanted.add(c.key)
        row = existing.get(c.key)
        if row is None:
            session.add(
                SubstitutionPair(
                    id=uuid.uuid4(),
                    ingredient_id=c.ingredient_id,
                    substitute_id=c.substitute_id,
                    context_slot=c.context_slot,
                    context_method_code=c.context_method_code,
                    ratio=c.ratio,
                    score=c.score,
                    source=c.source,
                    curated=True,
                )
            )
            counts["inserted"] += 1
        elif (
            Decimal(row.ratio) != c.ratio
            or abs(float(row.score) - c.score) > 1e-6  # real (float4) column
            or row.source != c.source
            or not row.curated
        ):
            row.ratio, row.score, row.source, row.curated = c.ratio, c.score, c.source, True
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
    gone = [r.id for k, r in existing.items() if r.curated and k not in wanted]
    if gone:
        session.execute(delete(SubstitutionPair).where(SubstitutionPair.id.in_(gone)))
    counts["removed"] = len(gone)
    session.flush()
    return counts


# ---------------------------------------------------------------- shopping items (UC18)


def _out(session: Session, rows: list[ShoppingItem]) -> list[ShoppingItemOut]:
    names = {k: v.name_vi for k, v in catalog.ingredients_by_ids(session, [r.ingredient_id for r in rows]).items()}
    return [
        ShoppingItemOut(
            id=r.id,
            ingredient_id=r.ingredient_id,
            ingredient_name_vi=names[r.ingredient_id],
            qty_g=float(r.qty_g) if r.qty_g is not None else None,
            note=r.note,
            status=r.status,  # type: ignore[arg-type]
            source_meal_plan_item_id=r.source_meal_plan_item_id,
            pantry_lot_id=r.pantry_lot_id,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rows
    ]


def list_items(
    session: Session, user: AuthUser, *, statuses: list[str], cursor: str | None, limit: int
) -> ShoppingItemPage:
    after = pagination.decode_created(cursor)
    q = (
        select(ShoppingItem)
        .where(ShoppingItem.user_id == user.id, ShoppingItem.status.in_(statuses or ["open"]))
        .order_by(ShoppingItem.created_at, ShoppingItem.id)
        .limit(limit + 1)
    )
    if after is not None:
        q = q.where(tuple_(ShoppingItem.created_at, ShoppingItem.id) > after)
    rows = list(session.scalars(q))
    page = rows[:limit]
    nxt = pagination.encode_created(page[-1].created_at, page[-1].id) if len(rows) > limit else None
    return ShoppingItemPage(items=_out(session, page), next_cursor=nxt)


def create_item(
    session: Session, deps: SubstituteDeps, user: AuthUser, body: ShoppingItemCreate
) -> tuple[ShoppingItemOut, bool]:
    """Returns (item, created). An open row for the same ingredient and plan item is updated instead (FR-18-05)."""
    ing = catalog.ingredients_by_ids(session, [body.ingredient_id]).get(body.ingredient_id)
    if ing is None or not ing.is_active:
        raise ApiError(422, ProblemCode.unknown_ingredient)
    src = body.source_meal_plan_item_id
    if src is not None and not deps.item_owned(session, user.id, src):
        raise ApiError(404, ProblemCode.not_found)  # FR-18-06
    now = utcnow()
    q = select(ShoppingItem).where(
        ShoppingItem.user_id == user.id, ShoppingItem.ingredient_id == ing.id, ShoppingItem.status == "open"
    )
    q = q.where(
        ShoppingItem.source_meal_plan_item_id.is_(None) if src is None else ShoppingItem.source_meal_plan_item_id == src
    )
    qty = Decimal(str(body.qty_g)) if body.qty_g is not None else None
    for _ in range(3):
        existing = session.scalars(q.with_for_update()).first()
        if existing is not None:
            if existing.qty_g != qty or existing.note != body.note:
                existing.qty_g, existing.note, existing.updated_at = qty, body.note, now
            session.flush()
            return _out(session, [existing])[0], False
        conflict_cols = (
            ["user_id", "ingredient_id"]
            if src is None
            else ["user_id", "ingredient_id", "source_meal_plan_item_id"]
        )
        conflict_where = (
            text("status = 'open' AND source_meal_plan_item_id IS NULL")
            if src is None
            else text("status = 'open' AND source_meal_plan_item_id IS NOT NULL")
        )
        new_id = uuid.uuid4()
        ins = (
            pg_insert(ShoppingItem)
            .values(
                id=new_id,
                user_id=user.id,
                ingredient_id=ing.id,
                qty_g=qty,
                note=body.note,
                status="open",
                source_meal_plan_item_id=src,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=conflict_cols, index_where=conflict_where)
            .returning(ShoppingItem.id)
        )
        inserted_id = session.execute(ins).scalar_one_or_none()
        if inserted_id is not None:
            created_row = session.scalars(select(ShoppingItem).where(ShoppingItem.id == inserted_id)).one()
            return _out(session, [created_row])[0], True
    existing = session.scalars(q.with_for_update()).first()
    assert existing is not None
    if existing.qty_g != qty or existing.note != body.note:
        existing.qty_g, existing.note, existing.updated_at = qty, body.note, now
    session.flush()
    return _out(session, [existing])[0], False


def update_item(session: Session, user: AuthUser, item_id: uuid.UUID, body: ShoppingItemPatch) -> ShoppingItemOut:
    row = session.scalars(
        select(ShoppingItem).where(ShoppingItem.id == item_id, ShoppingItem.user_id == user.id).with_for_update()
    ).one_or_none()
    if row is None:
        raise ApiError(404, ProblemCode.not_found)  # FR-18-09
    fields = body.model_fields_set
    changed = False
    target = body.status if "status" in fields and body.status is not None else row.status
    edits = {f: getattr(body, f) for f in ("qty_g", "note") if f in fields}
    if "qty_g" in edits and edits["qty_g"] is not None:
        edits["qty_g"] = Decimal(str(edits["qty_g"]))
    if any(getattr(row, f) != v for f, v in edits.items()):
        if row.status != "open" and target != "open":
            raise ApiError(409, ProblemCode.conflict_state, "Chỉ sửa lượng, ghi chú khi dòng đang open.")  # FR-18-08
        for f, v in edits.items():
            setattr(row, f, v)
        changed = True
    if target != row.status:
        if (row.status, target) not in TRANSITIONS:
            raise ApiError(409, ProblemCode.conflict_state, extra={"from": row.status, "to": target})
        row.status = target
        changed = True
    if changed:  # FR-18-10: the same PATCH again changes nothing, not even updated_at
        row.updated_at = utcnow()
    session.flush()
    return _out(session, [row])[0]


def to_pantry(
    session: Session,
    user: AuthUser,
    item_id: uuid.UUID,
    body: ShoppingItemToPantryRequest | None = None,
) -> ShoppingItemToPantryOut:
    row = session.scalars(
        select(ShoppingItem).where(ShoppingItem.id == item_id, ShoppingItem.user_id == user.id).with_for_update()
    ).one_or_none()
    if row is None:
        raise ApiError(404, ProblemCode.not_found)
    if row.status == "dropped":
        raise ApiError(409, ProblemCode.conflict_state, "Không thể đưa mục đã bỏ vào kho.")
    if row.pantry_lot_id is not None:
        raise ApiError(
            409,
            ProblemCode.conflict_state,
            "Mục này đã được đưa vào kho.",
            extra={"pantry_lot_id": str(row.pantry_lot_id)},
        )
    qty = body.qty_g if (body is not None and body.qty_g is not None) else (
        float(row.qty_g) if row.qty_g is not None else None
    )
    if qty is None:
        raise ApiError(
            422,
            ProblemCode.validation_error,
            errors=[{"pointer": "/qty_g", "code": "qty_required", "message": "Cần nhập khối lượng (gam) để đưa vào kho."}],
        )
    lot = pantry.create_lot_with_ledger(
        session,
        user,
        ingredient_id=row.ingredient_id,
        g_min=qty,
        g_max=qty,
        acquired_at=body.acquired_at if body is not None else None,
        acquired_basis="purchase_date_entered",
    )
    row.pantry_lot_id = lot.id
    row.status = "bought"
    if body is not None and body.qty_g is not None and row.qty_g is None:
        row.qty_g = Decimal(str(body.qty_g))
    row.updated_at = utcnow()
    session.flush()
    return ShoppingItemToPantryOut(shopping_item=_out(session, [row])[0], pantry_lot=lot)


# ---------------------------------------------------------------- data-subject requests


def _iso(d: datetime) -> str:
    return d.isoformat()


class SubstituteSubjectData:
    name = "substitute"

    def export(self, session: Session, user_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
        rows = session.scalars(
            select(ShoppingItem).where(ShoppingItem.user_id == user_id).order_by(ShoppingItem.created_at)
        )
        return {
            "shopping_items": [
                {
                    "id": str(r.id),
                    "ingredient_id": str(r.ingredient_id),
                    "qty_g": float(r.qty_g) if r.qty_g is not None else None,
                    "note": r.note,
                    "status": r.status,
                    "created_at": _iso(r.created_at),
                }
                for r in rows
            ]
        }

    def erase_purpose(self, session: Session, user_id: uuid.UUID, purpose: str) -> None:
        return None

    def erase_files(self, user_id: uuid.UUID) -> None:
        return None
