"""Visual QA & raw label mapping audit for Siddhanxt/Fruits-And-Vegetables-Detection-Dataset."""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageOps

SIDDHANXT_MAP: dict[str, str] = {
    # 13 new proposed_classes
    "onion": "hanh_tay",
    "bell pepper/capsicum": "ot_chuong",
    "cucumber/cuke": "dua_chuot",
    "eggplant/aubergine": "ca_tim",
    "edible corn/corn/maize": "ngo",
    "ginger/gingerroot": "gung",
    "lettuce": "xa_lach",
    "sweet potato": "khoai_lang",
    "radish/daikon": "cu_cai",
    "zucchini/courgette": "bi_ngoi",
    "celery": "can_tay",
    "banana": "chuoi",
    "pineapple": "dua",
    # Existing classes to reinforce
    "bean curd/tofu": "dau_phu",
    "chili/chili vegetable/chili pepper/chili pepper vegetable/chilli/chilli vegetable/chilly/chilly": "ot",
    "cayenne/cayenne spice/cayenne pepper/cayenne pepper spice/red pepper/red pepper": "ot",
    "garlic/ail": "toi",
    "green onion/spring onion/scallion": "hanh_la",
    "gourd": "bi_dao",
    "green bean": "dau_que",
    "lemon": "chanh",
    "lime": "chanh",
    "mushroom": "nam",
    "broccoli": "sup_lo",
    "cauliflower": "sup_lo",
    "carrot": "ca_rot",
    "potato": "khoai_tay",
    "pumpkin": "bi_do",
    "tomato": "ca_chua",
    "Tomato": "ca_chua",
}


def audit(stage_dir: Path, out_png: Path, seed: int = 0) -> dict:
    doc = yaml.safe_load((stage_dir / "data.yaml").read_text(encoding="utf-8"))
    raw_names = doc["names"]
    names = {int(k): str(v) for k, v in raw_names.items()} if isinstance(raw_names, dict) else {i: str(v) for i, v in enumerate(raw_names)}
    idx_to_cid = {i: SIDDHANXT_MAP[n] for i, n in names.items() if n in SIDDHANXT_MAP}

    counts = {sp: Counter() for sp in ("train", "val", "test")}
    samples: dict[str, list[tuple[Path, list[tuple[str, float, float, float, float]]]]] = defaultdict(list)

    for sp in ("train", "val", "test"):
        lbl_dir = stage_dir / "labels" / sp
        img_dir = stage_dir / "images" / sp
        if not lbl_dir.is_dir():
            continue
        for lbl in sorted(lbl_dir.glob("*.txt")):
            ip = img_dir / f"{lbl.stem}.jpg"
            if not ip.is_file():
                continue
            boxes = []
            for ln in lbl.read_text(encoding="utf-8", errors="replace").splitlines():
                toks = ln.strip().split()
                if len(toks) < 5:
                    continue
                old_i = int(float(toks[0]))
                cid = idx_to_cid.get(old_i)
                if cid is None:
                    continue
                xc, yc, w, h = (float(x) for x in toks[1:5])
                counts[sp][cid] += 1
                boxes.append((cid, xc, yc, w, h))
            if sp == "val" and boxes:
                for cid, *_ in boxes[:1]:
                    if len(samples[cid]) < 8:
                        samples[cid].append((ip, boxes))

    # Build contact sheet of up to 20 classes x 4 images with drawn bounding boxes
    rng = random.Random(seed)
    target_order = [
        "hanh_tay", "ot_chuong", "dua_chuot", "ca_tim", "ngo", "gung", "xa_lach",
        "khoai_lang", "cu_cai", "bi_ngoi", "can_tay", "chuoi", "dua",
        "dau_phu", "ot", "toi", "hanh_la", "bi_dao", "dau_que", "chanh",
    ]
    keys = [k for k in target_order if k in samples]
    tile, label_w = 136, 130
    canvas = Image.new("RGB", (label_w + 4 * tile, max(1, len(keys)) * tile), (24, 24, 24))
    draw = ImageDraw.Draw(canvas)
    for ri, cid in enumerate(keys):
        y0 = ri * tile
        draw.text((8, y0 + 56), cid[:16], fill=(240, 240, 240))
        chosen = list(samples[cid])
        rng.shuffle(chosen)
        for ci, (ip, boxes) in enumerate(chosen[:4]):
            try:
                with Image.open(ip) as im:
                    im = ImageOps.exif_transpose(im).convert("RGB")
                    im_fit = ImageOps.pad(im, (tile - 4, tile - 4), color=(16, 16, 16))
                    # Draw normalized boxes roughly if square/pad
                    ox = label_w + ci * tile + 2
                    oy = y0 + 2
                    canvas.paste(im_fit, (ox, oy))
                    # Overlay box at approximate original coords onto unpadded resize: use fit? Let's draw directly on resized im
                    rw, rh = tile - 4, tile - 4
                    im_rs = im.resize((rw, rh))
                    d2 = ImageDraw.Draw(im_rs)
                    for bcid, xc, yc, bw, bh in boxes:
                        col = (0, 255, 100) if bcid == cid else (255, 180, 0)
                        d2.rectangle([(xc - bw / 2) * rw, (yc - bh / 2) * rh, (xc + bw / 2) * rw, (yc + bh / 2) * rh], outline=col, width=2)
                    canvas.paste(im_rs, (ox, oy))
            except Exception:
                pass
    canvas.save(out_png, "PNG")
    return {sp: dict(sorted(c.items())) for sp, c in counts.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage-dir", type=Path, required=True)
    ap.add_argument("--out-png", type=Path, required=True)
    a = ap.parse_args()
    print(json.dumps(audit(a.stage_dir, a.out_png), indent=2))


if __name__ == "__main__":
    main()
