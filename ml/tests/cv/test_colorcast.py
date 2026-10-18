import random

import numpy as np

from tastoria_ml.cv import colorcast as cc
from tastoria_ml.cv import preprocess as pp


def test_unit_gains_are_identity():
    img = np.random.default_rng(0).integers(0, 256, (32, 48, 3), dtype=np.uint8)
    out = cc.apply_gains(img, np.ones(3))
    assert np.abs(out.astype(int) - img).max() <= 1  # 4096-level linear LUT


def test_gains_act_in_linear_space_and_bgr_order():
    img = np.full((4, 4, 3), 128, np.uint8)
    out = cc.apply_gains(img, cc.cast_gains(1.0, 0.0, 0.0))  # R x2, B x0.5 in linear light
    lin_in = pp.srgb_to_linear(img)[0, 0]
    lin_out = pp.srgb_to_linear(out)[0, 0]
    assert np.allclose(lin_out / lin_in, [2.0, 1.0, 0.5], atol=0.02)
    bgr = cc.apply_gains(img[..., ::-1], cc.cast_gains(1.0, 0.0, 0.0), bgr=True)
    assert np.array_equal(bgr[..., ::-1], out)


def test_gray_world_undoes_a_sampled_cast():
    rng = np.random.default_rng(1)
    lin = rng.uniform(0.05, 0.5, size=(64, 64, 1)).repeat(3, -1) * rng.uniform(0.9, 1.1, (64, 64, 3))
    img = pp.linear_to_srgb(lin)
    cast = cc.apply_gains(img, cc.cast_gains(0.5, 0.1, 0.0))
    m = pp.srgb_to_linear(cast).reshape(-1, 3).mean(0)
    assert m[0] / m[2] > 1.8
    fixed = pp.srgb_to_linear(pp.gray_world(cast)).reshape(-1, 3).mean(0)
    assert fixed.max() / fixed.min() < 1.05


def test_transform_respects_probability_and_shape():
    random.seed(0)
    img = np.full((8, 8, 3), 100, np.uint8)
    t0 = cc.RandomIlluminant(p=0.0)
    assert t0({"img": img.copy()})["img"] is not None
    assert np.array_equal(t0({"img": img.copy()})["img"], img)
    t1 = cc.RandomIlluminant(p=1.0)
    changed = [not np.array_equal(t1({"img": img.copy()})["img"], img) for _ in range(20)]
    assert sum(changed) >= 18
    assert t1({"img": img.copy()})["img"].shape == img.shape
