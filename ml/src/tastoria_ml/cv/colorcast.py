"""Illuminant-cast augmentation for the "augmentation only" arm of the preprocessing ablation.

Instead of correcting colour at inference (gray-world / CLAHE), the detector is trained on images whose
light source has been randomly changed, so it learns to ignore the cast. The cast is a von Kries diagonal
gain applied in **linear** RGB (sRGB decoded), the same model that gray-world inverts:

    rgb_lin' = clip(rgb_lin · k · 2^e),   k = (2^t, 2^g, 2^-t) for (R, G, B)

with t ~ U(-temp, temp) (warm ↔ cool, log2 R/B ratio = 2t), g ~ U(-tint, tint) (green ↔ magenta) and
e ~ U(-exposure, exposure) stops. With the defaults (temp 0.6) the R/B ratio spans 2^±1.2 ≈ 0.44–2.3,
roughly the gap between a 2700 K bulb and a 6500 K fridge LED. Applied with probability ``p`` per sample,
on top of ultralytics' own HSV jitter. Pure numpy (LUT based, ~3 ms per 640×640 image).
"""

from __future__ import annotations

import random

import numpy as np

from tastoria_ml.cv.preprocess import linear_to_srgb, srgb_to_linear

_TO_LIN = srgb_to_linear(np.arange(256)).astype(np.float32)
_LIN_LEVELS = 4096
_TO_SRGB = linear_to_srgb(np.linspace(0.0, 1.0, _LIN_LEVELS, dtype=np.float32))


def cast_gains(t: float, g: float, e: float) -> np.ndarray:
    """RGB gains for temperature shift ``t``, tint ``g`` and exposure ``e`` (all in log2 units)."""
    return np.array([2.0**t, 2.0**g, 2.0**-t], dtype=np.float32) * np.float32(2.0**e)


def apply_gains(img: np.ndarray, gains_rgb: np.ndarray, bgr: bool = False) -> np.ndarray:
    """Multiply linear RGB by ``gains_rgb`` and re-encode to sRGB uint8 (LUT, 1/4096 linear steps)."""
    g = np.asarray(gains_rgb, dtype=np.float32)
    if bgr:
        g = g[::-1]
    lin = _TO_LIN[np.asarray(img, dtype=np.uint8)] * g
    idx = np.clip(np.rint(lin * (_LIN_LEVELS - 1)), 0, _LIN_LEVELS - 1).astype(np.int32)
    return _TO_SRGB[idx]


def sample_gains(rng: random.Random, temp: float = 0.6, tint: float = 0.15, exposure: float = 0.4) -> np.ndarray:
    return cast_gains(rng.uniform(-temp, temp), rng.uniform(-tint, tint), rng.uniform(-exposure, exposure))


class RandomIlluminant:
    """ultralytics-style transform: ``labels['img']`` (BGR uint8) gets a random light-source cast."""

    def __init__(self, p: float = 0.5, temp: float = 0.6, tint: float = 0.15, exposure: float = 0.4):
        self.p, self.temp, self.tint, self.exposure = p, temp, tint, exposure

    def __call__(self, labels: dict) -> dict:
        if random.random() < self.p:  # python RNG: seeded per dataloader worker by ultralytics
            gains = sample_gains(random, self.temp, self.tint, self.exposure)  # type: ignore[arg-type]
            labels["img"] = np.ascontiguousarray(apply_gains(labels["img"], gains, bgr=True))
        return labels
