"""CPU ONNXRuntime visual dish classifier (pure numpy + PIL + onnxruntime)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from PIL import Image

from tastoria.modules.meal_calorie.estimator import (
    DEFAULT_SIZE,
    ArtifactIntegrityError,
    make_cpu_session,
    onnx_infer_slot,
    sha256_file,
)


@dataclass(frozen=True)
class DishCandidate:
    dish_id: str
    name_vi: str
    name_en: str
    confidence: float
    kb_slug: str | None = None
    slot: str | None = None


@dataclass(frozen=True)
class DishClassification:
    top_k: list[DishCandidate]
    top1_id: str | None
    top1_name_vi: str | None
    top1_confidence: float
    confident: bool
    conf_threshold: float
    latency_ms: float
    top_margin: float = 0.0
    energy_score: float = 0.0
    max_logit: float = 0.0
    raps_set_size: int = 1
    is_ood: bool = False


def center_crop_rgb(img: Image.Image, size: int = DEFAULT_SIZE) -> np.ndarray:
    """Resize shorter edge to ``int(size * 256 / 224)`` and center-crop ``(1, 3, size, size)`` in ``[0, 255]``."""
    rgb = img.convert("RGB")
    resize_short = max(size, int(round(size * 256 / 224)))
    w, h = rgb.size
    if w <= h:
        nw = resize_short
        nh = max(size, int(round(h * resize_short / max(1, w))))
    else:
        nh = resize_short
        nw = max(size, int(round(w * resize_short / max(1, h))))
    resized = rgb.resize((nw, nh), Image.Resampling.BILINEAR)
    left = max(0, (nw - size) // 2)
    top = max(0, (nh - size) // 2)
    crop = resized.crop((left, top, left + size, top + size))
    arr = np.asarray(crop, dtype=np.float32)
    return arr.transpose(2, 0, 1)[None, ...]


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits)
    exps = np.exp(shifted)
    s = float(np.sum(exps))
    return exps / s if s > 0.0 and np.isfinite(s) else np.full_like(logits, 1.0 / max(1, len(logits)))


class DishClassifier:
    """CPU ONNXRuntime wrapper for 131-class Vietnamese, Asian & Global dish recognition."""

    def __init__(self, session: ort.InferenceSession, *, serving: dict[str, Any]) -> None:
        self.session = session
        self.serving = serving
        inp = session.get_inputs()[0]
        self.input_name = inp.name
        self.size = int(inp.shape[2]) if len(inp.shape) == 4 and isinstance(inp.shape[2], int) else DEFAULT_SIZE
        self.conf_threshold = float(serving.get("conf_threshold", 0.45))
        self.margin_threshold = float(serving.get("margin_threshold", 0.15))
        self.ood_energy_max: float | None = (
            float(serving["ood_energy_max"]) if serving.get("ood_energy_max") is not None else None
        )
        self.ood_max_logit_min: float | None = (
            float(serving["ood_max_logit_min"]) if serving.get("ood_max_logit_min") is not None else None
        )
        self.raps_tau = float(serving.get("raps_tau", 0.95))
        self.raps_k_reg = int(serving.get("raps_k_reg", 3))
        self.raps_lambda = float(serving.get("raps_lambda", 0.01))
        self.classes: list[dict[str, Any]] = list(serving.get("classes") or [])

    def predict(self, img: Image.Image, *, top_k: int = 3) -> DishClassification:
        x = center_crop_rgb(img, size=self.size)
        with onnx_infer_slot("dish_classifier"):
            t0 = time.perf_counter()
            raw = self.session.run(None, {self.input_name: x})[0]
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)

        logits = np.asarray(raw, dtype=np.float64).reshape(-1)
        if not np.all(np.isfinite(logits)):
            return DishClassification(
                [],
                None,
                None,
                0.0,
                False,
                self.conf_threshold,
                latency_ms,
                is_ood=True,
                raps_set_size=max(1, len(self.classes)),
            )
        max_logit = float(np.max(logits)) if logits.size else 0.0
        energy_score = (
            float(-(max_logit + np.log(np.sum(np.exp(logits - max_logit)))))
            if logits.size
            else 0.0
        )
        probs = _softmax(logits)

        n = min(len(probs), len(self.classes))
        if n == 0:
            return DishClassification([], None, None, 0.0, False, self.conf_threshold, latency_ms)

        k = max(1, min(top_k, n))
        sorted_all = np.argsort(-probs[:n])
        top_idx = sorted_all[:k]
        candidates: list[DishCandidate] = []
        for idx in top_idx:
            meta = self.classes[int(idx)]
            candidates.append(
                DishCandidate(
                    dish_id=str(meta["id"]),
                    name_vi=str(meta.get("name_vi") or meta["id"]),
                    name_en=str(meta.get("name_en") or meta["id"]),
                    confidence=round(float(probs[int(idx)]), 4),
                    kb_slug=meta.get("kb_slug"),
                    slot=meta.get("slot"),
                )
            )
        top1 = candidates[0]
        top_margin = (
            round(max(0.0, float(probs[int(sorted_all[0])] - probs[int(sorted_all[1])])), 4)
            if n >= 2
            else top1.confidence
        )
        # RAPS conformal prediction set size (95% coverage target)
        cum = 0.0
        raps_set_size = 0
        for rank, idx in enumerate(sorted_all, start=1):
            cum += float(probs[int(idx)]) + (self.raps_lambda if rank > self.raps_k_reg else 0.0)
            raps_set_size = rank
            if cum >= self.raps_tau:
                break

        rgb_std = float(x.std(axis=(0, 2, 3)).max())
        flat_ood = rgb_std < 3.0
        zero_var_ood = rgb_std < 1.5
        energy_ood = self.ood_energy_max is not None and energy_score > self.ood_energy_max
        logit_ood = self.ood_max_logit_min is not None and max_logit < self.ood_max_logit_min
        is_ood = bool(energy_ood or logit_ood or zero_var_ood or (flat_ood and top1.confidence < 0.95))
        eff_thresh = max(self.conf_threshold, 0.95) if flat_ood else self.conf_threshold
        return DishClassification(
            top_k=candidates,
            top1_id=top1.dish_id,
            top1_name_vi=top1.name_vi,
            top1_confidence=top1.confidence,
            confident=(top1.confidence >= eff_thresh) and (not is_ood),
            conf_threshold=self.conf_threshold,
            latency_ms=latency_ms,
            top_margin=top_margin,
            energy_score=round(energy_score, 4),
            max_logit=round(max_logit, 4),
            raps_set_size=raps_set_size,
            is_ood=is_ood,
        )


def load_dish_classifier(model_dir: Path, *, verify_sha256: bool = True) -> DishClassifier:
    model_dir = Path(model_dir)
    serving_path = model_dir / "serving.json"
    if not serving_path.exists():
        raise ArtifactIntegrityError(f"Missing serving.json in {model_dir}")
    serving = json.loads(serving_path.read_text(encoding="utf-8"))
    artifact_name = str(serving.get("artifact_file") or "model.onnx")
    onnx_path = model_dir / artifact_name
    if not onnx_path.exists():
        raise ArtifactIntegrityError(f"Missing ONNX artifact {onnx_path}")
    if verify_sha256:
        expected = serving.get("artifact_sha256")
        if not expected:
            raise ArtifactIntegrityError(f"Missing artifact_sha256 in {serving_path}")
        actual = sha256_file(onnx_path)
        if actual != expected:
            raise ArtifactIntegrityError(f"SHA-256 mismatch for {onnx_path}: expected {expected}, got {actual}")
    sess = make_cpu_session(onnx_path, intra_threads=2)
    return DishClassifier(sess, serving=serving)
