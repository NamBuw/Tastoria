"""Tier 2: Boundary Value Analysis & Negative/Rejection E2E tests for ML/CV and detector pipelines."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pytest
from PIL import Image, ImageDraw

from tastoria.core.errors import ApiError
from tastoria.modules.scan.detector import Detector, Letterbox, decode, letterbox
from tastoria.modules.scan.images import MAX_BYTES, sanitize
from tastoria_ml.cv.classes import REPO
from tastoria_ml.cv.yolo_format import MIN_SIDE, from_corners_norm

pytestmark = pytest.mark.tier2


def _make_jpeg_bytes(w: int = 64, h: int = 48, *, color: tuple[int, int, int] = (120, 160, 80)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def _png_bomb_header() -> bytes:
    buf = io.BytesIO()
    Image.new("L", (1, 1)).save(buf, "PNG")
    data = bytearray(buf.getvalue())
    data[16:24] = (30000).to_bytes(4, "big") * 2
    return bytes(data)


@pytest.mark.parametrize(
    ("case", "expected_statuses", "expected_codes"),
    [
        ("zero_byte", {415}, {"unsupported_media_type"}),
        ("random_garbage", {415}, {"unsupported_media_type"}),
        ("truncated_jpeg", {415}, {"unsupported_media_type"}),
        ("svg_markup", {415}, {"unsupported_media_type"}),
        ("oversize_bytes", {413}, {"image_too_large"}),
        ("pixel_bomb_jpeg", {422}, {"image_too_many_pixels"}),
        ("png_ihdr_bomb", {415, 422}, {"unsupported_media_type", "image_too_many_pixels"}),
    ],
)
def test_corrupt_truncated_zero_byte_and_bomb_images_rejected(
    case: str, expected_statuses: set[int], expected_codes: set[str]
) -> None:
    if case == "zero_byte":
        payload = b""
    elif case == "random_garbage":
        payload = b"\x89NOTANIMAGE\x00\xff\x13\x37" * 8
    elif case == "truncated_jpeg":
        payload = _make_jpeg_bytes(64, 48)[:48]
    elif case == "svg_markup":
        payload = b"<svg xmlns='http://www.w3.org/2000/svg'><rect width='10' height='10'/></svg>"
    elif case == "oversize_bytes":
        base = _make_jpeg_bytes(32, 32)
        payload = base + b"\x00" * (MAX_BYTES + 1 - len(base))
    elif case == "pixel_bomb_jpeg":
        buf = io.BytesIO()
        Image.new("RGB", (4097, 4096), (0, 0, 0)).save(buf, "JPEG", quality=10)
        payload = buf.getvalue()
    else:
        payload = _png_bomb_header()

    with pytest.raises(ApiError) as exc:
        sanitize(payload)
    assert exc.value.status in expected_statuses
    assert exc.value.code.value in expected_codes


@pytest.mark.parametrize("size", [(1000, 10), (10, 1000), (1, 1), (4096, 256)])
def test_extreme_aspect_ratios_letterbox_and_detector(
    size: tuple[int, int], e2e_config, onnx_session: ort.InferenceSession
) -> None:
    serving = json.loads(e2e_config.serving_path.read_text(encoding="utf-8"))
    det = Detector(onnx_session, conf=float(serving["conf"]), iou=float(serving["iou"]))
    im = Image.new("RGB", size, (140, 180, 90))
    x, lb = letterbox(im, det.size)
    assert x.shape == (1, 3, det.size, det.size)
    assert np.all(np.isfinite(x))
    assert lb.scale > 0 and np.isfinite(lb.scale)

    boxes = det.detect(im)
    for b in boxes:
        assert 0.0 <= b.x1 < b.x2 <= 1.0
        assert 0.0 <= b.y1 < b.y2 <= 1.0
        assert 0.0 < b.confidence <= 1.0


@pytest.mark.parametrize("orientation", [1, 2, 3, 4, 5, 6, 7, 8])
def test_exif_all_8_orientations_roundtrip(orientation: int) -> None:
    # Upright canvas (80x60) with a bright red marker in the top-left quadrant
    upright = Image.new("RGB", (80, 60), (20, 30, 200))
    ImageDraw.Draw(upright).rectangle([0, 0, 24, 18], fill=(240, 20, 20))

    inverse_ops = {
        1: None,
        2: Image.Transpose.FLIP_LEFT_RIGHT,
        3: Image.Transpose.ROTATE_180,
        4: Image.Transpose.FLIP_TOP_BOTTOM,
        5: Image.Transpose.TRANSPOSE,
        6: Image.Transpose.ROTATE_90,
        7: Image.Transpose.TRANSVERSE,
        8: Image.Transpose.ROTATE_270,
    }
    op = inverse_ops[orientation]
    stored = upright.transpose(op) if op is not None else upright

    ex = Image.Exif()
    ex[0x0112] = orientation
    ex[0x010F] = "LeakCam"
    buf = io.BytesIO()
    stored.save(buf, "JPEG", quality=98, exif=ex.tobytes())

    cleaned = sanitize(buf.getvalue())
    assert (cleaned.width, cleaned.height) == (80, 60)
    with Image.open(io.BytesIO(cleaned.jpeg)) as out_im:
        assert not out_im.getexif()
        assert "exif" not in out_im.info
        px = out_im.getpixel((8, 6))
        assert px[0] > 180 and px[2] < 80, f"Top-left marker lost for orientation={orientation}: {px}"


@pytest.mark.parametrize("case", ["hard_neg_empty_txt", "below_min_side_dropped", "at_min_side_kept"])
def test_zero_box_hard_negatives_and_degenerate_yolo_boxes(
    case: str, e2e_config, manifest_rows: list[dict[str, str]]
) -> None:
    if case == "hard_neg_empty_txt":
        neg_rows = [r for r in manifest_rows if int(r["is_hard_neg"]) == 1]
        assert len(neg_rows) > 0
        for r in neg_rows[:20]:
            assert int(r["n_boxes"]) == 0
            stem = Path(r["file"]).stem
            lbl = e2e_config.dataset_dir / "labels" / r["split"] / f"{stem}.txt"
            assert lbl.is_file()
            assert lbl.read_text(encoding="utf-8").strip() == ""
    elif case == "below_min_side_dropped":
        assert from_corners_norm(0, 0.5, 0.5, 0.5 + MIN_SIDE * 0.5, 0.6) is None
        assert from_corners_norm(0, 0.5, 0.5, 0.6, 0.5 + MIN_SIDE * 0.5) is None
        assert from_corners_norm(0, 1.2, 1.2, 1.5, 1.5) is None
    else:
        b = from_corners_norm(0, 0.1, 0.2, 0.1 + MIN_SIDE + 1e-4, 0.2 + MIN_SIDE + 1e-4)
        assert b is not None and b.cls == 0 and b.w >= MIN_SIDE and b.h >= MIN_SIDE


@pytest.mark.parametrize(
    "case",
    ["below_conf", "at_conf", "disabled_class_conf_1", "all_zero_output", "padding_only_box"],
)
def test_decode_confidence_and_padding_boundaries(case: str) -> None:
    lb = Letterbox(scale=0.5, pad_x=0, pad_y=140, width=1280, height=720)
    ident = Letterbox(scale=1.0, pad_x=0, pad_y=0, width=640, height=640)
    conf = 0.33

    if case == "below_conf":
        out = np.zeros((1, 4 + 3, 2), dtype=np.float32)
        out[0, :4, 0] = (320.0, 320.0, 80.0, 80.0)
        out[0, 4 + 0, 0] = conf - 1e-6
        assert decode(out, ident, conf=conf, iou=0.45) == []
    elif case == "at_conf":
        out = np.zeros((1, 4 + 3, 2), dtype=np.float32)
        out[0, :4, 0] = (320.0, 320.0, 80.0, 80.0)
        out[0, 4 + 0, 0] = conf
        boxes = decode(out, ident, conf=conf, iou=0.45)
        assert len(boxes) == 1 and boxes[0].class_index == 0
    elif case == "disabled_class_conf_1":
        out = np.zeros((1, 4 + 3, 1), dtype=np.float32)
        out[0, :4, 0] = (200.0, 200.0, 60.0, 60.0)
        out[0, 4 + 0, 0] = 1.0  # disabled class must not steal anchor
        out[0, 4 + 1, 0] = 0.45  # enabled class survives
        boxes = decode(out, ident, conf=0.33, iou=0.45, class_conf={0: 1.0, 1: 0.40})
        assert len(boxes) == 1 and boxes[0].class_index == 1
    elif case == "all_zero_output":
        out = np.zeros((1, 4 + 37, 8400), dtype=np.float32)
        assert decode(out, ident, conf=0.05, iou=0.7) == []
    else:
        # Box sits entirely in top letterbox padding (y in [10, 90] < pad_y=140)
        out = np.zeros((1, 4 + 3, 1), dtype=np.float32)
        out[0, :4, 0] = (320.0, 50.0, 100.0, 80.0)
        out[0, 4 + 0, 0] = 0.99
        assert decode(out, lb, conf=0.10, iou=0.7) == []


def test_disk_free_space_and_no_leftover_archives_or_secrets(e2e_config) -> None:
    st = os.statvfs(REPO)
    free_gb = (st.f_bavail * st.f_frsize) / (1024**3)
    assert free_gb >= e2e_config.min_disk_gb, f"Free disk {free_gb:.2f} GB < {e2e_config.min_disk_gb} GB"

    archive_exts = {".zip", ".tar", ".gz", ".tgz", ".rar", ".7z"}
    check_dirs = [e2e_config.dataset_dir, REPO / "data/processed/cv"]
    if e2e_config.strict:
        check_dirs.append(REPO / "data/raw/images")
    else:
        for sub in ("dfv16", "nutrition5k", "roboflow", "v3det", "openimages_v7"):
            check_dirs.append(REPO / "data/raw/images" / sub)
    for folder in check_dirs:
        if folder.is_dir():
            leftovers = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in archive_exts]
            assert not leftovers, f"Leftover archives found under {folder}: {leftovers[:5]}"

    secret_markers = ("ROBOFLOW_API_KEY", "api_key=", "hf_", "BEGIN PRIVATE KEY")
    for meta_file in (
        e2e_config.stats_json,
        e2e_config.cleaning_json,
        e2e_config.serving_path,
        e2e_config.manifest_csv,
    ):
        txt = meta_file.read_text(encoding="utf-8", errors="ignore")[:500_000]
        for marker in secret_markers:
            assert marker not in txt, f"Potential secret marker {marker!r} found in {meta_file}"
