"""Open Images V7 boxable subset for the mappable vision classes, without credentials.

Steps (each writes under data/raw/images/openimages_v7/):
  annotations  stream the official bbox CSVs from storage.googleapis.com and keep only rows of the mapped
               labels (the 2.3 GB train CSV is never stored whole);
  select       per class, keep at most ``cap`` images per split (train cap 1500, val/test cap 250), drop
               images where any kept box is a depiction (drawing, toy) and images with EXIF rotation;
  metadata     stream the image CSVs and keep license, author and URLs of the selected images;
  images       download each selected image as its Open Images ~640 px thumbnail (Thumbnail300KURL), or
               from the public S3 bucket ``open-images-dataset`` when the thumbnail is gone, and store it
               with a longest side of at most 1024 px (JPEG q90).

Run (training env): ``python -m tastoria_ml.cv.openimages all``
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import random
import shutil
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from tastoria_ml.cv.classes import REPO, load_classes, source_label_map

ROOT = REPO / "data" / "raw" / "images" / "openimages_v7"
META = ROOT / "meta"
IMAGES = ROOT / "images"
SOURCE = "openimages_v7"
OOD_ROOT = ROOT / "ood"
OOD_META = OOD_ROOT / "meta"
OOD_IMAGES = OOD_ROOT / "images"
STAGE = Path(os.environ.get("TASTORIA_STAGE_DIR", "/dev/shm/tastoria_stage_m1/openimages"))

CLASS_CSV = "https://storage.googleapis.com/openimages/v7/oidv7-class-descriptions-boxable.csv"
BBOX_CSV = {
    "train": "https://storage.googleapis.com/openimages/v6/oidv6-train-annotations-bbox.csv",
    "validation": "https://storage.googleapis.com/openimages/v5/validation-annotations-bbox.csv",
    "test": "https://storage.googleapis.com/openimages/v5/test-annotations-bbox.csv",
}
IMAGE_CSV = {
    "train": "https://storage.googleapis.com/openimages/2018_04/train/train-images-boxable-with-rotation.csv",
    "validation": "https://storage.googleapis.com/openimages/2018_04/validation/validation-images-with-rotation.csv",
    "test": "https://storage.googleapis.com/openimages/2018_04/test/test-images-with-rotation.csv",
}
S3 = "https://open-images-dataset.s3.amazonaws.com/{split}/{image_id}.jpg"
CAPS = {"train": 1500, "validation": 250, "test": 250}
OOD_CAPS = {"train": 150, "validation": 30}
MAX_SIDE = 1024
OOD_JPEG_QUALITY = 88
MIN_ROOT_FREE_BYTES = 18 * (1024**3)

OOD_LABELS: tuple[str, ...] = (
    "Bell pepper",
    "Cucumber",
    "Apple",
    "Banana",
    "Orange (fruit)",
    "Radish",
    "Zucchini",
    "Cheese",
    "Crab",
    "Squid",
    "Pineapple",
    "Watermelon",
    "Grapefruit",
)

OOD_EXCLUDE_LABELS: tuple[str, ...] = (
    "Pizza",
    "Fast food",
    "Food",
    "Hamburger",
    "Sandwich",
    "Salad",
    "Pasta",
    "Sushi",
    "Cake",
    "Baked goods",
    "Snack",
    "Pastry",
    "Platter",
    "Tableware",
    "Plate",
    "Bowl",
    "Fork",
    "Knife",
    "Spoon",
    "Kitchen & dining room table",
    "Seafood",
    "Shellfish",
)


def label_mids() -> dict[str, str]:
    """MID -> Open Images display name, for the labels mapped in vision_classes.yaml."""
    wanted = set(source_label_map(load_classes(), SOURCE))
    text = (META / "oidv7-class-descriptions-boxable.csv").read_text(encoding="utf-8")
    out = {}
    for mid, name in csv.reader(io.StringIO(text)):
        if name in wanted:
            out[mid] = name
    missing = wanted - set(out.values())
    if missing:
        raise ValueError(f"labels not in Open Images boxable list: {sorted(missing)}")
    return out


def _stream_lines(url: str, retries: int = 20):
    """Yield text lines of a large remote CSV; on a dropped connection resume with an HTTP Range."""
    offset = 0
    buf = b""
    attempt = 0
    while True:
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        try:
            with requests.get(url, stream=True, timeout=120, headers=headers) as r:
                r.raise_for_status()
                if offset and r.status_code != 206:
                    raise RuntimeError("server ignored Range; cannot resume")
                for chunk in r.iter_content(chunk_size=1 << 20):
                    offset += len(chunk)
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    for line in lines:
                        yield line.decode("utf-8") + "\n"
            if buf:
                yield buf.decode("utf-8") + "\n"
            return
        except (requests.RequestException, ValueError, OSError):
            attempt += 1
            if attempt > retries:
                raise
            print(f"stream dropped at byte {offset}, resuming ({attempt}/{retries})", flush=True)


def fetch_annotations() -> None:
    META.mkdir(parents=True, exist_ok=True)
    cls = META / "oidv7-class-descriptions-boxable.csv"
    if not cls.exists():
        cls.write_bytes(requests.get(CLASS_CSV, timeout=60).content)
    mids = label_mids()
    for split, url in BBOX_CSV.items():
        out = META / f"{split}-bbox-filtered.csv"
        if out.exists():
            continue
        n_in = n_out = 0
        tmp = out.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8", newline="") as f:
            lines = _stream_lines(url)
            f.write(next(lines))
            for line in lines:
                n_in += 1
                # columns: ImageID,Source,LabelName,Confidence,...
                parts = line.split(",", 3)
                if len(parts) > 2 and parts[2] in mids:
                    f.write(line)
                    n_out += 1
        tmp.rename(out)
        print(f"{split}: kept {n_out} of {n_in} box rows")


def read_boxes(split: str) -> list[dict]:
    with (META / f"{split}-bbox-filtered.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def select(seed: int = 0) -> None:
    mids = label_mids()
    rng = random.Random(seed)
    for split, cap in CAPS.items():
        boxes = read_boxes(split)
        depiction = {b["ImageID"] for b in boxes if b["IsDepiction"] == "1"}
        by_label: dict[str, set[str]] = {}
        for b in boxes:
            if b["ImageID"] in depiction:
                continue
            by_label.setdefault(mids[b["LabelName"]], set()).add(b["ImageID"])
        chosen: set[str] = set()
        # rare labels first so their images are guaranteed; a chosen image counts for every label it has
        for label in sorted(by_label, key=lambda k: len(by_label[k])):
            ids = sorted(by_label[label])
            already = [i for i in ids if i in chosen]
            rest = [i for i in ids if i not in chosen]
            rng.shuffle(rest)
            chosen.update(rest[: max(0, cap - len(already))])
        out = META / f"{split}-selected.txt"
        out.write_text("\n".join(sorted(chosen)) + "\n", encoding="utf-8")
        counts = {k: len(v & chosen) for k, v in sorted(by_label.items())}
        print(split, len(chosen), "images; per label:", counts, "; depiction images dropped:", len(depiction))


def fetch_metadata() -> None:
    for split, url in IMAGE_CSV.items():
        ids = set((META / f"{split}-selected.txt").read_text().split())
        out = META / f"{split}-images-selected.csv"
        if out.exists():
            continue
        tmp = out.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8", newline="") as f:
            lines = _stream_lines(url)
            f.write(next(lines))
            for line in lines:
                if line.split(",", 1)[0] in ids:
                    f.write(line)
        tmp.rename(out)


def read_metadata(split: str) -> dict[str, dict]:
    with (META / f"{split}-images-selected.csv").open(encoding="utf-8", newline="") as f:
        return {r["ImageID"]: r for r in csv.DictReader(f)}


def _get_image(split: str, image_id: str, thumb: str):
    """The ~640 px Flickr thumbnail listed by Open Images (Thumbnail300KURL) when it still exists, else
    the full image from the public S3 bucket. Returns (PIL image, origin)."""
    from PIL import Image

    if thumb:
        try:
            r = requests.get(thumb, timeout=30)
            if r.ok and len(r.content) > 2000 and "photo_unavailable" not in r.url:
                im = Image.open(io.BytesIO(r.content))
                im.load()
                return im, "thumbnail"
        except Exception:  # noqa: BLE001 - fall back to S3
            pass
    r = requests.get(S3.format(split=split, image_id=image_id), timeout=60)
    r.raise_for_status()
    im = Image.open(io.BytesIO(r.content))
    im.load()
    return im, "s3"


def _download_one(split: str, image_id: str, thumb: str = "") -> str:
    dst = IMAGES / split / f"{image_id}.jpg"
    if dst.exists():
        return "skip"
    try:
        im, origin = _get_image(split, image_id, thumb)
        im = im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        tmp = dst.with_suffix(".part")
        im.save(tmp, "JPEG", quality=90)
        tmp.rename(dst)
        return origin
    except Exception as e:  # noqa: BLE001 - logged and counted, the image is skipped
        return f"fail {type(e).__name__}"


def fetch_images(workers: int = 16) -> None:
    for split in CAPS:
        meta = read_metadata(split)
        ids = []
        for i in sorted(set((META / f"{split}-selected.txt").read_text().split())):
            rot = (meta.get(i) or {}).get("Rotation", "")
            if rot not in ("", "0", "0.0"):
                continue
            ids.append(i)
        (IMAGES / split).mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(workers) as ex:
            res = list(ex.map(lambda i: _download_one(split, i, (meta.get(i) or {}).get("Thumbnail300KURL", "")), ids))
        stats: dict[str, int] = {}
        for r in res:
            stats[r] = stats.get(r, 0) + 1
        print(split, len(ids), stats)


def _is_commercial_license(license_url: str) -> bool:
    low = (license_url or "").strip().lower()
    if not low:
        return False
    if "-nc" in low or "noncommercial" in low:
        return False
    return ("creativecommons.org/" in low) or ("publicdomain" in low) or ("cc0" in low)


def ood_label_mids() -> tuple[dict[str, str], dict[str, str]]:
    """Return ``(ood_mid_to_name, exclude_mid_to_name)`` verified against boxable class descriptions."""
    cls_csv = META / "oidv7-class-descriptions-boxable.csv"
    if not cls_csv.exists():
        META.mkdir(parents=True, exist_ok=True)
        cls_csv.write_bytes(requests.get(CLASS_CSV, timeout=60).content)

    name_to_mid: dict[str, str] = {}
    for mid, name in csv.reader(io.StringIO(cls_csv.read_text(encoding="utf-8"))):
        name_to_mid[name] = mid

    pos_names = set(source_label_map(load_classes(), SOURCE))
    ood_mids: dict[str, str] = {}
    for name in OOD_LABELS:
        if name not in name_to_mid:
            raise ValueError(f"OOD label not in Open Images boxable list: {name!r}")
        ood_mids[name_to_mid[name]] = name

    excl_mids: dict[str, str] = {}
    for name in sorted(set(OOD_EXCLUDE_LABELS) | pos_names):
        if name not in name_to_mid:
            raise ValueError(f"Exclude label not in Open Images boxable list: {name!r}")
        excl_mids[name_to_mid[name]] = name

    overlap = set(ood_mids) & set(excl_mids)
    if overlap:
        raise ValueError(f"OOD and exclude MIDs overlap: {sorted(overlap)}")
    return ood_mids, excl_mids


def _stage_csv(url: str, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_suffix(".part")
    offset = part.stat().st_size if part.exists() else 0
    for attempt in range(8):
        headers = {"Range": f"bytes={offset}-"} if offset > 0 else {}
        try:
            with requests.get(url, stream=True, timeout=180, headers=headers) as r:
                r.raise_for_status()
                if offset > 0 and r.status_code != 206:
                    offset = 0
                mode = "ab" if (offset > 0 and r.status_code == 206) else "wb"
                with part.open(mode) as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        if chunk:
                            f.write(chunk)
                            offset += len(chunk)
            part.rename(dst)
            return dst
        except Exception:
            if attempt == 7:
                raise
            offset = part.stat().st_size if part.exists() else 0
    return dst


def select_ood(
    *,
    caps: dict[str, int] | None = None,
    csv_paths: dict[str, Path] | None = None,
    force: bool = False,
) -> dict:
    """Single-pass scan of train/validation bbox CSVs staged in /dev/shm (never touches test or meta/)."""
    OOD_META.mkdir(parents=True, exist_ok=True)
    use_caps = caps or OOD_CAPS
    ood_mids, excl_mids = ood_label_mids()
    summary: dict[str, dict] = {}

    STAGE.mkdir(parents=True, exist_ok=True)
    try:
        for split in ("validation", "train"):
            cap = use_caps[split]
            out_json = OOD_META / f"{split}-ood-selected.json"
            if out_json.exists() and not force:
                summary[split] = json.loads(out_json.read_text(encoding="utf-8"))
                continue

            existing_pos_ids: set[str] = set()
            pos_sel = META / f"{split}-selected.txt"
            if pos_sel.exists():
                existing_pos_ids.update(pos_sel.read_text(encoding="utf-8").split())

            staged_csv = STAGE / f"{split}-bbox.csv"
            local_csv = csv_paths.get(split) if csv_paths else None
            try:
                csv_file = local_csv if local_csv is not None else _stage_csv(BBOX_CSV[split], staged_csv)
                excluded_ids: set[str] = set(existing_pos_ids)
                ood_by_label: dict[str, set[str]] = defaultdict(set)
                rows_scanned = 0
                with csv_file.open("r", encoding="utf-8", newline="") as f:
                    header = next(csv.reader([f.readline()]))
                    idx_id = header.index("ImageID")
                    idx_lbl = header.index("LabelName")
                    idx_dep = header.index("IsDepiction")
                    max_idx = max(idx_id, idx_lbl, idx_dep)
                    for line in f:
                        rows_scanned += 1
                        parts = line.rstrip("\r\n").split(",", max_idx + 1)
                        if len(parts) <= max_idx:
                            continue
                        img_id = parts[idx_id]
                        lbl = parts[idx_lbl]
                        dep = parts[idx_dep]
                        if dep == "1" or lbl in excl_mids:
                            excluded_ids.add(img_id)
                        elif lbl in ood_mids:
                            ood_by_label[ood_mids[lbl]].add(img_id)
            finally:
                if local_csv is None:
                    staged_csv.unlink(missing_ok=True)
                    staged_csv.with_suffix(".part").unlink(missing_ok=True)

            # Remove any image that has an excluded label or depiction anywhere
            clean_by_label: dict[str, list[str]] = {}
            for lbl_name, iids in ood_by_label.items():
                clean_ids = sorted(iids - excluded_ids)
                clean_ids.sort(key=lambda iid: hashlib.sha1(f"oi_ood:{split}:{lbl_name}:{iid}".encode()).hexdigest())
                clean_by_label[lbl_name] = clean_ids

            chosen: set[str] = set()
            # Rare-first capped selection
            for lbl_name in sorted(clean_by_label, key=lambda k: len(clean_by_label[k])):
                ids = clean_by_label[lbl_name]
                already = sum(1 for i in ids if i in chosen)
                need = max(0, cap - already)
                if need <= 0:
                    continue
                rest = [i for i in ids if i not in chosen]
                chosen.update(rest[:need])

            chosen_labels: dict[str, list[str]] = {}
            per_label_selected: dict[str, int] = {}
            for lbl_name, ids in sorted(clean_by_label.items()):
                id_set = set(ids)
                sel_for_lbl = id_set & chosen
                per_label_selected[lbl_name] = len(sel_for_lbl)
                for iid in sel_for_lbl:
                    chosen_labels.setdefault(iid, []).append(lbl_name)
            for iid in chosen_labels:
                chosen_labels[iid].sort()

            payload = {
                "split": split,
                "cap_per_label": cap,
                "rows_scanned": rows_scanned,
                "excluded_images": len(excluded_ids),
                "selected_images": len(chosen_labels),
                "available_clean_per_label": {k: len(v) for k, v in sorted(clean_by_label.items())},
                "selected_per_label": per_label_selected,
                "chosen_labels": chosen_labels,
            }
            out_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            (OOD_META / f"{split}-ood-selected.txt").write_text(
                "\n".join(sorted(chosen_labels)) + ("\n" if chosen_labels else ""),
                encoding="utf-8",
            )
            print(
                f"[openimages_ood] {split}: scanned={rows_scanned} selected={len(chosen_labels)} "
                f"per_label={per_label_selected}",
                flush=True,
            )
            summary[split] = payload
    finally:
        shutil.rmtree(STAGE, ignore_errors=True)
    return summary


def fetch_ood_metadata(*, force: bool = False) -> None:
    OOD_META.mkdir(parents=True, exist_ok=True)
    for split in ("validation", "train"):
        sel_json = OOD_META / f"{split}-ood-selected.json"
        if not sel_json.exists():
            continue
        ids = set(json.loads(sel_json.read_text(encoding="utf-8"))["chosen_labels"].keys())
        out = OOD_META / f"{split}-ood-images-selected.csv"
        if out.exists() and not force:
            continue
        tmp = out.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8", newline="") as f:
            lines = _stream_lines(IMAGE_CSV[split])
            f.write(next(lines))
            for line in lines:
                if line.split(",", 1)[0] in ids:
                    f.write(line)
        tmp.rename(out)


def _read_ood_metadata(split: str) -> dict[str, dict]:
    p = OOD_META / f"{split}-ood-images-selected.csv"
    if not p.exists():
        return {}
    with p.open(encoding="utf-8", newline="") as f:
        return {r["ImageID"]: r for r in csv.DictReader(f)}


def _download_ood_one(split: str, image_id: str, thumb: str = "") -> tuple[str, int, int, str]:
    from PIL import Image

    dst = OOD_IMAGES / split / f"{image_id}.jpg"
    if dst.exists():
        try:
            with Image.open(dst) as im:
                w, h = im.size
            return image_id, w, h, "skip"
        except Exception:
            dst.unlink(missing_ok=True)
    try:
        im, origin = _get_image(split, image_id, thumb)
        im = im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
        w, h = im.size
        tmp = dst.with_suffix(".part")
        im.save(tmp, "JPEG", quality=OOD_JPEG_QUALITY)
        tmp.rename(dst)
        return image_id, w, h, origin
    except Exception as e:  # noqa: BLE001
        return image_id, 0, 0, f"fail {type(e).__name__}"


def fetch_ood_images(workers: int = 16) -> dict:
    root_free = shutil.disk_usage(REPO).free
    if root_free <= MIN_ROOT_FREE_BYTES:
        raise RuntimeError(f"Root disk free {root_free / (1024**3):.2f} GiB <= 18 GiB floor")

    out_records: list[dict] = []
    split_counts: Counter = Counter()
    ood_counts: Counter = Counter()
    comm_count = 0
    non_comm_count = 0
    all_stats: dict[str, dict[str, int]] = {}

    for split in ("validation", "train"):
        sel_json = OOD_META / f"{split}-ood-selected.json"
        if not sel_json.exists():
            continue
        chosen_labels = json.loads(sel_json.read_text(encoding="utf-8"))["chosen_labels"]
        meta = _read_ood_metadata(split)
        ids = []
        for iid in sorted(chosen_labels):
            rot = (meta.get(iid) or {}).get("Rotation", "")
            if rot not in ("", "0", "0.0"):
                continue
            ids.append(iid)

        (OOD_IMAGES / split).mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(workers) as ex:
            results = list(
                ex.map(
                    lambda iid: _download_ood_one(split, iid, (meta.get(iid) or {}).get("Thumbnail300KURL", "")),
                    ids,
                )
            )

        stats: dict[str, int] = {}
        split_hint = "val" if split == "validation" else "train"
        for iid, w, h, status in results:
            stats[status] = stats.get(status, 0) + 1
            if w <= 0 or h <= 0:
                continue
            m = meta.get(iid, {})
            lic = m.get("License", "")
            is_comm = _is_commercial_license(lic)
            if is_comm:
                comm_count += 1
            else:
                non_comm_count += 1
            lbls = chosen_labels.get(iid, ["__neg__"])
            for ol in lbls:
                ood_counts[ol] += 1
            split_counts[split_hint] += 1
            out_records.append({
                "id": f"openimages_v7_ood/{split}/{iid}",
                "stem": iid,
                "source_name": "openimages_v7_ood",
                "split": split_hint,
                "split_hint": split_hint,
                "file": f"images/{split}/{iid}.jpg",
                "width": w,
                "height": h,
                "license": lic,
                "is_commercial_ok": is_comm,
                "url": m.get("OriginalURL", ""),
                "is_neg": True,
                "ood_labels": lbls,
                "boxes": [],
            })
        all_stats[split] = stats
        print(f"[openimages_ood] {split}: {len(ids)} requested -> {stats}", flush=True)

    is_comm_top: bool | str
    if comm_count > 0 and non_comm_count == 0:
        is_comm_top = True
    elif comm_count == 0:
        is_comm_top = False
    else:
        is_comm_top = "mixed"

    manifest = {
        "schema_version": "m1_v1",
        "source": "openimages_v7_ood",
        "source_name": "openimages_v7_ood",
        "license": "CC BY 2.0 / Open Images V7 (per-image License)",
        "is_commercial_ok": is_comm_top,
        "url": "https://storage.googleapis.com/openimages/web/index.html",
        "categories": ["__neg__"],
        "images": len(out_records),
        "neg_images": len(out_records),
        "splits": dict(split_counts),
        "boxes_per_class": {},
        "ood_images_per_label": dict(sorted(ood_counts.items())),
        "download_stats": all_stats,
        "records": out_records,
    }
    OOD_ROOT.mkdir(parents=True, exist_ok=True)
    (OOD_ROOT / "annotations.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return {k: v for k, v in manifest.items() if k != "records"}


def ood_records() -> list[dict]:
    """Return standardized m1_v1 OOD hard-negative records from openimages_v7/ood/."""
    ann_path = OOD_ROOT / "annotations.json"
    if not ann_path.exists():
        return []
    d = json.loads(ann_path.read_text(encoding="utf-8"))
    out: list[dict] = []
    for r in d["records"]:
        p = OOD_ROOT / r["file"]
        if p.exists():
            out.append({**r, "source": "openimages_v7_ood", "path": p})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "step",
        choices=[
            "annotations",
            "select",
            "metadata",
            "images",
            "all",
            "ood-select",
            "ood-metadata",
            "ood-images",
            "ood-all",
        ],
    )
    a = ap.parse_args()
    if a.step in ("annotations", "all"):
        fetch_annotations()
    if a.step in ("select", "all"):
        select()
    if a.step in ("metadata", "all"):
        fetch_metadata()
    if a.step in ("images", "all"):
        fetch_images()
    if a.step in ("ood-select", "ood-all"):
        select_ood()
    if a.step in ("ood-metadata", "ood-all"):
        fetch_ood_metadata()
    if a.step in ("ood-images", "ood-all"):
        fetch_ood_images()


if __name__ == "__main__":
    main()
