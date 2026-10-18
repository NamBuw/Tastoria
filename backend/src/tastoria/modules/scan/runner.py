"""Bootstrap of the `worker` process (`tastoria worker`): load the deployed models, then run RQ (see worker.py)."""

from __future__ import annotations

import logging
import os
import socket
from pathlib import Path

from rq import SimpleWorker, Worker

from tastoria.core.config import Settings
from tastoria.core.db import make_engine, make_sessionmaker
from tastoria.modules.mlops import service as mlops
from tastoria.modules.mlops.schemas import MlopsError
from tastoria.modules.scan import worker as job
from tastoria.modules.scan.detector import Detector
from tastoria.modules.scan.queue import ScanQueue

log = logging.getLogger("tastoria.scan.runner")
INTRA_OP_THREADS = 2  # spec v2 §8


def build_context(settings: Settings, sm, queue: ScanQueue) -> job.WorkerContext:  # noqa: ANN001
    storage = Path(settings.storage_dir)
    with sm() as s:
        det = mlops.active_version(s, "detector")
        fresh = mlops.active_version(s, "freshness")
    if det is None:
        raise MlopsError("không có bản detector nào được deploy (tastoria mlops deploy detector <version>)")
    serving = det.metrics.get("serving") or {}
    session = mlops.load_onnx(storage, det, intra_op_threads=INTRA_OP_THREADS)  # verifies sha256 (SD10)
    detector = Detector(
        session, conf=float(serving["conf"]), iou=float(serving["iou"]), preprocess_version=det.preprocess_version
    )
    if fresh is not None:
        log.warning("a freshness model is deployed but this worker has no crop classifier yet; p_* stay NULL")
    return job.WorkerContext(sm, storage, queue, detector, det, None)


def worker_name() -> str:
    return f"scan-{socket.gethostname()}-{os.getpid()}"


def run(settings: Settings, *, burst: bool = False) -> int:
    engine = make_engine(settings.database_url, pool_size=2)
    sm = make_sessionmaker(engine)
    queue = ScanQueue(settings.valkey_url)
    try:
        ctx = build_context(settings, sm, queue)
    except (MlopsError, KeyError, ValueError) as exc:
        log.error("worker not started: %s", exc)
        engine.dispose()
        return 2
    job.install(ctx)
    log.info(
        "scan worker ready",
        extra={"detector": ctx.detector_version.version, "conf": ctx.detector.conf, "threads": INTRA_OP_THREADS},
    )
    w = SimpleWorker([queue.queue], connection=queue.redis, name=worker_name())
    try:
        w.work(burst=burst, logging_level=settings.log_level)
    finally:
        job.install(None)
        engine.dispose()
    return 0


def check(settings: Settings) -> int:
    """Container healthcheck: a worker of this host is registered on the scan queue (RQ heartbeat in Valkey)."""
    queue = ScanQueue(settings.valkey_url)
    host = socket.gethostname()
    names = [w.name for w in Worker.all(connection=queue.redis, queue=queue.queue)]
    return 0 if any(n.startswith(f"scan-{host}-") for n in names) else 1
