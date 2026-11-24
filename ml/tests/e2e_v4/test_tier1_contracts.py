"""Tier 1: Feature & Contract E2E tests for 37-class KB, yolo_v4 purity/EXIF/license/leakage, ONNX & MLOps gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
import pytest
import yaml
from PIL import Image

from tastoria_ml.cv.classes import INGREDIENTS, REPO, load_classes, source_label_map, validate
from tastoria_ml.cv.counting import countable_ids
from tastoria_ml.cv.phash import hamming, phash

pytestmark = pytest.mark.tier1

EXPECTED_COUNTABLE_19 = frozenset(
    {
        "trung",
        "dau_phu",
        "ca_chua",
        "ca_rot",
        "khoai_tay",
        "bap_cai",
        "sup_lo",
        "bi_do",
        "bi_dao",
        "su_su",
        "muop",
        "muop_dang",
        "mi_tom",
        "do_hop",
        "sua",
        "sua_chua",
        "chanh",
        "bim_bim",
        "nuoc_ngot",
    }
)


def _yaml_names_list(raw_names: Any) -> list[str]:
    if isinstance(raw_names, list):
        return [str(x) for x in raw_names]
    if isinstance(raw_names, dict):
        keys = sorted(int(k) for k in raw_names)
        assert keys == list(range(len(keys))), f"Non-contiguous class indices in YAML: {keys}"
        return [str(raw_names[k] if k in raw_names else raw_names[str(k)]) for k in keys]
    raise AssertionError(f"Unexpected names type in dataset YAML: {type(raw_names)}")


def test_vision_classes_37_schema_and_main_validation(vision_rows: list[dict[str, Any]]) -> None:
    assert len(vision_rows) == 37
    ids = [str(r["id"]) for r in vision_rows]
    assert len(set(ids)) == 37

    main = load_classes()
    assert len(main) == 22
    assert [c.id for c in main] == ids[:22]
    assert validate(main) == []


@pytest.mark.parametrize(
    "aspect",
    ["countable_item", "uncountable_package_group_of", "meal_ingredient_non_recipe"],
)
def test_vision_classes_countable_and_meal_ingredient_contracts(
    aspect: str, vision_rows: list[dict[str, Any]]
) -> None:
    if aspect == "countable_item":
        c_rows = [r for r in vision_rows if r.get("countable") is True]
        assert len(c_rows) == 19
        assert {str(r["id"]) for r in c_rows} == EXPECTED_COUNTABLE_19
        assert all(r.get("instance_def") == "item" for r in c_rows)
        assert countable_ids(include_proposed=True) == EXPECTED_COUNTABLE_19
    elif aspect == "uncountable_package_group_of":
        u_rows = [r for r in vision_rows if r.get("countable") is False]
        assert len(u_rows) == 18
        assert all(r.get("instance_def") in {"package", "group_of"} for r in u_rows)
    else:
        ing = {i["name_vi"]: i for i in yaml.safe_load(INGREDIENTS.read_text(encoding="utf-8"))["ingredients"]}
        recipe_ings: set[str] = set()
        for f in (INGREDIENTS.parent / "recipes").rglob("*.yaml"):
            doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            recipe_ings |= {ln.get("name") for ln in doc.get("ingredients") or [] if isinstance(ln, dict)}
        for r in vision_rows[22:]:
            for n in r.get("ingredients") or []:
                assert n in ing, f"Unknown ingredient {n!r} in proposed class {r['id']}"
                if ing[n]["food_group"] == "do_an_vat":
                    assert r.get("meal_ingredient") is False
                elif r.get("meal_ingredient") is False:
                    assert n not in recipe_ings, f"Non-meal class {r['id']} references recipe ingredient {n!r}"


@pytest.mark.parametrize(
    "source_name",
    ["openimages_v7", "mendeley_bd", "lvis_v1", "rpc_checkout", "omorros_kitchen"],
)
def test_vision_classes_public_data_mappings_unique(
    source_name: str, vision_rows: list[dict[str, Any]]
) -> None:
    if source_name in {"openimages_v7", "mendeley_bd"}:
        mapping = source_label_map(load_classes(), source_name)
        assert len(mapping) > 0
    labels = [lbl for r in vision_rows for lbl in (r.get("public_data") or {}).get(source_name, [])]
    assert len(labels) == len(set(labels)), f"Duplicate {source_name} source labels in vision_classes.yaml"


def test_yolo_v4_yaml_and_37_class_order(e2e_config, vision_rows: list[dict[str, Any]]) -> None:
    ds_yaml = e2e_config.dataset_dir / "dataset.yaml"
    if not ds_yaml.is_file():
        ds_yaml = e2e_config.dataset_dir / "data.yaml"
    assert ds_yaml.is_file(), f"Missing dataset.yaml/data.yaml in {e2e_config.dataset_dir}"

    data = yaml.safe_load(ds_yaml.read_text(encoding="utf-8"))
    expected_order = [str(r["id"]) for r in vision_rows]
    assert _yaml_names_list(data["names"]) == expected_order

    heldout_yaml = e2e_config.dataset_dir / "dataset_heldout.yaml"
    assert heldout_yaml.is_file(), f"Missing dataset_heldout.yaml in {e2e_config.dataset_dir}"
    h_data = yaml.safe_load(heldout_yaml.read_text(encoding="utf-8"))
    assert _yaml_names_list(h_data["names"]) == expected_order

    stats = json.loads(e2e_config.stats_json.read_text(encoding="utf-8"))
    assert int(stats["n_classes"]) == 37
    assert stats.get("classes_without_data", []) == []


@pytest.mark.parametrize("split", ["train", "val", "test", "heldout"])
def test_yolo_v4_split_image_label_parity_and_bounds(split: str, e2e_config) -> None:
    img_dir = e2e_config.dataset_dir / "images" / split
    lbl_dir = e2e_config.dataset_dir / "labels" / split
    assert img_dir.is_dir() and lbl_dir.is_dir()

    imgs = {p.stem: p for p in img_dir.iterdir() if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"}}
    lbls = {p.stem: p for p in lbl_dir.iterdir() if p.is_file() and p.suffix == ".txt"}
    assert len(imgs) > 0, f"Empty split {split}"
    assert set(imgs) == set(lbls), f"Stem mismatch in {split}: {set(imgs) ^ set(lbls)}"

    for stem, lp in sorted(lbls.items()):
        text = lp.read_text(encoding="utf-8").strip()
        if not text:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            parts = line.split()
            assert len(parts) == 5, f"{lp}:{line_no} invalid YOLO line: {line!r}"
            cls_idx = int(parts[0])
            xc, yc, w, h = (float(x) for x in parts[1:])
            assert 0 <= cls_idx < 37, f"{lp}:{line_no} class index {cls_idx} out of [0, 37)"
            assert 0.0 <= xc <= 1.0 and 0.0 <= yc <= 1.0, f"{lp}:{line_no} center out of bounds"
            assert 0.0 < w <= 1.0 and 0.0 < h <= 1.0, f"{lp}:{line_no} size out of bounds"
            x0, y0, x1, y1 = xc - w / 2.0, yc - h / 2.0, xc + w / 2.0, yc + h / 2.0
            assert -1e-5 <= x0 and -1e-5 <= y0 and x1 <= 1.0 + 1e-5 and y1 <= 1.0 + 1e-5, (
                f"{lp}:{line_no} corners exceed [0,1]: {(x0, y0, x1, y1)}"
            )


def test_yolo_v4_purged_defects_rf_tofu_oo_and_single_leaf_spinach(
    e2e_config, manifest_rows: list[dict[str, str]]
) -> None:
    sources = {r["source"] for r in manifest_rows}
    assert "rf_tofu_oo" not in sources
    assert not any("rf_tofu_oo" in r["file"] for r in manifest_rows)

    for r in manifest_rows:
        if r["source"] in {"rf_water_spinach", "rf_nhan_dien_rau"}:
            bpc = json.loads(r["boxes_per_class"] or "{}")
            assert "rau_muong" not in bpc, f"Single-leaf rau_muong defect retained in {r['file']}"

    cleaning = json.loads(e2e_config.cleaning_json.read_text(encoding="utf-8"))
    assert isinstance(cleaning, dict) and len(cleaning) > 0
    if "quarantined_sources" in cleaning and "rf_tofu_oo" in cleaning["quarantined_sources"]:
        assert cleaning["quarantined_sources"]["rf_tofu_oo"].get("kept", 0) == 0


def test_yolo_v4_purged_lvis_neg_cooked_and_whole_basket_countable(
    e2e_config, manifest_rows: list[dict[str, str]], vision_rows: list[dict[str, Any]]
) -> None:
    banned_ood = {"pizza", "dining_table", "sandwich"}
    lvis_neg_rows = [r for r in manifest_rows if r["source"] == "lvis_v1_neg"]
    for r in lvis_neg_rows:
        assert int(r["n_boxes"]) == 0
        low = f"{r['original_id']} {r['file']}".lower()
        assert not any(tok in low for tok in banned_ood), f"Banned OOD category in {r['file']}"

    if not e2e_config.is_synthetic_dataset and lvis_neg_rows:
        neg_sel = REPO / "data/raw/images/lvis_v1/ann/neg-selected.json"
        if neg_sel.is_file():
            sel_map = {str(item["id"]): str(item.get("ood_cat", "")).lower() for item in json.loads(neg_sel.read_text())}
            for r in lvis_neg_rows:
                img_id = str(r["group"] or r["original_id"].split("/")[-1])
                cat = sel_map.get(img_id, "")
                assert cat not in banned_ood, f"Kept lvis_v1_neg {img_id} has banned category {cat!r}"

    # Per-class group_of invariant: countable:true classes must NEVER be marked group_of
    # (an image may validly mix an uncountable group_of box with a normal countable box).
    for r in manifest_rows:
        bpc = json.loads(r["boxes_per_class"] or "{}")
        if "group_of_per_class" in r:
            gpc = json.loads(r["group_of_per_class"] or "{}")
            bad_gpc = {k for k, v in gpc.items() if int(v) > 0} & EXPECTED_COUNTABLE_19
            assert not bad_gpc, f"Countable class(es) {sorted(bad_gpc)} marked group_of in {r['file']}"
        if "countable_group_of_boxes" in r:
            assert int(r["countable_group_of_boxes"] or 0) == 0, (
                f"countable_group_of_boxes > 0 in {r['file']}"
            )
        if int(r["n_group_of"]) > 0:
            uncountable_in_img = set(bpc) - EXPECTED_COUNTABLE_19
            assert uncountable_in_img, (
                f"Image {r['file']} has n_group_of={r['n_group_of']} with only countable classes {sorted(bpc)}"
            )

    # Direct label scan for whole-basket countable:true frame-spanning boxes.
    # Verified against yolo_v3: openimages_v7/lvis_v1 have legitimate single close-up macro items,
    # whereas v3det has whole-basket/buffet defects (>=0.92) and mendeley_bd/rpc/omorros/synthetic have 0.
    class_ids = [str(r["id"]) for r in vision_rows]
    row_by_stem = {Path(r["file"]).stem: r for r in manifest_rows}
    is_synthetic_manifest = bool(
        e2e_config.is_synthetic_dataset
        or (manifest_rows and manifest_rows[0].get("author") == "synthetic_e2e")
    )
    for split in ("train", "val", "test", "heldout"):
        lbl_dir = e2e_config.dataset_dir / "labels" / split
        all_lbls = sorted(p for p in lbl_dir.iterdir() if p.is_file() and p.suffix == ".txt")
        if not e2e_config.strict and len(all_lbls) > 150:
            step = max(1, len(all_lbls) // 150)
            sampled = all_lbls[::step][:150]
            priority = [p for p in all_lbls if p.stem.startswith(("v3det__", "rf_"))][:150]
            lbls_to_check = sorted(set(sampled) | set(priority))
        else:
            lbls_to_check = all_lbls

        for lp in lbls_to_check:
            lines = [ln.strip() for ln in lp.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if not lines:
                continue
            row = row_by_stem.get(lp.stem)
            src = (row["source"] if row else lp.stem.split("__")[0]).strip()
            for ln in lines:
                parts = ln.split()
                cls_idx = int(parts[0])
                cname = class_ids[cls_idx]
                if cname not in EXPECTED_COUNTABLE_19:
                    continue
                w, h = float(parts[3]), float(parts[4])
                if src == "v3det":
                    assert not (w >= 0.92 and h >= 0.92), (
                        f"Whole-basket v3det countable box ({cname} {w:.3f}x{h:.3f}) in {lp}"
                    )
                elif len(lines) == 1 and (
                    is_synthetic_manifest
                    or src in {"mendeley_bd", "rpc_checkout", "omorros_kitchen"}
                    or row is None
                ):
                    assert not (w >= 0.94 and h >= 0.94), (
                        f"Whole-basket single countable box ({cname} {w:.3f}x{h:.3f}) in {lp}"
                    )

    # Verify cleaning_manifest.json records whole_basket_countable / group_of_countable purge accounting
    cleaning = json.loads(e2e_config.cleaning_json.read_text(encoding="utf-8"))
    purged_section = (
        cleaning.get("purged_defects")
        or cleaning.get("quarantine_reasons")
        or cleaning.get("filters")
        or {}
    )
    purge_keys = {k.lower(): v for k, v in {**cleaning, **purged_section}.items()}
    has_basket_or_group_record = any(
        ("whole_basket" in k or "group_of" in k) for k in purge_keys
    )
    if e2e_config.strict or is_synthetic_manifest:
        assert has_basket_or_group_record, (
            "cleaning_manifest.json must record whole_basket_countable / group_of_countable purge status"
        )


def test_yolo_v4_audited_f7_purges_v3det_viet_hoang_robo1(
    e2e_config, manifest_rows: list[dict[str, str]]
) -> None:
    """Verify F7 audited Track C defect purges across v3det, rf_viet_hoang, and rf_robo1."""
    banned_tokens = {
        "rf_robo1": ("infographic", "nutrition", "watermark"),
        "rf_viet_hoang": ("bbq", "grilled", "cooked_rib"),
        "v3det": ("buffet", "dolma", "pad_thai"),
    }
    for r in manifest_rows:
        src = r["source"]
        if src in banned_tokens:
            low = f"{r['original_id']} {r['file']}".lower()
            bad = [tok for tok in banned_tokens[src] if tok in low]
            assert not bad, f"Uncleaned {src} defect token(s) {bad} in {r['file']}"
            if src == "rf_robo1":
                assert int(r["is_hard_neg"]) == 0, f"rf_robo1 infographic NEG retained: {r['file']}"

    cleaning = json.loads(e2e_config.cleaning_json.read_text(encoding="utf-8"))
    sources_map: dict[str, Any] = {}
    for key in ("quarantined_sources", "per_source", "sources"):
        sec = cleaning.get(key)
        if isinstance(sec, dict):
            for sname, sval in sec.items():
                sources_map[sname] = sval
    reasons_map: dict[str, Any] = {}
    for key in ("purged_defects", "quarantine_reasons", "filters"):
        sec = cleaning.get(key)
        if isinstance(sec, dict):
            reasons_map.update(sec)

    for audited_src in ("v3det", "rf_viet_hoang", "rf_robo1"):
        src_entry = sources_map.get(audited_src)
        has_src_quarantine = False
        if isinstance(src_entry, dict):
            q_cnt = int(
                src_entry.get("quarantined")
                or src_entry.get("dropped")
                or src_entry.get("removed")
                or 0
            )
            k_cnt = src_entry.get("kept")
            has_src_quarantine = q_cnt > 0 or k_cnt == 0
        has_reason_purge = any(
            audited_src in k.lower() and (isinstance(v, (int, float)) and v > 0)
            for k, v in reasons_map.items()
        )
        assert has_src_quarantine or has_reason_purge, (
            f"cleaning_manifest.json missing Track C quarantine/purge accounting for audited source {audited_src!r}"
        )

    sheets = cleaning.get("contact_sheets")
    assert isinstance(sheets, list)
    if e2e_config.strict:
        assert len(sheets) > 0, "Strict M4 mode requires audited contact_sheets in cleaning_manifest.json"
        for item in sheets:
            rel = item.get("path") if isinstance(item, dict) else item
            assert rel, f"Empty contact sheet entry: {item!r}"
            cand = Path(str(rel))
            if not cand.is_absolute():
                cand_ds = e2e_config.dataset_dir / cand
                cand_repo = REPO / cand
                cand = cand_ds if cand_ds.is_file() else cand_repo
            assert cand.is_file(), f"Missing audited contact sheet: {rel}"


@pytest.mark.parametrize("split", ["train", "val", "test", "heldout"])
def test_yolo_v4_exif_orientation_and_decodability(split: str, e2e_config) -> None:
    img_dir = e2e_config.dataset_dir / "images" / split
    imgs = sorted(p for p in img_dir.iterdir() if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    if not e2e_config.strict and len(imgs) > 60:
        step = max(1, len(imgs) // 60)
        imgs = imgs[::step][:60]

    for p in imgs:
        with Image.open(p) as im:
            assert im.format in {"JPEG", "PNG"}, f"Unexpected format {im.format} at {p}"
            im.load()
            exif = im.getexif()
            orientation = exif.get(0x0112)
            assert orientation in (None, 1), f"Un-transposed EXIF orientation={orientation} in {p}"


def test_yolo_v4_license_tags_and_split_provenance_rules(manifest_rows: list[dict[str, str]]) -> None:
    assert len(manifest_rows) > 0
    for r in manifest_rows:
        flag = r["license_flag"]
        assert flag in {"ok", "non_commercial"}, f"Invalid license_flag={flag!r} for {r['file']}"
        src, lic, split = r["source"], r["license"], r["split"]
        if src == "rpc_checkout" or "NonCommercial" in lic or "BY-NC" in lic:
            assert flag == "non_commercial", f"{src} ({lic}) must be non_commercial"
        if src in {"mendeley_bd", "openimages_v7", "omorros_kitchen", "dfv16"} and "NC" not in lic:
            assert flag == "ok", f"{src} ({lic}) must be ok"
        if src == "omorros_kitchen":
            assert split == "heldout", f"omorros_kitchen leaked into split={split}"
        if src == "v3det" or src.startswith("rf_"):
            assert split in {"train", "val"}, f"{src} must not appear in {split}"


def test_yolo_v4_cross_split_phash_no_leakage(e2e_config, manifest_rows: list[dict[str, str]]) -> None:
    eval_rows = [r for r in manifest_rows if r["split"] in {"test", "heldout"}]
    dev_rows = [r for r in manifest_rows if r["split"] in {"train", "val"}]
    assert eval_rows and dev_rows

    dev_hashes = np.array([int(r["phash"], 16) for r in dev_rows], dtype=np.uint64)
    queries = eval_rows
    if e2e_config.phash_max_pairs > 0 and len(queries) > e2e_config.phash_max_pairs:
        step = max(1, len(queries) // e2e_config.phash_max_pairs)
        queries = queries[::step][: e2e_config.phash_max_pairs]

    for r in queries:
        eh = int(r["phash"], 16)
        min_d = int(hamming(dev_hashes, eh).min())
        assert min_d > 4, f"Cross-split pHash leakage (hamming={min_d}) for {r['file']}"

    # Verify manifest pHash matches actual pixel bytes on disk across eval & sampled dev rows (P5b).
    def _evenly_spaced(rows: list[dict[str, str]], cap: int) -> list[dict[str, str]]:
        if cap <= 0 or len(rows) <= cap:
            return rows
        step = max(1, len(rows) // cap)
        return rows[::step][:cap]

    def _resolve_img(rel_str: str) -> Path:
        rel = Path(rel_str)
        cand = e2e_config.dataset_dir / rel
        if not cand.is_file() and len(rel.parts) > 1:
            cand = e2e_config.dataset_dir / Path(*rel.parts[1:])
        assert cand.is_file(), f"Missing manifest image on disk: {rel_str}"
        return cand

    def _compute_disk_hashes(img_path: Path) -> tuple[int, int]:
        with Image.open(img_path) as im:
            rgb_h = int(phash(np.asarray(im.convert("RGB"))))
            gray = im.convert("L")
            gray.thumbnail((256, 256))
            l256_h = int(phash(np.asarray(gray)))
        return l256_h, rgb_h

    eval_sample = eval_rows if (e2e_config.strict or len(eval_rows) <= 200) else _evenly_spaced(eval_rows, 64)
    dev_sample = _evenly_spaced(dev_rows, 256 if e2e_config.strict else 64)

    eval_disk_hashes: list[int] = []
    for r in eval_sample:
        l256_h, rgb_h = _compute_disk_hashes(_resolve_img(r["file"]))
        manifest_h = int(r["phash"], 16)
        assert min(int(hamming(l256_h, manifest_h)), int(hamming(rgb_h, manifest_h))) == 0, (
            f"Stale/spoofed pHash in manifest for {r['file']}"
        )
        eval_disk_hashes.append(l256_h)

    eval_disk_arr = np.asarray(eval_disk_hashes, dtype=np.uint64)
    for r in dev_sample:
        l256_h, rgb_h = _compute_disk_hashes(_resolve_img(r["file"]))
        manifest_h = int(r["phash"], 16)
        assert min(int(hamming(l256_h, manifest_h)), int(hamming(rgb_h, manifest_h))) == 0, (
            f"Stale/spoofed pHash in manifest for {r['file']}"
        )
        if eval_disk_arr.size > 0:
            min_disk_d = int(hamming(eval_disk_arr, l256_h).min())
            assert min_disk_d > 4, f"Disk-pixel cross-split pHash leakage (hamming={min_disk_d}) for {r['file']}"


def test_detector_onnx_session_and_metadata_contract(
    e2e_config, onnx_session: ort.InferenceSession, onnx_names: list[str]
) -> None:
    inp = onnx_session.get_inputs()[0]
    out = onnx_session.get_outputs()[0]
    assert tuple(inp.shape) == (1, 3, 640, 640)
    assert tuple(out.shape) == (1, 4 + e2e_config.expected_nc, 8400)

    meta = onnx_session.get_modelmeta().custom_metadata_map
    assert meta.get("end2end") == "False"
    assert meta.get("task") == "detect"
    assert len(onnx_names) == e2e_config.expected_nc

    dummy = np.zeros((1, 3, 640, 640), dtype=np.float32)
    y = onnx_session.run(None, {inp.name: dummy})[0]
    assert y.shape == (1, 4 + e2e_config.expected_nc, 8400)
    assert np.all(np.isfinite(y))


def test_detector_serving_manifest_and_f05_contract(
    e2e_config, onnx_names: list[str], vision_rows: list[dict[str, Any]]
) -> None:
    serving = json.loads(e2e_config.serving_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(e2e_config.onnx_path.read_bytes()).hexdigest()
    assert serving["sha256"] == digest
    assert int(serving["imgsz"]) == 640
    assert 0.0 < float(serving["conf"]) < 1.0
    assert 0.0 < float(serving["iou"]) < 1.0

    classes = serving["classes"]
    assert classes == onnx_names
    assert len(classes) == e2e_config.expected_nc
    valid_ids = [str(r["id"]) for r in vision_rows]
    assert set(classes) <= set(valid_ids)
    if e2e_config.strict:
        assert classes == valid_ids

    if e2e_config.serving_f05_path is not None:
        f05 = json.loads(e2e_config.serving_f05_path.read_text(encoding="utf-8"))
        assert 0.0 < float(f05["conf"]) < 1.0
        assert 0.0 < float(f05["iou"]) < 1.0
        if f05.get("agnostic_iou") is not None:
            assert 0.0 < float(f05["agnostic_iou"]) < 1.0
        cc = f05.get("class_conf") or {}
        assert isinstance(cc, dict)
        assert set(cc) <= set(classes)
        assert all(not isinstance(v, bool) and 0.0 < float(v) <= 1.0 for v in cc.values())


def test_mlops_register_and_gate_schema_compatibility(
    e2e_config, onnx_names: list[str], vision_rows: list[dict[str, Any]]
) -> None:
    """Public ONNX & serving schema contract aligned with tastoria.modules.admin.mlops + Detector."""
    from tastoria.modules.admin.mlops import onnx_class_names
    from tastoria.modules.scan.detector import Detector
    from tastoria.modules.scan.runner import resolve_class_conf

    extracted = onnx_class_names(e2e_config.onnx_path)
    assert extracted == onnx_names
    assert len(set(extracted)) == len(extracted)
    known_codes = {str(r["id"]) for r in vision_rows}
    assert set(extracted) <= known_codes

    # Verify SHA-256 and public ONNXRuntime CPU session shape [1, 4+C, 8400] & square input
    serving = json.loads(e2e_config.serving_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(e2e_config.onnx_path.read_bytes()).hexdigest()
    assert digest == serving["sha256"]

    sess = ort.InferenceSession(str(e2e_config.onnx_path), providers=["CPUExecutionProvider"])
    inp = sess.get_inputs()[0].shape
    out = sess.get_outputs()[0].shape
    assert len(inp) == 4 and isinstance(inp[2], int) and inp[2] == inp[3]
    assert len(out) == 3 and out[1] == 4 + len(extracted)

    # Verify serving threshold block & Detector instantiation match MLOps gate rules
    active_serving = (
        json.loads(e2e_config.serving_f05_path.read_text(encoding="utf-8"))
        if e2e_config.serving_f05_path is not None
        else serving
    )
    for k in ("conf", "iou"):
        val = active_serving.get(k)
        assert not isinstance(val, bool) and isinstance(val, int | float) and 0 < val < 1
    ag = active_serving.get("agnostic_iou")
    if ag is not None:
        assert not isinstance(ag, bool) and isinstance(ag, int | float) and 0 < ag < 1
    cc = active_serving.get("class_conf")
    if cc is not None:
        assert isinstance(cc, dict)
        assert all(not isinstance(v, bool) and isinstance(v, int | float) and 0 < v <= 1 for v in cc.values())

    class_map = {i: 1000 + i for i in range(len(extracted))}
    code_by_vid = {1000 + i: code for i, code in enumerate(extracted)}
    resolved_cc = resolve_class_conf(cc, class_map, code_by_vid)
    det = Detector(
        sess,
        conf=float(active_serving["conf"]),
        iou=float(active_serving["iou"]),
        preprocess_version=active_serving.get("preprocess_version") or serving.get("preprocess_version"),
        agnostic_iou=float(ag) if ag is not None else None,
        class_conf=resolved_cc,
    )
    boxes = det.detect(Image.new("RGB", (320, 240), (114, 114, 114)))
    assert all(0 <= b.class_index < len(extracted) for b in boxes)


def test_detector_serving_f05_and_metrics_calibration_contract(
    e2e_config, onnx_session: ort.InferenceSession, onnx_names: list[str]
) -> None:
    """Validate serving_f05.json / metrics.json calibration fields and SHA-256 / class_conf parity."""
    from tastoria.modules.scan.runner import resolve_class_conf

    serving = json.loads(e2e_config.serving_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(e2e_config.onnx_path.read_bytes()).hexdigest()
    assert serving["sha256"] == digest
    if "onnx_bytes" in serving:
        assert int(serving["onnx_bytes"]) == e2e_config.onnx_path.stat().st_size
    if "n_classes" in serving:
        assert int(serving["n_classes"]) == len(onnx_names)

    metrics_path = e2e_config.model_dir / "metrics.json"
    if metrics_path.is_file():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        assert isinstance(metrics, dict) and len(metrics) > 0
        for num_key in ("map50", "mAP50", "map50_95", "mAP50_95", "f1", "f05"):
            if num_key in metrics and metrics[num_key] is not None:
                val = float(metrics[num_key])
                assert np.isfinite(val) and 0.0 <= val <= 1.0

    if e2e_config.serving_f05_path is not None:
        f05 = json.loads(e2e_config.serving_f05_path.read_text(encoding="utf-8"))
        cc = f05.get("class_conf") or {}
        class_map = {i: i for i in range(len(onnx_names))}
        code_by_vid = {i: code for i, code in enumerate(onnx_names)}
        resolved = resolve_class_conf(cc, class_map, code_by_vid) or {}
        assert set(cc) <= set(onnx_names)
        assert any(v < 1.0 for v in resolved.values()) or float(f05["conf"]) < 1.0

    out_shape = onnx_session.get_outputs()[0].shape
    assert tuple(out_shape) == (1, 4 + len(onnx_names), 8400)
