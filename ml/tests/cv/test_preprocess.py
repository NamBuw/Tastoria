import numpy as np
import pytest

from tastoria_ml.cv import preprocess as pp


def _cast_scene(rng, gains=(1.3, 1.0, 0.7), h=64, w=96):
    """Random neutral-average scene in linear RGB, rendered under a coloured light."""
    lin = rng.uniform(0.05, 0.6, size=(h, w, 1)).repeat(3, axis=-1)
    lin *= rng.uniform(0.8, 1.2, size=(h, w, 3))  # mild per-pixel chroma that averages out
    lin *= np.array(gains, dtype=np.float32)
    return pp.linear_to_srgb(lin)


def test_srgb_roundtrip_is_exact_on_8bit():
    v = np.arange(256, dtype=np.uint8)
    assert np.array_equal(pp.linear_to_srgb(pp.srgb_to_linear(v)), v)


def test_gray_world_removes_cast_in_linear_space():
    rng = np.random.default_rng(0)
    img = _cast_scene(rng)
    before = pp.srgb_to_linear(img).reshape(-1, 3).mean(0)
    out = pp.gray_world(img)
    after = pp.srgb_to_linear(out).reshape(-1, 3).mean(0)
    assert before.max() / before.min() > 1.5
    assert after.max() / after.min() < 1.03


def test_illuminant_ignores_clipped_pixels():
    rng = np.random.default_rng(1)
    img = _cast_scene(rng)
    e0 = pp.estimate_illuminant(img)
    blown = img.copy()
    blown[:, :40] = (255, 255, 120)  # blown-out yellow highlight (R, G clipped)
    e1 = pp.estimate_illuminant(blown)
    assert pp.angular_error_deg(e0, e1) < 1.0
    # without the mask the highlight would bias the estimate
    m = pp.valid_mask(blown)
    assert not m[:, :40].any() and m[:, 40:].mean() > 0.95


def test_estimated_illuminant_matches_true_light():
    rng = np.random.default_rng(2)
    light = np.array([1.3, 1.0, 0.7])
    img = _cast_scene(rng, gains=light)
    for p in (1.0, 6.0):
        assert pp.angular_error_deg(pp.estimate_illuminant(img, p), light) < 1.5


def test_shades_of_gray_p1_equals_gray_world_and_inf_is_max_rgb():
    rng = np.random.default_rng(3)
    img = _cast_scene(rng)
    assert np.array_equal(pp.shades_of_gray(img, p=1.0), pp.gray_world(img))
    lin = pp.srgb_to_linear(img).reshape(-1, 3)
    m = pp.valid_mask(img).reshape(-1)
    e = lin[m].max(0)
    assert pp.angular_error_deg(pp.estimate_illuminant(img, np.inf), e) < 1e-6


def test_gain_clamp_limits_single_hue_frames():
    green = np.zeros((32, 32, 3), np.uint8)
    green[...] = (40, 160, 40)  # a shelf full of greens: gray-world would push R and B up ~4x
    out = pp.gray_world(green, max_gain=2.0)
    gain = pp.srgb_to_linear(out)[0, 0] / pp.srgb_to_linear(green)[0, 0]
    assert gain.max() <= 2.0 + 0.02 and gain.min() >= 0.5 - 0.02  # 8-bit rounding


def test_angular_error():
    assert pp.angular_error_deg([1, 1, 1], [2, 2, 2]) == pytest.approx(0.0, abs=1e-6)
    assert pp.angular_error_deg([1, 0, 0], [0, 1, 0]) == pytest.approx(90.0)


def test_lab_known_values_and_roundtrip():
    white = np.full((1, 1, 3), 255, np.uint8)
    lab = pp.rgb_to_lab(white)[0, 0]
    assert lab[0] == pytest.approx(100.0, abs=0.01)
    assert abs(lab[1]) < 0.01 and abs(lab[2]) < 0.01
    red = pp.rgb_to_lab(np.array([[[255, 0, 0]]], np.uint8))[0, 0]
    assert red == pytest.approx([53.24, 80.09, 67.20], abs=0.05)
    rng = np.random.default_rng(4)
    img = rng.integers(0, 256, size=(50, 50, 3), dtype=np.uint8)
    back = pp.lab_to_rgb(pp.rgb_to_lab(img))
    assert np.abs(back.astype(int) - img).max() <= 1


def test_clahe_one_tile_no_clip_is_histogram_equalisation():
    rng = np.random.default_rng(5)
    ch = rng.integers(60, 120, size=(40, 40), dtype=np.uint8)
    out = pp.clahe_channel(ch, clip_limit=0, grid=(1, 1))
    cdf = np.cumsum(np.bincount(ch.ravel(), minlength=256))
    expected = np.clip(np.rint(cdf * 255.0 / ch.size), 0, 255).astype(np.uint8)[ch]
    assert np.array_equal(out, expected)


def test_clahe_raises_contrast_and_keeps_order_within_tile():
    x = np.linspace(100, 140, 64).astype(np.uint8)
    ch = np.tile(x, (64, 1))
    out = pp.clahe_channel(ch, clip_limit=4.0, grid=(1, 1))
    assert out.std() > ch.std() * 2
    assert np.all(np.diff(out[0].astype(int)) >= 0)


def test_clahe_handles_sizes_not_divisible_by_grid():
    rng = np.random.default_rng(6)
    ch = rng.integers(0, 256, size=(37, 53), dtype=np.uint8)
    out = pp.clahe_channel(ch, 2.0, (8, 8))
    assert out.shape == ch.shape and out.dtype == np.uint8


def test_clahe_lab_keeps_gray_gray():
    ramp = np.linspace(20, 230, 48).astype(np.uint8)
    img = np.repeat(np.tile(ramp, (48, 1))[..., None], 3, axis=-1)
    out = pp.clahe_lab(img)
    spread = out.astype(int).max(-1) - out.astype(int).min(-1)
    assert spread.max() <= 2  # no colour introduced: only L changed


def test_clahe_matches_opencv_when_available():
    cv2 = pytest.importorskip("cv2")
    rng = np.random.default_rng(7)
    ch = (rng.normal(128, 20, size=(120, 160)).clip(0, 255)).astype(np.uint8)
    ref = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(ch)
    out = pp.clahe_channel(ch, 2.0, (8, 8))
    assert np.abs(out.astype(int) - ref.astype(int)).max() <= 2


def test_apply_arm():
    rng = np.random.default_rng(8)
    img = _cast_scene(rng)
    assert np.array_equal(pp.apply_arm(img, "none"), img)
    assert np.array_equal(pp.apply_arm(img, "gw"), pp.gray_world(img))
    assert np.array_equal(pp.apply_arm(img, "gw_clahe"), pp.clahe_lab(pp.gray_world(img)))
    with pytest.raises(ValueError):
        pp.apply_arm(img, "bogus")
