"""Unit tests for train-only LVIS repeat-factor sampling (RFS) and dataset isolation."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import yaml

from tastoria_ml.cv.train_detector import (
    YOLO_V4_DIR,
    build_oversampled_dataset,
    resolve_yolo_dir,
)


def _make_synthetic_yolo(root: Path) -> Path:
    names = {0: "common_a", 1: "medium_b", 2: "rare_c", 3: "ultra_d"}
    for split in ("train", "val", "test", "heldout"):
        (root / "images" / split).mkdir(parents=True, exist_ok=True)
        (root / "labels" / split).mkdir(parents=True, exist_ok=True)

    # 100 train images:
    # - 0..79 (80 imgs): class 0 (f=0.80 -> r_c = 1.0)
    # - 80..89 (10 imgs): class 1 (f=0.10 -> sqrt(0.02/0.10)=0.447 -> r_c = 1.0)
    # - 90..93 (4 imgs): class 2 (f=0.04 -> sqrt(0.02/0.04)=0.707 -> r_c = 1.0)
    # Wait: let's use t=0.10 or 100 imgs where rare has 1 img (f=0.01) & t=0.05 -> sqrt(5)=2.236 -> 2
    # And multi-label image with common_a + ultra_d -> takes max r_c.
    for i in range(80):
        (root / "images" / "train" / f"img_{i:03d}.jpg").write_bytes(b"jpg")
        (root / "labels" / "train" / f"img_{i:03d}.txt").write_text("0 0.5 0.5 0.2 0.2\n")
    for i in range(80, 90):
        (root / "images" / "train" / f"img_{i:03d}.jpg").write_bytes(b"jpg")
        (root / "labels" / "train" / f"img_{i:03d}.txt").write_text("1 0.5 0.5 0.2 0.2\n")
    for i in range(90, 94):
        (root / "images" / "train" / f"img_{i:03d}.jpg").write_bytes(b"jpg")
        (root / "labels" / "train" / f"img_{i:03d}.txt").write_text("2 0.5 0.5 0.2 0.2\n")
    # 1 ultra-rare image containing both common (0) and ultra_d (3) -> f_3 = 0.01
    (root / "images" / "train" / "img_094.jpg").write_bytes(b"jpg")
    (root / "labels" / "train" / "img_094.txt").write_text("0 0.5 0.5 0.2 0.2\n3 0.2 0.2 0.1 0.1\n")
    # 5 background images: 3 empty .txt, 2 missing .txt
    for i in range(95, 98):
        (root / "images" / "train" / f"img_{i:03d}.jpg").write_bytes(b"jpg")
        (root / "labels" / "train" / f"img_{i:03d}.txt").write_text("")
    for i in range(98, 100):
        (root / "images" / "train" / f"img_{i:03d}.jpg").write_bytes(b"jpg")

    for split in ("val", "test", "heldout"):
        for j in range(3):
            (root / "images" / split / f"{split}_{j}.jpg").write_bytes(b"jpg")
            (root / "labels" / split / f"{split}_{j}.txt").write_text("3 0.5 0.5 0.1 0.1\n")

    ds = {"path": str(root), "train": "images/train", "val": "images/val", "test": "images/test", "names": names}
    (root / "dataset.yaml").write_text(yaml.safe_dump(ds, sort_keys=False))
    dsh = {"path": str(root), "train": "images/train", "val": "images/val", "test": "images/heldout", "names": names}
    (root / "dataset_heldout.yaml").write_text(yaml.safe_dump(dsh, sort_keys=False))
    return root


def test_resolve_yolo_v4():
    assert resolve_yolo_dir("yolo_v4") == YOLO_V4_DIR


def test_rfs_formula_cap_and_background_stay_1x(tmp_path: Path):
    ydir = _make_synthetic_yolo(tmp_path / "src_yolo")
    stage = tmp_path / "stage_os"

    # t=0.25, cap=4:
    # - class 0: 81/100=0.81 -> sqrt(0.25/0.81)=0.555 -> r_c=1.0 -> r_i=1
    # - class 1: 10/100=0.10 -> sqrt(0.25/0.10)=1.581 -> round=2
    # - class 2: 4/100=0.04  -> sqrt(0.25/0.04)=2.500 -> round(2.5)=2 (Python banker's rounding)
    #   Wait: let's also test explicit math.sqrt formula via t=0.36, cap=4:
    # - class 0: 81/100=0.81 -> sqrt(0.36/0.81)=0.667 -> r_c=1.0 -> r_i=1
    # - class 1: 10/100=0.10 -> sqrt(0.36/0.10)=1.897 -> round=2
    # - class 2: 4/100=0.04  -> sqrt(0.36/0.04)=3.0   -> round=3
    # - class 3: 1/100=0.01  -> sqrt(0.36/0.01)=6.0   -> capped at 4!
    # - background (95..99): 1 each
    ds_yaml, stats = build_oversampled_dataset(ydir, stage, t=0.36, cap=4)
    assert ds_yaml == stage / "dataset.yaml"

    lines = (stage / "train.txt").read_text().strip().splitlines()
    counts: dict[str, int] = {}
    for ln in lines:
        counts[Path(ln).name] = counts.get(Path(ln).name, 0) + 1

    assert len(counts) == 100
    for i in range(80):
        assert counts[f"img_{i:03d}.jpg"] == 1
    for i in range(80, 90):
        assert counts[f"img_{i:03d}.jpg"] == round(math.sqrt(0.36 / 0.10))
    for i in range(90, 94):
        assert counts[f"img_{i:03d}.jpg"] == 3
    # Multi-label image img_094 has common(0) + ultra_d(3), takes max -> capped at 4
    assert counts["img_094.jpg"] == 4
    # Empty background images (empty .txt and missing .txt) stay 1x
    for i in range(95, 100):
        assert counts[f"img_{i:03d}.jpg"] == 1

    expected_total = 80 * 1 + 10 * 2 + 4 * 3 + 4 + 5 * 1
    assert len(lines) == expected_total
    assert stats["n_train_unique"] == 100
    assert stats["n_train_oversampled"] == expected_total
    assert stats["n_background_images"] == 5
    assert stats["train_txt_sha256"] == hashlib.sha256((stage / "train.txt").read_bytes()).hexdigest()
    assert json.loads((stage / "oversample_stats.json").read_text())["n_train_oversampled"] == expected_total


def test_rfs_never_oversamples_eval_splits_and_isolates_source(tmp_path: Path):
    ydir = _make_synthetic_yolo(tmp_path / "src_yolo")
    before_files = sorted(str(p.relative_to(ydir)) for p in ydir.rglob("*"))
    stage = tmp_path / "stage_os"

    ds_yaml, _ = build_oversampled_dataset(ydir, stage, t=0.02, cap=20)
    ds = yaml.safe_load(ds_yaml.read_text())
    dsh = yaml.safe_load((stage / "dataset_heldout.yaml").read_text())

    assert ds["train"] == "train.txt"
    assert ds["val"] == "val.txt"
    assert ds["test"] == "test.txt"
    assert dsh["test"] == "heldout.txt"
    assert list(ds["names"].values()) == ["common_a", "medium_b", "rare_c", "ultra_d"]

    for split in ("val", "test", "heldout"):
        lines = (stage / f"{split}.txt").read_text().strip().splitlines()
        assert len(lines) == 3
        assert len(set(lines)) == 3
        assert all(str(stage / "images" / split) in ln for ln in lines)

    # Directory symlinks keep eval splits unrepeated and isolate Ultralytics .cache writes
    for split in ("train", "val", "test", "heldout"):
        img_link = stage / "images" / split
        lbl_link = stage / "labels" / split
        assert img_link.is_symlink() and img_link.resolve() == (ydir / "images" / split).resolve()
        assert lbl_link.is_symlink() and lbl_link.resolve() == (ydir / "labels" / split).resolve()

        # Simulate Ultralytics cache path calculation: Path(label_file).parent.with_suffix(".cache")
        sample_lbl = lbl_link / f"{split}_0.txt"
        cache_path = sample_lbl.parent.with_suffix(".cache")
        assert cache_path.parent == stage / "labels"
        assert not cache_path.is_relative_to(ydir)

    after_files = sorted(str(p.relative_to(ydir)) for p in ydir.rglob("*"))
    assert before_files == after_files
    assert list(ydir.rglob("*.cache")) == []
