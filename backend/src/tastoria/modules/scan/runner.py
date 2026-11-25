"""Bootstrap of the `worker` process (`tastoria worker`): load the deployed models, then run RQ (see worker.py)."""

from __future__ import annotations

import logging
import os
import socket
import warnings
from pathlib import Path
from typing import Any

from PIL import Image
from rq import SimpleWorker, Worker
from rq.serializers import JSONSerializer

from tastoria.core.config import Settings
from tastoria.core.db import make_engine, make_sessionmaker
from tastoria.modules.catalog import service as catalog
from tastoria.modules.mlops import service as mlops
from tastoria.modules.mlops.schemas import MlopsError
from tastoria.modules.scan import worker as job
from tastoria.modules.scan.detector import Detector
from tastoria.modules.scan.freshness import FreshnessClassifier
from tastoria.modules.scan.queue import ScanQueue

log = logging.getLogger("tastoria.scan.runner")
INTRA_OP_THREADS = 2  # spec v2 §8


def resolve_class_conf(
    raw: dict[str, Any] | None, class_map: dict[int, int], code_by_vid: dict[int, str]
) -> dict[int, float] | None:
    """Map serving `class_conf` (by vision_classes.code or class_index) -> {class_index: threshold}."""
    if not raw:
        return None
    idx_by_code = {code_by_vid[vid]: ci for ci, vid in class_map.items() if vid in code_by_vid}
    out: dict[int, float] = {}
    for key, val in raw.items():
        ci = idx_by_code.get(key)
        if ci is None and str(key).isdigit():
            cand = int(key)
            if cand in class_map:
                ci = cand
        if ci is not None:
            out[ci] = float(val)
    return out or None


def build_context(settings: Settings, sm, queue: ScanQueue) -> job.WorkerContext:  # noqa: ANN001
    storage = Path(settings.storage_dir)
    with sm() as s:
        active = mlops.active_versions_map(s)
        det = active.get("detector")
        fresh = active.get("freshness")
        mush = active.get("mushroom_classifier")
        vclasses = catalog.vision_classes(s) if det is not None else {}
    if det is None:
        raise MlopsError("không có bản detector nào được deploy (tastoria mlops deploy detector <version>)")
    serving = det.metrics.get("serving") or {}
    raw_ag = serving.get("agnostic_iou")
    agnostic_iou = float(raw_ag) if raw_ag is not None else None
    code_by_vid = {vid: vc.code for vid, vc in vclasses.items()}
    class_conf = resolve_class_conf(serving.get("class_conf"), det.class_map, code_by_vid)
    class_count_conf = resolve_class_conf(serving.get("class_count_conf"), det.class_map, code_by_vid)
    zoom_rescue = serving.get("zoom_rescue") if isinstance(serving.get("zoom_rescue"), dict) else None
    session = mlops.load_onnx(storage, det, intra_op_threads=INTRA_OP_THREADS)  # verifies sha256 (SD10)
    detector = Detector(
        session,
        conf=float(serving["conf"]),
        iou=float(serving["iou"]),
        preprocess_version=det.preprocess_version,
        agnostic_iou=agnostic_iou,
        class_conf=class_conf,
        class_count_conf=class_count_conf,
        zoom_rescue=zoom_rescue,
    )
    classifier: FreshnessClassifier | None = None
    if fresh is not None:
        fresh_sess = mlops.load_onnx(storage, fresh, intra_op_threads=INTRA_OP_THREADS)
        classifier = FreshnessClassifier(fresh_sess, serving=fresh.metrics.get("serving") or {})
    mushroom: job.MushroomClassifier | None = None
    if mush is not None:
        mush_sess = mlops.load_onnx(storage, mush, intra_op_threads=INTRA_OP_THREADS)
        mushroom = job.MushroomClassifier(mush_sess, serving=mush.metrics.get("serving") or {})
    elif (mush_dir := job.resolve_mushroom_model_dir()) is not None:
        try:
            mushroom = job.load_mushroom_classifier(mush_dir, verify_sha256=True)
        except Exception as exc:  # noqa: BLE001 — static fallback is optional
            log.warning("mushroom_classifier fallback unavailable at %s: %s", mush_dir, exc)
    return job.WorkerContext(
        sm,
        storage,
        queue,
        detector,
        det,
        fresh,
        freshness=classifier,
        mushroom_classifier=mushroom,
    )


def worker_name() -> str:
    return f"scan-{socket.gethostname()}-{os.getpid()}"


def run(settings: Settings, *, burst: bool = False) -> int:
    warnings.filterwarnings("error", category=Image.DecompressionBombWarning)
    engine = make_engine(settings.database_url, pool_size=2)
    sm = make_sessionmaker(engine)
    queue = ScanQueue(settings.valkey_url)
    try:
        ctx = build_context(settings, sm, queue)
    except (MlopsError, KeyError, ValueError) as exc:
        log.error("worker not started: %s", exc)
        queue.close()
        engine.dispose()
        return 2
    job.install(ctx)
    log.info(
        "scan worker ready",
        extra={
            "detector": ctx.detector_version.version,
            "conf": ctx.detector.conf,
            "iou": ctx.detector.iou,
            "agnostic_iou": ctx.detector.agnostic_iou,
            "n_class_conf": len(ctx.detector.class_conf or {}),
            "n_class_count_conf": len(ctx.detector.class_count_conf or {}),
            "zoom_rescue_enabled": bool(ctx.detector.zoom_rescue and ctx.detector.zoom_rescue.get("enabled")),
            "mushroom_classifier": ctx.mushroom_classifier is not None,
            "threads": INTRA_OP_THREADS,
        },
    )
    w = SimpleWorker([queue.queue], connection=queue.redis, name=worker_name(), serializer=JSONSerializer)
    try:
        w.work(burst=burst, logging_level=settings.log_level)
    finally:
        job.install(None)
        queue.close()
        engine.dispose()
    return 0


def check(settings: Settings) -> int:
    """Container healthcheck: a worker of this host is registered on the scan queue (RQ heartbeat in Valkey)."""
    queue = ScanQueue(settings.valkey_url)
    try:
        host = socket.gethostname()
        names = [w.name for w in Worker.all(connection=queue.redis, queue=queue.queue)]
        return 0 if any(n.startswith(f"scan-{host}-") for n in names) else 1
    finally:
        queue.close()
