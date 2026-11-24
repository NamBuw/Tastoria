"""Freshness crop classifier (freshness.serving.v1, ONNX Runtime + pure numpy)."""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from typing import Any

import numpy as np
from PIL import Image

from tastoria.core.health import metrics
from tastoria.modules.scan.aggregate import Probs
from tastoria.modules.scan.detector import Box

DEFAULT_SIZE = 224
DEFAULT_PAD = 128
DEFAULT_TAU = 0.60
FRESHNESS_BATCH_SIZE = 16


def crop_box_pixels(box: Box, width: int, height: int) -> tuple[int, int, int, int]:
    """Convert normalized [0, 1] box to non-empty integer pixel crop bounds `(x1, y1, x2, y2)`."""
    x1 = max(0, min(width - 1, math.floor(box.x1 * width)))
    y1 = max(0, min(height - 1, math.floor(box.y1 * height)))
    x2 = max(x1 + 1, min(width, math.ceil(box.x2 * width)))
    y2 = max(y1 + 1, min(height, math.ceil(box.y2 * height)))
    return (x1, y1, x2, y2)


def letterbox_crop(crop: Image.Image, size: int = DEFAULT_SIZE, pad_value: int = DEFAULT_PAD) -> np.ndarray:
    """Letterbox RGB crop to `(3, size, size)` float32 in `[0.0, 255.0]` with pad=`pad_value`."""
    im = crop.convert("RGB")
    im.thumbnail((size, size), Image.Resampling.BILINEAR)
    canvas = np.full((size, size, 3), pad_value, dtype=np.uint8)
    w, h = im.size
    px, py = (size - w) // 2, (size - h) // 2
    canvas[py : py + h, px : px + w] = np.asarray(im, dtype=np.uint8)
    return canvas.transpose(2, 0, 1).astype(np.float32)


class FreshnessClassifier:
    """Supports both `freshness.serving.v1` 2-output `["probs", "logits"]` and legacy 1-output `["logits"]` ONNX."""

    def __init__(self, session, *, serving: dict[str, Any] | None = None) -> None:  # noqa: ANN001
        self.session = session
        inp = session.get_inputs()[0]
        self.input_name = inp.name
        self.size = int(inp.shape[2]) if len(inp.shape) == 4 and isinstance(inp.shape[2], int) else DEFAULT_SIZE

        serving = serving or {}
        inp_cfg = serving.get("input") or {}
        self.pad_value = int(inp_cfg.get("pad_value", DEFAULT_PAD))
        abst = serving.get("abstention") or {}
        self.tau = float(abst.get("tau", DEFAULT_TAU))
        cal = serving.get("calibration") or {}
        self.temperature = float(cal.get("temperature", 1.0))
        out_cfg = serving.get("output") or {}
        self.cal_in_onnx = bool(out_cfg.get("calibration_applied_in_onnx", True))

        out_names = [o.name for o in session.get_outputs()]
        self._probs_idx = out_names.index("probs") if "probs" in out_names else None
        self._logits_idx = out_names.index("logits") if "logits" in out_names else 0

    def _postprocess_row(self, probs3: np.ndarray) -> Probs:
        raw = np.asarray(probs3, dtype=np.float64)
        if raw.shape != (3,) or not np.all(np.isfinite(raw)):
            return (0.0, 0.0, 0.0, 1.0)
        q = np.clip(raw, 0.0, 1.0)
        total = float(q.sum())
        if not math.isfinite(total) or total <= 0.0:
            q = np.array([1.0 / 3.0, 1.0 / 3.0, 1.0 / 3.0], dtype=np.float64)
        else:
            q = q / total
        if not np.all(np.isfinite(q)) or float(q.max()) < self.tau:
            return (0.0, 0.0, 0.0, 1.0)
        return (round(float(q[0]), 6), round(float(q[1]), 6), round(float(q[2]), 6), 0.0)

    def predict_crops(self, crops: Sequence[Image.Image], *, batch_size: int = FRESHNESS_BATCH_SIZE) -> list[Probs]:
        if not crops:
            return []
        step = max(1, int(batch_size))
        t_val = self.temperature if (math.isfinite(self.temperature) and self.temperature > 0.0) else 1.0
        out: list[Probs] = []
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
                metrics.observe_onnx("freshness", time.perf_counter() - t0, outcome=outcome)
            if self._probs_idx is not None and self.cal_in_onnx:
                probs_batch = np.asarray(raw_outs[self._probs_idx], dtype=np.float64)
            else:
                logits = np.asarray(raw_outs[self._logits_idx], dtype=np.float64)
                probs_rows: list[np.ndarray] = []
                for row in logits:
                    if row.shape != (3,) or not np.all(np.isfinite(row)):
                        probs_rows.append(np.array([np.nan, np.nan, np.nan], dtype=np.float64))
                        continue
                    z = row / t_val
                    z = z - z.max()
                    e = np.exp(z)
                    s = float(e.sum())
                    if not math.isfinite(s) or s <= 0.0:
                        probs_rows.append(np.array([np.nan, np.nan, np.nan], dtype=np.float64))
                    else:
                        probs_rows.append(e / s)
                probs_batch = np.stack(probs_rows, axis=0)
            out.extend(self._postprocess_row(row) for row in probs_batch)
        return out
