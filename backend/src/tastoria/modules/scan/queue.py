"""The scan job queue (RQ on Valkey, ADR 0003) and the per-scan notification channel used by the long-poll.

Valkey is never the source of truth: `scans.status` / `attempts` / `enqueued_at` in PostgreSQL decide what runs.
A job only carries the scan id; the worker claims the scan with `UPDATE … WHERE status = 'queued'`, so a job that
is enqueued twice (sweeper + API, or a retry racing a late job) runs the inference at most once per attempt.
RQ needs a bytes connection (redis-py, the protocol Valkey speaks), not the decode_responses client of core.kv.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable

import redis
from rq import Queue

log = logging.getLogger("tastoria.scan.queue")

QUEUE_NAME = "scan"
JOB_FUNC = "tastoria.modules.scan.worker.infer"
JOB_TIMEOUT_S = 30  # FR-12-10
MAX_ATTEMPTS = 3  # 1 run + at most 2 retries (spec v2 §8, FR-12-19)
MAX_QUEUED = 50  # UC12 4b; NFR-PERF-01 load is 5 concurrent users, a full queue means the worker is down


def channel(scan_id: uuid.UUID | str) -> str:
    return f"scan:{scan_id}"


class ScanQueue:
    def __init__(self, url: str) -> None:
        self.redis = redis.Redis.from_url(url, socket_timeout=5, socket_connect_timeout=2, health_check_interval=30)
        self.queue = Queue(QUEUE_NAME, connection=self.redis, default_timeout=JOB_TIMEOUT_S)

    def enqueue(self, scan_id: uuid.UUID, attempt: int) -> None:
        """One RQ job per (scan, attempt); retries are decided by the worker from `scans.attempts`."""
        self.queue.enqueue(
            JOB_FUNC,
            str(scan_id),
            job_id=f"scan-{scan_id}-{attempt}",
            job_timeout=JOB_TIMEOUT_S,
            result_ttl=600,
            failure_ttl=86400,
            description=f"scan {scan_id} attempt {attempt}",
        )

    def length(self) -> int:
        return self.queue.count

    def publish(self, scan_id: uuid.UUID, status: str) -> None:
        try:
            self.redis.publish(channel(scan_id), status)
        except redis.RedisError:  # waiters fall back to re-reading the database every second
            log.warning("publish failed", extra={"scan_id": str(scan_id)})

    def ping(self) -> None:
        self.redis.ping()

    def wait(self, scan_id: uuid.UUID, timeout: float, settled: Callable[[], bool]) -> None:
        """Return when `settled()` is true or after `timeout` s. Subscribes before the first check (no lost wake-up)
        and re-checks at least every second, so a missed or failed PUBLISH costs ≤ 1 s, never the whole wait."""
        deadline = time.monotonic() + timeout
        ps = None
        try:
            ps = self.redis.pubsub(ignore_subscribe_messages=True)
            ps.subscribe(channel(scan_id))
        except redis.RedisError:
            ps = None
        try:
            while not settled():
                left = deadline - time.monotonic()
                if left <= 0:
                    return
                step = min(1.0, left)
                if ps is None:
                    time.sleep(step)
                    continue
                try:
                    ps.get_message(timeout=step)
                except redis.RedisError:
                    ps = None
        finally:
            if ps is not None:
                try:
                    ps.close()
                except redis.RedisError:
                    pass
