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
    """CPU ONNXRuntime wrapper for 310-class closed-set + optional 1,220-class open-vocab dish recognition."""

    def __init__(
        self,
        session: ort.InferenceSession,
        *,
        serving: dict[str, Any],
        open_vocab_embeddings: np.ndarray | None = None,
        open_vocab_meta: list[dict[str, Any]] | None = None,
    ) -> None:
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
        self.open_vocab_min_cos = float(serving.get("open_vocab_min_cos", 0.135))
        self._open_emb: np.ndarray | None = None
        self._open_meta: list[dict[str, Any]] = []
        if open_vocab_embeddings is not None and open_vocab_meta and len(open_vocab_embeddings) == len(open_vocab_meta):
            arr = np.asarray(open_vocab_embeddings, dtype=np.float32)
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            norms = np.where(norms > 1e-8, norms, 1.0)
            self._open_emb = arr / norms
            self._open_meta = list(open_vocab_meta)

    def _open_vocab_fallback(self, raw_emb: np.ndarray, *, top_k: int, flat_ood: bool) -> DishClassification | None:
        if self._open_emb is None or not self._open_meta:
            return None
        vec = np.asarray(raw_emb, dtype=np.float32).reshape(-1)
        if vec.shape[0] != self._open_emb.shape[1] or not np.all(np.isfinite(vec)):
            return None
        norm = float(np.linalg.norm(vec))
        if norm <= 1e-8:
            return None
        sims = self._open_emb @ (vec / norm)
        pool_n = min(max(5, top_k), len(sims))
        top_idx = np.argsort(-sims)[:pool_n]
        top_sims = sims[top_idx]
        max_sim = float(top_sims[0])
        if max_sim < self.open_vocab_min_cos:
            return None
        second_sim = float(top_sims[1]) if len(top_sims) > 1 else max_sim
        exps = np.exp((top_sims - max_sim) * 55.0)
        rel_probs = exps / float(np.sum(exps))
        k = max(1, min(top_k, len(top_idx)))
        candidates: list[DishCandidate] = []
        for rank_i in range(k):
            idx = int(top_idx[rank_i])
            meta = self._open_meta[idx]
            candidates.append(
                DishCandidate(
                    dish_id=str(meta["dish_id"]),
                    name_vi=str(meta.get("name_vi") or meta["dish_id"]),
                    name_en=str(meta.get("name_en") or meta["dish_id"]),
                    confidence=round(float(rel_probs[rank_i]), 4),
                    kb_slug=meta.get("kb_slug"),
                    slot=meta.get("slot"),
                )
            )
        margin = round(max(0.0, float(rel_probs[0] - rel_probs[1])), 4) if k >= 2 else candidates[0].confidence
        confident = (not flat_ood) and (max_sim >= 0.145) and ((max_sim - second_sim) >= 0.004 or max_sim >= 0.160)
        return DishClassification(
            top_k=candidates,
            top1_id=candidates[0].dish_id,
            top1_name_vi=candidates[0].name_vi,
            top1_confidence=candidates[0].confidence,
            confident=confident,
            conf_threshold=self.conf_threshold,
            latency_ms=0.0,
            top_margin=margin,
            energy_score=0.0,
            max_logit=round(max_sim, 4),
            raps_set_size=1 if confident else 3,
            is_ood=not confident,
        )

    def predict(self, img: Image.Image, *, top_k: int = 3) -> DishClassification:
        x = center_crop_rgb(img, size=self.size)
        with onnx_infer_slot("dish_classifier"):
            t0 = time.perf_counter()
            raw_outs = self.session.run(None, {self.input_name: x})
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 3)

        logits = np.asarray(raw_outs[0], dtype=np.float64).reshape(-1)
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
        closed_confident = (top1.confidence >= eff_thresh) and (not is_ood)
        if (
            len(raw_outs) >= 2
            and self._open_emb is not None
            and not zero_var_ood
            and not (closed_confident and top_margin >= self.margin_threshold)
        ):
            ov = self._open_vocab_fallback(raw_outs[1], top_k=top_k, flat_ood=flat_ood)
            if ov is not None:
                return DishClassification(
                    top_k=ov.top_k,
                    top1_id=ov.top1_id,
                    top1_name_vi=ov.top1_name_vi,
                    top1_confidence=ov.top1_confidence,
                    confident=ov.confident,
                    conf_threshold=self.conf_threshold,
                    latency_ms=latency_ms,
                    top_margin=ov.top_margin,
                    energy_score=round(energy_score, 4),
                    max_logit=round(max_logit, 4),
                    raps_set_size=ov.raps_set_size,
                    is_ood=ov.is_ood,
                )
        return DishClassification(
            top_k=candidates,
            top1_id=top1.dish_id,
            top1_name_vi=top1.name_vi,
            top1_confidence=top1.confidence,
            confident=closed_confident,
            conf_threshold=self.conf_threshold,
            latency_ms=latency_ms,
            top_margin=top_margin,
            energy_score=round(energy_score, 4),
            max_logit=round(max_logit, 4),
            raps_set_size=raps_set_size,
            is_ood=is_ood,
        )


def load_open_vocab_index(model_dir: Path) -> tuple[np.ndarray | None, list[dict[str, Any]] | None]:
    npz_path = model_dir / "dish_prototypes_expanded.npz"
    tax_path = model_dir / "dish_taxonomy_expanded.json"
    if not (npz_path.is_file() and tax_path.is_file()):
        return None, None
    tax = json.loads(tax_path.read_text(encoding="utf-8")) or {}
    dishes = tax.get("dishes") or []
    by_id = {str(d["dish_id"]): d for d in dishes if isinstance(d, dict) and d.get("dish_id")}
    with np.load(npz_path, allow_pickle=False) as z:
        emb = np.asarray(z["embeddings"], dtype=np.float32)
        ids = [str(x) for x in z["dish_ids"]]
    keep_rows: list[int] = []
    meta: list[dict[str, Any]] = []
    for idx, did in enumerate(ids):
        row = by_id.get(did)
        if row is not None:
            keep_rows.append(idx)
            meta.append(row)
    if not keep_rows:
        return None, None
    return emb[keep_rows], meta


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
    open_emb, open_meta = load_open_vocab_index(model_dir)
    return DishClassifier(sess, serving=serving, open_vocab_embeddings=open_emb, open_vocab_meta=open_meta)
