"""RPC (Retail Product Checkout, Wei et al. 2019) subset for the packaged-food proposed classes.

Source: the Hugging Face mirror benjamintli/retail-product-checkout, validation split only (3 parquet files,
6,000 overhead checkout photos, 1865 px, white background). Labels are 200 SKUs named ``<n>_<meta>``; we map the
meta category (``instant_noodles``, ``canned_food``...) via ``public_data.rpc_checkout`` in vision_classes.yaml.
Unmapped products (dessert, alcohol, dried food...) stay unlabelled: they are not Tastoria classes.

Images are re-encoded at ≤ 1024 px (boxes scaled). Split by a hash of the file name: 15 % held-out, 10 % val,
the rest train. Every SKU appears in every split, so held-out scores are optimistic (same products).

License CC BY-NC-SA 4.0 (non-commercial; coursework only). Run: ``python -m tastoria_ml.cv.rpc``
"""

from __future__ import annotations

import hashlib
import io
import json

from tastoria_ml.cv.classes import REPO

ROOT = REPO / "data" / "raw" / "images" / "rpc_checkout"
IMAGES = ROOT / "images"
SOURCE = "rpc_checkout"
MAX_SIDE = 1024
CAP = 2500  # images kept (disk), chosen in file order


def label_map() -> dict[str, str]:
    from tastoria_ml.cv.build_yolo_v2 import all_class_rows

    out = {}
    for c in all_class_rows():
        for lab in (c.get("public_data") or {}).get(SOURCE, []):
            out[lab] = c["id"]
    return out


def our_split(name: str) -> str:
    h = int(hashlib.sha1(name.encode()).hexdigest(), 16) % 20
    return "heldout" if h < 3 else "val" if h < 5 else "train"


def extract() -> dict:
    import pyarrow.parquet as pq
    from PIL import Image

    lab = label_map()
    IMAGES.mkdir(parents=True, exist_ok=True)
    out = []
    for f in sorted(ROOT.glob("validation-*.parquet")):
        pf = pq.ParquetFile(f)
        meta = json.loads(pf.schema_arrow.metadata[b"huggingface"])
        cat_names = meta["info"]["features"]["objects"]["category"]["feature"]["names"]
        for rg in range(pf.num_row_groups):
            for row in pf.read_row_group(rg).to_pylist():
                if len(out) >= CAP:
                    break
                boxes = []
                for bb, c in zip(row["objects"]["bbox"], row["objects"]["category"]):
                    m = cat_names[c].split("_", 1)[1]
                    if m in lab:
                        boxes.append({"cat": m, "cls": lab[m], "bbox": bb})
                if not boxes:
                    continue
                name = row["image"]["path"] or hashlib.sha1(row["image"]["bytes"]).hexdigest()
                im = Image.open(io.BytesIO(row["image"]["bytes"])).convert("RGB")
                s = min(1.0, MAX_SIDE / max(im.size))
                w, h = im.size
                if s < 1:
                    im = im.resize((round(w * s), round(h * s)), Image.LANCZOS)
                p = IMAGES / (name.rsplit(".", 1)[0] + ".jpg")
                im.save(p, "JPEG", quality=90)
                for b in boxes:
                    b["bbox"] = [v * s for v in b["bbox"]]
                out.append({"id": name, "split": our_split(name), "file": p.name, "width": im.size[0],
                            "height": im.size[1], "boxes": boxes})
    (ROOT / "selected.json").write_text(json.dumps(out))
    return {"images": len(out)}


def records() -> list[dict]:
    return [{**r, "path": IMAGES / r["file"]} for r in json.loads((ROOT / "selected.json").read_text())]


if __name__ == "__main__":
    print(extract())
