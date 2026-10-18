"""scan public interface (M08): UC12 (send photos, inference job, long-poll), UC13 (edit chips, confirm, discard),
UC32 (purge photos after 30 days), UC34 (stuck scans) and the scan part of data-subject requests.

State machine ST01 lives in `scans.status`. Only `confirm` writes the pantry (BR-SCAN-02), in the request's Unit of
Work together with done → confirmed, under `SELECT … FOR UPDATE` of the scan row, so two devices confirming at once
write the pantry once and the second gets the same result (FR-13-17, UC13 11b).

Files (ADR 0002): photos are stored once, already sanitised, under the storage volume at
    tmp/scans/<user_id>/<scan_id>/<ordinal>.jpg        not contributed: deleted 30 days after the scan (BR-RETAIN-01)
    contrib/<user_id>/<scan_id>/<ordinal>.jpg          contributed (photo_contribution consent at upload)
and served by nginx through X-Accel-Redirect after the ownership check.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import Response
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session, sessionmaker

from tastoria.core.auth import AuthUser
from tastoria.core.clock import utcnow
from tastoria.core.config import Settings
from tastoria.core.errors import ApiError, ProblemCode
from tastoria.modules.catalog import service as catalog
from tastoria.modules.catalog.schemas import IngredientView
from tastoria.modules.mlops import service as mlops
from tastoria.modules.pantry import service as pantry
from tastoria.modules.pantry.schemas import ScanLotInput
from tastoria.modules.privacy import service as privacy
from tastoria.modules.scan import images as img
from tastoria.modules.scan.aggregate import Probs, u_img
from tastoria.modules.scan.models import Detection, Scan, ScanImage, ScanItem
from tastoria.modules.scan.queue import MAX_QUEUED, ScanQueue
from tastoria.modules.scan.schemas import (
    DetectionOut,
    ScanAccepted,
    ScanConfirmRequest,
    ScanConfirmResult,
    ScanImageOut,
    ScanItemCreate,
    ScanItemOut,
    ScanItemPatch,
    ScanOut,
    UnseenLot,
)

log = logging.getLogger("tastoria.scan")

MAX_IMAGES = 2
MAX_WAIT_S = 10
RETENTION_DAYS = 30  # BR-RETAIN-01
STUCK_S = 60  # ST01: sweeper threshold
MAX_AGE_S = 300  # FR-34-11: a scan not finished 5 minutes after creation is expired
PENDING = ("queued", "processing")


@dataclass
class ScanDeps:
    """Installed by tastoria.app on app.state.scan (and built by the worker / scheduler)."""

    settings: Settings
    sessionmaker: sessionmaker[Session]
    queue: ScanQueue

    @property
    def storage(self) -> Path:
        return Path(self.settings.storage_dir)


# ---------------------------------------------------------------- helpers


def _owned(session: Session, user_id: uuid.UUID, scan_id: uuid.UUID, *, lock: bool = False) -> Scan:
    q = select(Scan).where(Scan.id == scan_id, Scan.user_id == user_id)
    if lock:
        q = q.with_for_update()
    s = session.scalars(q).one_or_none()
    if s is None:
        raise ApiError(404, ProblemCode.not_found)  # FR-12-14: someone else's scan looks missing
    return s


def image_key(user_id: uuid.UUID, scan_id: uuid.UUID, ordinal: int, contributed: bool) -> str:
    root = "contrib" if contributed else "tmp/scans"
    return f"{root}/{user_id}/{scan_id}/{ordinal}.jpg"


def _write_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def is_count_kind(ing: IngredientView) -> bool:
    """A chip of this ingredient is counted (final_count) rather than given a level (qty_level)."""
    return ing.countable and bool(ing.units)


# ---------------------------------------------------------------- UC12: create


def request_digest(mode: str, shelf_groups: list[int] | None, contribute: bool | None, raws: list[bytes]) -> bytes:
    """Hash of the logical request (multipart boundaries differ between two sends of the same photos)."""
    canon = json.dumps(
        {
            "mode": mode,
            "shelf_groups": shelf_groups,
            "contribute": contribute,
            "images": [hashlib.sha256(r).hexdigest() for r in raws],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(b"POST\n/api/v1/scans\n" + canon.encode()).digest()


def _validation(pointer: str, code: str, message: str) -> ApiError:
    return ApiError(422, ProblemCode.validation_error, errors=[{"pointer": pointer, "code": code, "message": message}])


def create_scan(
    session: Session,
    deps: ScanDeps,
    user: AuthUser,
    *,
    mode: str,
    raws: list[bytes],
    shelf_groups: list[int] | None,
    contribute: bool | None,
) -> tuple[ScanAccepted, uuid.UUID]:
    if not 1 <= len(raws) <= MAX_IMAGES:
        raise _validation("/images", "count", "Gửi 1–2 ảnh.")
    groups = list(shelf_groups) if shelf_groups else [1] * len(raws)
    if len(groups) != len(raws) or any(g not in (1, 2) for g in groups):
        raise _validation("/shelf_groups", "shelf_groups", "Mỗi ảnh một số ngăn, 1 hoặc 2.")
    detector = mlops.active_version(session, "detector")
    if detector is None:
        raise ApiError(503, ProblemCode.model_unavailable, headers={"Retry-After": "30"})
    try:
        backlog = deps.queue.length()
    except Exception as exc:  # noqa: BLE001 — Valkey down: nothing would run the job
        raise ApiError(503, ProblemCode.service_unavailable, headers={"Retry-After": "5"}) from exc
    if backlog >= MAX_QUEUED:
        raise ApiError(503, ProblemCode.queue_full, headers={"Retry-After": "5"})
    cleaned = [img.sanitize(r, i) for i, r in enumerate(raws)]
    consent = privacy.has_consent(session, user.id, "photo_contribution")
    if contribute and not consent:
        raise ApiError(403, ProblemCode.consent_required, extra={"purpose": "photo_contribution"})
    contributed = consent and contribute is not False  # FR-12-17; contribute=false opts this scan out

    now = utcnow()
    scan = Scan(id=uuid.uuid4(), user_id=user.id, mode=mode, status="queued", attempts=0, created_at=now)
    session.add(scan)
    session.flush()
    written: list[Path] = []
    try:
        for i, (c, g) in enumerate(zip(cleaned, groups, strict=True), start=1):
            key = image_key(user.id, scan.id, i, contributed)
            path = deps.storage / key
            _write_file(path, c.jpeg)
            written.append(path)
            session.add(
                ScanImage(
                    scan_id=scan.id,
                    ordinal=i,
                    shelf_group=g,
                    storage_key=key,
                    width=c.width,
                    height=c.height,
                    contributed=contributed,
                )
            )
        session.flush()
    except BaseException:
        for p in written:
            p.unlink(missing_ok=True)
        raise
    return ScanAccepted(id=scan.id, created_at=now), scan.id


def enqueue_after_commit(deps: ScanDeps, scan_id: uuid.UUID) -> None:
    """After COMMIT (ADR 0007): push the job, then stamp enqueued_at. A failure here leaves enqueued_at NULL and the
    sweeper enqueues the scan a minute later (ST01)."""
    deps.queue.enqueue(scan_id, 1)
    with deps.sessionmaker() as s:
        s.execute(
            update(Scan)
            .where(Scan.id == scan_id, Scan.status == "queued", Scan.enqueued_at.is_(None))
            .values(enqueued_at=utcnow())
        )
        s.commit()


# ---------------------------------------------------------------- UC12/UC13: read


def _items_out(session: Session, scan: Scan) -> list[ScanItemOut]:
    if scan.status in ("queued", "processing", "failed", "expired"):
        return []
    items = list(
        session.scalars(
            select(ScanItem)
            .where(ScanItem.scan_id == scan.id, ScanItem.user_action != "deleted")
            .order_by(ScanItem.created_at, ScanItem.id)
        )
    )
    if not items:
        return []
    dets = session.execute(
        select(Detection, ScanImage.ordinal)
        .join(ScanImage, ScanImage.id == Detection.scan_image_id)
        .where(Detection.scan_item_id.in_([i.id for i in items]))
        .order_by(Detection.confidence.desc(), Detection.id)
    ).all()
    classes = catalog.vision_classes(session)
    by_item: dict[uuid.UUID, list[DetectionOut]] = {}
    probs_of: dict[uuid.UUID, Probs] = {}
    for d, ordinal in dets:
        by_item.setdefault(d.scan_item_id, []).append(
            DetectionOut(
                id=d.id,
                image_ordinal=ordinal,
                vision_class_code=classes[d.vision_class_id].code,
                x1=d.x1,
                y1=d.y1,
                x2=d.x2,
                y2=d.y2,
                confidence=d.confidence,
                p_tuoi=d.p_tuoi,
                p_dung_som=d.p_dung_som,
                p_dung_ngay=d.p_dung_ngay,
                p_kiem_tra=d.p_kiem_tra,
            )
        )
        if d.p_tuoi is not None:
            p = (d.p_tuoi, d.p_dung_som, d.p_dung_ngay, d.p_kiem_tra)
            if d.scan_item_id not in probs_of or u_img(p) > u_img(probs_of[d.scan_item_id]):  # type: ignore[arg-type]
                probs_of[d.scan_item_id] = p  # type: ignore[assignment]
    names = catalog.ingredients_by_ids(session, [i.ingredient_id for i in items])
    out = []
    for it in items:
        fr = pantry.image_freshness(probs_of.get(it.id))
        predicted = fr[1] if fr else None
        out.append(
            ScanItemOut(
                id=it.id,
                ingredient_id=it.ingredient_id,
                ingredient_name_vi=names[it.ingredient_id].name_vi,
                origin=it.origin,  # type: ignore[arg-type]
                model_count=it.model_count,
                final_count=it.final_count,
                qty_level=it.qty_level,  # type: ignore[arg-type]
                user_action=it.user_action,  # type: ignore[arg-type]
                original_ingredient_id=it.original_ingredient_id,
                predicted_freshness=predicted,  # type: ignore[arg-type]
                user_freshness=it.user_freshness,  # type: ignore[arg-type]
                needs_check=predicted == "kiem_tra" and it.user_freshness is None,
                detections=by_item.get(it.id, []),
                created_at=it.created_at,
                updated_at=it.updated_at,
            )
        )
    return out


def _probs_by_item(session: Session, item_ids: list[uuid.UUID]) -> dict[uuid.UUID, Probs]:
    out: dict[uuid.UUID, Probs] = {}
    if not item_ids:
        return out
    for d in session.scalars(
        select(Detection).where(Detection.scan_item_id.in_(item_ids), Detection.p_tuoi.isnot(None))
    ):
        p = (d.p_tuoi, d.p_dung_som, d.p_dung_ngay, d.p_kiem_tra)
        if d.scan_item_id not in out or u_img(p) > u_img(out[d.scan_item_id]):  # type: ignore[arg-type]
            out[d.scan_item_id] = p  # type: ignore[index, assignment]
    return out


def scan_out(session: Session, scan: Scan) -> ScanOut:
    images = list(session.scalars(select(ScanImage).where(ScanImage.scan_id == scan.id).order_by(ScanImage.ordinal)))
    items = _items_out(session, scan)
    unseen = None
    if scan.mode == "fridge" and scan.status == "done":
        lots = pantry.open_lots_without(session, scan.user_id, [i.ingredient_id for i in items])
        names = catalog.ingredients_by_ids(session, [lt.ingredient_id for lt in lots])
        unseen = [
            UnseenLot(lot_id=lt.id, ingredient_id=lt.ingredient_id, ingredient_name_vi=names[lt.ingredient_id].name_vi)
            for lt in lots
        ]
    return ScanOut(
        id=scan.id,
        mode=scan.mode,  # type: ignore[arg-type]
        status=scan.status,  # type: ignore[arg-type]
        error_code=scan.error_code,
        attempts=scan.attempts,
        created_at=scan.created_at,
        enqueued_at=scan.enqueued_at,
        started_at=scan.started_at,
        finished_at=scan.finished_at,
        confirmed_at=scan.confirmed_at,
        detector_version_id=scan.detector_version_id,
        classifier_version_id=scan.classifier_version_id,
        preprocess_version=scan.preprocess_version,
        images=[
            ScanImageOut(
                ordinal=i.ordinal,
                shelf_group=i.shelf_group,
                width=i.width,
                height=i.height,
                contributed=i.contributed,
                purged=i.purged_at is not None,
            )
            for i in images
        ],
        items=items,
        unseen_lots=unseen,
    )


def get_scan(session: Session, deps: ScanDeps, user: AuthUser, scan_id: uuid.UUID, wait: int) -> ScanOut:
    """GET /scans/{id}?wait= (FR-12-09). While waiting no database connection is held: the request transaction is
    ended, the wait is on the Valkey channel scan:<id>, and every check is a short read of its own."""
    scan = _owned(session, user.id, scan_id)
    if scan.status in PENDING and wait > 0:
        session.commit()  # returns the connection to the pool for the wait

        def settled() -> bool:
            with deps.sessionmaker() as s:
                st = s.execute(select(Scan.status).where(Scan.id == scan_id)).scalar_one_or_none()
            return st is None or st not in PENDING

        deps.queue.wait(scan_id, min(wait, MAX_WAIT_S), settled)
        session.expire_all()
        scan = _owned(session, user.id, scan_id)
    return scan_out(session, scan)


def image_response(session: Session, deps: ScanDeps, user: AuthUser, scan_id: uuid.UUID, ordinal: int) -> Response:
    _owned(session, user.id, scan_id)
    im = session.scalars(
        select(ScanImage).where(ScanImage.scan_id == scan_id, ScanImage.ordinal == ordinal)
    ).one_or_none()
    if im is None:
        raise ApiError(404, ProblemCode.not_found)
    if im.purged_at is not None:
        raise ApiError(410, ProblemCode.image_purged)
    return Response(
        status_code=200,
        media_type="image/jpeg",
        headers={
            "X-Accel-Redirect": deps.settings.accel_redirect_prefix + im.storage_key,
            "Cache-Control": "private, no-store",
        },
    )


# ---------------------------------------------------------------- UC13: chips


def _editable(session: Session, user_id: uuid.UUID, scan_id: uuid.UUID) -> Scan:
    scan = _owned(session, user_id, scan_id, lock=True)
    if scan.status != "done":
        raise ApiError(409, ProblemCode.scan_not_editable, extra={"status": scan.status})
    return scan


def _ingredient(session: Session, ingredient_id: uuid.UUID) -> IngredientView:
    ing = catalog.ingredients_by_ids(session, [ingredient_id]).get(ingredient_id)
    if ing is None or not ing.is_active:
        raise ApiError(422, ProblemCode.unknown_ingredient)
    return ing


def _check_kind(ing: IngredientView, *, final_count: int | None, qty_level: str | None) -> None:
    if final_count is not None and not is_count_kind(ing):
        raise ApiError(422, ProblemCode.qty_kind_mismatch, "Nguyên liệu này không đếm được; chọn mức ít/vừa/nhiều.")
    if qty_level is not None and is_count_kind(ing):
        raise ApiError(422, ProblemCode.qty_kind_mismatch, "Đồ đếm được: nhập số lượng.")


def _live_duplicate(
    session: Session, scan_id: uuid.UUID, ingredient_id: uuid.UUID, other_than: uuid.UUID | None
) -> bool:
    q = select(ScanItem.id).where(
        ScanItem.scan_id == scan_id, ScanItem.ingredient_id == ingredient_id, ScanItem.user_action != "deleted"
    )
    if other_than is not None:
        q = q.where(ScanItem.id != other_than)
    return session.execute(q.limit(1)).first() is not None


def _item_out(session: Session, scan: Scan, item_id: uuid.UUID) -> ScanItemOut:
    session.flush()
    return next(i for i in _items_out(session, scan) if i.id == item_id)


def add_item(session: Session, user: AuthUser, scan_id: uuid.UUID, body: ScanItemCreate) -> ScanItemOut:
    scan = _editable(session, user.id, scan_id)
    ing = _ingredient(session, body.ingredient_id)
    _check_kind(ing, final_count=body.final_count, qty_level=body.qty_level)
    if _live_duplicate(session, scan.id, ing.id, None):
        raise ApiError(409, ProblemCode.duplicate_item)
    now = utcnow()
    count = body.final_count if body.final_count is not None else (1 if is_count_kind(ing) else None)
    it = ScanItem(
        id=uuid.uuid4(),
        scan_id=scan.id,
        ingredient_id=ing.id,
        origin="user_added",
        model_count=None,
        final_count=count,
        qty_level=body.qty_level,
        user_action="kept",
        user_freshness=body.user_freshness,
        created_at=now,
        updated_at=now,
    )
    session.add(it)
    return _item_out(session, scan, it.id)


def _item(session: Session, scan: Scan, item_id: uuid.UUID) -> ScanItem:
    it = session.scalars(
        select(ScanItem).where(ScanItem.id == item_id, ScanItem.scan_id == scan.id).with_for_update()
    ).one_or_none()
    if it is None or it.user_action == "deleted":
        raise ApiError(404, ProblemCode.not_found)
    return it


def update_item(
    session: Session, user: AuthUser, scan_id: uuid.UUID, item_id: uuid.UUID, body: ScanItemPatch
) -> ScanItemOut:
    """JSON merge patch (FR-13-03, FR-13-04). No pantry write (FR-13-08)."""
    scan = _editable(session, user.id, scan_id)
    it = _item(session, scan, item_id)
    fields = body.model_fields_set
    changed = False
    relabeled = False
    ing = _ingredient(session, it.ingredient_id) if "ingredient_id" not in fields else None
    if "ingredient_id" in fields:
        if body.ingredient_id is None:
            raise _validation("/ingredient_id", "null", "ingredient_id không được null.")
        new = _ingredient(session, body.ingredient_id)
        if new.id != it.ingredient_id:
            if _live_duplicate(session, scan.id, new.id, it.id):
                raise ApiError(409, ProblemCode.duplicate_item)
            if it.origin == "model":
                if it.original_ingredient_id is None:
                    it.original_ingredient_id = it.ingredient_id
                elif it.original_ingredient_id == new.id:
                    it.original_ingredient_id = None  # back to the model's label
            it.ingredient_id = new.id
            relabeled = it.original_ingredient_id is not None
            # the amount kind follows the new ingredient
            if is_count_kind(new):
                it.qty_level = None
                if it.final_count is None:
                    it.final_count = it.model_count or 1
            else:
                it.final_count = None
            changed = True
        ing = new
    assert ing is not None
    count = body.final_count if "final_count" in fields else None
    level = body.qty_level if "qty_level" in fields else None
    _check_kind(ing, final_count=count, qty_level=level)
    if "final_count" in fields:
        if body.final_count is None and is_count_kind(ing):
            raise _validation("/final_count", "null", "Đồ đếm được cần số lượng.")
        if body.final_count != it.final_count:
            it.final_count = body.final_count
            changed = True
    if "qty_level" in fields and body.qty_level != it.qty_level:
        it.qty_level = body.qty_level
        changed = True
    if "user_freshness" in fields and body.user_freshness != it.user_freshness:
        it.user_freshness = body.user_freshness
        changed = True
    if changed:
        if relabeled or it.original_ingredient_id is not None:
            it.user_action = "relabeled"
        elif it.origin == "model":
            it.user_action = "edited"
        it.updated_at = utcnow()
    return _item_out(session, scan, it.id)


def delete_item(session: Session, user: AuthUser, scan_id: uuid.UUID, item_id: uuid.UUID) -> None:
    """FR-13-06: a model chip stays (user_action = deleted, signal for active learning); a user chip is removed.
    Deleting again answers 204 (idempotent)."""
    scan = _editable(session, user.id, scan_id)
    it = session.scalars(
        select(ScanItem).where(ScanItem.id == item_id, ScanItem.scan_id == scan.id).with_for_update()
    ).one_or_none()
    if it is None or it.user_action == "deleted":
        # a removed user chip leaves no row, so an unknown chip id of the caller's own editable scan is "already
        # deleted" too (the scan itself is owner-checked: nothing of another user can be probed this way)
        return None
    if it.origin == "user_added":
        session.delete(it)
    else:
        it.user_action = "deleted"
        it.updated_at = utcnow()
    session.flush()
    return None


# ---------------------------------------------------------------- UC13: confirm / discard


def _acquired(scan: Scan, settings: Settings, purchase_date: date | None, now: datetime) -> tuple[datetime, str]:
    """BR-PANTRY-01/03: haul = bought today (or the entered date); fridge = first seen at the scan, unless a date is
    entered. A date is turned into an instant in the server's time zone (the scan module does not read the user's
    settings): today → now, an earlier day → noon of that day."""
    if purchase_date is not None:
        tz = ZoneInfo(settings.timezone)
        today = now.astimezone(tz).date()
        if purchase_date > today:
            raise ApiError(422, ProblemCode.acquired_at_in_future)
        at = now if purchase_date == today else datetime.combine(purchase_date, time(12), tz)
        return at, "purchase_date_entered"
    if scan.mode == "haul":
        return now, "purchase_date_entered"
    return scan.created_at, "first_seen"


def _replay(session: Session, scan: Scan) -> ScanConfirmResult:
    item_ids = list(session.scalars(select(ScanItem.id).where(ScanItem.scan_id == scan.id)))
    assert scan.confirmed_at is not None
    return ScanConfirmResult(
        scan_id=scan.id,
        confirmed_at=scan.confirmed_at,
        created_lot_ids=pantry.scan_lot_ids(session, scan.user_id, item_ids),
        not_seen_lot_ids=pantry.lots_marked_at(session, scan.user_id, scan.confirmed_at)
        if scan.mode == "fridge"
        else [],
    )


def confirm(
    session: Session, deps: ScanDeps, user: AuthUser, scan_id: uuid.UUID, body: ScanConfirmRequest | None
) -> ScanConfirmResult:
    scan = _owned(session, user.id, scan_id, lock=True)
    if scan.status == "confirmed":
        return _replay(session, scan)
    if scan.status != "done":
        raise ApiError(409, ProblemCode.invalid_scan_state, extra={"status": scan.status})
    items = list(
        session.scalars(
            select(ScanItem)
            .where(ScanItem.scan_id == scan.id, ScanItem.user_action != "deleted")
            .order_by(ScanItem.created_at, ScanItem.id)
        )
    )
    probs = _probs_by_item(session, [i.id for i in items])
    labels = {i.id: (pantry.image_freshness(probs.get(i.id)) or (None, None))[1] for i in items}
    unchecked = [str(i.id) for i in items if labels[i.id] == "kiem_tra" and i.user_freshness is None]
    if unchecked:
        raise ApiError(409, ProblemCode.freshness_check_required, extra={"item_ids": unchecked})  # FR-13-09
    ings = catalog.ingredients_by_ids(session, [i.ingredient_id for i in items])
    missing_level = [str(i.id) for i in items if not is_count_kind(ings[i.ingredient_id]) and i.qty_level is None]
    if missing_level:
        raise ApiError(422, ProblemCode.qty_level_required, extra={"item_ids": missing_level})  # FR-13-11
    lots: list[ScanLotInput] = []
    for it in items:
        ing = ings[it.ingredient_id]
        if is_count_kind(ing):
            count = it.final_count if it.final_count is not None else it.model_count
            if not count:
                continue  # counted 0: nothing goes into the pantry
            try:
                g_min, g_max = pantry.chip_grams(session, ing, count=count, level=None)
            except ApiError as exc:
                exc.extra["item_id"] = str(it.id)
                raise
        else:
            g_min, g_max = pantry.chip_grams(session, ing, count=None, level=it.qty_level)
        checked = labels[it.id] == "kiem_tra" and it.user_freshness in ("tuoi", "dung_som", "dung_ngay")
        lots.append(ScanLotInput(it.id, it.ingredient_id, g_min, g_max, probs.get(it.id), checked))
    now = utcnow()
    acquired_at, basis = _acquired(scan, deps.settings, body.purchase_date if body else None, now)
    res = pantry.apply_scan(
        session,
        user.id,
        mode=scan.mode,
        items=lots,
        acquired_at=acquired_at,
        acquired_basis=basis,
        observed_at=scan.finished_at,
        model_version_id=scan.classifier_version_id,
        now=now,
    )
    scan.status = "confirmed"
    scan.confirmed_at = now
    session.flush()
    return ScanConfirmResult(
        scan_id=scan.id,
        confirmed_at=now,
        # same order as a replay reads them back (uuid order = PostgreSQL's)
        created_lot_ids=sorted(res.created_lot_ids, key=str),
        not_seen_lot_ids=sorted(res.not_seen_lot_ids, key=str),
    )


def discard(session: Session, user: AuthUser, scan_id: uuid.UUID) -> ScanOut:
    """FR-13-18: done → discarded, no pantry write; a resend on a discarded scan answers 200."""
    scan = _owned(session, user.id, scan_id, lock=True)
    if scan.status == "done":
        scan.status = "discarded"
        session.flush()
    elif scan.status != "discarded":
        raise ApiError(409, ProblemCode.invalid_scan_state, extra={"status": scan.status})
    return scan_out(session, scan)


# ---------------------------------------------------------------- UC34: stuck scans (scheduler)


def sweep_stuck_scans(session: Session, queue: ScanQueue | None) -> dict[str, int]:
    """ST01 sweeper: enqueue scans whose enqueue never happened; expire scans no worker is handling."""
    now = utcnow()
    stuck = now - timedelta(seconds=STUCK_S)
    oldest = now - timedelta(seconds=MAX_AGE_S)
    requeued = 0
    if queue is not None:
        rows = session.execute(
            select(Scan.id, Scan.attempts).where(
                Scan.status == "queued", Scan.enqueued_at.is_(None), Scan.created_at < stuck, Scan.created_at >= oldest
            )
        ).all()
        for sid, attempts in rows:
            try:
                queue.enqueue(sid, attempts + 1)
            except Exception:  # noqa: BLE001 — try again next minute; expiry below still applies
                log.warning("sweeper enqueue failed", extra={"scan_id": str(sid)})
                continue
            session.execute(update(Scan).where(Scan.id == sid, Scan.status == "queued").values(enqueued_at=utcnow()))
            requeued += 1
    expired = (
        session.execute(
            text(
                "UPDATE scans SET status = 'expired', error_code = 'stuck', finished_at = :now "
                "WHERE (status = 'queued' AND enqueued_at < :stuck) "
                "OR (status = 'processing' AND started_at < :stuck) "
                "OR (status IN ('queued', 'processing') AND created_at < :oldest) RETURNING id"
            ),
            {"now": now, "stuck": stuck, "oldest": oldest},
        )
        .scalars()
        .all()
    )
    if queue is not None:
        for sid in expired:
            queue.publish(sid, "expired")
    return {"scans_requeued": requeued, "scans_expired": len(expired)}


# ---------------------------------------------------------------- UC32: photo retention (scheduler)


def purge_images(session: Session, storage_dir: Path, *, now: datetime | None = None) -> dict[str, int]:
    """BR-RETAIN-01: delete non-contributed photos 30 days after their scan; mark them purged (the scan, its chips
    and boxes stay). Also removes upload directories left by a transaction that rolled back (no scan row)."""
    now = now or utcnow()
    cutoff = now - timedelta(days=RETENTION_DAYS)
    rows = (
        session.execute(
            select(ScanImage)
            .join(Scan, Scan.id == ScanImage.scan_id)
            .where(ScanImage.purged_at.is_(None), ScanImage.contributed.is_(False), Scan.created_at < cutoff)
            .with_for_update(of=ScanImage, skip_locked=True)
        )
        .scalars()
        .all()
    )
    for im in rows:
        (Path(storage_dir) / im.storage_key).unlink(missing_ok=True)
        im.purged_at = now
    session.flush()
    orphans = 0
    root = Path(storage_dir) / "tmp" / "scans"
    if root.is_dir():
        day_ago = (now - timedelta(days=1)).timestamp()
        for user_dir in root.iterdir():
            for scan_dir in user_dir.iterdir() if user_dir.is_dir() else ():
                try:
                    sid = uuid.UUID(scan_dir.name)
                except ValueError:
                    continue
                if scan_dir.stat().st_mtime > day_ago:
                    continue
                if session.get(Scan, sid) is None:
                    shutil.rmtree(scan_dir, ignore_errors=True)
                    orphans += 1
    return {"images_purged": len(rows), "orphan_dirs_removed": orphans}


# ---------------------------------------------------------------- data-subject requests


class ScanSubjectData:
    name = "scan"

    def __init__(self, storage_dir: Path) -> None:
        self.storage_dir = Path(storage_dir)

    def export(self, session: Session, user_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
        scans = list(session.scalars(select(Scan).where(Scan.user_id == user_id).order_by(Scan.created_at)))
        ids = [s.id for s in scans]
        ims = list(session.scalars(select(ScanImage).where(ScanImage.scan_id.in_(ids)))) if ids else []
        its = list(session.scalars(select(ScanItem).where(ScanItem.scan_id.in_(ids)))) if ids else []
        return {
            "scans": [
                {"id": str(s.id), "mode": s.mode, "status": s.status, "created_at": s.created_at.isoformat(),
                 "confirmed_at": s.confirmed_at.isoformat() if s.confirmed_at else None}
                for s in scans
            ],
            "scan_images": [
                {"scan_id": str(i.scan_id), "ordinal": i.ordinal, "width": i.width, "height": i.height,
                 "contributed": i.contributed, "purged_at": i.purged_at.isoformat() if i.purged_at else None}
                for i in ims
            ],
            "scan_items": [
                {"scan_id": str(i.scan_id), "ingredient_id": str(i.ingredient_id), "origin": i.origin,
                 "model_count": i.model_count, "final_count": i.final_count, "qty_level": i.qty_level,
                 "user_action": i.user_action}
                for i in its
            ],
        }  # fmt: skip

    def erase_purpose(self, session: Session, user_id: uuid.UUID, purpose: str) -> None:
        """Withdrawing photo_contribution (BR-CONSENT-04): contributed photos go back under the 30-day rule."""
        if purpose != "photo_contribution":
            return
        rows = (
            session.execute(
                select(ScanImage)
                .join(Scan, Scan.id == ScanImage.scan_id)
                .where(Scan.user_id == user_id, ScanImage.contributed.is_(True))
            )
            .scalars()
            .all()
        )
        for im in rows:
            new_key = image_key(user_id, im.scan_id, im.ordinal, False)
            src, dst = self.storage_dir / im.storage_key, self.storage_dir / new_key
            if im.purged_at is None and src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.replace(src, dst)
            im.storage_key = new_key
            im.contributed = False
        session.flush()

    def erase_files(self, user_id: uuid.UUID) -> None:
        for root in ("tmp/scans", "contrib"):
            shutil.rmtree(self.storage_dir / root / str(user_id), ignore_errors=True)
