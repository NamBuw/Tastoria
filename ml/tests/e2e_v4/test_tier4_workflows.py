"""Tier 4: End-to-end workflows — dataset reconciliation (S1) and sanitize->ONNX->chips->latency SLA (S2)."""

from __future__ import annotations

import io
import json
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import onnxruntime as ort
import pytest
from PIL import Image

from tastoria.modules.scan.aggregate import ClassRule, FoundBox, build_chips
from tastoria.modules.scan.detector import Detector
from tastoria.modules.scan.images import sanitize
from tastoria.modules.scan.runner import resolve_class_conf
from tastoria_ml.cv.classes import REPO

pytestmark = pytest.mark.tier4


def test_s1_dataset_manifest_stats_cleaning_reconciliation(
    e2e_config, manifest_rows: list[dict[str, str]], vision_rows: list[dict]
) -> None:
    """S1: Full reconciliation across yolo_v4/{images,labels}, manifest_v4.csv, dataset_stats_v4.json, cleaning_manifest."""
    class_ids = [str(r["id"]) for r in vision_rows]
    stats = json.loads(e2e_config.stats_json.read_text(encoding="utf-8"))
    cleaning = json.loads(e2e_config.cleaning_json.read_text(encoding="utf-8"))
    assert isinstance(cleaning, dict) and len(cleaning) > 0

    disk_imgs: dict[str, int] = {}
    disk_boxes: dict[str, dict[str, int]] = {}
    for split in ("train", "val", "test", "heldout"):
        img_files = [
            p
            for p in (e2e_config.dataset_dir / "images" / split).iterdir()
            if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}
        ]
        disk_imgs[split] = len(img_files)
        cnt: Counter[str] = Counter()
        for lp in (e2e_config.dataset_dir / "labels" / split).glob("*.txt"):
            for line in lp.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s:
                    cnt[class_ids[int(s.split()[0])]] += 1
        disk_boxes[split] = dict(cnt)

    man_imgs: Counter[str] = Counter()
    man_boxes: dict[str, Counter[str]] = defaultdict(Counter)
    man_lic: Counter[str] = Counter()
    train_bg = 0
    for r in manifest_rows:
        sp = r["split"]
        man_imgs[sp] += 1
        man_lic[r["license_flag"]] += 1
        if sp == "train" and int(r["is_hard_neg"]) == 1:
            train_bg += 1
        for cname, n in json.loads(r["boxes_per_class"] or "{}").items():
            man_boxes[sp][cname] += int(n)

    assert dict(man_imgs) == disk_imgs == stats["images_per_split"]
    assert dict(man_lic) == stats["images_per_license_flag"]
    assert train_bg == int(stats["total_train_bg_images"])
    for split in ("train", "val", "test", "heldout"):
        assert dict(man_boxes[split]) == disk_boxes[split] == stats["boxes_per_split_class"].get(split, {})


def test_s2_raw_image_to_chip_summary_and_cpu_latency_sla(
    e2e_config, onnx_session: ort.InferenceSession, onnx_names: list[str], vision_rows: list[dict]
) -> None:
    """S2: sanitize(EXIF=6) -> Image.open -> Detector.detect -> serving -> countable/non-countable chips + p95<=3s."""
    serving_cfg = json.loads(
        (e2e_config.serving_f05_path or e2e_config.serving_path).read_text(encoding="utf-8")
    )
    class_map = {i: 1000 + i for i in range(len(onnx_names))}
    code_by_vid = {1000 + i: cid for i, cid in enumerate(onnx_names)}
    cc = resolve_class_conf(serving_cfg.get("class_conf"), class_map, code_by_vid)

    det = Detector(
        onnx_session,
        conf=float(serving_cfg["conf"]),
        iou=float(serving_cfg["iou"]),
        preprocess_version=serving_cfg.get("preprocess_version"),
        agnostic_iou=serving_cfg.get("agnostic_iou"),
        class_conf=cc,
    )

    # Gather real validation/test photos if present, else synthetic EXIF-6 photos from dataset_dir
    sample_paths: list[Path] = []
    for cand_dir in (
        e2e_config.dataset_dir / "images/val",
        REPO / "data/processed/cv/yolo_v2/images/test",
    ):
        if cand_dir.is_dir():
            sample_paths.extend(sorted(cand_dir.glob("*.jpg"))[:10])
    assert len(sample_paths) > 0

    # Wrap first image with EXIF Orientation=6 to verify end-to-end sanitize->detect
    with Image.open(sample_paths[0]) as src_im:
        ex = Image.Exif()
        ex[0x0112] = 6
        ex[0x010F] = "FieldCamera"
        buf = io.BytesIO()
        src_im.convert("RGB").save(buf, "JPEG", quality=90, exif=ex.tobytes())
        exif_payloads = [buf.getvalue()] + [p.read_bytes() for p in sample_paths[1:]]

    countable_by_code = {str(r["id"]): bool(r.get("countable")) for r in vision_rows}
    ing_by_vid = {vid: uuid.uuid5(uuid.NAMESPACE_DNS, f"ing.{code}") for vid, code in code_by_vid.items()}
    rules = {
        vid: ClassRule(countable=countable_by_code[code], ingredient_id=ing_by_vid[vid])
        for vid, code in code_by_vid.items()
    }

    # Warmup
    warm = sanitize(exif_payloads[0])
    with Image.open(io.BytesIO(warm.jpeg)) as wim:
        _ = det.detect(wim)

    latencies_ms: list[float] = []
    all_chips = []
    for idx in range(e2e_config.latency_runs):
        raw = exif_payloads[idx % len(exif_payloads)]
        t0 = time.perf_counter()
        cleaned = sanitize(raw)
        with Image.open(io.BytesIO(cleaned.jpeg)) as im:
            assert not im.getexif()
            boxes = det.detect(im)
        found = [FoundBox(image=0, shelf_group=1, vision_class_id=class_map[b.class_index], confidence=b.confidence) for b in boxes]
        chips = build_chips(found, rules)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(dt_ms)
        all_chips.extend(chips)

        for ch in chips:
            matching_boxes = [found[bi] for bi in ch.boxes]
            is_countable = any(rules[fb.vision_class_id].countable for fb in matching_boxes)
            if is_countable:
                assert ch.model_count is not None and ch.model_count >= 1
            else:
                assert ch.model_count is None

    p95_ms = float(np.percentile(np.asarray(latencies_ms, dtype=np.float64), 95))
    assert p95_ms <= e2e_config.latency_sla_ms, (
        f"ML CPU pipeline p95={p95_ms:.1f} ms exceeded {e2e_config.latency_sla_ms:.1f} ms SLA"
    )
