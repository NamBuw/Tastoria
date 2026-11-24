from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

from tastoria_ml.cv import build_yolo_v2, roboflow_ingest as rf


def _make_display_patch(w: int = 120, h: int = 80, box: tuple[int, int, int, int] = (14, 10, 26, 18)) -> Image.Image:
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[..., 2] = 180  # dark blue background
    x, y, bw, bh = box
    arr[y : y + bh, x : x + bw] = (235, 25, 25)  # bright red target patch
    return Image.fromarray(arr, mode="RGB")


def _encode_with_exif(display_im: Image.Image, orient: int, path: Path) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Save raw JPEG with EXIF Orientation tag ``orient`` such that exif_transpose(raw) == display_im.

    Returns ``(raw_im, raw_box_xywh)``.
    """
    w, h = display_im.size
    bx, by, bw, bh = 14, 10, 26, 18
    if orient == 1:
        raw = display_im.copy()
        raw_box = (bx, by, bw, bh)
    elif orient == 3:
        raw = display_im.transpose(Image.Transpose.ROTATE_180)
        raw_box = (w - (bx + bw), h - (by + bh), bw, bh)
    elif orient == 6:
        # Display = ROTATE_270(raw), so raw = ROTATE_90(display)
        raw = display_im.transpose(Image.Transpose.ROTATE_90)
        raw_box = (by, w - (bx + bw), bh, bw)
    elif orient == 8:
        # Display = ROTATE_90(raw), so raw = ROTATE_270(display)
        raw = display_im.transpose(Image.Transpose.ROTATE_270)
        raw_box = (h - (by + bh), bx, bh, bw)
    else:
        raise ValueError(orient)
    exif = Image.Exif()
    exif[274] = orient
    path.parent.mkdir(parents=True, exist_ok=True)
    raw.save(path, format="JPEG", quality=98, exif=exif)
    return raw, raw_box


def _assert_patch_is_red(img_path: Path, bbox: list[float]) -> None:
    x, y, w, h = bbox
    with Image.open(img_path) as im:
        arr = np.asarray(im.convert("RGB"))
    cx0 = max(0, int(round(x + w * 0.25)))
    cx1 = min(arr.shape[1], int(round(x + w * 0.75)))
    cy0 = max(0, int(round(y + h * 0.25)))
    cy1 = min(arr.shape[0], int(round(y + h * 0.75)))
    patch = arr[cy0:cy1, cx0:cx1]
    assert patch.size > 0
    mean_rgb = patch.mean(axis=(0, 1))
    assert mean_rgb[0] > 180 and mean_rgb[1] < 70 and mean_rgb[2] < 70, f"bbox patch not red: {mean_rgb}"


@pytest.mark.parametrize("orient", [1, 3, 6, 8])
def test_coco_raw_space_exif(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, orient: int) -> None:
    monkeypatch.setattr(rf, "ROOT", tmp_path / "raw_rf")
    disp = _make_display_patch(120, 80)
    extract = tmp_path / "extract"
    img_path = extract / "train" / f"sample_{orient}.jpg"
    raw_im, raw_box = _encode_with_exif(disp, orient, img_path)

    coco = {
        "categories": [{"id": 1, "name": "tomato"}],
        "images": [{"id": 10, "file_name": img_path.name, "width": raw_im.width, "height": raw_im.height}],
        "annotations": [{"id": 1, "image_id": 10, "category_id": 1, "bbox": list(raw_box)}],
    }
    (extract / "train" / "_annotations.coco.json").write_text(json.dumps(coco), encoding="utf-8")

    spec = rf.SourceSpec(
        name="test_coco_raw",
        workspace="w",
        project="p",
        version=1,
        fmt="coco",
        license="CC BY 4.0",
        url="https://example.com",
        class_map={"tomato": "ca_chua"},
        exif_mode="auto",
    )
    cands = rf._parse_coco_dir(extract, spec)
    summary = rf._materialize_source(spec, cands)
    assert summary["schema_version"] == "m1_v1"
    assert summary["source_name"] == "rf_test_coco_raw"
    ann = json.loads((rf.ROOT / spec.name / "annotations.json").read_text(encoding="utf-8"))
    rec = ann["records"][0]
    assert rec["exif_orientation"] == orient
    assert rec["exif_applied"] is False
    if orient == 3:
        assert rec["exif_suspect"] is True
    _assert_patch_is_red(rf.ROOT / spec.name / rec["file"], rec["boxes"][0]["bbox"])


@pytest.mark.parametrize("orient", [1, 3, 6, 8])
def test_coco_display_space_exif(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, orient: int) -> None:
    monkeypatch.setattr(rf, "ROOT", tmp_path / "raw_rf")
    disp = _make_display_patch(120, 80)
    disp_box = [14.0, 10.0, 26.0, 18.0]
    extract = tmp_path / "extract"
    img_path = extract / "train" / f"sample_{orient}.jpg"
    _encode_with_exif(disp, orient, img_path)

    coco = {
        "categories": [{"id": 1, "name": "tomato"}],
        "images": [{"id": 10, "file_name": img_path.name, "width": 120, "height": 80}],
        "annotations": [{"id": 1, "image_id": 10, "category_id": 1, "bbox": disp_box}],
    }
    (extract / "train" / "_annotations.coco.json").write_text(json.dumps(coco), encoding="utf-8")

    spec = rf.SourceSpec(
        name="test_coco_disp",
        workspace="w",
        project="p",
        version=1,
        fmt="coco",
        license="CC BY 4.0",
        url="https://example.com",
        class_map={"tomato": "ca_chua"},
        # Orient 3 shares raw/display dims (120x80), so display-space exports use exif_mode="transpose"
        exif_mode="transpose" if orient == 3 else "auto",
    )
    cands = rf._parse_coco_dir(extract, spec)
    rf._materialize_source(spec, cands)
    ann = json.loads((rf.ROOT / spec.name / "annotations.json").read_text(encoding="utf-8"))
    rec = ann["records"][0]
    assert (rec["width"], rec["height"]) == (120, 80)
    assert rec["exif_applied"] is (orient != 1)
    _assert_patch_is_red(rf.ROOT / spec.name / rec["file"], rec["boxes"][0]["bbox"])


@pytest.mark.parametrize("orient", [1, 3, 6, 8])
def test_yolo_display_and_raw_space_exif(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, orient: int) -> None:
    monkeypatch.setattr(rf, "ROOT", tmp_path / "raw_rf")
    disp = _make_display_patch(120, 80)

    # 1) YOLO display-space (no README auto-orientation, boxes in display coords)
    ex_disp = tmp_path / "ex_disp"
    (ex_disp / "train" / "images").mkdir(parents=True)
    (ex_disp / "train" / "labels").mkdir(parents=True)
    (ex_disp / "data.yaml").write_text(yaml.safe_dump({"names": ["tomato"]}), encoding="utf-8")
    _encode_with_exif(disp, orient, ex_disp / "train" / "images" / "item.jpg")
    xc, yc, bw, bh = (14 + 13) / 120.0, (10 + 9) / 80.0, 26 / 120.0, 18 / 80.0
    (ex_disp / "train" / "labels" / "item.txt").write_text(f"0 {xc:.6f} {yc:.6f} {bw:.6f} {bh:.6f}\n", encoding="utf-8")

    spec_disp = rf.SourceSpec(
        name="test_yolo_disp",
        workspace="w",
        project="p",
        version=1,
        fmt="yolov8",
        license="CC BY 4.0",
        url="https://example.com",
        class_map={"tomato": "ca_chua"},
        exif_mode="auto",
    )
    rf._materialize_source(spec_disp, rf._parse_yolo_dir(ex_disp, spec_disp))
    ann_disp = json.loads((rf.ROOT / spec_disp.name / "annotations.json").read_text(encoding="utf-8"))
    rec_d = ann_disp["records"][0]
    assert (rec_d["width"], rec_d["height"]) == (120, 80)
    assert rec_d["exif_applied"] is (orient != 1)
    _assert_patch_is_red(rf.ROOT / spec_disp.name / rec_d["file"], rec_d["boxes"][0]["bbox"])

    # 2) YOLO raw-space (README has Auto-orientation of pixel data -> do not re-rotate)
    ex_raw = tmp_path / "ex_raw"
    (ex_raw / "train" / "images").mkdir(parents=True)
    (ex_raw / "train" / "labels").mkdir(parents=True)
    (ex_raw / "data.yaml").write_text(yaml.safe_dump({"names": ["tomato"]}), encoding="utf-8")
    (ex_raw / "README.roboflow.txt").write_text(
        "Image Pre-processing:\n* Auto-orientation of pixel data (with EXIF-orientation stripping)\n",
        encoding="utf-8",
    )
    raw_im, raw_box = _encode_with_exif(disp, orient, ex_raw / "train" / "images" / "item.jpg")
    rx, ry, rw, rh = raw_box
    rxc, ryc = (rx + rw / 2) / raw_im.width, (ry + rh / 2) / raw_im.height
    rnw, rnh = rw / raw_im.width, rh / raw_im.height
    (ex_raw / "train" / "labels" / "item.txt").write_text(f"0 {rxc:.6f} {ryc:.6f} {rnw:.6f} {rnh:.6f}\n", encoding="utf-8")

    spec_raw = rf.SourceSpec(
        name="test_yolo_raw",
        workspace="w",
        project="p",
        version=1,
        fmt="yolov8",
        license="CC BY 4.0",
        url="https://example.com",
        class_map={"tomato": "ca_chua"},
        exif_mode="auto",
    )
    cands_r = rf._parse_yolo_dir(ex_raw, spec_raw)
    assert cands_r[0]["auto_oriented"] is True
    rf._materialize_source(spec_raw, cands_r)
    ann_raw = json.loads((rf.ROOT / spec_raw.name / "annotations.json").read_text(encoding="utf-8"))
    rec_r = ann_raw["records"][0]
    assert rec_r["exif_applied"] is False
    _assert_patch_is_red(rf.ROOT / spec_raw.name / rec_r["file"], rec_r["boxes"][0]["bbox"])


def test_collapse_twins_prefers_color_and_black_corners(tmp_path: Path) -> None:
    gray = tmp_path / "a.rf.111.jpg"
    color = tmp_path / "a.rf.222.jpg"
    Image.new("RGB", (64, 64), (100, 100, 100)).save(gray)
    Image.new("RGB", (64, 64), (220, 40, 20)).save(color)

    cands = [
        {"stem": "a", "src_path": gray, "boxes": [{"cat": "x", "cls": "ca_chua", "bbox": [0.1, 0.1, 0.5, 0.5]}]},
        {"stem": "a", "src_path": color, "boxes": [{"cat": "x", "cls": "ca_chua", "bbox": [0.1, 0.1, 0.5, 0.5]}]},
    ]
    collapsed = rf._collapse_twins(cands)
    assert len(collapsed) == 1
    assert collapsed[0]["src_path"] == color

    rot_im = Image.new("RGB", (64, 64), (120, 120, 120)).rotate(45)
    assert rf._has_black_corners(rot_im) is True
    assert rf._has_black_corners(Image.new("RGB", (64, 64), (120, 120, 120))) is False


def test_sources_registered_and_missing_key_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    by_name = {s.name: s for s in rf.SOURCES}
    assert "smartpantry" in by_name
    assert "phcs" in by_name
    assert by_name["smartpantry"].class_map["pork"] == "thit_lon"
    assert by_name["smartpantry"].class_map["tofu"] == "dau_phu"
    assert by_name["phcs"].class_map["tofu"] == "dau_phu"
    assert by_name["phcs"].class_map["winter_melon"] == "bi_dao"

    valid_classes = {c["id"] for c in build_yolo_v2.all_class_rows()}
    for spec in rf.SOURCES:
        for cls_id in spec.class_map.values():
            assert cls_id in valid_classes, f"{spec.name} maps to unknown class {cls_id}"

    monkeypatch.delenv("ROBOFLOW_API_KEY", raising=False)
    monkeypatch.setattr(rf, "ROOT", tmp_path / "rf_empty")
    monkeypatch.setattr(rf, "STAGE", tmp_path / "stage")
    res = rf.ingest_all(only={"smartpantry", "phcs"}, skip_missing_key=True)
    assert res["smartpantry"]["status"] == "skipped_missing_api_key"
    assert res["phcs"]["status"] == "skipped_missing_api_key"
    with pytest.raises(RuntimeError, match="ROBOFLOW_API_KEY"):
        rf.ingest_all(only={"smartpantry"}, skip_missing_key=False)


def test_square_image_exif_6_coco_flags_suspect(tmp_path: Path) -> None:
    disp = _make_display_patch(100, 100)
    img_path = tmp_path / "sq6.jpg"
    _encode_with_exif(disp, 6, img_path)
    with Image.open(img_path) as im_raw:
        im_out, meta = rf._load_oriented_rgb(
            im_raw,
            norm_boxes=False,
            orig_w=100,
            orig_h=100,
            exif_mode="auto",
            auto_oriented=False,
        )
        assert im_out.size == (100, 100)
        assert meta == {"exif_orientation": 6, "exif_applied": False, "exif_suspect": True}

        _, meta_ao = rf._load_oriented_rgb(
            im_raw,
            norm_boxes=False,
            orig_w=100,
            orig_h=100,
            exif_mode="auto",
            auto_oriented=True,
        )
        assert meta_ao == {"exif_orientation": 6, "exif_applied": False, "exif_suspect": False}


def test_corrupt_exif_tag_99_normalized_no_transpose(tmp_path: Path) -> None:
    disp = _make_display_patch(120, 80)
    img_path = tmp_path / "bad99.jpg"
    exif = Image.Exif()
    exif[274] = 99
    disp.save(img_path, format="JPEG", quality=98, exif=exif)

    with Image.open(img_path) as im_raw:
        for mode in ("raw", "transpose", "auto"):
            im_out, meta = rf._load_oriented_rgb(
                im_raw,
                norm_boxes=(mode == "auto"),
                orig_w=None if mode == "auto" else 120,
                orig_h=None if mode == "auto" else 80,
                exif_mode=mode,
                auto_oriented=False,
            )
            assert im_out.size == (120, 80)
            assert meta == {"exif_orientation": 1, "exif_applied": False, "exif_suspect": True}


@pytest.mark.parametrize("orient", [6, 8])
def test_coco_exif_mode_raw_swapped_display_boxes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, orient: int
) -> None:
    monkeypatch.setattr(rf, "ROOT", tmp_path / "raw_rf")
    disp = _make_display_patch(120, 80)
    disp_box = [14.0, 10.0, 26.0, 18.0]
    extract = tmp_path / "extract"
    img_path = extract / "train" / f"raw_{orient}.jpg"
    _encode_with_exif(disp, orient, img_path)

    coco = {
        "categories": [{"id": 1, "name": "tomato"}],
        "images": [{"id": 10, "file_name": img_path.name, "width": 120, "height": 80}],
        "annotations": [{"id": 1, "image_id": 10, "category_id": 1, "bbox": disp_box}],
    }
    (extract / "train" / "_annotations.coco.json").write_text(json.dumps(coco), encoding="utf-8")

    spec = rf.SourceSpec(
        name="test_coco_raw_mode",
        workspace="w",
        project="p",
        version=1,
        fmt="coco",
        license="CC BY 4.0",
        url="https://example.com",
        class_map={"tomato": "ca_chua"},
        exif_mode="raw",
    )
    cands = rf._parse_coco_dir(extract, spec)
    rf._materialize_source(spec, cands)
    ann = json.loads((rf.ROOT / spec.name / "annotations.json").read_text(encoding="utf-8"))
    rec = ann["records"][0]
    assert (rec["width"], rec["height"]) == (80, 120)
    assert rec["exif_applied"] is False
    assert rec["exif_suspect"] is False
    # Zero aspect distortion: bbox width/height should swap cleanly (26, 18) -> (18, 26)
    assert pytest.approx(rec["boxes"][0]["bbox"][2:], abs=1e-4) == [18.0, 26.0]
    _assert_patch_is_red(rf.ROOT / spec.name / rec["file"], rec["boxes"][0]["bbox"])
