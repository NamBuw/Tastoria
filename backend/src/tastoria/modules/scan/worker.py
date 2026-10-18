"""The inference job and the worker process (spec v2 §8, SD01, ST01).

`tastoria worker` (container `worker`): loads the deployed detector once — SHA-256 checked, onnxruntime session with
2 intra-op threads and no spinning — and only then starts an RQ SimpleWorker on the `scan` queue. SimpleWorker runs
jobs in the worker process itself (no fork per job), so the ONNX session and the database pool are reused, and RQ's
SIGALRM death penalty enforces the 30 s job timeout (FR-12-10). Without a deployed detector, or with a wrong
SHA-256, the process exits with an error and Compose restarts it (SD10).

One job = one attempt of one scan:
  claim     UPDATE scans SET status = 'processing', attempts + 1, started_at, versions WHERE status = 'queued';
            no row → the scan was expired / discarded / already handled: the job does nothing;
  infer     read the stored photos, detect, aggregate into chips (no database transaction is open meanwhile);
  write     scan_items + detections + status done in one transaction, guarded by status = 'processing'
            (a scan the sweeper expired meanwhile is left expired);
  failure   (any exception, including RQ's timeout) attempts < 3 → back to queued + a new job for the next attempt;
            attempts = 3 → failed with error_code (FR-12-19).
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image
from rq.timeouts import JobTimeoutException
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from tastoria.core.clock import utcnow
from tastoria.modules.catalog import service as catalog
from tastoria.modules.mlops.schemas import ModelVersionView
from tastoria.modules.scan.aggregate import ClassRule, FoundBox, build_chips
from tastoria.modules.scan.detector import Box, Detector
from tastoria.modules.scan.models import Detection, Scan, ScanImage, ScanItem
from tastoria.modules.scan.queue import MAX_ATTEMPTS, ScanQueue

log = logging.getLogger("tastoria.scan.worker")


@dataclass
class WorkerContext:
    sessionmaker: sessionmaker[Session]
    storage_dir: Path
    queue: ScanQueue
    detector: Detector
    detector_version: ModelVersionView
    freshness_version: ModelVersionView | None = None  # no freshness model is deployed yet (p_* stay NULL)
    timings: list[dict[str, float]] = field(default_factory=list)  # last jobs, for logs and tests


_ctx: WorkerContext | None = None


def install(ctx: WorkerContext | None) -> None:
    global _ctx
    _ctx = ctx


def infer(scan_id: str) -> str:
    """RQ entry point (queue.JOB_FUNC)."""
    if _ctx is None:
        raise RuntimeError("scan worker context not installed (run `tastoria worker`)")
    return run_job(_ctx, uuid.UUID(scan_id))


@dataclass(frozen=True)
class _Photo:
    id: uuid.UUID
    ordinal: int
    shelf_group: int
    storage_key: str


def _claim(ctx: WorkerContext, scan_id: uuid.UUID) -> tuple[int, list[_Photo]] | None:
    with ctx.sessionmaker() as s:
        now = utcnow()
        row = s.execute(
            update(Scan)
            .where(Scan.id == scan_id, Scan.status == "queued")
            .values(
                status="processing",
                started_at=now,
                attempts=Scan.attempts + 1,
                detector_version_id=ctx.detector_version.id,
                classifier_version_id=ctx.freshness_version.id if ctx.freshness_version else None,
                preprocess_version=ctx.detector_version.preprocess_version,
                error_code=None,
            )
            .returning(Scan.attempts, Scan.enqueued_at)
        ).first()
        if row is None:
            s.rollback()
            return None
        if row.enqueued_at is None:  # the API's stamp lost the race with this worker
            s.execute(update(Scan).where(Scan.id == scan_id).values(enqueued_at=now))
        photos = [
            _Photo(i.id, i.ordinal, i.shelf_group, i.storage_key)
            for i in s.scalars(select(ScanImage).where(ScanImage.scan_id == scan_id).order_by(ScanImage.ordinal))
        ]
        s.commit()
    return int(row.attempts), photos


def _detect(ctx: WorkerContext, photos: list[_Photo]) -> list[tuple[_Photo, Box]]:
    out = []
    for p in photos:
        with Image.open(ctx.storage_dir / p.storage_key) as im:
            rgb = im.convert("RGB")
        for b in ctx.detector.detect(rgb):
            out.append((p, b))
    return out


def _write(ctx: WorkerContext, scan_id: uuid.UUID, found: list[tuple[_Photo, Box]]) -> bool:
    class_map = ctx.detector_version.class_map
    with ctx.sessionmaker() as s:
        scan = s.scalars(select(Scan).where(Scan.id == scan_id).with_for_update()).one_or_none()
        if scan is None or scan.status != "processing":
            s.rollback()
            return False  # expired by the sweeper (or the account was deleted) meanwhile
        classes = catalog.vision_classes(s)
        rules = {vid: ClassRule(v.countable, v.default_ingredient_id) for vid, v in classes.items()}
        boxes = [FoundBox(p.ordinal - 1, p.shelf_group, class_map[b.class_index], b.confidence) for p, b in found]
        chips = build_chips(boxes, rules)
        ings = catalog.ingredients_by_ids(s, [c.ingredient_id for c in chips])
        now = utcnow()
        item_of_box: dict[int, uuid.UUID] = {}
        for c in chips:
            ing = ings[c.ingredient_id]
            counted = ing.countable and bool(ing.units)
            item = ScanItem(
                id=uuid.uuid4(),
                scan_id=scan_id,
                ingredient_id=c.ingredient_id,
                origin="model",
                model_count=c.model_count,
                final_count=(c.model_count or 1) if counted else None,
                qty_level=None,  # the user picks ít / vừa / nhiều (FR-13-11)
                user_action="kept",
                created_at=now,
                updated_at=now,
            )
            s.add(item)
            for i in c.boxes:
                item_of_box[i] = item.id
        s.flush()
        for i, (p, b) in enumerate(found):
            s.add(
                Detection(
                    scan_image_id=p.id,
                    scan_item_id=item_of_box.get(i),
                    vision_class_id=class_map[b.class_index],
                    x1=b.x1,
                    y1=b.y1,
                    x2=b.x2,
                    y2=b.y2,
                    confidence=b.confidence,
                )
            )
        scan.status = "done"
        scan.finished_at = now
        s.commit()
    return True


def _fail(ctx: WorkerContext, scan_id: uuid.UUID, attempts: int, code: str) -> str:
    with ctx.sessionmaker() as s:
        if attempts < MAX_ATTEMPTS:
            n = s.execute(
                update(Scan)
                .where(Scan.id == scan_id, Scan.status == "processing")
                .values(status="queued", error_code=code, enqueued_at=utcnow())
            ).rowcount
            s.commit()
            if n:
                ctx.queue.enqueue(scan_id, attempts + 1)
            return "requeued"
        s.execute(
            update(Scan)
            .where(Scan.id == scan_id, Scan.status == "processing")
            .values(status="failed", error_code=code, finished_at=utcnow())
        )
        s.commit()
    ctx.queue.publish(scan_id, "failed")
    return "failed"


def run_job(ctx: WorkerContext, scan_id: uuid.UUID) -> str:
    t0 = time.perf_counter()
    claimed = _claim(ctx, scan_id)
    if claimed is None:
        return "skipped"
    attempts, photos = claimed
    try:
        t1 = time.perf_counter()
        found = _detect(ctx, photos)
        t2 = time.perf_counter()
        ok = _write(ctx, scan_id, found)
        t3 = time.perf_counter()
    except JobTimeoutException:
        log.warning("scan job timed out", extra={"scan_id": str(scan_id), "attempts": attempts})
        return _fail(ctx, scan_id, attempts, "timeout")
    except Exception as exc:  # noqa: BLE001 — every inference error is retried, then reported (FR-12-19)
        log.exception("scan job failed", extra={"scan_id": str(scan_id), "attempts": attempts})
        return _fail(ctx, scan_id, attempts, f"inference_error:{type(exc).__name__}"[:64])
    if not ok:
        return "dropped"
    ctx.queue.publish(scan_id, "done")
    timing = {"claim_ms": (t1 - t0) * 1e3, "infer_ms": (t2 - t1) * 1e3, "write_ms": (t3 - t2) * 1e3,
              "boxes": float(len(found)), "images": float(len(photos))}  # fmt: skip
    ctx.timings = (ctx.timings + [timing])[-100:]
    log.info("scan done", extra={"scan_id": str(scan_id), **{k: round(v, 1) for k, v in timing.items()}})
    return "done"
