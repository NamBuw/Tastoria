"""Tier 2: Backend Boundary Value Analysis & Negative/Rejection E2E tests."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image, ImageDraw

from tastoria.core.errors import ApiError
from tastoria.modules.journal.service import parse_week
from tastoria.modules.scan.aggregate import build_chips
from tastoria.modules.scan.detector import Letterbox, decode
from tastoria.modules.scan.images import MAX_BYTES, sanitize

pytestmark = pytest.mark.tier2

REPO_ROOT = Path(__file__).resolve().parents[3]
KB_DIR = REPO_ROOT / "data/kb"


def _jpeg(w: int = 64, h: int = 48, color: tuple[int, int, int] = (180, 90, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _png_bomb() -> bytes:
    buf = io.BytesIO()
    Image.new("L", (1, 1)).save(buf, "PNG")
    data = bytearray(buf.getvalue())
    data[16:24] = (30000).to_bytes(4, "big") * 2
    return bytes(data)


@pytest.mark.parametrize(
    ("case", "statuses", "codes"),
    [
        ("empty", {415}, {"unsupported_media_type"}),
        ("truncated_jpeg", {415}, {"unsupported_media_type"}),
        ("svg", {415}, {"unsupported_media_type"}),
        ("html", {415}, {"unsupported_media_type"}),
        ("pdf", {415}, {"unsupported_media_type"}),
        ("oversize", {413}, {"image_too_large"}),
        ("pixel_bomb_4097", {422}, {"image_too_many_pixels"}),
        ("png_ihdr_30k", {415, 422}, {"unsupported_media_type", "image_too_many_pixels"}),
    ],
)
def test_images_sanitize_attack_and_corrupt_payloads(case: str, statuses: set[int], codes: set[str]) -> None:
    if case == "empty":
        raw = b""
    elif case == "truncated_jpeg":
        raw = b"\xff\xd8\xff\xe0" + b"\x00" * 64
    elif case == "svg":
        raw = b"<svg xmlns='http://www.w3.org/2000/svg'/>"
    elif case == "html":
        raw = b"<html><script>alert(1)</script></html>"
    elif case == "pdf":
        raw = b"%PDF-1.7\n%%EOF\n"
    elif case == "oversize":
        small = _jpeg()
        raw = small + b"\x00" * (MAX_BYTES + 1 - len(small))
    elif case == "pixel_bomb_4097":
        buf = io.BytesIO()
        Image.new("RGB", (4097, 4096), (0, 0, 0)).save(buf, "JPEG", quality=10)
        raw = buf.getvalue()
    else:
        raw = _png_bomb()

    with pytest.raises(ApiError) as exc:
        sanitize(raw)
    assert exc.value.status in statuses
    assert exc.value.code.value in codes


@pytest.mark.parametrize("size", [(1600, 100), (100, 1600), (32, 32), (4096, 4096)])
def test_detector_extreme_aspect_ratios(size: tuple[int, int], e2e_detector) -> None:
    im = Image.new("RGB", size, (110, 130, 150))
    boxes = e2e_detector.detector.detect(im)
    for b in boxes:
        assert np.isfinite(b.confidence) and 0.0 < b.confidence <= 1.0
        assert 0.0 <= b.x1 < b.x2 <= 1.0 and 0.0 <= b.y1 < b.y2 <= 1.0


@pytest.mark.parametrize("orientation", [1, 2, 3, 4, 5, 6, 7, 8])
def test_sanitize_and_detect_all_8_exif_orientations(orientation: int, e2e_detector) -> None:
    upright = Image.new("RGB", (96, 64), (30, 150, 40))
    ImageDraw.Draw(upright).rectangle([0, 0, 28, 20], fill=(240, 30, 30))

    inv = {
        1: None,
        2: Image.Transpose.FLIP_LEFT_RIGHT,
        3: Image.Transpose.ROTATE_180,
        4: Image.Transpose.FLIP_TOP_BOTTOM,
        5: Image.Transpose.TRANSPOSE,
        6: Image.Transpose.ROTATE_90,
        7: Image.Transpose.TRANSVERSE,
        8: Image.Transpose.ROTATE_270,
    }[orientation]
    stored = upright.transpose(inv) if inv is not None else upright

    ex = Image.Exif()
    ex[0x0112] = orientation
    ex[0x010F] = "SecretMaker"
    ex[0x8825] = {1: "N", 2: (21.0, 1.0, 30.0), 3: "E", 4: (105.0, 51.0, 0.0)}
    buf = io.BytesIO()
    stored.save(buf, "JPEG", quality=96, exif=ex.tobytes())

    cleaned = sanitize(buf.getvalue())
    assert (cleaned.width, cleaned.height) == (96, 64)
    assert b"Exif" not in cleaned.jpeg and b"SecretMaker" not in cleaned.jpeg and b"\xff\xe1" not in cleaned.jpeg
    with Image.open(io.BytesIO(cleaned.jpeg)) as out_im:
        assert not out_im.getexif()
        px = out_im.getpixel((10, 8))
        assert px[0] > 180 and px[1] < 90
        boxes = e2e_detector.detector.detect(out_im)
        assert all(0.0 <= b.x1 < b.x2 <= 1.0 and 0.0 <= b.y1 < b.y2 <= 1.0 for b in boxes)


@pytest.mark.parametrize(
    "case",
    ["black", "white", "gray114", "noise", "conf_minus_eps", "conf_exact", "anchor_steal_guard", "empty_chips"],
)
def test_borderline_confidence_anchor_stealing_and_empty_chips(case: str, e2e_detector) -> None:
    ident = Letterbox(1.0, 0, 0, 640, 640)
    if case in {"black", "white", "gray114", "noise"}:
        if case == "black":
            im = Image.new("RGB", (320, 320), (0, 0, 0))
        elif case == "white":
            im = Image.new("RGB", (320, 320), (255, 255, 255))
        elif case == "gray114":
            im = Image.new("RGB", (320, 320), (114, 114, 114))
        else:
            arr = np.random.default_rng(7).integers(0, 256, size=(320, 320, 3), dtype=np.uint8)
            im = Image.fromarray(arr, mode="RGB")
        boxes = e2e_detector.detector.detect(im)
        assert all(0.0 <= b.x1 < b.x2 <= 1.0 and 0.0 <= b.y1 < b.y2 <= 1.0 for b in boxes)
    elif case == "conf_minus_eps":
        out = np.zeros((1, 4 + 3, 1), dtype=np.float32)
        out[0, :4, 0] = (320.0, 320.0, 80.0, 80.0)
        out[0, 4, 0] = 0.33 - 1e-5
        assert decode(out, ident, conf=0.33, iou=0.45) == []
    elif case == "conf_exact":
        out = np.zeros((1, 4 + 3, 1), dtype=np.float32)
        out[0, :4, 0] = (320.0, 320.0, 80.0, 80.0)
        out[0, 4, 0] = 0.33
        assert len(decode(out, ident, conf=0.33, iou=0.45)) == 1
    elif case == "anchor_steal_guard":
        out = np.zeros((1, 4 + 3, 1), dtype=np.float32)
        out[0, :4, 0] = (320.0, 320.0, 80.0, 80.0)
        out[0, 4 + 0, 0] = 0.95  # disabled via class_conf=1.0
        out[0, 4 + 1, 0] = 0.50  # enabled class must not be masked
        boxes = decode(out, ident, conf=0.33, iou=0.45, class_conf={0: 1.0, 1: 0.33})
        assert len(boxes) == 1 and boxes[0].class_index == 1
    else:
        assert build_chips([], {}) == []


@pytest.mark.parametrize("week", ["2026-W54", "abc", "2026-W00", "2021-W53", ""])
def test_journal_invalid_iso_week_rejected(week: str) -> None:
    with pytest.raises(ApiError) as exc:
        parse_week(week)
    assert exc.value.status == 422
    assert exc.value.code.value == "invalid_iso_week"


def test_pantry_qty_level_and_meal_calorie_portion_boundaries(
    e2e_cfg, meal_calorie_probe: dict | None
) -> None:
    qty_doc = yaml.safe_load((KB_DIR / "ref/qty_levels.yaml").read_text(encoding="utf-8"))
    qty_groups = qty_doc.get("qty_levels") or qty_doc.get("food_groups") or qty_doc
    assert isinstance(qty_groups, dict) and len(qty_groups) > 0
    for grp, lvls in qty_groups.items():
        if not isinstance(lvls, dict) or not {"it", "vua", "nhieu"} <= set(lvls):
            continue
        it_rng, vua_rng, nhieu_rng = lvls["it"], lvls["vua"], lvls["nhieu"]
        assert 0 < it_rng[0] <= it_rng[1] <= vua_rng[0] <= vua_rng[1] <= nhieu_rng[0] <= nhieu_rng[1], (
            f"Invalid qty_level intervals for {grp}: {lvls}"
        )

    if meal_calorie_probe is None:
        assert not e2e_cfg.strict
        return

    svc = meal_calorie_probe["service"]
    deps = meal_calorie_probe["deps"]
    pho_bytes = (REPO_ROOT / "app/assets/food/pho.webp").read_bytes()
    with pytest.raises(ApiError) as exc_p:
        svc.estimate_meal_calories(deps, dish_slug="bo-kho", portion="khong_lo")
    assert exc_p.value.status == 422

    with pytest.raises(ApiError) as exc_e:
        svc.estimate_meal_calories(deps, image_bytes=None, dish_slug=None, dish_name="  ")
    assert exc_e.value.status == 422

    with pytest.raises(ApiError) as exc_i:
        svc.estimate_meal_calories(deps, image_bytes=b"not-an-image", portion="vua")
    assert exc_i.value.status == 415

    if meal_calorie_probe["has_onnx"] or e2e_cfg.strict:
        res = svc.estimate_meal_calories(deps, image_bytes=pho_bytes, portion="vua")
        assert res.estimated_kcal > 0.0
