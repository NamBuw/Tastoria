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

import hashlib
import json
import logging
import math
import os
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from rq.timeouts import JobTimeoutException
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from tastoria.core.clock import utcnow
from tastoria.core.health import metrics
from tastoria.modules.catalog import service as catalog
from tastoria.modules.mlops.schemas import ModelVersionView
from tastoria.modules.scan.aggregate import ClassRule, FoundBox, Probs, build_chips
from tastoria.modules.scan.detector import MAX_DETECTIONS_PER_PHOTO, Box, Detector
from tastoria.modules.scan.freshness import (
    DEFAULT_PAD,
    DEFAULT_SIZE,
    FreshnessClassifier,
    crop_box_pixels,
    letterbox_crop,
)
from tastoria.modules.scan.models import Detection, Scan, ScanImage, ScanItem
from tastoria.modules.scan.queue import MAX_ATTEMPTS, ScanQueue

log = logging.getLogger("tastoria.scan.worker")

MUSHROOM_SLUGS: tuple[str, ...] = (
    "nam-rom",
    "nam-huong-tuoi",
    "nam-kim-cham",
    "nam-dui-ga",
    "nam-so",
    "nam-mo",
)
MUSHROOM_SLUG_TO_NAME_VI: dict[str, str] = {
    "nam-rom": "nấm rơm",
    "nam-huong-tuoi": "nấm hương tươi",
    "nam-kim-cham": "nấm kim châm",
    "nam-dui-ga": "nấm đùi gà",
    "nam-so": "nấm sò",
    "nam-mo": "nấm mỡ",
}
MUSHROOM_CULINARY_PROB_MIN = 0.85
MUSHROOM_OTHER_PROB_MAX = 0.03
MUSHROOM_NOT_MUSHROOM_PROB_MIN = 0.50
MUSHROOM_NOT_MUSHROOM_OTHER_MAX = 0.15
MUSHROOM_NOT_MUSHROOM_MARGIN_MIN = 0.15
MUSHROOM_OOD_CLASS = "other_mushroom"
MUSHROOM_NOT_MUSHROOM_CLASS = "not_mushroom"
INTRA_OP_THREADS = 2
MUSHROOM_BATCH_SIZE = 16


@dataclass(frozen=True)
class MushroomPrediction:
    sub_species_slug: str | None
    sub_species_conf: float | None
    safety_abstained: bool = False
    suppress_not_mushroom: bool = False


class MushroomClassifier:
    """Direction 1 8-class FungiCLEF safety-gated mushroom sub-classifier (mushroom_classifier.serving.v1)."""

    def __init__(self, session, *, serving: dict[str, Any] | None = None) -> None:  # noqa: ANN001
        self.session = session
        inp = session.get_inputs()[0]
        self.input_name = inp.name
        self.size = int(inp.shape[2]) if len(inp.shape) == 4 and isinstance(inp.shape[2], int) else DEFAULT_SIZE

        serving = serving or {}
        inp_cfg = serving.get("input") or {}
        self.pad_value = int(inp_cfg.get("pad_value", DEFAULT_PAD))
        safety = serving.get("safety") or {}
        abst = serving.get("abstention") or {}
        self.tau = float(safety.get("culinary_prob_min", abst.get("tau", MUSHROOM_CULINARY_PROB_MIN)))
        self.other_max = float(safety.get("other_mushroom_prob_max", abst.get("other_mushroom_max", MUSHROOM_OTHER_PROB_MAX)))
        raw_et = safety.get("energy_threshold", abst.get("energy_threshold"))
        self.energy_threshold: float | None = float(raw_et) if raw_et is not None else None
        self.ood_class = str(abst.get("ood_class") or MUSHROOM_OOD_CLASS)
        self.not_mushroom_class = str(abst.get("not_mushroom_class") or MUSHROOM_NOT_MUSHROOM_CLASS)
        cal = serving.get("calibration") or {}
        self.temperature = float(cal.get("temperature", 1.0))
        out_cfg = serving.get("output") or {}
        self.cal_in_onnx = bool(out_cfg.get("calibration_applied_in_onnx", False))
        raw_classes = serving.get("classes") or []
        self.classes = (
            [str(c["id"]) if isinstance(c, dict) else str(c) for c in raw_classes]
            if raw_classes
            else [*MUSHROOM_SLUGS, MUSHROOM_OOD_CLASS, MUSHROOM_NOT_MUSHROOM_CLASS]
        )
        self._other_idx = self.classes.index(self.ood_class) if self.ood_class in self.classes else None

        out_names = [o.name for o in session.get_outputs()]
        self._probs_idx = out_names.index("probs") if "probs" in out_names else None
        self._logits_idx = out_names.index("logits") if "logits" in out_names else 0

    def _postprocess_row(self, probs: np.ndarray, energy: float | None) -> MushroomPrediction:
        n = min(len(probs), len(self.classes))
        if n == 0:
            return MushroomPrediction(None, None, safety_abstained=True, suppress_not_mushroom=False)
        p = np.asarray(probs[:n], dtype=np.float64)
        if not np.all(np.isfinite(p)) or np.any(p < 0.0) or np.any(p > 1.0 + 1e-3):
            return MushroomPrediction(None, None, safety_abstained=True, suppress_not_mushroom=False)
        if energy is not None and not np.isfinite(energy):
            return MushroomPrediction(None, None, safety_abstained=True, suppress_not_mushroom=False)
        tot = float(p.sum())
        if tot <= 0.0:
            return MushroomPrediction(None, None, safety_abstained=True, suppress_not_mushroom=False)
        p = p / tot
        idx = int(np.argmax(p))
        conf = float(p[idx])
        slug = self.classes[idx]
        p_other = float(p[self._other_idx]) if (self._other_idx is not None and self._other_idx < n) else 0.0

        # 1. Suppress false-positive non-mushroom detector boxes only when clear & far from other_mushroom
        if slug == self.not_mushroom_class:
            if (
                conf >= MUSHROOM_NOT_MUSHROOM_PROB_MIN
                and p_other < MUSHROOM_NOT_MUSHROOM_OTHER_MAX
                and (conf - p_other) >= MUSHROOM_NOT_MUSHROOM_MARGIN_MIN
            ):
                return MushroomPrediction(None, None, safety_abstained=False, suppress_not_mushroom=True)
            return MushroomPrediction(None, None, safety_abstained=True, suppress_not_mushroom=False)

        # 2. FungiCLEF c_PSC=100 3-condition safety gate
        energy_ok = self.energy_threshold is None or (energy is not None and energy <= self.energy_threshold)
        if slug in MUSHROOM_SLUG_TO_NAME_VI and conf >= self.tau and p_other < self.other_max and energy_ok:
            return MushroomPrediction(sub_species_slug=slug, sub_species_conf=round(conf, 6))

        # 3. Safe abstention to generic mushroom warning
        return MushroomPrediction(None, None, safety_abstained=True, suppress_not_mushroom=False)

    def predict_crops(
        self, crops: Sequence[Image.Image], *, batch_size: int = MUSHROOM_BATCH_SIZE
    ) -> list[MushroomPrediction]:
        if not crops:
            return []
        step = max(1, int(batch_size))
        t = 1.0 if self.cal_in_onnx else (self.temperature if self.temperature > 0.0 else 1.0)
        results: list[MushroomPrediction] = []
        for start in range(0, len(crops), step):
            chunk = crops[start : start + step]
            batch = np.stack([letterbox_crop(c, self.size, self.pad_value) for c in chunk], axis=0)
            t0 = time.perf_counter()
            outcome = "ok"
            try:
                raw_outs = self.session.run(None, {self.input_name: batch})
            except Exception:
                outcome = "error"
                raise
            finally:
                metrics.observe_onnx("mushroom_classifier", time.perf_counter() - t0, outcome=outcome)
            if self._probs_idx is not None and self.cal_in_onnx:
                probs_batch = np.asarray(raw_outs[self._probs_idx], dtype=np.float64)
                for row in probs_batch:
                    if not np.all(np.isfinite(row)) or np.any(row < 0.0) or np.any(row > 1.0 + 1e-3):
                        results.append(MushroomPrediction(None, None, safety_abstained=True, suppress_not_mushroom=False))
                    else:
                        results.append(self._postprocess_row(row, None))
                continue

            logits = np.asarray(raw_outs[self._logits_idx], dtype=np.float64)
            for row in logits:
                if not np.all(np.isfinite(row)):
                    results.append(MushroomPrediction(None, None, safety_abstained=True, suppress_not_mushroom=False))
                    continue
                scaled = row / t
                m = float(scaled.max())
                exp_s = np.exp(scaled - m)
                sum_exp = float(exp_s.sum())
                if not np.isfinite(sum_exp) or sum_exp <= 0.0:
                    results.append(MushroomPrediction(None, None, safety_abstained=True, suppress_not_mushroom=False))
                    continue
                probs = exp_s / sum_exp
                e_val = float(-t * (m + np.log(sum_exp)))
                if not np.isfinite(e_val) or not np.all(np.isfinite(probs)):
                    results.append(MushroomPrediction(None, None, safety_abstained=True, suppress_not_mushroom=False))
                    continue
                results.append(self._postprocess_row(probs, e_val))
        return results


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_mushroom_classifier(model_dir: Path, *, verify_sha256: bool = True) -> MushroomClassifier:
    import onnxruntime as ort

    model_dir = Path(model_dir)
    serving_path = model_dir / "serving.json"
    if not serving_path.is_file():
        raise FileNotFoundError(f"Missing serving.json in {model_dir}")
    serving = json.loads(serving_path.read_text(encoding="utf-8"))
    artifact_name = str(serving.get("artifact_file") or "model.onnx")
    onnx_path = model_dir / artifact_name
    if not onnx_path.is_file():
        raise FileNotFoundError(f"Missing ONNX artifact {onnx_path}")
    if verify_sha256:
        expected = serving.get("artifact_sha256")
        if not expected:
            raise ValueError(f"Missing artifact_sha256 in {serving_path}")
        actual = _sha256_file(onnx_path)
        if actual != expected:
            raise ValueError(f"SHA-256 mismatch for {onnx_path}: expected {expected}, got {actual}")
    so = ort.SessionOptions()
    so.intra_op_num_threads = INTRA_OP_THREADS
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    so.add_session_config_entry("session.inter_op.allow_spinning", "0")
    sess = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])
    return MushroomClassifier(sess, serving=serving)


def _default_mushroom_dirs() -> tuple[Path, ...]:
    repo_root = Path(__file__).resolve().parents[5]
    return (
        Path("/app/models/mushroom_classifier"),
        Path("/opt/tastoria/models/mushroom_classifier"),
        repo_root / "deploy" / "models" / "mushroom_classifier",
    )


def resolve_mushroom_model_dir() -> Path | None:
    env_val = os.environ.get("TASTORIA_MUSHROOM_CLASSIFIER_MODEL_DIR")
    if env_val is not None:
        cleaned = env_val.strip()
        if not cleaned or cleaned.lower() in {"none", "off", "disabled"}:
            return None
        cand = Path(cleaned)
        return cand if (cand / "serving.json").is_file() else None
    for cand in _default_mushroom_dirs():
        if (cand / "serving.json").is_file():
            return cand
    return None


_mushroom_lock = threading.Lock()
_mushroom_cache: dict[Path, MushroomClassifier] = {}


def _get_mushroom_classifier(ctx: WorkerContext) -> MushroomClassifier | None:
    if ctx.mushroom_classifier is not None:
        return ctx.mushroom_classifier
    model_dir = resolve_mushroom_model_dir()
    if model_dir is None:
        return None
    resolved = model_dir.resolve()
    with _mushroom_lock:
        cached = _mushroom_cache.get(resolved)
        if cached is not None:
            return cached
        try:
            clf = load_mushroom_classifier(resolved, verify_sha256=True)
        except Exception as exc:  # noqa: BLE001 — optional sub-classifier must never crash scan worker
            log.warning("mushroom_classifier unavailable at %s: %s", resolved, exc)
            return None
        _mushroom_cache[resolved] = clf
        return clf


@dataclass
class WorkerContext:
    sessionmaker: sessionmaker[Session]
    storage_dir: Path
    queue: ScanQueue
    detector: Detector
    detector_version: ModelVersionView
    freshness_version: ModelVersionView | None = None
    timings: list[dict[str, float]] = field(default_factory=list)  # last jobs, for logs and tests
    freshness: FreshnessClassifier | None = None
    mushroom_classifier: MushroomClassifier | None = None


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


def _claim(ctx: WorkerContext, scan_id: uuid.UUID) -> tuple[int, list[_Photo], int | None, frozenset[int]] | None:
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
        classes = catalog.vision_classes(s)
        nam_vid = next((vid for vid, vc in classes.items() if vc.code == "nam"), None)
        freshness_vids = frozenset(vid for vid, vc in classes.items() if vc.has_freshness_model)
        s.commit()
    return int(row.attempts), photos, nam_vid, freshness_vids


def _detect(
    ctx: WorkerContext,
    photos: list[_Photo],
    *,
    nam_vid: int | None = None,
    freshness_vids: frozenset[int] | None = None,
) -> list[tuple[_Photo, Box, Probs | None, MushroomPrediction | None]]:
    out: list[tuple[_Photo, Box, Probs | None, MushroomPrediction | None]] = []
    nam_indices = {ci for ci, vid in ctx.detector_version.class_map.items() if nam_vid is not None and vid == nam_vid}
    for p in photos:
        with Image.open(ctx.storage_dir / p.storage_key) as im:
            rgb = im.convert("RGB")
        boxes = ctx.detector.detect(rgb)[:MAX_DETECTIONS_PER_PHOTO]
        fresh_positions = [
            idx
            for idx, b in enumerate(boxes)
            if ctx.freshness is not None
            and (freshness_vids is None or ctx.detector_version.class_map.get(b.class_index) in freshness_vids)
        ]
        nam_positions = [idx for idx, b in enumerate(boxes) if b.class_index in nam_indices]
        needed_positions = sorted(set(fresh_positions) | set(nam_positions))
        crops_by_pos = (
            {idx: rgb.crop(crop_box_pixels(boxes[idx], rgb.width, rgb.height)) for idx in needed_positions}
            if needed_positions
            else {}
        )
        probs_list: list[Probs | None] = [None] * len(boxes)
        if ctx.freshness is not None and fresh_positions:
            raw_probs = list(ctx.freshness.predict_crops([crops_by_pos[idx] for idx in fresh_positions]))
            for pos, pr in zip(fresh_positions, raw_probs, strict=True):
                probs_list[pos] = (
                    pr if (pr is not None and len(pr) == 4 and all(math.isfinite(x) for x in pr)) else (0.0, 0.0, 0.0, 1.0)
                )

        mush_list: list[MushroomPrediction | None] = [None] * len(boxes)
        if nam_positions:
            mclf = _get_mushroom_classifier(ctx)
            if mclf is not None:
                try:
                    nam_preds = mclf.predict_crops([crops_by_pos[idx] for idx in nam_positions])
                    log.info(
                        "mushroom sub-classifier",
                        extra={
                            "crops": len(nam_preds),
                            "species": [mp.sub_species_slug for mp in nam_preds],
                            "abstained": sum(1 for mp in nam_preds if mp.safety_abstained),
                            "suppressed": sum(1 for mp in nam_preds if mp.suppress_not_mushroom),
                        },
                    )
                except Exception as exc:  # noqa: BLE001 — unexpected ONNX error abstains safely
                    log.warning(
                        "mushroom sub-classifier failed; abstaining safely",
                        extra={"crops": len(nam_positions), "error": repr(exc)},
                    )
                    nam_preds = [
                        MushroomPrediction(None, None, safety_abstained=True, suppress_not_mushroom=False)
                        for _ in nam_positions
                    ]
                for pos, pred in zip(nam_positions, nam_preds, strict=True):
                    mush_list[pos] = pred
            else:
                for pos in nam_positions:
                    mush_list[pos] = MushroomPrediction(None, None, safety_abstained=True, suppress_not_mushroom=False)

        for b, pr, mp in zip(boxes, probs_list, mush_list, strict=True):
            if mp is not None and mp.suppress_not_mushroom:
                continue  # suppress false-positive `nam` detections classified as not_mushroom
            out.append((p, b, pr, mp))
    return out


def _write(
    ctx: WorkerContext,
    scan_id: uuid.UUID,
    found: list[tuple[_Photo, Box, Probs | None, MushroomPrediction | None]],
) -> bool:
    class_map = ctx.detector_version.class_map
    with ctx.sessionmaker() as s:
        scan = s.scalars(select(Scan).where(Scan.id == scan_id).with_for_update()).one_or_none()
        if scan is None or scan.status != "processing":
            s.rollback()
            return False  # expired by the sweeper (or the account was deleted) meanwhile
        classes = catalog.vision_classes(s)
        agg_rules = {vid: ClassRule(v.countable, v.default_ingredient_id) for vid, v in classes.items()}
        slug_to_agg_vid: dict[str, int] = {}
        if any(mp is not None and mp.sub_species_slug is not None for _, _, _, mp in found):
            nam_ings = catalog.active_ingredients(s, food_group_code="nam")
            nam_by_name = {ing.name_vi: ing.id for ing in nam_ings.values()}
            nam_vclass = next((v for v in classes.values() if v.code == "nam"), None)
            nam_countable = nam_vclass.countable if nam_vclass is not None else False
            for idx, slug in enumerate(MUSHROOM_SLUGS):
                ing_id = nam_by_name.get(MUSHROOM_SLUG_TO_NAME_VI[slug])
                if ing_id is not None:
                    syn_vid = -(idx + 1)
                    agg_rules[syn_vid] = ClassRule(nam_countable, ing_id)
                    slug_to_agg_vid[slug] = syn_vid

        agg_boxes: list[FoundBox] = []
        for p, b, pr, mp in found:
            vid = class_map[b.class_index]
            if mp is not None and mp.sub_species_slug is not None and mp.sub_species_slug in slug_to_agg_vid:
                vid = slug_to_agg_vid[mp.sub_species_slug]
            agg_boxes.append(FoundBox(p.ordinal - 1, p.shelf_group, vid, b.confidence, pr))

        chips = build_chips(agg_boxes, agg_rules)
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
                final_count=min(99, max(0, c.model_count or 1)) if counted else None,
                qty_level=None,  # the user picks ít / vừa / nhiều (FR-13-11)
                user_action="kept",
                created_at=now,
                updated_at=now,
            )
            s.add(item)
            for i in c.boxes:
                item_of_box[i] = item.id
        s.flush()
        for i, (p, b, pr, mp) in enumerate(found):
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
                    p_tuoi=pr[0] if pr else None,
                    p_dung_som=pr[1] if pr else None,
                    p_dung_ngay=pr[2] if pr else None,
                    p_kiem_tra=pr[3] if pr else None,
                    sub_species_slug=mp.sub_species_slug if mp is not None else None,
                    sub_species_conf=mp.sub_species_conf if mp is not None else None,
                    safety_abstained=mp.safety_abstained if mp is not None else False,
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
                .values(status="queued", error_code=code, enqueued_at=None)
            ).rowcount
            s.commit()
            if n:
                try:
                    ctx.queue.enqueue(scan_id, attempts + 1)
                except Exception:  # noqa: BLE001 — leave enqueued_at=None so sweeper recovers it
                    metrics.inc_scan_job("enqueue_error")
                    log.warning("worker retry enqueue failed", extra={"scan_id": str(scan_id), "attempts": attempts})
                else:
                    with ctx.sessionmaker() as s2:
                        s2.execute(
                            update(Scan)
                            .where(Scan.id == scan_id, Scan.status == "queued", Scan.enqueued_at.is_(None))
                            .values(enqueued_at=utcnow())
                        )
                        s2.commit()
            metrics.inc_scan_job("requeued")
            return "requeued"
        s.execute(
            update(Scan)
            .where(Scan.id == scan_id, Scan.status == "processing")
            .values(status="failed", error_code=code, finished_at=utcnow())
        )
        s.commit()
    ctx.queue.publish(scan_id, "failed")
    metrics.inc_scan_job("failed")
    return "failed"


def run_job(ctx: WorkerContext, scan_id: uuid.UUID) -> str:
    t0 = time.perf_counter()
    claimed = _claim(ctx, scan_id)
    if claimed is None:
        metrics.inc_scan_job("skipped")
        return "skipped"
    attempts, photos, nam_vid, freshness_vids = claimed
    try:
        t1 = time.perf_counter()
        found = _detect(ctx, photos, nam_vid=nam_vid, freshness_vids=freshness_vids)
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
        metrics.inc_scan_job("dropped")
        return "dropped"
    ctx.queue.publish(scan_id, "done")
    metrics.inc_scan_job("done")
    timing = {"claim_ms": (t1 - t0) * 1e3, "infer_ms": (t2 - t1) * 1e3, "write_ms": (t3 - t2) * 1e3,
              "boxes": float(len(found)), "images": float(len(photos))}  # fmt: skip
    ctx.timings = (ctx.timings + [timing])[-100:]
    log.info("scan done", extra={"scan_id": str(scan_id), **{k: round(v, 1) for k, v in timing.items()}})
    return "done"
