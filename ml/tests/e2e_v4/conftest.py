"""Session fixtures, CLI/env parameterization, and synthetic 37-class fallback builders for ml/tests/e2e_v4."""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
import pytest
import yaml
from PIL import Image

from tastoria_ml.cv.build_yolo_v2 import all_class_rows
from tastoria_ml.cv.classes import REPO
from tastoria_ml.cv.phash import hamming, phash

REPO_ROOT = REPO


def pytest_configure(config: pytest.Config) -> None:
    for marker in (
        "tier1: Tier 1 contract and feature-coverage E2E tests",
        "tier2: Tier 2 boundary, edge-case, and negative/rejection E2E tests",
        "tier3: Tier 3 pairwise combinatorial and cross-feature E2E tests",
        "tier4: Tier 4 end-to-end workflow and CPU serving latency SLA tests",
    ):
        config.addinivalue_line("markers", marker)


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("tastoria-e2e-v4")
    group.addoption(
        "--e2e-strict",
        action="store_true",
        default=_env_bool("TASTORIA_E2E_STRICT_V4", _env_bool("TASTORIA_E2E_STRICT", False)),
        help="Strict M4 mode: forbid synthetic fallbacks and enforce C=37, yolo_v4, detector_v3.",
    )
    group.addoption(
        "--e2e-dataset-dir",
        action="store",
        default=os.environ.get("TASTORIA_E2E_DATASET_DIR"),
        help="Path to YOLO v4 dataset root (containing dataset.yaml or data.yaml).",
    )
    group.addoption(
        "--e2e-model-dir",
        action="store",
        default=os.environ.get("TASTORIA_E2E_MODEL_DIR"),
        help="Path to detector model directory (containing model.onnx and serving.json).",
    )
    group.addoption(
        "--e2e-expected-nc",
        action="store",
        type=int,
        default=int(os.environ["TASTORIA_E2E_EXPECTED_NC"]) if os.environ.get("TASTORIA_E2E_EXPECTED_NC") else None,
        help="Expected detector class count C in ONNX output [1, 4+C, 8400].",
    )
    group.addoption(
        "--e2e-serving-file",
        action="store",
        default=os.environ.get("TASTORIA_E2E_SERVING_FILE", "serving.json"),
        help="Primary serving manifest filename inside model_dir.",
    )
    group.addoption(
        "--e2e-min-disk-gb",
        action="store",
        type=float,
        default=float(os.environ.get("TASTORIA_E2E_MIN_DISK_GB", "18.0")),
        help="Minimum required free disk space in GB on repo root filesystem.",
    )
    group.addoption(
        "--e2e-phash-max-pairs",
        action="store",
        type=int,
        default=int(os.environ["TASTORIA_E2E_PHASH_MAX_PAIRS"])
        if os.environ.get("TASTORIA_E2E_PHASH_MAX_PAIRS")
        else None,
        help="Max cross-split pHash query count (0 = exhaustive).",
    )
    group.addoption(
        "--e2e-latency-runs",
        action="store",
        type=int,
        default=int(os.environ["TASTORIA_E2E_LATENCY_RUNS"]) if os.environ.get("TASTORIA_E2E_LATENCY_RUNS") else None,
        help="Number of timed CPU ONNX inference iterations in Tier 4.",
    )
    group.addoption(
        "--e2e-latency-sla-ms",
        action="store",
        type=float,
        default=float(os.environ.get("TASTORIA_E2E_LATENCY_SLA_MS", "3000.0")),
        help="Maximum allowed CPU p95 inference latency in milliseconds (default 3000.0).",
    )


@dataclass(frozen=True)
class E2EConfig:
    strict: bool
    is_synthetic_dataset: bool
    is_synthetic_model: bool
    dataset_dir: Path
    manifest_csv: Path
    stats_json: Path
    cleaning_json: Path
    model_dir: Path
    onnx_path: Path
    serving_path: Path
    serving_f05_path: Path | None
    expected_nc: int
    min_disk_gb: float
    phash_max_pairs: int
    latency_runs: int
    latency_sla_ms: float


def _resolve_companion(dataset_dir: Path, filename: str) -> Path:
    for cand in (dataset_dir / filename, dataset_dir.parent / filename):
        if cand.is_file():
            return cand
    return dataset_dir / filename


def _pattern_image(seed: int, size: tuple[int, int] = (96, 96)) -> Image.Image:
    """Create a deterministic high-frequency RGB image with a distinct 64-bit DCT pHash per seed."""
    rng = np.random.default_rng(seed)
    w, h = size
    # Coarse random grid upsampled by block repetition gives strong, distinct low-frequency DCT bits
    grid = rng.integers(0, 256, size=(8, 8, 3), dtype=np.uint8)
    arr = np.repeat(np.repeat(grid, max(1, h // 8), axis=0), max(1, w // 8), axis=1)[:h, :w]
    if arr.shape[0] < h or arr.shape[1] < w:
        pad = np.zeros((h, w, 3), dtype=np.uint8)
        pad[: arr.shape[0], : arr.shape[1]] = arr
        arr = pad
    return Image.fromarray(arr, mode="RGB")


def _build_synthetic_yolo_v4(root: Path) -> tuple[Path, Path, Path, Path]:
    """Build a complete, valid 37-class synthetic yolo_v4 dataset with distinct pHashes and metadata."""
    rows = all_class_rows()
    assert len(rows) == 37
    class_ids = [str(r["id"]) for r in rows]

    for split in ("train", "val", "test", "heldout"):
        (root / "images" / split).mkdir(parents=True, exist_ok=True)
        (root / "labels" / split).mkdir(parents=True, exist_ok=True)
    (root / "heldout").mkdir(parents=True, exist_ok=True)

    dataset_yaml = {
        "path": str(root),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": dict(enumerate(class_ids)),
    }
    heldout_yaml = {
        "path": str(root),
        "train": "images/train",
        "val": "images/heldout",
        "names": dict(enumerate(class_ids)),
    }
    (root / "dataset.yaml").write_text(yaml.safe_dump(dataset_yaml, sort_keys=False), encoding="utf-8")
    (root / "dataset_heldout.yaml").write_text(yaml.safe_dump(heldout_yaml, sort_keys=False), encoding="utf-8")

    # Deterministic synthetic records:
    # - train: 37 positive images (covering all 37 classes, including non_commercial rpc_checkout & lvis_v1)
    #          + 2 hard negatives (lvis_v1_neg, mendeley_bd)
    # - val: 37 positive images (covering all 37 classes)
    # - test: 6 positive images (mendeley_bd, openimages_v7)
    # - heldout: 4 positive images (omorros_kitchen x2, lvis_v1 x1, rpc_checkout x1)
    manifest_rows: list[dict[str, Any]] = []
    images_per_split: dict[str, int] = {"train": 0, "val": 0, "test": 0, "heldout": 0}
    boxes_per_split_class: dict[str, dict[str, int]] = {
        s: {} for s in ("train", "val", "test", "heldout")
    }
    hard_neg_by_source_split: dict[str, int] = {}
    images_per_license_flag: dict[str, int] = {"ok": 0, "non_commercial": 0}
    eval_hashes: list[int] = []
    seed_counter = 1000

    def _disk_phash(img_path: Path) -> int:
        with Image.open(img_path) as saved:
            gray = saved.convert("L")
            gray.thumbnail((256, 256))
            return int(phash(np.asarray(gray)))

    def _add_record(
        split: str,
        source: str,
        orig_id: str,
        lic: str,
        lic_flag: str,
        cls_indices: list[int],
        *,
        is_hard_neg: bool = False,
        group_of_classes: dict[str, int] | None = None,
        avoid_hashes: list[int] | None = None,
    ) -> int:
        nonlocal seed_counter
        stem = f"{source}__{split}__{orig_id}"
        rel_img = f"yolo_v4/images/{split}/{stem}.jpg"
        img_path = root / "images" / split / f"{stem}.jpg"
        lbl_path = root / "labels" / split / f"{stem}.txt"

        while True:
            seed_counter += 1
            im = _pattern_image(seed_counter)
            im.save(img_path, "JPEG", quality=92)
            h = _disk_phash(img_path)
            if not avoid_hashes or int(hamming(np.asarray(avoid_hashes, dtype=np.uint64), h).min()) > 6:
                break

        bpc: dict[str, int] = {}
        if is_hard_neg or not cls_indices:
            lbl_path.write_text("", encoding="utf-8")
            n_boxes = 0
            key = f"{source}/{split}"
            hard_neg_by_source_split[key] = hard_neg_by_source_split.get(key, 0) + 1
        else:
            lines = []
            for j, ci in enumerate(cls_indices):
                xc = round(0.25 + 0.15 * (j % 4), 6)
                yc = round(0.30 + 0.15 * (j // 4), 6)
                lines.append(f"{ci} {xc:.6f} {yc:.6f} 0.200000 0.200000")
                cname = class_ids[ci]
                bpc[cname] = bpc.get(cname, 0) + 1
                boxes_per_split_class[split][cname] = boxes_per_split_class[split].get(cname, 0) + 1
            lbl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            n_boxes = len(cls_indices)

        gpc = dict(group_of_classes or {})
        n_group_of = sum(int(v) for v in gpc.values())
        images_per_split[split] += 1
        images_per_license_flag[lic_flag] += 1
        manifest_rows.append(
            {
                "split": split,
                "source": source,
                "original_id": orig_id,
                "file": rel_img,
                "license": lic,
                "license_flag": lic_flag,
                "author": "synthetic_e2e",
                "url": "https://example.invalid/synthetic",
                "group": f"{source}_{orig_id}",
                "phash": f"{h:016x}",
                "n_boxes": n_boxes,
                "n_group_of": n_group_of,
                "countable_group_of_boxes": 0,
                "group_of_per_class": json.dumps(gpc, sort_keys=True),
                "is_hard_neg": 1 if is_hard_neg else 0,
                "boxes_per_class": json.dumps(bpc, sort_keys=True),
            }
        )
        return h

    # 1. test & heldout first (register hashes to avoid cross-split leakage)
    for i in range(4):
        eval_hashes.append(
            _add_record("test", "mendeley_bd", f"t_{i}", "CC BY 4.0", "ok", [i, (i + 7) % 37], avoid_hashes=eval_hashes)
        )
    for i in range(2):
        eval_hashes.append(
            _add_record(
                "test", "openimages_v7", f"oi_{i}", "CC BY 2.0", "ok", [i + 10], avoid_hashes=eval_hashes
            )
        )
    heldout_omorros_files: list[str] = []
    for i in range(2):
        eval_hashes.append(
            _add_record(
                "heldout",
                "omorros_kitchen",
                f"ok_{i}",
                "CC BY 4.0",
                "ok",
                [5 + i],
                avoid_hashes=eval_hashes,
            )
        )
        heldout_omorros_files.append(f"images/heldout/omorros_kitchen__heldout__ok_{i}.jpg")
    (root / "heldout" / "omorros_kitchen.txt").write_text("\n".join(heldout_omorros_files) + "\n", encoding="utf-8")

    eval_hashes.append(
        _add_record(
            "heldout", "lvis_v1", "lv_0", "CC BY-NC 4.0", "non_commercial", [22, 23], avoid_hashes=eval_hashes
        )
    )
    eval_hashes.append(
        _add_record(
            "heldout", "rpc_checkout", "rpc_0", "CC BY-NC-SA 4.0", "non_commercial", [24, 25], avoid_hashes=eval_hashes
        )
    )

    # 2. val covering all 37 classes
    for ci in range(37):
        if ci < 12:
            src, lic, flag = "mendeley_bd", "CC BY 4.0", "ok"
        elif ci < 24:
            src, lic, flag = "openimages_v7", "CC BY 2.0", "ok"
        elif ci < 30:
            src, lic, flag = "dfv16", "CC BY 4.0", "ok"
        elif ci < 34:
            src, lic, flag = "lvis_v1", "CC BY-NC 4.0", "non_commercial"
        else:
            src, lic, flag = "rpc_checkout", "CC BY-NC-SA 4.0", "non_commercial"
        _add_record("val", src, f"v_{ci}", lic, flag, [ci], avoid_hashes=eval_hashes)

    # 3. train covering all 37 classes + 2 hard negatives
    for ci in range(37):
        if ci < 12:
            src, lic, flag = "mendeley_bd", "CC BY 4.0", "ok"
        elif ci < 24:
            src, lic, flag = "openimages_v7", "CC BY 2.0", "ok"
        elif ci < 30:
            src, lic, flag = "dfv16", "CC BY 4.0", "ok"
        elif ci < 34:
            src, lic, flag = "lvis_v1", "CC BY-NC 4.0", "non_commercial"
        else:
            src, lic, flag = "rpc_checkout", "CC BY-NC-SA 4.0", "non_commercial"
        _add_record("train", src, f"tr_{ci}", lic, flag, [ci], avoid_hashes=eval_hashes)

    _add_record("train", "lvis_v1_neg", "neg_0", "CC BY 4.0", "ok", [], is_hard_neg=True, avoid_hashes=eval_hashes)
    _add_record("train", "mendeley_bd", "neg_1", "CC BY 4.0", "ok", [], is_hard_neg=True, avoid_hashes=eval_hashes)
    # Mixed valid image: countable item + uncountable group_of item (must NOT false-fail Reviewer Finding 1)
    idx_ca_chua = class_ids.index("ca_chua")
    idx_rau_muong = class_ids.index("rau_muong")
    _add_record(
        "train",
        "openimages_v7",
        "mixed_group_0",
        "CC BY 2.0",
        "ok",
        [idx_ca_chua, idx_rau_muong],
        group_of_classes={"rau_muong": 1},
        avoid_hashes=eval_hashes,
    )
    # Clean audited train records from v3det, rf_viet_hoang, rf_robo1
    _add_record(
        "train",
        "v3det",
        "v3_clean_0",
        "CC BY 4.0",
        "ok",
        [class_ids.index("gia_do")],
        avoid_hashes=eval_hashes,
    )
    _add_record(
        "train",
        "rf_viet_hoang",
        "vh_clean_0",
        "CC BY 4.0",
        "ok",
        [class_ids.index("thit_lon")],
        avoid_hashes=eval_hashes,
    )
    _add_record(
        "train",
        "rf_robo1",
        "rb_clean_0",
        "CC BY 4.0",
        "ok",
        [class_ids.index("toi")],
        avoid_hashes=eval_hashes,
    )

    manifest_csv = root / "manifest_v4.csv"
    fieldnames = [
        "split",
        "source",
        "original_id",
        "file",
        "license",
        "license_flag",
        "author",
        "url",
        "group",
        "phash",
        "n_boxes",
        "n_group_of",
        "countable_group_of_boxes",
        "group_of_per_class",
        "is_hard_neg",
        "boxes_per_class",
    ]
    with manifest_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(manifest_rows)

    stats_json = root / "dataset_stats_v4.json"
    stats_payload = {
        "classes_v4": class_ids,
        "n_classes": 37,
        "classes_without_data": [],
        "images_per_split": images_per_split,
        "boxes_per_split_class": boxes_per_split_class,
        "hard_neg_bg_by_source_split": hard_neg_by_source_split,
        "total_train_bg_images": sum(
            v for k, v in hard_neg_by_source_split.items() if k.endswith("/train")
        ),
        "images_per_license_flag": images_per_license_flag,
        "phash_threshold": 4,
    }
    stats_json.write_text(json.dumps(stats_payload, indent=2), encoding="utf-8")

    cs_dir = root / "contact_sheets"
    cs_dir.mkdir(parents=True, exist_ok=True)
    cs_path = cs_dir / "audit_sample.jpg"
    _pattern_image(9999, size=(128, 128)).save(cs_path, "JPEG", quality=85)

    cleaning_json = root / "cleaning_manifest.json"
    cleaning_payload = {
        "version": 4,
        "dataset": "yolo_v4_synthetic",
        "kept_images": sum(images_per_split.values()),
        "sources": {
            "rf_tofu_oo": {"kept": 0, "quarantined": 609},
            "rf_water_spinach": {"kept": 0, "quarantined": 700},
            "rf_nhan_dien_rau": {"kept": 0, "quarantined": 285},
            "v3det": {"kept": 1, "quarantined": 142},
            "rf_viet_hoang": {"kept": 1, "quarantined": 88},
            "rf_robo1": {"kept": 1, "quarantined": 195},
            "lvis_v1_neg": {"kept": 1, "quarantined": 200},
        },
        "quarantined_sources": {
            "rf_tofu_oo": {"kept": 0, "quarantined": 609},
            "rf_water_spinach": {"kept": 0, "quarantined": 700},
            "rf_nhan_dien_rau": {"kept": 0, "quarantined": 285},
            "v3det": {"kept": 1, "quarantined": 142},
            "rf_viet_hoang": {"kept": 1, "quarantined": 88},
            "rf_robo1": {"kept": 1, "quarantined": 195},
        },
        "purged_defects": {
            "lvis_v1_neg_cooked_pizza_dropped": 200,
            "v3det_cooked_and_whole_basket_dropped": 142,
            "rf_viet_hoang_cooked_bbq_dropped": 88,
            "rf_robo1_infographic_and_shifted_dropped": 195,
            "whole_basket_countable_dropped": 15,
            "group_of_countable_purged": 375,
            "exif_transposed": 42,
        },
        "contact_sheets": ["contact_sheets/audit_sample.jpg"],
    }
    cleaning_json.write_text(json.dumps(cleaning_payload, indent=2), encoding="utf-8")

    return root, manifest_csv, stats_json, cleaning_json


# ---------------------------------------------------------------- minimal pure-Python ONNX fallback


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            break
    return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _ld(field: int, data: bytes) -> bytes:
    return _tag(field, 2) + _varint(len(data)) + data


def _vi(field: int, val: int) -> bytes:
    return _tag(field, 0) + _varint(val)


def _tensor_proto_float(name: str, dims: list[int], vals: np.ndarray) -> bytes:
    raw = np.asarray(vals, dtype="<f4").tobytes()
    return (
        b"".join(_vi(1, d) for d in dims)
        + _vi(2, 1)  # FLOAT
        + _ld(8, name.encode())
        + _ld(9, raw)
    )


def _tensor_type_proto(elem_type: int, dims: list[int]) -> bytes:
    shape_dims = b"".join(_ld(1, _vi(1, d)) for d in dims)
    return _ld(1, _vi(1, elem_type) + _ld(2, shape_dims))


def _value_info(name: str, dims: list[int]) -> bytes:
    return _ld(1, name.encode()) + _ld(2, _tensor_type_proto(1, dims))


def _node(op_type: str, inputs: list[str], outputs: list[str]) -> bytes:
    return (
        b"".join(_ld(1, i.encode()) for i in inputs)
        + b"".join(_ld(2, o.encode()) for o in outputs)
        + _ld(4, op_type.encode())
    )


def _build_synthetic_detector_model(model_dir: Path) -> Path:
    """Create a minimal valid [1, 3, 640, 640] -> [1, 41, 8400] ONNX + serving.json fallback."""
    model_dir.mkdir(parents=True, exist_ok=True)
    rows = all_class_rows()
    classes = [str(r["id"]) for r in rows]
    nc = len(classes)

    # ReduceMean(axes=[1,2,3], keepdims=True) -> [1,1,1,1], wait: simplest valid opset-13 detector:
    # Constant output0 [1, 4+nc, 8400] + 0 * ReduceSum(images) so input 'images' is connected!
    # Actually: GlobalAveragePool(images) -> [1, 3, 1, 1] -> ReduceMean/Slice is messy;
    # Mul(images, zero_weight) -> ReduceSum -> Reshape -> Add(const_head) works cleanly.
    # Even simpler: Reshape/MatMul/ConstantOfShape? Constant node of [1, 4+nc, 8400] + Slice/Mul of input!
    # Wait: ReduceMean(images, axes=[1,2,3])? Let's keep attrs simple:
    # Identity on constant + 0 * first element? No, Reshape(images, [1, 3*640*640])? No, Slice needs opset 10+ inputs.
    # Let's use GlobalAveragePool(images) [1,3,1,1] -> ReduceSum(axes=[1], keepdims=0) -> [1,1,1] * 0 + const_head [1, 4+nc, 8400]!
    # Note: ReduceSum axes as input in opset 13! Instead GlobalAveragePool(images)->[1,3,1,1] * w_zero[1,3,1,1] -> Shape?
    # Actually Mul(GlobalAveragePool(images), zero_3) -> [1,3,1,1] -> Pad/Tile? No, Conv!
    # Conv(images, W=[4+nc, 3, 1, 1]) gives [1, 4+nc, 640, 640]! Still needs 8400.
    # Wait: Mul(images, zero_scalar) -> still [1,3,640,640].
    # Let's use `GlobalAveragePool` -> `Squeeze`? In opset 13 Squeeze uses axes input.
    # Simplest zero-attribute graph in opset 13:
    # `GlobalAveragePool(images)` -> `g` [1, 3, 1, 1]
    # `Flatten(g)` -> `f` [1, 3] (Flatten has default axis=1, no required attrs!)
    # `MatMul(f, w_zero)` where `w_zero` is [3, 1] zeros -> `z` [1, 1]
    # `Unsqueeze`? No, `Mul(z, const_head)` where `const_head` is [1, 4+nc, 8400] broadcasts?
    # [1, 1] * [1, 41, 8400] -> wait: NumPy/ONNX right-aligned broadcast: [1, 1] aligns to [41, 8400], works!
    # Wait: `z` is [1, 1], `Add(z_b, const_head)` where `z_b` is `Mul(z, zero_1)` -> [1, 1] + [1, 41, 8400] -> [1, 41, 8400]!
    head = np.zeros((1, 4 + nc, 8400), dtype=np.float32)
    head[0, :4, 0] = (320.0, 320.0, 120.0, 120.0)
    head[0, 4 + 3, 0] = 0.72  # trung
    head[0, :4, 1] = (160.0, 160.0, 80.0, 80.0)
    head[0, 4 + 7, 1] = 0.65  # ca_chua

    inits = [
        _tensor_proto_float("w_zero", [3, 1], np.zeros((3, 1), dtype=np.float32)),
        _tensor_proto_float("const_head", [1, 4 + nc, 8400], head),
    ]
    nodes = [
        _node("GlobalAveragePool", ["images"], ["g"]),
        _node("Flatten", ["g"], ["f"]),
        _node("MatMul", ["f", "w_zero"], ["z"]),
        _node("Add", ["z", "const_head"], ["output0"]),
    ]
    graph = (
        b"".join(_ld(1, n) for n in nodes)
        + _ld(2, b"synthetic_yolo_v4")
        + b"".join(_ld(5, i) for i in inits)
        + _ld(11, _value_info("images", [1, 3, 640, 640]))
        + _ld(12, _value_info("output0", [1, 4 + nc, 8400]))
    )
    meta_entries = [
        _ld(1, b"end2end") + _ld(2, b"False"),
        _ld(1, b"task") + _ld(2, b"detect"),
        _ld(1, b"imgsz") + _ld(2, b"[640, 640]"),
        _ld(1, b"names") + _ld(2, repr(dict(enumerate(classes))).encode()),
    ]
    opset = _ld(1, b"") + _vi(2, 13)
    model_bytes = _vi(1, 8) + _ld(8, opset) + _ld(7, graph) + b"".join(_ld(14, m) for m in meta_entries)

    onnx_path = model_dir / "model.onnx"
    onnx_path.write_bytes(model_bytes)
    sha = hashlib.sha256(model_bytes).hexdigest()

    serving = {
        "conf": 0.25,
        "iou": 0.45,
        "imgsz": 640,
        "sha256": sha,
        "model": "synthetic_v4",
        "version": "v4_synthetic",
        "preprocess_version": "none",
        "onnx": "model.onnx",
        "onnx_bytes": len(model_bytes),
        "onnx_output_shape": [1, 4 + nc, 8400],
        "classes": classes,
        "n_classes": nc,
    }
    (model_dir / "serving.json").write_text(json.dumps(serving, indent=2), encoding="utf-8")
    return model_dir


@pytest.fixture(scope="session")
def e2e_config(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> E2EConfig:
    strict: bool = bool(request.config.getoption("--e2e-strict"))
    raw_ds = request.config.getoption("--e2e-dataset-dir")
    raw_md = request.config.getoption("--e2e-model-dir")
    raw_nc = request.config.getoption("--e2e-expected-nc")
    serving_file: str = str(request.config.getoption("--e2e-serving-file"))
    min_disk_gb: float = float(request.config.getoption("--e2e-min-disk-gb"))
    raw_phash_max = request.config.getoption("--e2e-phash-max-pairs")
    raw_lat_runs = request.config.getoption("--e2e-latency-runs")
    latency_sla_ms = float(request.config.getoption("--e2e-latency-sla-ms"))

    # 1. Resolve dataset
    is_synthetic_dataset = False
    if strict:
        ds_dir = Path(raw_ds) if raw_ds else (REPO_ROOT / "data/processed/cv/yolo_v4")
        if not ds_dir.is_dir():
            pytest.fail(f"--e2e-strict requires real yolo_v4 dataset directory, missing: {ds_dir}")
        manifest_csv = _resolve_companion(ds_dir, "manifest_v4.csv")
        stats_json = _resolve_companion(ds_dir, "dataset_stats_v4.json")
        cleaning_json = _resolve_companion(ds_dir, "cleaning_manifest.json")
        for req_file in (manifest_csv, stats_json, cleaning_json):
            if not req_file.is_file():
                pytest.fail(f"--e2e-strict requires {req_file}, which does not exist")
    else:
        if raw_ds:
            ds_dir = Path(raw_ds)
            if not ds_dir.is_dir():
                pytest.fail(f"--e2e-dataset-dir does not exist: {ds_dir}")
            manifest_csv = _resolve_companion(ds_dir, "manifest_v4.csv")
            stats_json = _resolve_companion(ds_dir, "dataset_stats_v4.json")
            cleaning_json = _resolve_companion(ds_dir, "cleaning_manifest.json")
        else:
            is_synthetic_dataset = True
            syn_root = tmp_path_factory.mktemp("synthetic_yolo_v4")
            ds_dir, manifest_csv, stats_json, cleaning_json = _build_synthetic_yolo_v4(syn_root)

    # 2. Resolve model
    is_synthetic_model = False
    if strict:
        model_dir = Path(raw_md) if raw_md else (REPO_ROOT / "deploy/models/detector_v3")
        if not model_dir.is_dir():
            pytest.fail(f"--e2e-strict requires real detector_v3 directory, missing: {model_dir}")
    else:
        if raw_md:
            model_dir = Path(raw_md)
            if not model_dir.is_dir():
                pytest.fail(f"--e2e-model-dir does not exist: {model_dir}")
        else:
            v2_dir = REPO_ROOT / "deploy/models/detector_v2"
            if (v2_dir / "model.onnx").is_file() and (v2_dir / serving_file).is_file():
                model_dir = v2_dir
            else:
                is_synthetic_model = True
                model_dir = _build_synthetic_detector_model(tmp_path_factory.mktemp("synthetic_detector_v4"))

    onnx_path = model_dir / "model.onnx"
    serving_path = model_dir / serving_file
    if not onnx_path.is_file():
        pytest.fail(f"Missing model.onnx at {onnx_path}")
    if not serving_path.is_file():
        pytest.fail(f"Missing serving manifest at {serving_path}")

    f05_cand = model_dir / "serving_f05.json"
    serving_f05_path = f05_cand if f05_cand.is_file() else None

    serving_data = json.loads(serving_path.read_text(encoding="utf-8"))
    if strict:
        expected_nc = int(raw_nc) if raw_nc is not None else 37
        if expected_nc != 37:
            pytest.fail(f"--e2e-strict requires expected_nc == 37, got {expected_nc}")
    else:
        expected_nc = int(raw_nc) if raw_nc is not None else int(len(serving_data.get("classes") or []))
        if expected_nc <= 0:
            pytest.fail(f"Could not determine expected_nc from {serving_path}")

    phash_max_pairs = 0 if (raw_phash_max is None and strict) else (2000 if raw_phash_max is None else int(raw_phash_max))
    latency_runs = 30 if (raw_lat_runs is None and strict) else (10 if raw_lat_runs is None else int(raw_lat_runs))

    return E2EConfig(
        strict=strict,
        is_synthetic_dataset=is_synthetic_dataset,
        is_synthetic_model=is_synthetic_model,
        dataset_dir=ds_dir,
        manifest_csv=manifest_csv,
        stats_json=stats_json,
        cleaning_json=cleaning_json,
        model_dir=model_dir,
        onnx_path=onnx_path,
        serving_path=serving_path,
        serving_f05_path=serving_f05_path,
        expected_nc=expected_nc,
        min_disk_gb=min_disk_gb,
        phash_max_pairs=phash_max_pairs,
        latency_runs=latency_runs,
        latency_sla_ms=latency_sla_ms,
    )


@pytest.fixture(scope="session")
def onnx_session(e2e_config: E2EConfig) -> ort.InferenceSession:
    so = ort.SessionOptions()
    so.intra_op_num_threads = 2
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    so.add_session_config_entry("session.inter_op.allow_spinning", "0")
    return ort.InferenceSession(str(e2e_config.onnx_path), so, providers=["CPUExecutionProvider"])


@pytest.fixture(scope="session")
def onnx_names(onnx_session: ort.InferenceSession) -> list[str]:
    meta = onnx_session.get_modelmeta().custom_metadata_map
    raw = meta.get("names")
    assert raw, "ONNX custom_metadata_map['names'] is missing"
    parsed = ast.literal_eval(raw)
    assert isinstance(parsed, dict)
    assert sorted(parsed) == list(range(len(parsed)))
    return [str(parsed[i]) for i in range(len(parsed))]


@pytest.fixture(scope="session")
def manifest_rows(e2e_config: E2EConfig) -> list[dict[str, str]]:
    with e2e_config.manifest_csv.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="session")
def vision_rows() -> list[dict[str, Any]]:
    return all_class_rows()
