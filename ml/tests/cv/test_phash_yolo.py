import numpy as np

from tastoria_ml.cv.phash import dedupe, hamming, phash
from tastoria_ml.cv.yolo_format import from_corners_norm, from_voc, write_label


def _img(seed, h=120, w=160):
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 256, size=(12, 16, 3)).astype(np.uint8)
    return np.kron(base, np.ones((h // 12, w // 16, 1), dtype=np.uint8))


def test_phash_is_stable_under_small_changes_and_differs_between_images():
    a = _img(0)
    noisy = np.clip(a.astype(int) + np.random.default_rng(1).integers(-6, 7, a.shape), 0, 255).astype(np.uint8)
    brighter = np.clip(a.astype(int) + 20, 0, 255).astype(np.uint8)
    ha = phash(a)
    assert hamming(ha, phash(noisy)) <= 4
    assert hamming(ha, phash(brighter)) <= 4
    assert hamming(ha, phash(_img(2))) > 12


def test_dedupe_keeps_protected_items_and_drops_copies():
    a, b = phash(_img(0)), phash(_img(5))
    keep = dedupe([a, b, a, b, phash(_img(9))], threshold=4, keep_first=2)
    assert keep == [0, 1, 4]


def test_box_conversions():
    b = from_corners_norm(3, 0.2, 0.1, 0.6, 0.5)
    assert b.line() == "3 0.400000 0.300000 0.400000 0.400000"
    clipped = from_corners_norm(1, -0.1, 0.0, 0.5, 1.2)
    assert (clipped.xc, clipped.w, clipped.h) == (0.25, 0.5, 1.0)
    assert from_corners_norm(0, 0.5, 0.5, 0.501, 0.9) is None
    v = from_voc(2, 64, 36, 192, 108, 640, 360)
    assert abs(v.xc - 0.2) < 1e-9 and abs(v.yc - 0.2) < 1e-9 and abs(v.w - 0.2) < 1e-9
    assert write_label([b, v]).count("\n") == 2
