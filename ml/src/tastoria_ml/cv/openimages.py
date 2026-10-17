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
import io
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from tastoria_ml.cv.classes import REPO, load_classes, source_label_map

ROOT = REPO / "data" / "raw" / "images" / "openimages_v7"
META = ROOT / "meta"
IMAGES = ROOT / "images"
SOURCE = "openimages_v7"

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
MAX_SIDE = 1024


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["annotations", "select", "metadata", "images", "all"])
    a = ap.parse_args()
    if a.step in ("annotations", "all"):
        fetch_annotations()
    if a.step in ("select", "all"):
        select()
    if a.step in ("metadata", "all"):
        fetch_metadata()
    if a.step in ("images", "all"):
        fetch_images()


if __name__ == "__main__":
    main()
