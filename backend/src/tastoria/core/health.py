"""GET /healthz (process alive, no DB), GET /readyz (dependencies, fail-closed), and Prometheus metrics registry.

Readiness checks are registered by the assembly root (tastoria.app) under the names of the OpenAPI
`Readiness.checks` object. A missing or failing check always fails closed ("fail", HTTP 503).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import threading
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("tastoria.health")
router = APIRouter(tags=["core"])

READINESS_CHECKS = ("database", "valkey", "models")

_HTTP_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_ONNX_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


def _esc_label(val: str) -> str:
    return val.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _fmt_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    inner = ",".join(f'{k}="{_esc_label(v)}"' for k, v in labels)
    return f"{{{inner}}}"


class MetricsRegistry:
    """Thread-safe stdlib Prometheus metrics collector (HTTP, ONNX inference/contention, scan outcomes)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._http_requests: dict[tuple[str, str, str], int] = defaultdict(int)
        self._http_hist_counts: dict[tuple[str, str], list[int]] = {}
        self._http_hist_sums: dict[tuple[str, str], float] = defaultdict(float)
        self._http_hist_totals: dict[tuple[str, str], int] = defaultdict(int)

        self._onnx_total: dict[tuple[str, str], int] = defaultdict(int)
        self._onnx_hist_counts: dict[str, list[int]] = {}
        self._onnx_hist_sums: dict[str, float] = defaultdict(float)
        self._onnx_hist_totals: dict[str, int] = defaultdict(int)
        self._onnx_contention_503: dict[str, int] = defaultdict(int)

        self._scan_jobs: dict[str, int] = defaultdict(int)

    def reset(self) -> None:
        with self._lock:
            self._http_requests.clear()
            self._http_hist_counts.clear()
            self._http_hist_sums.clear()
            self._http_hist_totals.clear()
            self._onnx_total.clear()
            self._onnx_hist_counts.clear()
            self._onnx_hist_sums.clear()
            self._onnx_hist_totals.clear()
            self._onnx_contention_503.clear()
            self._scan_jobs.clear()

    def observe_http(self, method: str, path: str, status: int, duration_s: float) -> None:
        dur = duration_s if math.isfinite(duration_s) and duration_s >= 0.0 else 0.0
        st = str(status)
        with self._lock:
            self._http_requests[(method, path, st)] += 1
            key = (method, path)
            buckets = self._http_hist_counts.get(key)
            if buckets is None:
                buckets = [0] * len(_HTTP_BUCKETS)
                self._http_hist_counts[key] = buckets
            for idx, bound in enumerate(_HTTP_BUCKETS):
                if dur <= bound:
                    buckets[idx] += 1
            self._http_hist_sums[key] += dur
            self._http_hist_totals[key] += 1

    def observe_onnx(self, model: str, duration_s: float, *, outcome: str = "ok") -> None:
        dur = duration_s if math.isfinite(duration_s) and duration_s >= 0.0 else 0.0
        with self._lock:
            self._onnx_total[(model, outcome)] += 1
            buckets = self._onnx_hist_counts.get(model)
            if buckets is None:
                buckets = [0] * len(_ONNX_BUCKETS)
                self._onnx_hist_counts[model] = buckets
            for idx, bound in enumerate(_ONNX_BUCKETS):
                if dur <= bound:
                    buckets[idx] += 1
            self._onnx_hist_sums[model] += dur
            self._onnx_hist_totals[model] += 1

    def inc_onnx_contention(self, model: str) -> None:
        with self._lock:
            self._onnx_contention_503[model] += 1

    def inc_scan_job(self, outcome: str, count: int = 1) -> None:
        if count <= 0:
            return
        with self._lock:
            self._scan_jobs[outcome] += count

    def render_prometheus(self, *, scan_queue_depth: int | None = None) -> str:
        with self._lock:
            http_req = dict(self._http_requests)
            http_buckets = {k: list(v) for k, v in self._http_hist_counts.items()}
            http_sums = dict(self._http_hist_sums)
            http_totals = dict(self._http_hist_totals)
            onnx_tot = dict(self._onnx_total)
            onnx_buckets = {k: list(v) for k, v in self._onnx_hist_counts.items()}
            onnx_sums = dict(self._onnx_hist_sums)
            onnx_totals = dict(self._onnx_hist_totals)
            onnx_503 = dict(self._onnx_contention_503)
            scan_jobs = dict(self._scan_jobs)

        lines: list[str] = [
            "# HELP tastoria_http_requests_total Total HTTP requests handled.",
            "# TYPE tastoria_http_requests_total counter",
        ]
        for (method, path, st), cnt in sorted(http_req.items()):
            lbl = _fmt_labels((("method", method), ("path", path), ("status", st)))
            lines.append(f"tastoria_http_requests_total{lbl} {cnt}")

        lines.extend([
            "# HELP tastoria_http_request_duration_seconds HTTP request latency in seconds.",
            "# TYPE tastoria_http_request_duration_seconds histogram",
        ])
        for (method, path), buckets in sorted(http_buckets.items()):
            for bound, cnt in zip(_HTTP_BUCKETS, buckets, strict=True):
                lbl = _fmt_labels((("method", method), ("path", path), ("le", str(bound))))
                lines.append(f"tastoria_http_request_duration_seconds_bucket{lbl} {cnt}")
            lbl_inf = _fmt_labels((("method", method), ("path", path), ("le", "+Inf")))
            tot = http_totals[(method, path)]
            lines.append(f"tastoria_http_request_duration_seconds_bucket{lbl_inf} {tot}")
            base_lbl = _fmt_labels((("method", method), ("path", path)))
            lines.append(f"tastoria_http_request_duration_seconds_sum{base_lbl} {http_sums[(method, path)]:.6f}")
            lines.append(f"tastoria_http_request_duration_seconds_count{base_lbl} {tot}")

        lines.extend([
            "# HELP tastoria_onnx_inference_total Total ONNX inference executions.",
            "# TYPE tastoria_onnx_inference_total counter",
        ])
        for (model, outcome), cnt in sorted(onnx_tot.items()):
            lbl = _fmt_labels((("model", model), ("outcome", outcome)))
            lines.append(f"tastoria_onnx_inference_total{lbl} {cnt}")

        lines.extend([
            "# HELP tastoria_onnx_inference_duration_seconds ONNX inference duration in seconds.",
            "# TYPE tastoria_onnx_inference_duration_seconds histogram",
        ])
        for model, buckets in sorted(onnx_buckets.items()):
            for bound, cnt in zip(_ONNX_BUCKETS, buckets, strict=True):
                lbl = _fmt_labels((("model", model), ("le", str(bound))))
                lines.append(f"tastoria_onnx_inference_duration_seconds_bucket{lbl} {cnt}")
            lbl_inf = _fmt_labels((("model", model), ("le", "+Inf")))
            tot = onnx_totals[model]
            lines.append(f"tastoria_onnx_inference_duration_seconds_bucket{lbl_inf} {tot}")
            base_lbl = _fmt_labels((("model", model),))
            lines.append(f"tastoria_onnx_inference_duration_seconds_sum{base_lbl} {onnx_sums[model]:.6f}")
            lines.append(f"tastoria_onnx_inference_duration_seconds_count{base_lbl} {tot}")

        lines.extend([
            "# HELP tastoria_onnx_contention_503_total ONNX inference semaphore acquire timeouts returning 503.",
            "# TYPE tastoria_onnx_contention_503_total counter",
        ])
        for model, cnt in sorted(onnx_503.items()):
            lines.append(f'tastoria_onnx_contention_503_total{{model="{_esc_label(model)}"}} {cnt}')

        lines.extend([
            "# HELP tastoria_scan_jobs_total Scan job and queue outcomes.",
            "# TYPE tastoria_scan_jobs_total counter",
        ])
        for outcome, cnt in sorted(scan_jobs.items()):
            lines.append(f'tastoria_scan_jobs_total{{outcome="{_esc_label(outcome)}"}} {cnt}')

        if scan_queue_depth is not None:
            lines.extend([
                "# HELP tastoria_scan_queue_depth Current number of queued jobs in scan queue.",
                "# TYPE tastoria_scan_queue_depth gauge",
                f"tastoria_scan_queue_depth {scan_queue_depth}",
            ])

        return "\n".join(lines) + "\n"


metrics = MetricsRegistry()


@router.get("/healthz", operation_id="core_get_health")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz", operation_id="core_get_readiness")
async def readyz(request: Request) -> JSONResponse:
    checks: dict[str, Callable[[], Any]] = getattr(request.app.state, "readiness_checks", {})
    results: dict[str, str] = {}
    for name in READINESS_CHECKS:
        fn = checks.get(name)
        if fn is None:
            log.warning("readiness check missing", extra={"check": name})
            results[name] = "fail"
            continue
        try:
            if inspect.iscoroutinefunction(fn):
                await fn()
            else:
                res = await asyncio.to_thread(fn)
                if inspect.isawaitable(res):
                    await res
            results[name] = "ok"
        except Exception as exc:  # report, never raise
            log.warning("readiness check failed", extra={"check": name, "error": repr(exc)})
            results[name] = "fail"
    ready = all(v == "ok" for v in results.values())
    body = {"status": "ready" if ready else "not_ready", "checks": results}
    if ready:
        return JSONResponse(body)
    return JSONResponse(body, status_code=503, headers={"Retry-After": "5"})
