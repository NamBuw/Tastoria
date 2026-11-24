"""Selective multi-source 8-class culinary mushroom dataset curation (`G-11`, FungiCLEF safety).

Stages a clean, deduplicated, zero-leakage 8-class dataset into ``/dev/shm/mushroom_stage``:
  1. ``nam-rom``        (nấm rơm — Volvariella volvacea)
  2. ``nam-huong-tuoi`` (nấm hương tươi — Lentinula edodes)
  3. ``nam-kim-cham``   (nấm kim châm — white cultivated/market Flammulina; wild orange filtered out)
  4. ``nam-dui-ga``     (nấm đùi gà — Pleurotus eryngii)
  5. ``nam-so``         (nấm sò — Pleurotus ostreatus / P. pulmonarius)
  6. ``nam-mo``         (nấm mỡ — Agaricus bisporus)
  7. ``other_mushroom`` (wild / OOD + deadly lookalikes: Amanita phalloides/virosa egg & mature,
                         Galerina marginata, Agaricus xanthodermus, Omphalotus, wild Flammulina)
  8. ``not_mushroom``   (~2k hard negatives: garlic, tofu, potato, ginger, cooked food / yolo_v4 crops)
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import re
import shutil
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from PIL import Image, ImageOps

from tastoria_ml.cv.phash import hamming, phash

CLASSES: tuple[str, ...] = (
    "nam-rom",
    "nam-huong-tuoi",
    "nam-kim-cham",
    "nam-dui-ga",
    "nam-so",
    "nam-mo",
    "other_mushroom",
    "not_mushroom",
)

CULINARY_CLASSES: tuple[str, ...] = CLASSES[:6]

REPO = Path(__file__).resolve().parents[4]
DEFAULT_STAGE_DIR = Path("/dev/shm/mushroom_stage")
DEFAULT_YOLO_V4_DIR = REPO / "data" / "processed" / "cv" / "yolo_v4"

MAX_EDGE = 384
MIN_EDGE = 48
MIN_STD = 5.0
DEDUP_HAMMING = 4
GROUP_MERGE_HAMMING = 8
USER_AGENT = "TastoriaResearchBot/1.0 (https://tastoria.ctslab.net; culinary-cv-research)"

WIKI_BAD_TITLE_RE = re.compile(
    r"(?:dried|powder|soup|noodle|ramen|udon|hotpot|risotto|pasta|pizza|omelet|omelette|"
    r"salad|stir[-_ ]?fry|grilled|cooked|fried|sauce|gravy|canned|pickled|jar|bottle|"
    r"diagram|map|distribution|spore|microscop|histolog|stamp|drawing|sketch|illustration|"
    r"logo|icon|symbol|cartoon|poster|book|menu|recipe|restaurant|plate_of|dish_of)",
    re.IGNORECASE,
)

# Permissive title filter for not_mushroom hard negatives (allows cooked dishes, ginger, tofu, etc.)
WIKI_NON_MUSHROOM_BAD_RE = re.compile(
    r"(?:diagram|map|distribution|spore|microscop|histolog|stamp|drawing|sketch|illustration|"
    r"logo|icon|symbol|cartoon|poster|mushroom|fungi|fungus|agaricus|amanita|pleurotus|shiitake)",
    re.IGNORECASE,
)

WIKI_QUERIES: dict[str, list[str]] = {
    "nam-rom": [
        '"Volvariella volvacea"',
        '"straw mushroom"',
        '"paddy straw mushroom"',
        '"nấm rơm"',
    ],
    "nam-huong-tuoi": [
        '"Lentinula edodes"',
        '"shiitake mushroom"',
        '"fresh shiitake"',
        '"shiitake"',
    ],
    "nam-kim-cham": [
        '"enoki mushroom"',
        '"enokitake"',
        '"enoki" market OR bundle OR white OR cultivated',
        '"Flammulina filiformis"',
        '"enoki"',
    ],
    "nam-dui-ga": [
        '"Pleurotus eryngii"',
        '"king oyster mushroom"',
        '"king trumpet mushroom"',
        '"eryngii"',
    ],
    "nam-so": [
        '"Pleurotus ostreatus"',
        '"oyster mushroom"',
        '"Pleurotus pulmonarius"',
    ],
    "nam-mo": [
        '"Agaricus bisporus"',
        '"button mushroom"',
        '"champignon mushroom"',
        '"cremini mushroom"',
        '"portobello mushroom"',
    ],
    "other_mushroom": [
        '"Amanita phalloides"',
        '"Amanita virosa"',
        '"Galerina marginata"',
        '"Agaricus xanthodermus"',
        '"Omphalotus olearius"',
        '"Omphalotus illudens"',
    ],
    "not_mushroom": [
        '"ginger root" OR "Zingiber officinale" rhizome',
        '"tofu" blocks OR cubes',
        '"garlic cloves" OR "garlic bulb"',
        '"raw potatoes" OR "potatoes"',
        '"cooked rice" OR "fried rice" OR "noodle soup"',
    ],
}

INAT_TAXON_QUERIES: dict[str, list[tuple[str, int]]] = {
    "nam-rom": [("Volvariella volvacea", 200)],
    "nam-huong-tuoi": [("Lentinula edodes", 260)],
    "nam-kim-cham": [("Flammulina filiformis", 120), ("Flammulina velutipes", 120)],
    "nam-dui-ga": [("Pleurotus eryngii", 280)],
    "nam-so": [("Pleurotus ostreatus", 160), ("Pleurotus pulmonarius", 80)],
    "nam-mo": [("Agaricus bisporus", 160)],
    "other_mushroom": [
        # Deadly lookalikes (FungiCLEF c_PSC=100 priority)
        ("Amanita phalloides", 100),
        ("Amanita virosa", 80),
        ("Galerina marginata", 100),
        ("Agaricus xanthodermus", 100),
        ("Omphalotus olearius", 60),
        ("Omphalotus illudens", 60),
        ("Omphalotus japonicus", 40),
        # Wild forest OOD
        ("Amanita muscaria", 60),
        ("Russula emetica", 50),
    ],
}

# yolo_v4 class indices -> prioritization weight for not_mushroom hard negatives
YOLO_HARD_NEG_CLASSES: dict[int, tuple[str, int]] = {
    28: ("toi", 360),          # garlic (strong visual lookalike to nam-mo / nam-rom)
    6: ("dau_phu", 40),        # tofu (white blocks)
    9: ("khoai_tay", 320),     # potato
    11: ("sup_lo", 240),       # cauliflower/broccoli
    5: ("trung", 220),         # eggs
    13: ("bi_dao", 160),       # winter melon
    14: ("su_su", 60),         # chayote
    27: ("hanh_la", 140),      # scallions
    36: ("banh_mi", 140),      # bread
    0: ("thit_lon", 100),      # pork
    2: ("thit_ga", 100),       # chicken
    3: ("ca", 100),            # fish
}
YOLO_NAM_CLASS_IDX = 21


@dataclass(frozen=True)
class CandidateImage:
    slug: str
    source: str
    license: str
    group_id: str
    origin_ref: str
    url: str | None = None
    raw_bytes: bytes | None = None
    fixed_split: str | None = None  # optional split lock (e.g. yolo_v4 val/test alignment)


def is_clean_wiki_title(title: str, *, allow_cooked: bool = False) -> bool:
    low = title.lower()
    if not low.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return False
    if allow_cooked:
        return WIKI_NON_MUSHROOM_BAD_RE.search(title) is None
    return WIKI_BAD_TITLE_RE.search(title) is None


def _normalize_and_hash(raw: bytes, max_edge: int = MAX_EDGE) -> tuple[bytes, int, int, int] | None:
    """Decode, validate, resize to ``max_edge`` RGB JPEG, and compute 64-bit pHash."""
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            w, h = im.size
            if min(w, h) < MIN_EDGE:
                return None
            arr = np.asarray(im, dtype=np.float32)
            if float(arr.std()) < MIN_STD:
                return None
            if max(w, h) > max_edge:
                im.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
            rgb_arr = np.asarray(im, dtype=np.uint8)
            h_val = phash(rgb_arr)
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=92, optimize=True)
            return buf.getvalue(), im.width, im.height, h_val
    except Exception:
        return None


def _http_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def fetch_inaturalist(
    slug: str,
    taxon_name: str,
    limit: int,
    session: requests.Session,
) -> list[CandidateImage]:
    out: list[CandidateImage] = []
    seen_obs: Counter[str] = Counter()
    page = 1
    while len(out) < limit and page <= 12:
        params = {
            "taxon_name": taxon_name,
            "quality_grade": "research",
            "photos": "true",
            "photo_license": "cc0,cc-by,cc-by-sa,cc-by-nc",
            "per_page": 100,
            "page": page,
            "order_by": "votes",
        }
        try:
            r = session.get("https://api.inaturalist.org/v1/observations", params=params, timeout=20)
            if r.status_code == 429:
                time.sleep(2.0)
                continue
            r.raise_for_status()
            results = r.json().get("results") or []
        except Exception:
            break
        if not results:
            break
        for obs in results:
            obs_id = str(obs.get("id"))
            photos = obs.get("photos") or []
            for p_idx, ph in enumerate(photos):
                if seen_obs[obs_id] >= 2:
                    break
                lic = str(ph.get("license_code") or "").lower()
                if lic not in {"cc0", "cc-by", "cc-by-sa", "cc-by-nc"}:
                    continue
                url = str(ph.get("url") or "").replace("/square.", "/medium.").replace("/thumb.", "/medium.")
                if not url.startswith("http"):
                    continue
                out.append(
                    CandidateImage(
                        slug=slug,
                        source="inaturalist",
                        license=lic,
                        group_id=f"inat:{obs_id}",
                        origin_ref=f"{taxon_name}:obs:{obs_id}:{p_idx}",
                        url=url,
                    )
                )
                seen_obs[obs_id] += 1
                if len(out) >= limit:
                    break
            if len(out) >= limit:
                break
        page += 1
        time.sleep(0.2)
    return out


def fetch_wikimedia(
    slug: str,
    queries: list[str],
    limit: int,
    session: requests.Session,
    *,
    allow_cooked: bool = False,
) -> list[CandidateImage]:
    out: list[CandidateImage] = []
    seen_titles: set[str] = set()
    for q in queries:
        if len(out) >= limit:
            break
        offset = 0
        while len(out) < limit and offset < 250:
            params = {
                "action": "query",
                "generator": "search",
                "gsrsearch": q,
                "gsrnamespace": 6,
                "gsrlimit": 50,
                "gsroffset": offset,
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|mime|size",
                "iiurlwidth": 512,
                "format": "json",
            }
            try:
                r = session.get("https://commons.wikimedia.org/w/api.php", params=params, timeout=20)
                r.raise_for_status()
                pages = (r.json().get("query") or {}).get("pages") or {}
            except Exception:
                break
            if not pages:
                break
            for page_id, page in pages.items():
                title = str(page.get("title") or "")
                if title in seen_titles or not is_clean_wiki_title(title, allow_cooked=allow_cooked):
                    continue
                seen_titles.add(title)
                infos = page.get("imageinfo") or []
                if not infos:
                    continue
                info = infos[0]
                mime = str(info.get("mime") or "")
                if not mime.startswith("image/") or "svg" in mime or "gif" in mime or "tiff" in mime:
                    continue
                url = str(info.get("thumburl") or info.get("url") or "")
                if not url.startswith("http"):
                    continue
                meta = info.get("extmetadata") or {}
                lic_raw = str((meta.get("LicenseShortName") or {}).get("value") or "cc-wiki").lower()
                lic = lic_raw[:32] if lic_raw else "cc-wiki"
                out.append(
                    CandidateImage(
                        slug=slug,
                        source="wikimedia",
                        license=lic,
                        group_id=f"wiki:{page_id}",
                        origin_ref=title,
                        url=url,
                    )
                )
                if len(out) >= limit:
                    break
            offset += 50
            time.sleep(0.2)
    return out


def fetch_mushroom_net(cache_dir: Path, max_ood: int = 200) -> list[CandidateImage]:
    """Selectively fetch ``agaricus_bisporus`` + wild *Agaricus*/*Amanita* OOD from ``ShivRamSaud/mushroom-net``."""
    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi()
    files = api.list_repo_files("ShivRamSaud/mushroom-net", repo_type="dataset")
    agaricus_bis = [f for f in files if f.startswith("data\\train\\agaricus_bisporus\\")]
    wild_ood = [
        f
        for f in files
        if (f.startswith("data\\train\\agaricus_") and not f.startswith("data\\train\\agaricus_bisporus\\"))
        or f.startswith("data\\train\\amanita_")
    ]
    rng = np.random.default_rng(42)
    if len(wild_ood) > max_ood:
        idx = sorted(rng.choice(len(wild_ood), max_ood, replace=False).tolist())
        wild_ood = [wild_ood[i] for i in idx]

    selected = [(f, "nam-mo") for f in agaricus_bis] + [(f, "other_mushroom") for f in wild_ood]
    out: list[CandidateImage] = []
    dl_root = cache_dir / "mushroom_net"
    dl_root.mkdir(parents=True, exist_ok=True)

    def _dl(item: tuple[str, str]) -> CandidateImage | None:
        fpath, slug = item
        try:
            local = hf_hub_download(
                "ShivRamSaud/mushroom-net",
                fpath,
                repo_type="dataset",
                local_dir=str(dl_root),
            )
            stem = fpath.replace("\\", "/").split("/")[-1]
            return CandidateImage(
                slug=slug,
                source="mushroom-net",
                license="cc-by-nc-4.0",
                group_id=f"mnet:{stem}",
                origin_ref=fpath,
                raw_bytes=Path(local).read_bytes(),
            )
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(_dl, selected):
            if res is not None:
                out.append(res)
    return out


def fetch_agml_oyster(cache_dir: Path, limit: int = 220) -> list[CandidateImage]:
    """Fetch cultivated *Pleurotus ostreatus* from ``Project-AgML/oyster_mushroom_maturity_detection``."""
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    dl_root = cache_dir / "agml_oyster"
    dl_root.mkdir(parents=True, exist_ok=True)
    pq_path = hf_hub_download(
        "Project-AgML/oyster_mushroom_maturity_detection",
        "data/train-00000-of-00001.parquet",
        repo_type="dataset",
        local_dir=str(dl_root),
    )
    table = pq.read_table(pq_path)
    cols = table.column_names
    img_col = "image" if "image" in cols else cols[0]
    n = table.num_rows
    rng = np.random.default_rng(42)
    indices = sorted(rng.choice(n, min(limit, n), replace=False).tolist())
    col_data = table[img_col]
    out: list[CandidateImage] = []
    for i in indices:
        val = col_data[i].as_py()
        raw = val.get("bytes") if isinstance(val, dict) else val
        if not isinstance(raw, (bytes, bytearray)):
            continue
        path_hint = str(val.get("path") or f"row_{i}") if isinstance(val, dict) else f"row_{i}"
        grp_token = re.sub(r"[^a-zA-Z0-9]+", "_", path_hint.rsplit("_", 1)[0])[:40]
        out.append(
            CandidateImage(
                slug="nam-so",
                source="agml-oyster",
                license="cc-by-4.0",
                group_id=f"agml:{grp_token}",
                origin_ref=path_hint,
                raw_bytes=bytes(raw),
            )
        )
    return out


def fetch_fungi_id(cache_dir: Path, limit_per_class: dict[str, int] | None = None) -> list[CandidateImage]:
    """Selectively extract target & OOD species from ``meed2000/fungi-id``."""
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    dl_root = cache_dir / "fungi_id"
    dl_root.mkdir(parents=True, exist_ok=True)
    labels_path = hf_hub_download("meed2000/fungi-id", "mushroom_labels.json", repo_type="dataset", local_dir=str(dl_root))
    pq_path = hf_hub_download(
        "meed2000/fungi-id", "data/train-00000-of-00001.parquet", repo_type="dataset", local_dir=str(dl_root)
    )
    labels_raw = json.loads(Path(labels_path).read_text(encoding="utf-8"))
    if isinstance(labels_raw, dict):
        id_to_name = {int(k): str(v) for k, v in labels_raw.items()}
    else:
        id_to_name = {i: str(v) for i, v in enumerate(labels_raw)}

    def _map_species(name: str) -> str | None:
        low = name.lower()
        if "agaricus bisporus" in low:
            return "nam-mo"
        if "flammulina velutipes" in low or "flammulina filiformis" in low:
            return "nam-kim-cham"
        if "pleurotus ostreatus" in low or "pleurotus pulmonarius" in low:
            return "nam-so"
        if "pleurotus eryngii" in low:
            return "nam-dui-ga"
        if "lentinula edodes" in low:
            return "nam-huong-tuoi"
        if "volvariella volvacea" in low:
            return "nam-rom"
        if any(g in low for g in ("amanita ", "russula ", "cortinarius ", "boletus ", "galerina ")):
            return "other_mushroom"
        return None

    caps = limit_per_class or {"nam-mo": 80, "nam-kim-cham": 80, "nam-so": 80, "other_mushroom": 160}
    table = pq.read_table(pq_path)
    cols = table.column_names
    img_col = "image" if "image" in cols else cols[0]
    lbl_col = "label" if "label" in cols else cols[1]
    labels_col = table[lbl_col].to_pylist()
    rng = np.random.default_rng(42)
    order = rng.permutation(len(labels_col)).tolist()
    counts: Counter[str] = Counter()
    chosen: list[tuple[int, str, str]] = []
    for i in order:
        lbl = labels_col[i]
        sp_name = id_to_name.get(int(lbl), str(lbl)) if isinstance(lbl, int) else str(lbl)
        slug = _map_species(sp_name)
        if slug is None:
            continue
        cap = caps.get(slug, 0)
        if counts[slug] >= cap:
            continue
        counts[slug] += 1
        chosen.append((i, slug, sp_name))

    col_img = table[img_col]
    out: list[CandidateImage] = []
    for i, slug, sp_name in chosen:
        val = col_img[i].as_py()
        raw = val.get("bytes") if isinstance(val, dict) else val
        if not isinstance(raw, (bytes, bytearray)):
            continue
        out.append(
            CandidateImage(
                slug=slug,
                source="fungi-id",
                license="cc-by-nc-4.0",
                group_id=f"fungiid:{i}",
                origin_ref=sp_name,
                raw_bytes=bytes(raw),
            )
        )
    return out


def extract_yolo_v4_hard_negatives(
    yolo_v4_dir: Path = DEFAULT_YOLO_V4_DIR,
    *,
    total_cap: int = 1600,
    seed: int = 42,
) -> list[CandidateImage]:
    """Crop non-``nam`` boxes from ``yolo_v4`` as ``not_mushroom`` hard negatives.

    Strictly preserves ``train/val/test`` alignment from ``yolo_v4`` and skips any box
    overlapping with a ``nam`` box in the same image.
    """
    if not yolo_v4_dir.is_dir():
        return []

    rng = np.random.default_rng(seed)
    split_mult = {"train": 0.76, "val": 0.12, "test": 0.12}
    per_cls_boxes: dict[tuple[str, int], list[tuple[Path, str, tuple[float, float, float, float]]]] = defaultdict(list)

    for split in ("train", "val", "test"):
        lbl_dir = yolo_v4_dir / "labels" / split
        img_dir = yolo_v4_dir / "images" / split
        if not lbl_dir.is_dir():
            continue
        for lp in sorted(lbl_dir.glob("*.txt")):
            parsed: list[tuple[int, float, float, float, float]] = []
            for ln in lp.read_text(encoding="utf-8").splitlines():
                parts = ln.strip().split()
                if len(parts) >= 5:
                    parsed.append((int(parts[0]), *map(float, parts[1:5])))
            if not parsed:
                continue
            nam_boxes = [
                (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
                for cid, cx, cy, w, h in parsed
                if cid == YOLO_NAM_CLASS_IDX
            ]
            img_path = None
            for ext in (".jpg", ".jpeg", ".png", ".webp"):
                cand = img_dir / (lp.stem + ext)
                if cand.is_file():
                    img_path = cand
                    break
            if img_path is None:
                continue
            for cid, cx, cy, w, h in parsed:
                if cid not in YOLO_HARD_NEG_CLASSES:
                    continue
                x1, y1, x2, y2 = max(0.0, cx - w / 2), max(0.0, cy - h / 2), min(1.0, cx + w / 2), min(1.0, cy + h / 2)
                # Skip if overlapping a nam box
                overlap_nam = any(
                    max(0.0, min(x2, nx2) - max(x1, nx1)) * max(0.0, min(y2, ny2) - max(y1, ny1)) > 0.0
                    for nx1, ny1, nx2, ny2 in nam_boxes
                )
                if overlap_nam:
                    continue
                per_cls_boxes[(split, cid)].append((img_path, lp.stem, (x1, y1, x2, y2)))

    out: list[CandidateImage] = []
    for (split, cid), items in sorted(per_cls_boxes.items()):
        cls_name, base_cap = YOLO_HARD_NEG_CLASSES[cid]
        cap = max(2, int(round(base_cap * split_mult[split] * (total_cap / 1600.0))))
        if len(items) > cap:
            chosen_idx = sorted(rng.choice(len(items), cap, replace=False).tolist())
            items = [items[i] for i in chosen_idx]
        for b_idx, (img_path, stem, (x1, y1, x2, y2)) in enumerate(items):
            try:
                with Image.open(img_path) as im:
                    rgb = ImageOps.exif_transpose(im).convert("RGB")
                    W, H = rgb.size
                    px1 = max(0, min(W - 1, math.floor(x1 * W)))
                    py1 = max(0, min(H - 1, math.floor(y1 * H)))
                    px2 = max(px1 + 1, min(W, math.ceil(x2 * W)))
                    py2 = max(py1 + 1, min(H, math.ceil(y2 * H)))
                    if min(px2 - px1, py2 - py1) < MIN_EDGE:
                        continue
                    crop = rgb.crop((px1, py1, px2, py2))
                    buf = io.BytesIO()
                    crop.save(buf, format="JPEG", quality=92)
                    out.append(
                        CandidateImage(
                            slug="not_mushroom",
                            source="yolo-hard-neg",
                            license="yolo-v4-local",
                            group_id=f"yolo:{stem}",
                            origin_ref=f"{split}:{cls_name}:{stem}:{b_idx}",
                            raw_bytes=buf.getvalue(),
                            fixed_split=split,
                        )
                    )
            except Exception:
                continue
    return out


def filter_wild_enoki_with_siglip2(
    records: list[dict[str, Any]],
    cache_dir: Path,
    *,
    white_prob_min: float = 0.50,
    relabel_wild_to_other: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Filter wild forest orange *Flammulina velutipes* out of white culinary ``nam-kim-cham``."""
    enoki_idx = [i for i, r in enumerate(records) if r["slug"] == "nam-kim-cham"]
    if not enoki_idx:
        return records, {"checked": 0, "kept_white": 0, "filtered_wild": 0}

    import open_clip
    import torch

    os.environ.setdefault("HF_HOME", str(cache_dir / "hf_clip"))
    os.environ.setdefault("TORCH_HOME", str(cache_dir / "torch_clip"))
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        try:
            torch.cuda.set_per_process_memory_fraction(0.15)
        except Exception:
            pass
    try:
        tokenizer = open_clip.get_tokenizer("ViT-B-16-SigLIP2")
        model, _, preprocess = open_clip.create_model_and_transforms("ViT-B-16-SigLIP2", pretrained="webli", device=device)
    except Exception:
        tokenizer = open_clip.get_tokenizer("ViT-B-16")
        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-B-16", pretrained="openai", quick_gelu=True, device=device
        )
    prompts = [
        "white cultivated enoki mushrooms in a bundle or plastic pack, pale slender stems, grocery store food",
        "wild orange or brown mushrooms growing on tree bark, wood, or mossy forest floor outdoors",
    ]
    with torch.no_grad():
        txt_tok = tokenizer(prompts).to(device)
        txt_feat = model.encode_text(txt_tok)
        txt_feat = txt_feat / txt_feat.norm(dim=-1, keepdim=True)
        logit_scale = model.logit_scale.exp()
        raw_bias = getattr(model, "logit_bias", None)
        logit_bias = raw_bias if raw_bias is not None else 0.0

        kept = 0
        filtered = 0
        out = [dict(r) for r in records]
        batch_imgs = []
        batch_pos = []

        def _flush() -> None:
            nonlocal kept, filtered
            if not batch_imgs:
                return
            xb = torch.stack(batch_imgs, dim=0).to(device)
            img_feat = model.encode_image(xb)
            img_feat = img_feat / img_feat.norm(dim=-1, keepdim=True)
            logits = img_feat @ txt_feat.T * logit_scale + logit_bias
            probs = torch.softmax(logits, dim=-1).cpu().numpy()
            for r_pos, p_row in zip(batch_pos, probs, strict=True):
                p_white = float(p_row[0])
                if p_white >= white_prob_min:
                    kept += 1
                else:
                    filtered += 1
                    if relabel_wild_to_other:
                        out[r_pos]["slug"] = "other_mushroom"
                        out[r_pos]["origin_ref"] = f"wild_enoki_filtered:{out[r_pos]['origin_ref']}"
                    else:
                        out[r_pos]["_drop"] = True
            batch_imgs.clear()
            batch_pos.clear()

        for i in enoki_idx:
            with Image.open(records[i]["pool_path"]) as im:
                batch_imgs.append(preprocess(im.convert("RGB")))
                batch_pos.append(i)
            if len(batch_imgs) >= 64:
                _flush()
        _flush()

    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    final = [r for r in out if not r.get("_drop")]
    return final, {"checked": len(enoki_idx), "kept_white": kept, "filtered_wild": filtered}


def deduplicate_records(records: list[dict[str, Any]], threshold: int = DEDUP_HAMMING) -> list[dict[str, Any]]:
    """Remove near-duplicates across ALL classes and within classes (``Hamming <= threshold``)."""
    n = len(records)
    if n == 0:
        return []
    hashes = np.array([int(r["phash"]) for r in records], dtype=np.uint64)
    slugs = [r["slug"] for r in records]
    keep = np.ones(n, dtype=bool)
    kept_hashes: list[int] = []
    kept_indices: list[int] = []

    for i in range(n):
        if not keep[i]:
            continue
        hi = hashes[i]
        if kept_hashes:
            dists = hamming(np.asarray(kept_hashes, dtype=np.uint64), hi)
            hits = np.where(dists <= threshold)[0]
            if hits.size > 0:
                for h_idx in hits:
                    prev_i = kept_indices[int(h_idx)]
                    if slugs[prev_i] != slugs[i]:
                        keep[prev_i] = False
                keep[i] = False
                continue
        kept_hashes.append(int(hi))
        kept_indices.append(i)

    return [records[i] for i in range(n) if keep[i]]


def merge_near_groups(
    records: list[dict[str, Any]],
    merge_hamming: int = GROUP_MERGE_HAMMING,
) -> list[dict[str, Any]]:
    """Union-Find group merging on shared ``group_id`` and same-class pHash ``<= merge_hamming``."""
    n = len(records)
    if n == 0:
        return records
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    first_by_gid: dict[str, int] = {}
    for i, r in enumerate(records):
        gid = r["group_id"]
        if gid in first_by_gid:
            union(i, first_by_gid[gid])
        else:
            first_by_gid[gid] = i

    by_slug: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(records):
        by_slug[r["slug"]].append(i)

    hashes = np.array([int(r["phash"]) for r in records], dtype=np.uint64)
    for idxs in by_slug.values():
        if len(idxs) < 2:
            continue
        arr = np.asarray(idxs, dtype=np.int64)
        hs = hashes[arr]
        for a in range(len(arr) - 1):
            d = hamming(hs[a + 1 :], int(hs[a]))
            for hit in np.where(d <= merge_hamming)[0]:
                union(int(arr[a]), int(arr[a + 1 + int(hit)]))

    out = []
    for i, r in enumerate(records):
        rec = dict(r)
        rec["split_group"] = f"g_{find(i)}"
        out.append(rec)
    return out


def assign_stratified_group_splits(
    records: list[dict[str, Any]],
    val_frac: float = 0.12,
    test_frac: float = 0.12,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Assign ``train`` / ``val`` / ``test`` splits respecting ``split_group`` and ``fixed_split``."""
    rng = np.random.default_rng(seed)
    by_group: dict[str, list[int]] = defaultdict(list)
    for i, r in enumerate(records):
        by_group[r["split_group"]].append(i)

    class_counts = Counter(r["slug"] for r in records)
    target_val = {c: max(1, round(class_counts[c] * val_frac)) for c in class_counts}
    target_test = {c: max(1, round(class_counts[c] * test_frac)) for c in class_counts}
    got_val: Counter[str] = Counter()
    got_test: Counter[str] = Counter()

    group_split: dict[str, str] = {}
    free_groups: list[tuple[str, list[int]]] = []
    for gid, idxs in by_group.items():
        locked = {records[i].get("fixed_split") for i in idxs if records[i].get("fixed_split")}
        if len(locked) == 1:
            sp = next(iter(locked))
            group_split[gid] = sp
            for i in idxs:
                if sp == "val":
                    got_val[records[i]["slug"]] += 1
                elif sp == "test":
                    got_test[records[i]["slug"]] += 1
        elif len(locked) > 1:
            # Extremely rare cross-yolo-split hash merge -> assign majority or train
            sp = "train"
            group_split[gid] = sp
        else:
            free_groups.append((gid, idxs))

    rng.shuffle(free_groups)
    free_groups.sort(
        key=lambda kv: (
            min(class_counts[records[i]["slug"]] for i in kv[1]),
            -len(kv[1]),
        )
    )

    for gid, idxs in free_groups:
        g_classes = Counter(records[i]["slug"] for i in idxs)
        can_val = all(got_val[c] + n <= max(1, int(class_counts[c] * (val_frac + 0.05))) for c, n in g_classes.items())
        can_test = all(got_test[c] + n <= max(1, int(class_counts[c] * (test_frac + 0.05))) for c, n in g_classes.items())
        need_test = sum(max(0, target_test[c] - got_test[c]) for c in g_classes)
        need_val = sum(max(0, target_val[c] - got_val[c]) for c in g_classes)

        if can_test and need_test > 0 and (need_test >= need_val):
            sp = "test"
        elif can_val and need_val > 0:
            sp = "val"
        else:
            sp = "train"

        group_split[gid] = sp
        for c, n in g_classes.items():
            if sp == "test":
                got_test[c] += n
            elif sp == "val":
                got_val[c] += n

    out = []
    for r in records:
        rec = dict(r)
        rec["split"] = group_split[r["split_group"]]
        out.append(rec)
    return out


def verify_zero_leakage(records: list[dict[str, Any]], threshold: int = DEDUP_HAMMING) -> dict[str, Any]:
    """Verify zero shared ``split_group`` and zero cross-split pHash ``<= threshold``."""
    groups_by_split: dict[str, set[str]] = defaultdict(set)
    for r in records:
        groups_by_split[r["split"]].add(r["split_group"])

    splits = list(groups_by_split)
    group_overlap = 0
    for i in range(len(splits)):
        for j in range(i + 1, len(splits)):
            group_overlap += len(groups_by_split[splits[i]] & groups_by_split[splits[j]])

    train_h = np.array([int(r["phash"]) for r in records if r["split"] == "train"], dtype=np.uint64)
    eval_h = np.array([int(r["phash"]) for r in records if r["split"] in ("val", "test")], dtype=np.uint64)
    cross_phash_le_thr = 0
    if train_h.size and eval_h.size:
        for eh in eval_h:
            if int(hamming(train_h, int(eh)).min()) <= threshold:
                cross_phash_le_thr += 1

    val_h = np.array([int(r["phash"]) for r in records if r["split"] == "val"], dtype=np.uint64)
    test_h = np.array([int(r["phash"]) for r in records if r["split"] == "test"], dtype=np.uint64)
    if val_h.size and test_h.size:
        for th in test_h:
            if int(hamming(val_h, int(th)).min()) <= threshold:
                cross_phash_le_thr += 1

    if group_overlap > 0 or cross_phash_le_thr > 0:
        raise RuntimeError(
            f"Leakage detected: group_overlap={group_overlap}, cross_phash_le_{threshold}={cross_phash_le_thr}"
        )
    return {"group_overlap": 0, f"cross_split_phash_le_{threshold}": 0}


def _load_existing_stage_candidates(stage_dir: Path) -> list[CandidateImage]:
    manifest = stage_dir / "manifest.csv"
    if not manifest.is_file():
        return []
    df = pd.read_csv(manifest)
    out: list[CandidateImage] = []
    for row in df.itertuples(index=False):
        p = stage_dir / str(row.rel_path)
        if not p.is_file():
            continue
        out.append(
            CandidateImage(
                slug=str(row.slug),
                source=str(row.source),
                license=str(row.license),
                group_id=str(row.group_id),
                origin_ref=str(row.origin_ref),
                raw_bytes=p.read_bytes(),
            )
        )
    return out


def materialize_dataset(
    candidates: list[CandidateImage],
    stage_dir: Path,
    *,
    max_per_class: int = 500,
    max_not_mushroom: int = 2000,
    workers: int = 12,
    apply_siglip_enoki_filter: bool = True,
) -> dict[str, Any]:
    """Download/decode candidates, SigLIP-filter enoki, normalize, dedupe, split, and write tree."""
    stage_dir = Path(stage_dir)
    raw_dir = stage_dir / "_pool"
    if raw_dir.exists():
        shutil.rmtree(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    session = _http_session()

    def _process(cand: CandidateImage) -> dict[str, Any] | None:
        raw = cand.raw_bytes
        if raw is None:
            if not cand.url:
                return None
            for attempt in range(2):
                try:
                    resp = session.get(cand.url, timeout=20)
                    if resp.status_code == 429:
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    if resp.status_code != 200:
                        return None
                    raw = resp.content
                    break
                except Exception:
                    if attempt == 0:
                        time.sleep(0.5)
            if raw is None:
                return None
        norm = _normalize_and_hash(raw)
        if norm is None:
            return None
        jpg_bytes, w, h, ph = norm
        sha = hashlib.sha256(jpg_bytes).hexdigest()[:16]
        fname = f"{cand.slug}_{cand.source}_{sha}.jpg"
        p = raw_dir / fname
        p.write_bytes(jpg_bytes)
        return {
            "slug": cand.slug,
            "source": cand.source,
            "license": cand.license,
            "group_id": cand.group_id,
            "origin_ref": cand.origin_ref,
            "pool_path": p,
            "width": w,
            "height": h,
            "phash": str(ph),
            "fixed_split": cand.fixed_split,
        }

    priority = {"wikimedia": 0, "agml-oyster": 1, "mushroom-net": 2, "inaturalist": 3, "fungi-id": 4, "yolo-hard-neg": 5}
    ordered = sorted(candidates, key=lambda c: priority.get(c.source, 9))
    records: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_process, c) for c in ordered]
        for fut in as_completed(futures):
            res = fut.result()
            if res is not None:
                records.append(res)

    records.sort(key=lambda r: (priority.get(r["source"], 9), r["slug"], r["origin_ref"]))

    enoki_filter_stats: dict[str, int] = {"checked": 0, "kept_white": 0, "filtered_wild": 0}
    if apply_siglip_enoki_filter:
        records, enoki_filter_stats = filter_wild_enoki_with_siglip2(
            records, cache_dir=stage_dir / "_hf_cache", white_prob_min=0.50, relabel_wild_to_other=True
        )
        print(f"[ingest] SigLIP2 enoki filter: {enoki_filter_stats}", flush=True)

    deduped = deduplicate_records(records, threshold=DEDUP_HAMMING)

    by_slug_src: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for r in deduped:
        by_slug_src[r["slug"]][r["source"]].append(r)

    capped: list[dict[str, Any]] = []
    for slug in CLASSES:
        cap = max_not_mushroom if slug == "not_mushroom" else (650 if slug == "other_mushroom" else max_per_class)
        src_map = by_slug_src.get(slug, {})
        if not src_map:
            continue
        selected: list[dict[str, Any]] = []
        src_keys = sorted(src_map.keys(), key=lambda s: priority.get(s, 9))
        idx = 0
        while len(selected) < cap:
            added = False
            for sk in src_keys:
                lst = src_map[sk]
                if idx < len(lst):
                    selected.append(lst[idx])
                    added = True
                    if len(selected) >= cap:
                        break
            if not added:
                break
            idx += 1
        capped.extend(selected)

    grouped = merge_near_groups(capped, merge_hamming=GROUP_MERGE_HAMMING)
    split_recs = assign_stratified_group_splits(grouped, val_frac=0.12, test_frac=0.12, seed=42)
    leakage = verify_zero_leakage(split_recs, threshold=DEDUP_HAMMING)

    img_root = stage_dir / "images"
    if img_root.exists():
        shutil.rmtree(img_root)
    manifest_rows: list[dict[str, Any]] = []
    for r in split_recs:
        dst = img_root / r["split"] / r["slug"] / r["pool_path"].name
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(r["pool_path"], dst)
        manifest_rows.append({
            "rel_path": str(dst.relative_to(stage_dir)),
            "slug": r["slug"],
            "split": r["split"],
            "source": r["source"],
            "license": r["license"],
            "group_id": r["group_id"],
            "split_group": r["split_group"],
            "origin_ref": r["origin_ref"],
            "width": r["width"],
            "height": r["height"],
            "phash": r["phash"],
        })

    shutil.rmtree(raw_dir, ignore_errors=True)
    df = pd.DataFrame(manifest_rows)
    df.to_csv(stage_dir / "manifest.csv", index=False)

    summary = {
        "total_downloaded_valid": len(records),
        "total_after_dedup": len(deduped),
        "total_final": len(df),
        "siglip2_enoki_filter": enoki_filter_stats,
        "leakage_check": leakage,
        "by_split_class": {
            sp: {cl: int(((df["split"] == sp) & (df["slug"] == cl)).sum()) for cl in CLASSES}
            for sp in ("train", "val", "test")
        },
        "by_source": {k: int(v) for k, v in df["source"].value_counts().to_dict().items()},
        "by_license": {k: int(v) for k, v in df["license"].value_counts().to_dict().items()},
    }
    (stage_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def run_ingest(
    stage_dir: Path = DEFAULT_STAGE_DIR,
    max_per_class: int = 450,
    max_not_mushroom: int = 2000,
    workers: int = 12,
    augment_existing: bool = False,
) -> dict[str, Any]:
    stage_dir = Path(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = stage_dir / "_hf_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    session = _http_session()

    candidates: list[CandidateImage] = []
    if augment_existing and (stage_dir / "manifest.csv").is_file():
        existing = _load_existing_stage_candidates(stage_dir)
        print(f"[ingest] reusing {len(existing)} existing staged mushroom images...", flush=True)
        candidates.extend(existing)
    else:
        print("[ingest] fetching ShivRamSaud/mushroom-net subset...", flush=True)
        candidates.extend(fetch_mushroom_net(cache_dir, max_ood=200))
        print("[ingest] fetching Project-AgML/oyster_mushroom_maturity_detection...", flush=True)
        candidates.extend(fetch_agml_oyster(cache_dir, limit=220))
        print("[ingest] fetching meed2000/fungi-id subset...", flush=True)
        candidates.extend(fetch_fungi_id(cache_dir))

        for slug, queries in WIKI_QUERIES.items():
            if slug in ("other_mushroom", "not_mushroom"):
                continue
            w_cands = fetch_wikimedia(slug, queries, limit=260, session=session)
            candidates.extend(w_cands)
            print(f"[ingest] wikimedia {slug}: {len(w_cands)}", flush=True)

        for slug, taxons in INAT_TAXON_QUERIES.items():
            if slug == "other_mushroom":
                continue
            for taxon_name, lim in taxons:
                i_cands = fetch_inaturalist(slug, taxon_name, limit=lim, session=session)
                candidates.extend(i_cands)
                print(f"[ingest] iNat {slug} ({taxon_name}): {len(i_cands)}", flush=True)

    # Always fetch deadly lookalikes (other_mushroom) + hard negatives (not_mushroom) + extra white enoki
    if augment_existing:
        extra_enoki = fetch_wikimedia(
            "nam-kim-cham",
            ['"enoki mushroom"', '"enokitake"', '"Flammulina filiformis"'],
            limit=120,
            session=session,
        )
        candidates.extend(extra_enoki)
        print(f"[ingest] extra wikimedia white enoki: {len(extra_enoki)}", flush=True)

    for taxon_name, lim in INAT_TAXON_QUERIES["other_mushroom"]:
        i_cands = fetch_inaturalist("other_mushroom", taxon_name, limit=lim, session=session)
        candidates.extend(i_cands)
        print(f"[ingest] iNat deadly/OOD ({taxon_name}): {len(i_cands)}", flush=True)

    w_deadly = fetch_wikimedia("other_mushroom", WIKI_QUERIES["other_mushroom"], limit=200, session=session)
    candidates.extend(w_deadly)
    print(f"[ingest] wikimedia deadly lookalikes: {len(w_deadly)}", flush=True)

    w_not_mush = fetch_wikimedia(
        "not_mushroom", WIKI_QUERIES["not_mushroom"], limit=450, session=session, allow_cooked=True
    )
    candidates.extend(w_not_mush)
    print(f"[ingest] wikimedia not_mushroom hard negatives: {len(w_not_mush)}", flush=True)

    yolo_neg = extract_yolo_v4_hard_negatives(total_cap=1650)
    candidates.extend(yolo_neg)
    print(f"[ingest] yolo_v4 not_mushroom hard-negative crops: {len(yolo_neg)}", flush=True)

    summary = materialize_dataset(
        candidates,
        stage_dir,
        max_per_class=max_per_class,
        max_not_mushroom=max_not_mushroom,
        workers=workers,
        apply_siglip_enoki_filter=True,
    )
    shutil.rmtree(cache_dir, ignore_errors=True)
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage-dir", type=Path, default=DEFAULT_STAGE_DIR)
    ap.add_argument("--max-per-class", type=int, default=450)
    ap.add_argument("--max-not-mushroom", type=int, default=2000)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--augment-existing", action="store_true")
    a = ap.parse_args()
    summary = run_ingest(
        a.stage_dir,
        max_per_class=a.max_per_class,
        max_not_mushroom=a.max_not_mushroom,
        workers=a.workers,
        augment_existing=a.augment_existing,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
