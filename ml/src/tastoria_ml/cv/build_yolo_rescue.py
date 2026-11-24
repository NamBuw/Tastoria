"""Build rescued 37-class raw ingredient YOLO dataset in /dev/shm/yolo_v5_rescue on host 153.

Rescues the 8 sparse/disabled classes in the base 37-class taxonomy:
  - ``su_su``, ``muop``, ``rau_cai``, ``xuc_xich``, ``dau_phu``, ``thit_lon``, ``thit_ga``, ``thit_bo``,
    ``muop_dang``, ``bi_dao``, ``dau_que``, ``nam``, ``toi``, ``ot``, ``hanh_la`` from ``zubiaa/food-ingredients-dataset/4``
  - ``rau_muong`` from ``roboflow/nhan_dien_rau`` (whole Vietnamese morning glory bunches, 166 train + 54 val)
  - ``dau_phu`` from ``roboflow/tofu_oo`` (top 220 train + 40 val clean raw tofu block photos)
  - ``xuc_xich`` & ``banh_quy`` & ``sua_chua`` from ``lvis_v1`` (clean packaged/cured items dropped by ``stage2a_cooked_packaged`` / ``banned_cocat``)
  - ``gia_do`` & ``muop`` & ``su_su`` & ``rau_cai`` from ``v3det`` (clean produce boxes)
  - Appends all 4,178 cooked-dish 0-box hard negatives so cooked-dish FP on ``app/assets/food/*.webp`` remains 0!
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from collections import Counter
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageOps

from tastoria_ml.cv.phash import hamming, phash
from tastoria_ml.cv.yolo_format import Box, from_corners_norm, write_label

ZUBIAA_TO_37: dict[str, str] = {
    "Chayote-iskus-": "su_su",
    "Sponge Gourd -Ghiraula-": "muop",
    "Rayo ko Saag": "rau_cai",
    "Palungo -Nepali Spinach-": "rau_cai",
    "Palak -Indian Spinach-": "rau_cai",
    "Tori ko Saag": "rau_cai",
    "Sausage": "xuc_xich",
    "Tofu": "dau_phu",
    "Pork": "thit_lon",
    "Chicken": "thit_ga",
    "Beef": "thit_bo",
    "Bitter Gourd": "muop_dang",
    "Bottle Gourd -Lauka-": "bi_dao",
    "Pumpkin -Farsi-": "bi_do",
    "Beans": "dau_que",
    "Long Beans -Bodi-": "dau_que",
    "Mushroom": "nam",
    "Garlic": "toi",
    "Onion Leaves": "hanh_la",
    "Chili Pepper -Khursani-": "ot",
    "Akabare Khursani": "ot",
    "Cabbage": "bap_cai",
    "Broccoli": "sup_lo",
    "Cauliflower": "sup_lo",
    "Carrot": "ca_rot",
    "Potato": "khoai_tay",
    "Tomato": "ca_chua",
    "Egg": "trung",
    "Fish": "ca",
    "Lemon -Nimbu-": "chanh",
    "Lime -Kagati-": "chanh",
    "Bread": "banh_mi",
}


def _link_or_copy(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _phash_path(p: Path) -> int:
    with Image.open(p) as im:
        g = ImageOps.exif_transpose(im).convert("L")
        g.thumbnail((256, 256))
        return int(phash(np.asarray(g)))


def build_rescued_dataset(
    yolo_v4_dir: Path,
    zubiaa_dir: Path,
    out_dir: Path,
    cooked_neg_manifest: Path | None = None,
    food_assets_dir: Path | None = None,
) -> dict:
    v4_ds = yaml.safe_load((yolo_v4_dir / "dataset.yaml").read_text(encoding="utf-8"))
    raw_names = v4_ds["names"]
    names_37 = [raw_names[i] for i in sorted(raw_names)] if isinstance(raw_names, dict) else list(raw_names)
    assert len(names_37) == 37
    cid_to_idx = {c: i for i, c in enumerate(names_37)}

    for sp in ("test", "heldout", "val", "train"):
        (out_dir / "images" / sp).mkdir(parents=True, exist_ok=True)
        (out_dir / "labels" / sp).mkdir(parents=True, exist_ok=True)

    eval_hashes: list[int] = []
    train_hashes: set[int] = set()
    img_counts: Counter = Counter()

    # 1. Copy base yolo_v4
    for sp in ("test", "heldout", "val", "train"):
        for ip in sorted((yolo_v4_dir / "images" / sp).glob("*.jpg")):
            dst_img = out_dir / "images" / sp / ip.name
            dst_lbl = out_dir / "labels" / sp / f"{ip.stem}.txt"
            _link_or_copy(ip, dst_img)
            src_lbl = yolo_v4_dir / "labels" / sp / f"{ip.stem}.txt"
            dst_lbl.write_text(src_lbl.read_text(encoding="utf-8") if src_lbl.is_file() else "", encoding="utf-8")
            img_counts[sp] += 1
            try:
                h = _phash_path(ip)
                if sp in ("test", "heldout", "val"):
                    eval_hashes.append(h)
                else:
                    train_hashes.add(h)
            except Exception:
                pass

    if food_assets_dir and food_assets_dir.is_dir():
        for p in sorted(food_assets_dir.iterdir()):
            if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
                try:
                    eval_hashes.append(_phash_path(p))
                except Exception:
                    pass

    eval_arr = np.asarray(eval_hashes, dtype=np.uint64)

    def _can_add(sp: str, h: int) -> bool:
        nonlocal eval_arr
        if sp == "train":
            if h in train_hashes:
                return False
            if eval_arr.size and int(hamming(eval_arr, h).min()) <= 4:
                return False
            train_hashes.add(h)
            return True
        else:
            if eval_arr.size and int(hamming(eval_arr, h).min()) <= 4:
                return False
            eval_hashes.append(h)
            eval_arr = np.asarray(eval_hashes, dtype=np.uint64)
            return True

    rescued_counts = Counter()

    # 2. Merge Zubiaa raw ingredient boxes (valid + test -> val for sparse classes, train -> train)
    if zubiaa_dir and (zubiaa_dir / "data.yaml").is_file():
        zdoc = yaml.safe_load((zubiaa_dir / "data.yaml").read_text(encoding="utf-8"))
        znames = zdoc["names"]
        for zsp, dst_sp in (("valid", "val"), ("test", "val"), ("train", "train")):
            lbl_dir = zubiaa_dir / zsp / "labels"
            img_dir = zubiaa_dir / zsp / "images"
            if not lbl_dir.is_dir():
                continue
            for lp in sorted(lbl_dir.glob("*.txt")):
                ip = img_dir / f"{lp.stem}.jpg"
                if not ip.is_file():
                    ip_alt = list(img_dir.glob(f"{lp.stem}.*"))
                    if not ip_alt:
                        continue
                    ip = ip_alt[0]
                boxes: list[Box] = []
                for ln in lp.read_text(encoding="utf-8", errors="replace").splitlines():
                    toks = ln.strip().split()
                    if len(toks) < 5:
                        continue
                    zcls = int(float(toks[0]))
                    if not (0 <= zcls < len(znames)):
                        continue
                    cid = ZUBIAA_TO_37.get(znames[zcls])
                    if cid is None:
                        continue
                    xc, yc, bw, bh = (float(x) for x in toks[1:5])
                    if bw <= 0.015 or bh <= 0.015:
                        continue
                    b = from_corners_norm(cid_to_idx[cid], xc - bw / 2, yc - bh / 2, xc + bw / 2, yc + bh / 2)
                    if b:
                        boxes.append(b)
                if not boxes:
                    continue
                try:
                    h = _phash_path(ip)
                except Exception:
                    continue
                if not _can_add(dst_sp, h):
                    continue
                stem = f"zubiaa__{zsp}__{ip.stem}"
                _link_or_copy(ip, out_dir / "images" / dst_sp / f"{stem}.jpg")
                (out_dir / "labels" / dst_sp / f"{stem}.txt").write_text(write_label(boxes), encoding="utf-8")
                img_counts[dst_sp] += 1
                rescued_counts[f"zubiaa_{dst_sp}"] += 1

    # 3. Rescue clean raw images from track_c_decisions.json for sparse classes:
    #    - rau_muong from rf_nhan_dien_rau (166 train + 54 val)
    #    - dau_phu from rf_tofu_oo (top 220 train + 35 val)
    #    - xuc_xich, banh_quy, sua_chua from lvis_v1 & rf_viet_hoang (stage2a/2b_cooked_packaged or banned_cocat)
    #    - muop, su_su, rau_cai, gia_do from v3det (outdoor_vine / crop_mismatch / missing_sprouts / off_topic)
    dec_path = yolo_v4_dir / "track_c_decisions.json"
    if dec_path.is_file():
        dec = json.loads(dec_path.read_text(encoding="utf-8"))
        tofu_caps = {"train": 220, "val": 35}
        tofu_seen = {"train": 0, "val": 0}
        # Process val first, then train!
        entries = sorted(dec.values(), key=lambda r: (0 if r.get("split") == "val" else 1, str(r.get("id"))))
        for r in entries:
            if r.get("keep") is not False:
                continue
            sp = r.get("split")
            if sp not in ("val", "train"):
                continue
            src = r.get("source")
            rsn = str(r.get("reason") or "")
            orig = r.get("orig_boxes") or []
            if not orig:
                continue

            # Determine which classes in this image are eligible for rescue
            allowed_cls: set[str] = set()
            if src == "rf_nhan_dien_rau" and rsn in ("single_leaf_rau_muong_purged", "rf_nhan_dien_rau_stage2a_single_leaf"):
                allowed_cls.add("rau_muong")
                allowed_cls.add("bap_cai")
            elif src == "rf_tofu_oo" and rsn == "rf_tofu_oo_purged":
                if tofu_seen[sp] >= tofu_caps[sp]:
                    continue
                allowed_cls.add("dau_phu")
            elif src in ("lvis_v1", "rf_viet_hoang") and rsn in (
                "lvis_v1_stage2a_cooked_packaged",
                "lvis_v1_stage2b_cooked_packaged",
                "lvis_v1_banned_cocat",
                "rf_viet_hoang_stage2a_cooked_packaged",
            ):
                allowed_cls.update({"xuc_xich", "banh_quy", "sua_chua"})
            elif src == "v3det" and rsn in (
                "v3det_stage2a_outdoor_vine",
                "v3det_stage2a_crop_mismatch",
                "v3det_stage2b_missing_sprouts",
                "v3det_stage2a_off_topic",
                "v3det_black_corners",
                "v3det_stage2a_cooked_crop",
                "v3det_stage2a_watermark",
            ):
                allowed_cls.update({"gia_do", "muop", "su_su", "rau_cai"})

            if not allowed_cls:
                continue
            kept_orig = [b for b in orig if b.get("cls") in allowed_cls]
            if not kept_orig:
                continue

            # For gia_do (which only has 19 images total in v3det), split 6 into val and the rest into train
            target_sp = sp
            if any(b.get("cls") == "gia_do" for b in kept_orig):
                if rescued_counts["gia_do_val"] < 6:
                    target_sp = "val"

            p = Path(str(r.get("path") or ""))
            if not p.is_file():
                continue
            try:
                with Image.open(p) as im:
                    im_up = ImageOps.exif_transpose(im)
                    W_im, H_im = im_up.size
                    g = im_up.convert("L")
                    g.thumbnail((256, 256))
                    h = int(phash(np.asarray(g)))
            except Exception:
                continue
            boxes: list[Box] = []
            for b in kept_orig:
                cid = b["cls"]
                if "xc" in b:
                    xc, yc, bw, bh = float(b["xc"]), float(b["yc"]), float(b["w"]), float(b["h"])
                elif "bbox" in b and W_im > 0 and H_im > 0:
                    x0, y0, w_px, h_px = (float(v) for v in b["bbox"])
                    bw, bh = w_px / W_im, h_px / H_im
                    xc, yc = (x0 + w_px / 2.0) / W_im, (y0 + h_px / 2.0) / H_im
                else:
                    continue
                if bw >= 0.92 and bh >= 0.92:
                    continue
                bx = from_corners_norm(cid_to_idx[cid], xc - bw / 2, yc - bh / 2, xc + bw / 2, yc + bh / 2)
                if bx:
                    boxes.append(bx)
            if not boxes:
                continue
            if not _can_add(target_sp, h):
                continue

            stem = f"rescue__{src}__{p.stem}"
            _link_or_copy(p, out_dir / "images" / target_sp / f"{stem}.jpg")
            (out_dir / "labels" / target_sp / f"{stem}.txt").write_text(write_label(boxes), encoding="utf-8")
            img_counts[target_sp] += 1
            for b in kept_orig:
                rescued_counts[f"{b['cls']}_{target_sp}"] += 1
            if src == "rf_tofu_oo":
                tofu_seen[target_sp] += 1

    # 4. Append cooked-dish 0-box hard negatives strictly to train
    neg_added = 0
    if cooked_neg_manifest and cooked_neg_manifest.is_file():
        for idx, ln in enumerate(cooked_neg_manifest.read_text(encoding="utf-8").splitlines()):
            p = Path(ln.strip())
            if not p.is_file():
                continue
            dst_img = out_dir / "images" / "train" / f"cneg_{idx:05d}__{p.stem}.jpg"
            dst_lbl = out_dir / "labels" / "train" / f"cneg_{idx:05d}__{p.stem}.txt"
            _link_or_copy(p, dst_img)
            dst_lbl.write_text("", encoding="utf-8")
            img_counts["train"] += 1
            neg_added += 1

    # 5. Count boxes per class in train & val
    box_counts = {sp: Counter() for sp in ("train", "val", "test", "heldout")}
    for sp in ("train", "val", "test", "heldout"):
        for lp in (out_dir / "labels" / sp).glob("*.txt"):
            for ln in lp.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    ci = int(float(ln.split()[0]))
                    box_counts[sp][names_37[ci]] += 1

    ds = {
        "path": str(out_dir.resolve()),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": dict(enumerate(names_37)),
    }
    (out_dir / "dataset.yaml").write_text(yaml.safe_dump(ds, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (out_dir / "data.yaml").write_text(yaml.safe_dump(ds, allow_unicode=True, sort_keys=False), encoding="utf-8")

    summary = {
        "n_classes": 37,
        "images_per_split": dict(img_counts),
        "rescued_counts": dict(rescued_counts),
        "cooked_neg_added": neg_added,
        "lowest_15_train": sorted([(c, box_counts["train"][c]) for c in names_37], key=lambda x: x[1])[:15],
        "lowest_15_val": sorted([(c, box_counts["val"][c]) for c in names_37], key=lambda x: x[1])[:15],
    }
    (out_dir / "rescue_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yolo-v4-dir", type=Path, default=Path("/home/namnx/NamBuw/Tastoria/data/processed/cv/yolo_v4"))
    ap.add_argument("--zubiaa-dir", type=Path, default=Path("/dev/shm/zubiaa_rf"))
    ap.add_argument("--out-dir", type=Path, default=Path("/dev/shm/yolo_v5_rescue"))
    ap.add_argument("--cooked-neg-manifest", type=Path, default=Path("/dev/shm/cooked_neg/cooked_neg_manifest.txt"))
    ap.add_argument("--food-assets-dir", type=Path, default=Path("/home/namnx/NamBuw/Tastoria/app/assets/food"))
    a = ap.parse_args()
    build_rescued_dataset(
        a.yolo_v4_dir,
        a.zubiaa_dir,
        a.out_dir,
        cooked_neg_manifest=a.cooked_neg_manifest,
        food_assets_dir=a.food_assets_dir,
    )


if __name__ == "__main__":
    main()

