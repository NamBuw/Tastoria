from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
import yaml
from PIL import Image

from tastoria_ml.cv import build_yolo_v2, dfv16


def _make_fake_dfv16_zip(zip_path: Path) -> None:
    names = [
        "Apple Red", "Apple Yellow", "Avocado", "Banana", "Corn",
        "Cucumber", "Eggplant", "Kiwi", "Lemon", "Mango",
        "Orange", "Pear", "Pepper Green", "Pomegranate", "Potato", "Tomato",
    ]
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("01_YOLO_Detection/data.yaml", yaml.safe_dump({"nc": 16, "names": names}))

        def _add_sample(split: str, stem: str, w: int, h: int, lines: list[str]) -> None:
            buf = io.BytesIO()
            Image.new("RGB", (w, h), (40, 140, 60)).save(buf, format="JPEG", quality=90)
            zf.writestr(f"01_YOLO_Detection/{split}/images/{stem}.jpg", buf.getvalue())
            zf.writestr(f"01_YOLO_Detection/{split}/labels/{stem}.txt", "\n".join(lines) + "\n")

        # 1) train positive Tomato + co-occurring Avocado OOD, oversized 2048x1024 -> 1024x512
        _add_sample("train", "img_pos", 2048, 1024, [
            "15 0.5 0.5 0.2 0.4",   # Tomato -> ca_chua
            "2 0.1 0.1 0.1 0.1",    # Avocado -> ood_labels
        ])
        # 2) val negative (only Cucumber + Banana OOD -> is_neg=True)
        _add_sample("val", "img_neg", 800, 600, [
            "5 0.3 0.3 0.2 0.2",    # Cucumber
            "3 0.7 0.7 0.15 0.2",   # Banana
        ])
        # 3) test positive Potato + Lemon -> must map to heldout!
        _add_sample("test", "img_test", 1280, 960, [
            "14 0.4 0.5 0.2 0.25",  # Potato -> khoai_tay
            "8 0.8 0.2 0.1 0.1",    # Lemon -> chanh
        ])


def test_dfv16_ingest_zip_schema_and_splits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "dfv16"
    monkeypatch.setattr(dfv16, "ROOT", root)
    zip_path = tmp_path / "fake_dfv16.zip"
    _make_fake_dfv16_zip(zip_path)

    summary = dfv16.ingest_zip(zip_path, root=root)
    assert summary["schema_version"] == "m1_v1"
    assert summary["source_name"] == "dfv16"
    assert summary["license"] == "CC BY 4.0"
    assert summary["is_commercial_ok"] is True
    assert summary["images"] == 3
    assert summary["neg_images"] == 1
    assert summary["splits"] == {"train": 1, "val": 1, "heldout": 1}
    assert "test" not in summary["splits"]
    assert summary["boxes_per_class"] == {"ca_chua": 1, "chanh": 1, "khoai_tay": 1}

    ann = json.loads((root / "annotations.json").read_text(encoding="utf-8"))
    assert "__neg__" in ann["categories"]
    valid_classes = {c["id"] for c in build_yolo_v2.all_class_rows()}
    for c in ann["categories"]:
        if c != "__neg__":
            assert c in valid_classes

    recs = dfv16.records()
    assert len(recs) == 3
    by_stem = {r["stem"]: r for r in recs}

    r_pos = by_stem["img_pos"]
    assert r_pos["split"] == "train"
    assert r_pos["split_hint"] == "train"
    assert r_pos["is_neg"] is False
    assert r_pos["ood_labels"] == ["Avocado"]
    assert max(r_pos["width"], r_pos["height"]) <= 1024
    assert (r_pos["width"], r_pos["height"]) == (1024, 512)
    bx, by, bw, bh = r_pos["boxes"][0]["bbox"]
    assert pytest.approx(bw, abs=1e-3) == 0.2 * 1024
    assert pytest.approx(bh, abs=1e-3) == 0.4 * 512

    r_neg = by_stem["img_neg"]
    assert r_neg["split"] == "val"
    assert r_neg["is_neg"] is True
    assert r_neg["boxes"] == []
    assert r_neg["ood_labels"] == ["Banana", "Cucumber"]

    r_test = by_stem["img_test"]
    assert r_test["split"] == "heldout"
    assert r_test["split_hint"] == "heldout"
    assert {b["cls"] for b in r_test["boxes"]} == {"khoai_tay", "chanh"}


def test_dfv16_stage_cleanup_on_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "dfv16"
    stage = tmp_path / "stage_dfv16"
    monkeypatch.setattr(dfv16, "ROOT", root)
    monkeypatch.setattr(dfv16, "STAGE", stage)
    monkeypatch.setattr(dfv16, "_check_disk_guard", lambda *a, **kw: None)

    def _boom(*a, **kw):
        (stage / "partial.part").write_bytes(b"123")
        raise RuntimeError("network error")

    monkeypatch.setattr(dfv16, "_download_zip", _boom)
    with pytest.raises(RuntimeError, match="network error"):
        dfv16.ingest(force=True)
    assert not stage.exists()


def test_dfv16_dropped_tiny_positive_box_never_flips_is_neg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = ["Avocado", "Tomato"]
    zip_path = tmp_path / "tiny_dfv16.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("01_YOLO_Detection/data.yaml", yaml.safe_dump({"nc": 2, "names": names}))
        buf = io.BytesIO()
        Image.new("RGB", (200, 200), (40, 140, 60)).save(buf, format="JPEG", quality=90)
        zf.writestr("01_YOLO_Detection/train/images/tiny.jpg", buf.getvalue())
        # Tomato (cls 1) has w=0.005 (>0.002 raw threshold) -> 1.0 px (<2.0 px scaled threshold) + Avocado OOD
        zf.writestr("01_YOLO_Detection/train/labels/tiny.txt", "1 0.5 0.5 0.005 0.005\n0 0.2 0.2 0.2 0.2\n")

    root = tmp_path / "dfv16"
    monkeypatch.setattr(dfv16, "ROOT", root)
    summary = dfv16.ingest_zip(zip_path, root=root)
    assert summary["images"] == 0
    assert summary["neg_images"] == 0
    assert dfv16.records() == []
