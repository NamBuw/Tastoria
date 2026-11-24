"""Ingest the Tastoria v3 310-class Dish Recognition corpus on host 153 /dev/shm.

Combines 7 curated sources with strict 64-bit DCT pHash deduplication (Hamming <= 4):
  1. ``jeandeanny/vn-food-combined-2026`` (103 Vietnamese dish classes, ~40k images)
  2. ``kng-research/uecfood256`` (256 Asian & home-cooked dish classes, ~31k images)
  3. ``mi_tom`` crops & full frames from ``yolo_v4``
  4. ``ethz/food101`` (101 Global & Asian classes, capped to balance VN/Asian)
  5. ``TuyenTrungLe/vietnamese_food_images`` (25,136 diverse Vietnamese photos across 30 core classes)
  6. ``HoagMin/Vietnamese_StreetFood_Dataset`` (~3,500 street-food photos across 14 VN classes incl. ``com_vong``)
  7. ``Humanbased-AI/MM-Food-100K`` (real camera/homemade/restaurant photos filling everyday home dishes:
     ``trung_xao_ca_chua``, ``thit_kho_tau``, ``ca_hap_xi_dau``, ``dau_phu_xao_rau_cu``,
     ``dau_phu_sot_cay``, ``dau_phu_non``, cooked ``mi_tom``, ``pho``, ``rau_cai_xao``, ``omelette``, etc.)
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import random
import re
import shutil
import urllib.request
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import yaml
from huggingface_hub import HfApi, hf_hub_download
from PIL import Image, ImageOps

from tastoria_ml.calorie.dish_taxonomy import (
    BY_ID,
    CANONICAL_DISHES,
    UEC256_TO_CANONICAL,
    VN103_TO_CANONICAL,
    map_food101_label,
)
from tastoria_ml.cv.phash import hamming, phash

TUYEN_VN_TO_CANONICAL: dict[str, str] = {
    "Banh beo": "banh_beo",
    "Banh bot loc": "banh_bot_loc",
    "Banh can": "banh_can",
    "Banh canh": "banh_canh",
    "Banh chung": "banh_chung",
    "Banh cuon": "banh_cuon",
    "Banh duc": "banh_duc",
    "Banh gio": "banh_gio",
    "Banh khot": "banh_khot",
    "Banh mi": "banh_mi",
    "Banh pia": "banh_pia",
    "Banh tet": "banh_tet",
    "Banh trang nuong": "banh_trang_nuong",
    "Banh xeo": "banh_xeo",
    "Bun bo Hue": "bun_bo_hue",
    "Bun dau mam tom": "bun_dau_mam_tom",
    "Bun mam": "bun_mam",
    "Bun rieu": "bun_rieu",
    "Bun thit nuong": "bun_thit_nuong",
    "Ca kho to": "ca_kho_to",
    "Canh chua": "canh_chua",
    "Cao lau": "cao_lau",
    "Chao long": "chao_long",
    "Com tam": "com_tam",
    "Goi cuon": "goi_cuon",
    "Hu tieu": "hu_tieu",
    "Mi quang": "mi_quang",
    "Nem chua": "nem_chua",
    "Pho": "pho",
    "Xoi xeo": "xoi_xeo",
}

HOAGMIN_VN_TO_CANONICAL: dict[str, str] = {
    "Steamed Rice Rolls": "banh_cuon",
    "Vietnamese pyramid rice dumpling": "banh_gio",
    "Grilled Pork Banh Mi": "banh_mi",
    "Hue-style Spicy Beef Noodle Soup": "bun_bo_hue",
    "Grilled Pork with Vermicelli": "bun_cha",
    "Vermicelli with Tofu": "bun_dau_mam_tom",
    "Grilled Pork Vermicelli": "bun_thit_nuong",
    "Pork Offal Porridge": "chao_long",
    "Flattened green rice": "com_vong",
    "Broken Rice": "com_tam",
    "Fried Rice": "com_rang",
    "Beef Pho": "pho",
    "Spring Rolls": "goi_cuon",
    "Sticky Rice": "xoi_xeo",
}

# Exact / curated pattern mapping from MM-Food-100K dish_name (lowercased) -> canonical dish_id
MMFOOD_EXACT: dict[str, str] = {
    "pho": "pho",
    "beef pho": "pho",
    "chicken pho": "pho",
    "banh mi": "banh_mi",
    "vietnamese banh mi": "banh_mi",
    "spring rolls": "goi_cuon",
    "vietnamese spring rolls": "goi_cuon",
    "shrimp spring rolls": "goi_cuon",
    "fried spring rolls": "cha_gio_ran",
    "instant noodles": "mi_tom",
    "spicy instant noodles": "mi_tom",
    "instant noodle soup": "mi_tom",
    "instant noodles with egg": "mi_tom",
    "beef instant noodles": "mi_tom",
    "spicy beef instant noodles": "mi_tom",
    "instant noodles with sausage": "mi_tom",
    "tomato and egg stir-fry": "trung_xao_ca_chua",
    "scrambled eggs with tomatoes": "trung_xao_ca_chua",
    "tomato scrambled eggs": "trung_xao_ca_chua",
    "tomato and scrambled eggs": "trung_xao_ca_chua",
    "braised pork belly": "thit_kho_tau",
    "braised pork": "thit_kho_tau",
    "braised pork with eggs": "thit_kho_tau",
    "steamed fish": "ca_hap_xi_dau",
    "steamed fish with vegetables": "ca_hap_xi_dau",
    "steamed fish with sauce": "ca_hap_xi_dau",
    "tofu stir-fry": "dau_phu_xao_rau_cu",
    "stir-fried tofu with vegetables": "dau_phu_xao_rau_cu",
    "stir-fried tofu": "dau_phu_xao_rau_cu",
    "mapo tofu": "dau_phu_sot_cay",
    "spicy tofu": "dau_phu_sot_cay",
    "tofu": "dau_phu_non",
    "tofu soup": "canh_dau_phu_thanh_dam",
    "tofu vegetable soup": "canh_dau_phu_thanh_dam",
    "stir-fried greens": "rau_cai_xao",
    "stir-fried cabbage": "rau_cai_xao",
    "stir-fried vegetables": "rau_cu_xao_thap_cam",
    "vegetable stir-fry": "rau_cu_xao_thap_cam",
    "omelet": "omelette",
    "omelette": "omelette",
    "vegetable omelet": "omelette",
    "vegetable omelette": "omelette",
    "shrimp omelette": "omelette",
    "shrimp omelet": "omelette",
    "fried rice": "com_rang",
    "egg fried rice": "com_rang",
    "dumplings": "dumplings",
    "pan-fried dumplings": "gyoza",
    "hot pot": "lau_thap_cam",
    "fried chicken": "ga_chien_nuoc_mam",
    "fried chicken wings": "chicken_wings",
    "chicken curry": "chicken_curry",
    "ramen": "ramen",
    "sushi": "sushi",
    "bibimbap": "bibimbap",
    "pizza": "pizza",
    "hamburger": "hamburger",
    "french fries": "french_fries",
    "pancakes": "pancakes",
    "waffles": "waffles",
    "steak": "steak",
    "grilled salmon": "grilled_salmon",
    "caesar salad": "caesar_salad",
}


def _img_phash(rgb_im: Image.Image) -> int:
    gray = rgb_im.convert("L")
    gray.thumbnail((256, 256))
    return int(phash(np.asarray(gray)))


def _decode_exif_rgb(data: bytes | Image.Image, max_side: int = 384) -> Image.Image:
    im = data if isinstance(data, Image.Image) else Image.open(io.BytesIO(data))
    im.load()
    im = ImageOps.exif_transpose(im).convert("RGB")
    if max(im.size) > max_side:
        im.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
    return Image.frombytes("RGB", im.size, im.tobytes())


def _extract_parquet_bytes(cell) -> bytes:
    if isinstance(cell, dict):
        if cell.get("bytes"):
            return cell["bytes"]
        if cell.get("path") and Path(cell["path"]).is_file():
            return Path(cell["path"]).read_bytes()
    if isinstance(cell, (bytes, bytearray)):
        return bytes(cell)
    raise ValueError(f"Unsupported image cell: {type(cell)}")


def _download_image_bytes(url: str, timeout: int = 8) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 TastoriaResearch/3.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(4_000_000)
            return raw if len(raw) > 1000 else None
    except Exception:
        return None


def _resolve_vn103_dir(hint: Path) -> Path:
    api = HfApi()
    info = api.dataset_info("jeandeanny/vn-food-combined-2026")
    pq_sibs = [s.rfilename for s in info.siblings if s.rfilename.endswith(".parquet")]
    if hint.is_dir() and len(list(hint.rglob("*.parquet"))) >= len(pq_sibs):
        return hint
    snaps = sorted((Path.home() / ".cache/huggingface/hub/datasets--jeandeanny--vn-food-combined-2026/snapshots").glob("*"))
    if snaps and len(list(snaps[0].rglob("*.parquet"))) >= len(pq_sibs):
        return snaps[0]
    for rf in pq_sibs:
        hf_hub_download("jeandeanny/vn-food-combined-2026", rf, repo_type="dataset")
    return sorted((Path.home() / ".cache/huggingface/hub/datasets--jeandeanny--vn-food-combined-2026/snapshots").glob("*"))[-1]


def _resolve_uec256_zip(hint: Path) -> Path:
    if hint.is_file():
        return hint
    snaps = list((Path.home() / ".cache/huggingface/hub/datasets--kng-research--uecfood256/snapshots").glob("*/dataset256.zip"))
    if snaps:
        return snaps[0]
    return Path(hf_hub_download("kng-research/uecfood256", "dataset256.zip", repo_type="dataset"))


def run_ingest(
    work_dir: Path,
    vn103_dir: Path,
    uec256_zip: Path,
    yolo_v4_dir: Path,
    exclude_dir: Path | None = None,
    max_side: int = 384,
    max_food101_train_per_cls: int = 550,
    max_mmfood_per_cls: int = 400,
    seed: int = 0,
) -> dict:
    work_dir = Path(work_dir)
    img_root = work_dir / "images"
    dl_dir = work_dir / "_dl"
    dl_dir.mkdir(parents=True, exist_ok=True)
    for sp in ("train", "val"):
        for d in CANONICAL_DISHES:
            (img_root / sp / d.dish_id).mkdir(parents=True, exist_ok=True)

    excluded_hashes: list[int] = []
    if exclude_dir and exclude_dir.exists():
        for p in sorted(exclude_dir.iterdir()):
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                with Image.open(p) as im:
                    excluded_hashes.append(_img_phash(im.convert("RGB")))

    counts: dict[str, Counter] = {"train": Counter(), "val": Counter()}
    val_hashes: list[int] = list(excluded_hashes)
    val_hash_arr: np.ndarray | None = None
    seen_train_hashes: set[int] = set()
    dropped_dupes = 0

    def _refresh_val_arr() -> None:
        nonlocal val_hash_arr
        val_hash_arr = np.asarray(val_hashes, dtype=np.uint64) if val_hashes else None

    _refresh_val_arr()

    def _save_sample(split: str, cid: str, src_tag: str, idx: int, rgb: Image.Image) -> bool:
        nonlocal dropped_dupes
        if cid not in BY_ID:
            return False
        h = _img_phash(rgb)
        if split == "val":
            if excluded_hashes and int(hamming(np.asarray(excluded_hashes, dtype=np.uint64), h).min()) <= 4:
                dropped_dupes += 1
                return False
            if val_hash_arr is not None and val_hash_arr.size > 0 and int(hamming(val_hash_arr, h).min()) <= 2:
                dropped_dupes += 1
                return False
            val_hashes.append(h)
            if len(val_hashes) % 500 == 0:
                _refresh_val_arr()
        else:
            if h in seen_train_hashes:
                dropped_dupes += 1
                return False
            if val_hash_arr is not None and val_hash_arr.size > 0 and int(hamming(val_hash_arr, h).min()) <= 4:
                dropped_dupes += 1
                return False
            seen_train_hashes.add(h)
        out = img_root / split / cid / f"{src_tag}_{idx:06d}.jpg"
        rgb.save(out, "JPEG", quality=88)
        counts[split][cid] += 1
        return True

    # ---- STAGE A: Collect ALL VAL samples first so val_hash_arr blocks train leaks cleanly ----
    rng = random.Random(seed)

    # 1. VNFood-103
    print("[1/7] VNFood-103...", flush=True)
    vn_dir = _resolve_vn103_dir(vn103_dir)
    pfiles = sorted(vn_dir.rglob("*.parquet"))
    schema = pq.read_schema(pfiles[0])
    vn103_names = json.loads(schema.metadata[b"huggingface"].decode())["info"]["features"]["label"]["names"]
    vn103_map = [VN103_TO_CANONICAL[n] for n in vn103_names]
    vn_val_files = [p for p in pfiles if "validation-" in p.name]
    vn_tr_files = [p for p in pfiles if "train-" in p.name or "test-" in p.name]
    g_idx = 0
    for lp in vn_val_files:
        for batch in pq.ParquetFile(lp).iter_batches(batch_size=256, columns=["image", "label"]):
            for cell, li in zip(batch.column("image").to_pylist(), batch.column("label").to_pylist()):
                try:
                    _save_sample("val", vn103_map[int(li)], "vn103", g_idx, _decode_exif_rgb(_extract_parquet_bytes(cell), max_side))
                except Exception:
                    pass
                g_idx += 1

    # 2. TuyenTrungLe/vietnamese_food_images (validation -> val, train+test -> train)
    print("[2/7] TuyenTrungLe/vietnamese_food_images...", flush=True)
    tuyen_info = HfApi().dataset_info("TuyenTrungLe/vietnamese_food_images")
    tuyen_pqs = sorted(s.rfilename for s in tuyen_info.siblings if s.rfilename.endswith(".parquet"))
    tuyen_val_pqs = [f for f in tuyen_pqs if "validation-" in f or "test-" in f][:4]
    tuyen_tr_pqs = [f for f in tuyen_pqs if f not in tuyen_val_pqs]
    with urllib.request.urlopen("https://datasets-server.huggingface.co/info?dataset=TuyenTrungLe/vietnamese_food_images", timeout=15) as r:
        tuyen_names = next(iter(json.loads(r.read().decode())["dataset_info"].values()))["features"]["label"]["names"]
    tuyen_map = [TUYEN_VN_TO_CANONICAL.get(n) for n in tuyen_names]
    t_idx = 0
    tuyen_val_local = []
    for rf in tuyen_val_pqs:
        lp = Path(hf_hub_download("TuyenTrungLe/vietnamese_food_images", rf, repo_type="dataset", local_dir=str(dl_dir / "tuyen")))
        tuyen_val_local.append(lp)
        # Put official validation split into val, test into train
        sp = "val" if "validation-" in rf else "train"
        if sp == "val":
            for batch in pq.ParquetFile(lp).iter_batches(batch_size=256, columns=["image", "label"]):
                for cell, li in zip(batch.column("image").to_pylist(), batch.column("label").to_pylist()):
                    cid = tuyen_map[int(li)]
                    if cid:
                        try:
                            _save_sample("val", cid, "tuyen", t_idx, _decode_exif_rgb(_extract_parquet_bytes(cell), max_side))
                        except Exception:
                            pass
                    t_idx += 1

    # 3. HoagMin/Vietnamese_StreetFood_Dataset (val split -> val, train+test -> train)
    print("[3/7] HoagMin/Vietnamese_StreetFood_Dataset...", flush=True)
    hoag_zip = Path(hf_hub_download("HoagMin/Vietnamese_StreetFood_Dataset", "Vietnamese_StreetFood_14Class.zip", repo_type="dataset"))
    hoag_tr_items: list[tuple[str, str]] = []
    h_idx = 0
    with zipfile.ZipFile(hoag_zip) as zf:
        dy = yaml.safe_load(zf.read("data.yaml").decode("utf-8"))
        h_names = dy["names"]
        for split_prefix, target_sp in (("valid/images/", "val"), ("train/images/", "train"), ("test/images/", "train")):
            for nm in sorted(zf.namelist()):
                if not nm.startswith(split_prefix) or not nm.lower().endswith((".jpg", ".jpeg", ".png")):
                    continue
                lbl_nm = nm.replace("/images/", "/labels/").rsplit(".", 1)[0] + ".txt"
                if lbl_nm not in zf.namelist():
                    continue
                cls_ids = {int(float(ln.split()[0])) for ln in zf.read(lbl_nm).decode().splitlines() if ln.strip()}
                if len(cls_ids) != 1:
                    continue
                cid = HOAGMIN_VN_TO_CANONICAL.get(h_names[next(iter(cls_ids))])
                if not cid:
                    continue
                if target_sp == "val":
                    try:
                        _save_sample("val", cid, "hoag", h_idx, _decode_exif_rgb(zf.read(nm), max_side))
                    except Exception:
                        pass
                    h_idx += 1
                else:
                    hoag_tr_items.append((nm, cid))

    # 4. Prepare UEC256 split list & extract UEC val
    print("[4/7] UECFood-256 val...", flush=True)
    uec_zip_path = _resolve_uec256_zip(uec256_zip)
    uec_tr_items: list[tuple[str, int, str]] = []
    with zipfile.ZipFile(uec_zip_path) as zf:
        by_cat: dict[int, list[str]] = defaultdict(list)
        for nm in sorted(zf.namelist()):
            if not nm.lower().endswith((".jpg", ".jpeg", ".png")):
                continue
            for part in Path(nm).parts[:-1]:
                if part.isdigit() and int(part) in UEC256_TO_CANONICAL:
                    by_cat[int(part)].append(nm)
                    break
        u_idx = 0
        for cat_id, nms in sorted(by_cat.items()):
            shuf = list(nms)
            rng.shuffle(shuf)
            n_val = max(2, int(round(len(shuf) * 0.15)))
            cid = UEC256_TO_CANONICAL[cat_id]
            for i, zname in enumerate(shuf):
                if i < n_val:
                    try:
                        _save_sample("val", cid, f"uec{cat_id}", u_idx, _decode_exif_rgb(zf.read(zname), max_side))
                    except Exception:
                        pass
                    u_idx += 1
                else:
                    uec_tr_items.append((zname, cat_id, cid))

    # 5. Food101 val
    print("[5/7] Food101 val...", flush=True)
    f_info = HfApi().dataset_info("ethz/food101")
    f_files = sorted(s.rfilename for s in f_info.siblings if s.rfilename.endswith(".parquet"))
    with urllib.request.urlopen("https://datasets-server.huggingface.co/info?dataset=ethz/food101", timeout=15) as r:
        f_names = next(iter(json.loads(r.read().decode())["dataset_info"].values()))["features"]["label"]["names"]
    f_label_map = [map_food101_label(n) for n in f_names]
    f101_counts: dict[str, Counter] = {"train": Counter(), "val": Counter()}
    f_idx = 0
    for rf in [f for f in f_files if "validation" in f]:
        lp = Path(hf_hub_download("ethz/food101", rf, repo_type="dataset", local_dir=str(dl_dir / "food101")))
        for batch in pq.ParquetFile(lp).iter_batches(batch_size=256, columns=["image", "label"]):
            for cell, li in zip(batch.column("image").to_pylist(), batch.column("label").to_pylist()):
                cid = f_label_map[int(li)]
                if cid in BY_ID and f101_counts["val"][cid] < 200:
                    try:
                        if _save_sample("val", cid, "f101", f_idx, _decode_exif_rgb(_extract_parquet_bytes(cell), max_side)):
                            f101_counts["val"][cid] += 1
                    except Exception:
                        pass
                f_idx += 1
        lp.unlink(missing_ok=True)

    # 6. MM-Food-100K (sample curated home-cooked/asian/mi_tom classes & download concurrently!)
    print("[6/7] MM-Food-100K real phone/home dishes...", flush=True)
    mm_csv = next((Path.home() / ".cache/huggingface/hub/datasets--Humanbased-AI--MM-Food-100K/snapshots").glob("*/MM-Food-100K.csv"))
    mm_by_cls: dict[str, list[str]] = defaultdict(list)
    with mm_csv.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                if float(row.get("food_prob") or 0) < 0.85:
                    continue
            except Exception:
                continue
            dn = (row.get("dish_name") or "").strip().lower()
            cid = MMFOOD_EXACT.get(dn)
            if cid is None:
                if ("tomato" in dn and "egg" in dn) or "tomato scrambled egg" in dn:
                    cid = "trung_xao_ca_chua"
                elif "braised pork" in dn and "noodle" not in dn:
                    cid = "thit_kho_tau"
                elif "steamed fish" in dn:
                    cid = "ca_hap_xi_dau"
                elif "braised fish" in dn or "caramelized fish" in dn:
                    cid = "ca_kho_to"
                elif "instant noodle" in dn:
                    cid = "mi_tom"
                elif "water spinach" in dn or "morning glory" in dn:
                    cid = "rau_muong_xao"
                elif "bok choy" in dn or "stir-fried spinach" in dn:
                    cid = "rau_cai_xao"
                elif ("shrimp" in dn and ("vegetable" in dn or "cabbage" in dn)) or dn == "stir-fried shrimp with vegetables":
                    cid = "rau_cu_xao_thap_cam"
                elif any(t in dn for t in ("soft tofu", "steamed tofu", "cold tofu", "silken tofu")) or dn in ("braised tofu", "tofu"):
                    cid = "dau_phu_non"
                elif dn in ("fried egg", "fried eggs"):
                    cid = "trung_op_la"
            if cid and cid in BY_ID and row.get("image_url"):
                mm_by_cls[cid].append(row["image_url"])

    mm_tasks: list[tuple[str, str, str]] = []
    for cid, urls in sorted(mm_by_cls.items()):
        rng.shuffle(urls)
        cap = max_mmfood_per_cls + 60
        selected = urls[:cap]
        n_val = max(4, int(round(len(selected) * 0.14)))
        for i, u in enumerate(selected):
            mm_tasks.append(("val" if i < n_val else "train", cid, u))

    print(f"  MM-Food-100K downloading {len(mm_tasks)} curated real-photo URLs across {len(mm_by_cls)} classes...", flush=True)
    mm_val_blobs: list[tuple[str, bytes]] = []
    mm_tr_blobs: list[tuple[str, bytes]] = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        fut_map = {ex.submit(_download_image_bytes, u): (sp, cid) for sp, cid, u in mm_tasks}
        for fut in as_completed(fut_map):
            sp, cid = fut_map[fut]
            raw = fut.result()
            if raw:
                (mm_val_blobs if sp == "val" else mm_tr_blobs).append((cid, raw))
    mm_idx = 0
    for cid, raw in mm_val_blobs:
        try:
            _save_sample("val", cid, "mm", mm_idx, _decode_exif_rgb(raw, max_side))
        except Exception:
            pass
        mm_idx += 1

    # 7. mi_tom val from yolo_v4
    if (yolo_v4_dir / "dataset.yaml").is_file():
        ds = yaml.safe_load((yolo_v4_dir / "dataset.yaml").read_text(encoding="utf-8"))
        rn = ds["names"]
        nm_map = {int(k): v for k, v in rn.items()} if isinstance(rn, dict) else dict(enumerate(rn))
        mt_id = next((k for k, v in nm_map.items() if v == "mi_tom"), None)
    else:
        mt_id = None

    m_idx = 0
    def _extract_mitom(sp: str) -> None:
        nonlocal m_idx
        if mt_id is None:
            return
        for lbl in sorted((yolo_v4_dir / "labels" / sp).glob("*.txt")):
            lines = [ln.strip().split() for ln in lbl.read_text(encoding="utf-8").splitlines() if ln.strip()]
            mt_boxes = [ln for ln in lines if int(float(ln[0])) == mt_id]
            if not mt_boxes:
                continue
            ip = yolo_v4_dir / "images" / sp / f"{lbl.stem}.jpg"
            if not ip.is_file():
                continue
            with Image.open(ip) as im:
                rgb = ImageOps.exif_transpose(im).convert("RGB")
                W, H = rgb.size
                rc = rgb.copy()
                rc.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
                _save_sample(sp, "mi_tom", "mtw", m_idx, rc)
                m_idx += 1
                for toks in mt_boxes[:2]:
                    xc, yc, bw, bh = (float(x) for x in toks[1:5])
                    x1, y1 = max(0, int((xc - bw * 0.65) * W)), max(0, int((yc - bh * 0.65) * H))
                    x2, y2 = min(W, int((xc + bw * 0.65) * W)), min(H, int((yc + bh * 0.65) * H))
                    if x2 - x1 >= 32 and y2 - y1 >= 32:
                        crop = rgb.crop((x1, y1, x2, y2))
                        crop.thumbnail((max_side, max_side), Image.Resampling.BILINEAR)
                        _save_sample(sp, "mi_tom", "mtc", m_idx, crop)
                        m_idx += 1

    _extract_mitom("val")

    # ---- STAGE B: Freeze ALL VAL hashes, then ingest ALL TRAIN sources with zero leakage ----
    _refresh_val_arr()
    print(f"[VAL COMPLETE] val={sum(counts['val'].values())} across {sum(1 for c in counts['val'].values() if c > 0)}/310 classes", flush=True)

    # Train: VN103
    for lp in vn_tr_files:
        for batch in pq.ParquetFile(lp).iter_batches(batch_size=256, columns=["image", "label"]):
            for cell, li in zip(batch.column("image").to_pylist(), batch.column("label").to_pylist()):
                try:
                    _save_sample("train", vn103_map[int(li)], "vn103", g_idx, _decode_exif_rgb(_extract_parquet_bytes(cell), max_side))
                except Exception:
                    pass
                g_idx += 1

    # Train: TuyenTrungLe (test + train shards)
    for lp in tuyen_val_local:
        if "test-" in lp.name:
            for batch in pq.ParquetFile(lp).iter_batches(batch_size=256, columns=["image", "label"]):
                for cell, li in zip(batch.column("image").to_pylist(), batch.column("label").to_pylist()):
                    cid = tuyen_map[int(li)]
                    if cid:
                        try:
                            _save_sample("train", cid, "tuyen", t_idx, _decode_exif_rgb(_extract_parquet_bytes(cell), max_side))
                        except Exception:
                            pass
                    t_idx += 1
        lp.unlink(missing_ok=True)
    for rf in tuyen_tr_pqs:
        lp = Path(hf_hub_download("TuyenTrungLe/vietnamese_food_images", rf, repo_type="dataset", local_dir=str(dl_dir / "tuyen")))
        for batch in pq.ParquetFile(lp).iter_batches(batch_size=256, columns=["image", "label"]):
            for cell, li in zip(batch.column("image").to_pylist(), batch.column("label").to_pylist()):
                cid = tuyen_map[int(li)]
                if cid:
                    try:
                        _save_sample("train", cid, "tuyen", t_idx, _decode_exif_rgb(_extract_parquet_bytes(cell), max_side))
                    except Exception:
                        pass
                t_idx += 1
        lp.unlink(missing_ok=True)

    # Train: HoagMin
    with zipfile.ZipFile(hoag_zip) as zf:
        for nm, cid in hoag_tr_items:
            try:
                _save_sample("train", cid, "hoag", h_idx, _decode_exif_rgb(zf.read(nm), max_side))
            except Exception:
                pass
            h_idx += 1

    # Train: UEC256
    with zipfile.ZipFile(uec_zip_path) as zf:
        for zname, cat_id, cid in uec_tr_items:
            try:
                _save_sample("train", cid, f"uec{cat_id}", u_idx, _decode_exif_rgb(zf.read(zname), max_side))
            except Exception:
                pass
            u_idx += 1

    # Train: MM-Food-100K
    mm_cls_tr = Counter()
    for cid, raw in mm_tr_blobs:
        if mm_cls_tr[cid] >= max_mmfood_per_cls:
            continue
        try:
            if _save_sample("train", cid, "mm", mm_idx, _decode_exif_rgb(raw, max_side)):
                mm_cls_tr[cid] += 1
        except Exception:
            pass
        mm_idx += 1

    # Train: mi_tom
    _extract_mitom("train")

    # Train: Food101
    for rf in [f for f in f_files if "validation" not in f]:
        lp = Path(hf_hub_download("ethz/food101", rf, repo_type="dataset", local_dir=str(dl_dir / "food101")))
        for batch in pq.ParquetFile(lp).iter_batches(batch_size=256, columns=["image", "label"]):
            for cell, li in zip(batch.column("image").to_pylist(), batch.column("label").to_pylist()):
                cid = f_label_map[int(li)]
                if cid in BY_ID and f101_counts["train"][cid] < max_food101_train_per_cls:
                    try:
                        if _save_sample("train", cid, "f101", f_idx, _decode_exif_rgb(_extract_parquet_bytes(cell), max_side)):
                            f101_counts["train"][cid] += 1
                    except Exception:
                        pass
                f_idx += 1
        lp.unlink(missing_ok=True)

    shutil.rmtree(dl_dir, ignore_errors=True)
    summary = {
        "n_classes": len(CANONICAL_DISHES),
        "total_train": int(sum(counts["train"].values())),
        "total_val": int(sum(counts["val"].values())),
        "dropped_dupes": dropped_dupes,
        "mmfood_train_added": int(sum(mm_cls_tr.values())),
        "empty_train_classes": [d.dish_id for d in CANONICAL_DISHES if counts["train"][d.dish_id] == 0],
        "empty_val_classes": [d.dish_id for d in CANONICAL_DISHES if counts["val"][d.dish_id] == 0],
    }
    (work_dir / "ingest_v3_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def backfill_vn103(work_dir: Path, vn103_dir: Path, exclude_dir: Path | None = None, max_side: int = 384) -> dict:
    """Backfill all 12 VNFood-103 parquet shards into an existing stage dir without duplicates."""
    work_dir = Path(work_dir)
    img_root = work_dir / "images"
    vn_dir = _resolve_vn103_dir(vn103_dir)
    pfiles = sorted(vn_dir.rglob("*.parquet"))
    schema = pq.read_schema(pfiles[0])
    vn103_names = json.loads(schema.metadata[b"huggingface"].decode())["info"]["features"]["label"]["names"]
    vn103_map = [VN103_TO_CANONICAL[n] for n in vn103_names]

    ex_hashes: list[int] = []
    if exclude_dir and exclude_dir.exists():
        for p in sorted(exclude_dir.iterdir()):
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                with Image.open(p) as im:
                    ex_hashes.append(_img_phash(im.convert("RGB")))
    ex_arr = np.asarray(ex_hashes, dtype=np.uint64) if ex_hashes else None

    val_hashes: list[int] = list(ex_hashes)
    seen_train: set[int] = set()
    for p in (img_root / "val").rglob("*.jpg"):
        with Image.open(p) as im:
            val_hashes.append(_img_phash(im))
    val_arr = np.asarray(val_hashes, dtype=np.uint64) if val_hashes else None

    for p in (img_root / "train").rglob("*.jpg"):
        with Image.open(p) as im:
            seen_train.add(_img_phash(im))

    added = {"val": 0, "train": 0}
    dupes = 0
    g_idx = 0
    val_pqs = [p for p in pfiles if "validation-" in p.name]
    tr_pqs = [p for p in pfiles if "train-" in p.name or "test-" in p.name]

    for lp in val_pqs:
        for batch in pq.ParquetFile(lp).iter_batches(batch_size=256, columns=["image", "label"]):
            for cell, li in zip(batch.column("image").to_pylist(), batch.column("label").to_pylist()):
                cid = vn103_map[int(li)]
                try:
                    rgb = _decode_exif_rgb(_extract_parquet_bytes(cell), max_side)
                    h = _img_phash(rgb)
                    if ex_arr is not None and ex_arr.size > 0 and int(hamming(ex_arr, h).min()) <= 4:
                        dupes += 1
                    elif val_arr is not None and val_arr.size > 0 and int(hamming(val_arr, h).min()) <= 2:
                        dupes += 1
                    else:
                        rgb.save(img_root / "val" / cid / f"vn103b_{g_idx:06d}.jpg", "JPEG", quality=88)
                        val_hashes.append(h)
                        if len(val_hashes) % 500 == 0:
                            val_arr = np.asarray(val_hashes, dtype=np.uint64)
                        added["val"] += 1
                except Exception:
                    pass
                g_idx += 1

    val_arr = np.asarray(val_hashes, dtype=np.uint64) if val_hashes else None
    for lp in tr_pqs:
        for batch in pq.ParquetFile(lp).iter_batches(batch_size=256, columns=["image", "label"]):
            for cell, li in zip(batch.column("image").to_pylist(), batch.column("label").to_pylist()):
                cid = vn103_map[int(li)]
                try:
                    rgb = _decode_exif_rgb(_extract_parquet_bytes(cell), max_side)
                    h = _img_phash(rgb)
                    if h in seen_train or (val_arr is not None and val_arr.size > 0 and int(hamming(val_arr, h).min()) <= 4):
                        dupes += 1
                    else:
                        rgb.save(img_root / "train" / cid / f"vn103b_{g_idx:06d}.jpg", "JPEG", quality=88)
                        seen_train.add(h)
                        added["train"] += 1
                except Exception:
                    pass
                g_idx += 1

    tr_counts = {d.dish_id: sum(1 for _ in (img_root / "train" / d.dish_id).glob("*.jpg")) for d in CANONICAL_DISHES}
    va_counts = {d.dish_id: sum(1 for _ in (img_root / "val" / d.dish_id).glob("*.jpg")) for d in CANONICAL_DISHES}
    summary = {
        "n_classes": len(CANONICAL_DISHES),
        "total_train": sum(tr_counts.values()),
        "total_val": sum(va_counts.values()),
        "backfill_added": added,
        "backfill_dupes": dupes,
        "empty_train_classes": [k for k, v in tr_counts.items() if v == 0],
        "empty_val_classes": [k for k, v in va_counts.items() if v == 0],
    }
    (work_dir / "ingest_v3_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", type=Path, default=Path("/dev/shm/dish_v3_stage"))
    ap.add_argument("--vn103-dir", type=Path, default=Path("/dev/shm/hf_vn103"))
    ap.add_argument("--uec256-zip", type=Path, default=Path("/dev/shm/hf_uec256/dataset256.zip"))
    ap.add_argument("--yolo-v4-dir", type=Path, default=Path("/home/namnx/NamBuw/Tastoria/data/processed/cv/yolo_v4"))
    ap.add_argument("--exclude-dir", type=Path, default=Path("/home/namnx/NamBuw/Tastoria/app/assets/food"))
    ap.add_argument("--max-food101-train", type=int, default=550)
    ap.add_argument("--max-mmfood-per-cls", type=int, default=600)
    ap.add_argument("--backfill-vn103", action="store_true")
    args = ap.parse_args()
    if args.backfill_vn103:
        backfill_vn103(args.work_dir, args.vn103_dir, args.exclude_dir)
        return
    run_ingest(
        work_dir=args.work_dir,
        vn103_dir=args.vn103_dir,
        uec256_zip=args.uec256_zip,
        yolo_v4_dir=args.yolo_v4_dir,
        exclude_dir=args.exclude_dir,
        max_food101_train_per_cls=args.max_food101_train,
        max_mmfood_per_cls=args.max_mmfood_per_cls,
    )


if __name__ == "__main__":
    main()
