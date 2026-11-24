from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest
from PIL import Image

from tastoria_ml.cv import build_yolo_v2, hf_kaggle_ingest as hk, v3det


def test_v3det_flickr_fallback_and_429_backoff(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dst = tmp_path / "train_0000001.jpg"
    buf = io.BytesIO()
    Image.new("RGB", (1200, 800), (30, 170, 50)).save(buf, format="JPEG", quality=90)
    jpeg_bytes = buf.getvalue()

    calls: list[str] = []

    class _Resp:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def read(self) -> bytes:
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _fake_urlopen(req, timeout=20):
        url = req.full_url
        calls.append(url)
        if url.endswith("_o.jpg"):
            raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
        if url.endswith("_b.jpg") and calls.count(url) == 1:
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
        return _Resp(jpeg_bytes)

    monkeypatch.setattr(v3det.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(v3det.time, "sleep", lambda s: None)

    rec = {
        "id": "train/1",
        "split": "train",
        "orig_w": 1200,
        "orig_h": 800,
        "url": "https://live.staticflickr.com/1/10_abc_o.jpg",
        "boxes": [{"cat": "bean sprouts", "cls": "gia_do", "bbox": [120.0, 80.0, 240.0, 160.0]}],
    }
    out_rec, status = v3det._download_one((rec, dst))
    assert status == "ok"
    assert dst.exists()
    assert out_rec["url"].endswith("_b.jpg")
    assert out_rec["width"] == 1024
    assert out_rec["is_commercial_ok"] is False
    assert out_rec["is_neg"] is False
    assert pytest.approx(out_rec["boxes"][0]["bbox"][2], rel=1e-2) == 240.0 * (1024 / 1200)

    # Re-running on existing file ("skip") must ALSO scale boxes properly
    out_skip, st_skip = v3det._download_one((rec, dst))
    assert st_skip == "skip"
    assert pytest.approx(out_skip["boxes"][0]["bbox"][2], rel=1e-2) == 240.0 * (1024 / 1200)


def test_v3det_refrigerator_ood_and_target_map() -> None:
    valid = {c["id"] for c in build_yolo_v2.all_class_rows()} | {"__neg__"}
    for cat, cls_id in v3det.TARGET_CATS.items():
        assert cls_id in valid, f"v3det TARGET_CATS[{cat!r}] -> {cls_id!r} invalid"

    boxes, ood = v3det._scale_positive_boxes(
        [{"cat": "refrigerator", "cls": "__neg__", "bbox": [10.0, 10.0, 200.0, 300.0]}],
        sx=0.5,
        sy=0.5,
    )
    assert boxes == []
    assert ood == ["refrigerator"]
    rec = v3det._format_record(
        {"id": "train/99", "split": "train"},
        "train_0000099.jpg",
        512,
        512,
        "https://ex/99.jpg",
        boxes,
        ood,
    )
    assert rec["is_neg"] is True
    assert rec["ood_labels"] == ["refrigerator"]
    assert rec["source_name"] == "v3det"


def test_hf_kaggle_voc_coco_disk_guard_and_contact_sheet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1) Spec validation rejects unknown class
    bad_spec = hk.HFKaggleSpec(
        source_name="bad",
        platform="hf",
        repo_id="x/y",
        license="MIT",
        is_commercial_ok=True,
        url="https://example.com",
        class_map={"foo": "nonexistent_class"},
    )
    with pytest.raises(ValueError, match="unknown class"):
        hk.validate_spec(bad_spec)

    # 2) Credential status boolean check only
    monkeypatch.delenv("ROBOFLOW_API_KEY", raising=False)
    creds = hk.credential_status()
    assert set(creds) == {"roboflow_api_key", "kaggle_json"}
    assert creds["roboflow_api_key"] is False

    # 3) Parse VOC dir with exclude_co_labels and OOD
    voc_root = tmp_path / "voc"
    (voc_root / "images").mkdir(parents=True)
    Image.new("RGB", (1600, 800), (200, 50, 50)).save(voc_root / "images" / "a.jpg")
    Image.new("RGB", (600, 400), (50, 200, 50)).save(voc_root / "images" / "b.jpg")
    Image.new("RGB", (600, 400), (50, 50, 200)).save(voc_root / "images" / "c.jpg")

    (voc_root / "a.xml").write_text(
        "<annotation><filename>a.jpg</filename><size><width>1600</width><height>800</height></size>"
        "<object><name>tofu</name><bndbox><xmin>160</xmin><ymin>80</ymin><xmax>480</xmax><ymax>400</ymax></bndbox></object>"
        "</annotation>",
        encoding="utf-8",
    )
    (voc_root / "b.xml").write_text(
        "<annotation><filename>b.jpg</filename><size><width>600</width><height>400</height></size>"
        "<object><name>apple</name><bndbox><xmin>50</xmin><ymin>50</ymin><xmax>200</xmax><ymax>200</ymax></bndbox></object>"
        "</annotation>",
        encoding="utf-8",
    )
    (voc_root / "c.xml").write_text(
        "<annotation><filename>c.jpg</filename><size><width>600</width><height>400</height></size>"
        "<object><name>tofu</name><bndbox><xmin>50</xmin><ymin>50</ymin><xmax>200</xmax><ymax>200</ymax></bndbox></object>"
        "<object><name>pizza</name><bndbox><xmin>10</xmin><ymin>10</ymin><xmax>300</xmax><ymax>300</ymax></bndbox></object>"
        "</annotation>",
        encoding="utf-8",
    )

    spec = hk.HFKaggleSpec(
        source_name="synth_voc",
        platform="hf",
        repo_id="synth/voc",
        license="CC BY 4.0",
        is_commercial_ok=True,
        url="https://example.com",
        class_map={"tofu": "dau_phu"},
        ood_neg_labels=("apple",),
        exclude_co_labels=("pizza",),
    )
    monkeypatch.setattr(hk, "ROOT", tmp_path / "hf_out")
    summary = hk.parse_voc_dir(voc_root, spec)
    assert summary["schema_version"] == "m1_v1"
    assert summary["images"] == 2  # c excluded due to pizza!
    assert summary["neg_images"] == 1
    assert summary["boxes_per_class"] == {"dau_phu": 1}

    recs = hk.records(commercial_only=True)
    assert len(recs) == 2
    sheet = hk.render_contact_sheet(recs, tmp_path / "sheet.jpg", title="Test Sheet", cols=2, rows=1)
    assert sheet.exists() and sheet.stat().st_size > 1000


def test_v3det_scale_positive_boxes_clamps_oob_and_dedups() -> None:
    raw = [
        {"cat": "garlic", "cls": "toi", "bbox": [-10.0, -8.0, 60.0, 48.0]},
        {"cat": "potato", "cls": "khoai_tay", "bbox": [-10.0, -8.0, 60.0, 48.0]},  # distinct cls -> keep
        {"cat": "garlic", "cls": "toi", "bbox": [-10.0, -8.0, 60.0, 48.0]},  # exact dup -> drop
        {"cat": "prawn", "cls": "tom", "bbox": [90.0, 70.0, 30.0, 30.0]},  # right/bottom OOB -> clamp to 100x80
        {"cat": "chili", "cls": "ot", "bbox": [99.0, 10.0, 20.0, 20.0]},  # width after clamp = 1.0 < 2.0 -> drop
        {"cat": "refrigerator", "cls": "__neg__", "bbox": [0.0, 0.0, 100.0, 80.0]},
    ]
    scaled, ood = v3det._scale_positive_boxes(raw, sx=1.0, sy=1.0, w_new=100, h_new=80)
    assert ood == ["refrigerator"]
    assert len(scaled) == 3
    assert scaled[0]["cls"] == "toi" and scaled[0]["bbox"] == [0.0, 0.0, 50.0, 40.0]
    assert scaled[1]["cls"] == "khoai_tay" and scaled[1]["bbox"] == [0.0, 0.0, 50.0, 40.0]
    assert scaled[2]["cls"] == "tom" and scaled[2]["bbox"] == [90.0, 70.0, 10.0, 10.0]
    for b in scaled:
        x, y, bw, bh = b["bbox"]
        assert x >= 0.0 and y >= 0.0 and x + bw <= 100.0 and y + bh <= 80.0


def test_hf_kaggle_voc_exif_orientation_3_and_square_6(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import numpy as np

    # 1) Non-square 200x100 VOC image with EXIF=3 (180-deg rotation)
    voc_root = tmp_path / "voc_exif"
    (voc_root / "images").mkdir(parents=True)

    disp_rect = np.zeros((100, 200, 3), dtype=np.uint8)
    disp_rect[..., 2] = 180
    disp_rect[10:30, 10:40] = (235, 25, 25)  # display top-left red patch
    raw_rect = Image.fromarray(disp_rect).transpose(Image.Transpose.ROTATE_180)
    ex3 = Image.Exif()
    ex3[274] = 3
    raw_rect.save(voc_root / "images" / "rect3.jpg", format="JPEG", quality=98, exif=ex3)
    (voc_root / "rect3.xml").write_text(
        "<annotation><filename>rect3.jpg</filename><size><width>200</width><height>100</height></size>"
        "<object><name>tofu</name><bndbox><xmin>10</xmin><ymin>10</ymin><xmax>40</xmax><ymax>30</ymax></bndbox></object>"
        "</annotation>",
        encoding="utf-8",
    )

    # 2) Square 100x100 VOC image with EXIF=6 (90-deg CW display; raw = ROTATE_90(display))
    disp_sq = np.zeros((100, 100, 3), dtype=np.uint8)
    disp_sq[..., 2] = 180
    disp_sq[10:34, 10:34] = (235, 25, 25)  # display top-left red patch
    raw_sq = Image.fromarray(disp_sq).transpose(Image.Transpose.ROTATE_90)
    ex6 = Image.Exif()
    ex6[274] = 6
    raw_sq.save(voc_root / "images" / "sq6.jpg", format="JPEG", quality=98, exif=ex6)
    (voc_root / "sq6.xml").write_text(
        "<annotation><filename>sq6.jpg</filename><size><width>100</width><height>100</height></size>"
        "<object><name>tofu</name><bndbox><xmin>10</xmin><ymin>10</ymin><xmax>34</xmax><ymax>34</ymax></bndbox></object>"
        "</annotation>",
        encoding="utf-8",
    )

    spec = hk.HFKaggleSpec(
        source_name="exif_voc",
        platform="hf",
        repo_id="synth/exif",
        license="CC BY 4.0",
        is_commercial_ok=True,
        url="https://example.com",
        class_map={"tofu": "dau_phu"},
    )
    monkeypatch.setattr(hk, "ROOT", tmp_path / "hf_out_exif")
    summary = hk.parse_voc_dir(voc_root, spec)
    assert summary["images"] == 2

    recs = {r["stem"]: r for r in hk.records()}
    for stem in ("rect3", "sq6"):
        r = recs[stem]
        bx, by, bw, bh = r["boxes"][0]["bbox"]
        with Image.open(r["path"]) as im:
            arr = np.asarray(im.convert("RGB"))
        patch = arr[int(by + 3) : int(by + bh - 3), int(bx + 3) : int(bx + bw - 3)].mean(axis=(0, 1))
        assert patch[0] > 180 and patch[1] < 70 and patch[2] < 70, f"{stem} patch misaligned: {patch}"
        br = arr[-20:-5, -20:-5].mean(axis=(0, 1))
        assert br[0] < 70 and br[2] > 140, f"{stem} bottom-right should stay blue, got {br}"
