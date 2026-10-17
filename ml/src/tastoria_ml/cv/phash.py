"""Perceptual hash (DCT pHash, 64 bit) and near-duplicate removal, numpy only."""

from __future__ import annotations

import numpy as np

_N = 32
_K = 8


def _dct_matrix(n: int) -> np.ndarray:
    k = np.arange(n)[:, None]
    i = np.arange(n)[None, :]
    m = np.cos(np.pi * (2 * i + 1) * k / (2 * n)) * np.sqrt(2 / n)
    m[0] /= np.sqrt(2)
    return m


_D = _dct_matrix(_N)


def _area_resize(gray: np.ndarray, n: int) -> np.ndarray:
    h, w = gray.shape
    ys = (np.arange(h) * n // h).astype(np.int64)
    xs = (np.arange(w) * n // w).astype(np.int64)
    idx = ys[:, None] * n + xs[None, :]
    s = np.bincount(idx.ravel(), weights=gray.ravel().astype(np.float64), minlength=n * n)
    c = np.bincount(idx.ravel(), minlength=n * n)
    return (s / np.maximum(c, 1)).reshape(n, n)


def phash(img: np.ndarray) -> int:
    """64-bit pHash of an RGB or gray uint8 image (larger than 32×32)."""
    a = np.asarray(img, dtype=np.float64)
    if a.ndim == 3:
        a = a[..., :3] @ np.array([0.299, 0.587, 0.114])
    small = _area_resize(a, _N)
    coef = (_D @ small @ _D.T)[:_K, :_K].ravel()
    bits = coef > np.median(coef[1:])
    return int(np.packbits(bits).view(">u8")[0])


def hamming(a: np.ndarray | int, b: np.ndarray | int) -> np.ndarray:
    x = np.atleast_1d(np.bitwise_xor(np.asarray(a, dtype=np.uint64), np.asarray(b, dtype=np.uint64)))
    d = np.unpackbits(x.view(np.uint8).reshape(*x.shape, 8), axis=-1).sum(axis=-1)
    return d if np.ndim(a) or np.ndim(b) else int(d[0])


def dedupe(hashes: list[int], threshold: int = 4, keep_first: int = 0) -> list[int]:
    """Greedy near-duplicate removal; returns indices to keep.

    Items are visited in order, an item is dropped when its Hamming distance to any kept item is
    ≤ ``threshold``. The first ``keep_first`` items are always kept (e.g. the frozen test images), so
    later train images that copy them are removed rather than the test images.
    """
    h = np.asarray(hashes, dtype=np.uint64)
    kept: list[int] = []
    kept_h = np.empty(0, dtype=np.uint64)
    for i, v in enumerate(h):
        if i >= keep_first and kept_h.size and hamming(kept_h, v).min() <= threshold:
            continue
        kept.append(i)
        kept_h = np.append(kept_h, v)
    return kept
