"""Whole-image preprocessing for the detector and freshness classifier (thiết kế v2 §7, review:cv#7).

Pure numpy so it runs (and is tested) in the project env and gives byte-identical results in the
training env. All functions take and return RGB ``uint8`` arrays of shape (H, W, 3) unless noted.

- White balance estimates the illuminant in **linear** RGB (sRGB decoded), ignoring clipped pixels
  (any channel ≥ ``clip_high`` or all channels ≤ ``clip_low`` in 8-bit code values), then applies a
  von Kries diagonal correction and re-encodes to sRGB.
  * gray-world      = Minkowski mean with p = 1;
  * shades-of-gray  = Minkowski mean with p (Finlayson & Trezzi 2004; p = 6 is the usual choice);
  * p = inf gives max-RGB (white patch).
  Gains are normalised to keep the mean luminance and clamped to ``max_gain`` so a frame full of greens
  (where gray-world is known to be wrong) cannot be pushed to magenta.
- CLAHE is applied to the L channel of CIE L*a*b* (D65) only, so hue is untouched. The implementation
  follows OpenCV's ``cv::CLAHE`` (tile histograms, clip and redistribute, bilinear blend of tile LUTs).

Apply the same function to train, val and test at the whole-image level, never on crops.
"""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------- sRGB transfer


def _srgb_to_linear_formula(u8: np.ndarray) -> np.ndarray:
    c = np.asarray(u8, dtype=np.float32) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4).astype(np.float32)


_SRGB_LUT = _srgb_to_linear_formula(np.arange(256))


def srgb_to_linear(u8: np.ndarray) -> np.ndarray:
    """sRGB code values (uint8 or float 0..255) -> linear RGB float32 in [0, 1].

    uint8 input goes through a 256-entry table (same values as the formula, ~20× faster on a frame).
    """
    a = np.asarray(u8)
    if a.dtype == np.uint8:
        return _SRGB_LUT[a]
    return _srgb_to_linear_formula(a)


def linear_to_srgb(lin: np.ndarray) -> np.ndarray:
    """Linear RGB float in [0, 1] (clipped) -> sRGB uint8."""
    c = np.clip(np.asarray(lin, dtype=np.float32), 0.0, 1.0)
    s = np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1 / 2.4) - 0.055)
    return np.clip(np.rint(s * 255.0), 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- white balance


def valid_mask(img: np.ndarray, clip_high: int = 250, clip_low: int = 5) -> np.ndarray:
    """True for pixels used to estimate the illuminant: no clipped channel and not near-black."""
    img = np.asarray(img)
    return ~((img >= clip_high).any(axis=-1) | (img <= clip_low).all(axis=-1))


def estimate_illuminant(
    img: np.ndarray, p: float = 1.0, clip_high: int = 250, clip_low: int = 5
) -> np.ndarray:
    """Illuminant RGB in linear space, unit L2 norm. p=1 gray-world, p>1 shades-of-gray, inf max-RGB."""
    lin = srgb_to_linear(img).reshape(-1, 3)
    m = valid_mask(img, clip_high, clip_low).reshape(-1)
    if m.sum() < 16:  # nothing usable: assume neutral light
        m = np.ones_like(m)
    v = lin[m].astype(np.float64)
    if np.isinf(p):
        e = v.max(axis=0)
    else:
        e = np.power(np.mean(np.power(v, p), axis=0), 1.0 / p)
    e = np.maximum(e, 1e-8)
    return (e / np.linalg.norm(e)).astype(np.float64)


def apply_white_balance(img: np.ndarray, illuminant: np.ndarray, max_gain: float = 2.0) -> np.ndarray:
    """Von Kries correction in linear RGB so ``illuminant`` maps to neutral gray."""
    e = np.asarray(illuminant, dtype=np.float64)
    gains = e.mean() / e
    gains = np.clip(gains, 1.0 / max_gain, max_gain)
    lin = srgb_to_linear(img)
    return linear_to_srgb(lin * gains.astype(np.float32))


def gray_world(img: np.ndarray, max_gain: float = 2.0, clip_high: int = 250, clip_low: int = 5) -> np.ndarray:
    return apply_white_balance(img, estimate_illuminant(img, 1.0, clip_high, clip_low), max_gain)


def shades_of_gray(
    img: np.ndarray, p: float = 6.0, max_gain: float = 2.0, clip_high: int = 250, clip_low: int = 5
) -> np.ndarray:
    return apply_white_balance(img, estimate_illuminant(img, p, clip_high, clip_low), max_gain)


def angular_error_deg(a: np.ndarray, b: np.ndarray) -> float:
    """Recovery angular error (degrees) between two illuminant RGB vectors (gray-card evaluation)."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    cos = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)))
    return float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))


# ---------------------------------------------------------------- CIE Lab (D65)

_M_RGB2XYZ = np.array(
    [[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]],
    dtype=np.float64,
)
_M_XYZ2RGB = np.linalg.inv(_M_RGB2XYZ)
_WHITE = _M_RGB2XYZ.sum(axis=1)  # D65 white of sRGB primaries
_EPS = (6 / 29) ** 3
_K = (29 / 6) ** 2 / 3


def _f(t: np.ndarray) -> np.ndarray:
    return np.where(t > _EPS, np.cbrt(t), t * _K + 4 / 29)


def _finv(t: np.ndarray) -> np.ndarray:
    return np.where(t > 6 / 29, t**3, (t - 4 / 29) / _K)


def rgb_to_lab(img: np.ndarray) -> np.ndarray:
    """sRGB uint8 -> float32 Lab with L in [0, 100]."""
    xyz = srgb_to_linear(img).astype(np.float64) @ _M_RGB2XYZ.T / _WHITE
    fx, fy, fz = (_f(xyz[..., i]) for i in range(3))
    lab = np.stack([116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)], axis=-1)
    return lab.astype(np.float32)


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    lab = np.asarray(lab, dtype=np.float64)
    fy = (lab[..., 0] + 16) / 116
    fx = fy + lab[..., 1] / 500
    fz = fy - lab[..., 2] / 200
    xyz = np.stack([_finv(fx), _finv(fy), _finv(fz)], axis=-1) * _WHITE
    return linear_to_srgb((xyz @ _M_XYZ2RGB.T).astype(np.float32))


# ---------------------------------------------------------------- CLAHE


def _clip_histograms(hist: np.ndarray, limit: int) -> np.ndarray:
    """Clip each 256-bin histogram at ``limit`` and redistribute the excess like OpenCV."""
    hist = hist.copy()
    excess = np.clip(hist - limit, 0, None).sum(axis=-1)
    hist = np.minimum(hist, limit)
    bonus = excess // 256
    hist += bonus[..., None]
    residual = excess - bonus * 256
    flat = hist.reshape(-1, 256)
    for i, r in enumerate(residual.reshape(-1)):
        if r > 0:
            step = max(256 // int(r), 1)
            idx = np.arange(0, 256, step)[: int(r)]
            flat[i, idx] += 1
    return flat.reshape(hist.shape)


def clahe_channel(ch: np.ndarray, clip_limit: float = 2.0, grid: tuple[int, int] = (8, 8)) -> np.ndarray:
    """CLAHE on a single uint8 channel (same parameters as ``cv2.createCLAHE``)."""
    ch = np.asarray(ch, dtype=np.uint8)
    h, w = ch.shape
    gy, gx = grid
    th, tw = -(-h // gy), -(-w // gx)
    ph, pw = th * gy - h, tw * gx - w
    mode = "reflect" if (ph < h and pw < w) else "edge"
    padded = np.pad(ch, ((0, ph), (0, pw)), mode=mode) if (ph or pw) else ch
    tiles = padded.reshape(gy, th, gx, tw).transpose(0, 2, 1, 3).reshape(gy * gx, th * tw)
    offs = (np.arange(gy * gx, dtype=np.int64) * 256)[:, None]
    hist = np.bincount((tiles.astype(np.int64) + offs).ravel(), minlength=256 * gy * gx).reshape(gy, gx, 256)
    area = th * tw
    if clip_limit > 0:
        limit = max(int(clip_limit * area / 256), 1)
        hist = _clip_histograms(hist, limit)
    lut = np.clip(np.rint(np.cumsum(hist, axis=-1) * (255.0 / area)), 0, 255).astype(np.float32)

    yf = (np.arange(h) + 0.5) / th - 0.5
    xf = (np.arange(w) + 0.5) / tw - 0.5
    y1 = np.floor(yf).astype(int)
    x1 = np.floor(xf).astype(int)
    ya = (yf - y1).astype(np.float32)[:, None]
    xa = (xf - x1).astype(np.float32)[None, :]
    y2 = np.clip(y1 + 1, 0, gy - 1)
    x2 = np.clip(x1 + 1, 0, gx - 1)
    y1 = np.clip(y1, 0, gy - 1)
    x1 = np.clip(x1, 0, gx - 1)
    v = ch.astype(np.int64)
    l11 = lut[y1[:, None], x1[None, :], v]
    l12 = lut[y1[:, None], x2[None, :], v]
    l21 = lut[y2[:, None], x1[None, :], v]
    l22 = lut[y2[:, None], x2[None, :], v]
    out = (1 - ya) * ((1 - xa) * l11 + xa * l12) + ya * ((1 - xa) * l21 + xa * l22)
    return np.clip(np.rint(out), 0, 255).astype(np.uint8)


def clahe_lab(img: np.ndarray, clip_limit: float = 2.0, grid: tuple[int, int] = (8, 8)) -> np.ndarray:
    """CLAHE on L* only (L scaled to 0..255 like OpenCV's 8-bit Lab), a* and b* untouched."""
    lab = rgb_to_lab(img)
    l8 = np.clip(np.rint(lab[..., 0] * 255.0 / 100.0), 0, 255).astype(np.uint8)
    lab[..., 0] = clahe_channel(l8, clip_limit, grid).astype(np.float32) * 100.0 / 255.0
    return lab_to_rgb(lab)


# ---------------------------------------------------------------- arms of the ablation

ARMS = ("none", "gw", "clahe", "gw_clahe")


def apply_arm(img: np.ndarray, arm: str, clip_limit: float = 2.0, grid: tuple[int, int] = (8, 8)) -> np.ndarray:
    """Preprocessing arm of the 2×2 ablation: none / gray-world / CLAHE-L / gray-world then CLAHE-L."""
    if arm == "none":
        return np.asarray(img, dtype=np.uint8)
    if arm == "gw":
        return gray_world(img)
    if arm == "clahe":
        return clahe_lab(img, clip_limit, grid)
    if arm == "gw_clahe":
        return clahe_lab(gray_world(img), clip_limit, grid)
    raise ValueError(f"unknown arm {arm!r}; expected one of {ARMS}")
