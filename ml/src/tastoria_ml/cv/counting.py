"""Counting metrics for countable classes (thiết kế v2 §7).

Evaluation unit: an (image, countable class) pair with c > 0 or ĉ > 0, where c is the number of GT boxes
and ĉ the number of detections with score ≥ conf (after NMS / the NMS-free head).

* MAE = mean |ĉ − c|; relative MAE = Σ|ĉ − c| / Σ c (pooled, so pairs with c = 0 contribute their error
  without a division by zero); exact = share of pairs with ĉ = c; ±1 = share with |ĉ − c| ≤ 1.
* conf is chosen on val (grid 0.05…0.95, min pooled MAE over the countable classes) and then fixed for test.
* Baseline "median per class": ĉ = median of c over train pairs with c > 0, predicted for every pair where
  the class is present in GT (it therefore gets presence for free and is an optimistic baseline).
* Open Images group-of boxes (one box around a heap) do not tell how many objects there are, so a pair
  whose class has a group-of box in that image is excluded and the exclusion count is reported.

Metric functions are pure numpy and unit tested; ``python -m tastoria_ml.cv.counting <run> [--mode nms]``
reads the prediction dumps of ``predict_dump`` (numpy only).
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from tastoria_ml.cv.classes import REPO, load_classes

YOLO_DIR = REPO / "data" / "processed" / "cv" / "yolo"
OUT = REPO / "data" / "processed" / "cv" / "counting"
CONF_GRID = np.round(np.arange(0.05, 0.951, 0.05), 2)


def count_metrics(c: np.ndarray, chat: np.ndarray) -> dict:
    c = np.asarray(c, int).ravel()
    chat = np.asarray(chat, int).ravel()
    keep = (c > 0) | (chat > 0)
    c, chat = c[keep], chat[keep]
    if len(c) == 0:
        return {"n_pairs": 0, "mae": None, "rel_mae": None, "exact": None, "within1": None}
    e = np.abs(chat - c)
    return {
        "n_pairs": int(len(c)),
        "mae": float(e.mean()),
        "rel_mae": float(e.sum() / max(c.sum(), 1)),
        "exact": float((e == 0).mean()),
        "within1": float((e <= 1).mean()),
        "mean_true": float(c.mean()),
        "mean_pred": float(chat.mean()),
    }


def gt_counts(files: np.ndarray, split: str, n_classes: int) -> np.ndarray:
    out = np.zeros((len(files), n_classes), int)
    for i, f in enumerate(files):
        p = YOLO_DIR / "labels" / split / (Path(str(f)).stem + ".txt")
        if p.exists():
            for line in p.read_text().splitlines():
                if line.strip():
                    out[i, int(line.split()[0])] += 1
    return out


def pred_counts(pred: dict, n_images: int, n_classes: int, conf: float) -> np.ndarray:
    k = pred["scores"] >= conf
    out = np.zeros((n_images, n_classes), int)
    np.add.at(out, (pred["img"][k], pred["cls"][k].astype(int)), 1)
    return out


def masked_metrics(c: np.ndarray, chat: np.ndarray, excluded: np.ndarray, cols: list[int]) -> dict:
    m = ~excluded[:, cols]
    return count_metrics(c[:, cols][m], chat[:, cols][m])


def choose_conf(c: np.ndarray, pred: dict, cols: list[int], excluded: np.ndarray | None = None,
                grid=CONF_GRID) -> tuple[float, list]:
    """conf minimising pooled MAE over ``cols`` (ties -> lower conf)."""
    n_img, n_cls = c.shape
    excluded = np.zeros_like(c, bool) if excluded is None else excluded
    curve = []
    for t in grid:
        ch = pred_counts(pred, n_img, n_cls, float(t))
        curve.append((float(t), masked_metrics(c, ch, excluded, cols)["mae"]))
    best = min(curve, key=lambda x: (x[1], x[0]))
    return best[0], curve


def group_of_pairs(split: str, files: np.ndarray, names: list[str]) -> np.ndarray:
    """Boolean (n_images, n_classes): True when that class has an Open Images group-of box in the image."""
    from tastoria_ml.cv import openimages as oi
    from tastoria_ml.cv.classes import source_label_map

    oi_split = {"val": "validation", "test": "test", "train": "train"}[split]
    lab = source_label_map(load_classes(), "openimages_v7")
    mids = oi.label_mids()
    gof = defaultdict(set)
    for b in oi.read_boxes(oi_split):
        if b["IsGroupOf"] == "1":
            gof[b["ImageID"]].add(lab[mids[b["LabelName"]]].id)
    idx = {n: k for k, n in enumerate(names)}
    out = np.zeros((len(files), len(names)), bool)
    for i, f in enumerate(files):
        f = Path(str(f)).stem
        if f.startswith("openimages_v7__"):
            for cid in gof.get(f.split("__")[-1], ()):
                if cid in idx:
                    out[i, idx[cid]] = True
    return out


def train_medians(names: list[str]) -> dict[int, int]:
    counts = defaultdict(list)
    for p in (YOLO_DIR / "labels" / "train").glob("*.txt"):
        per = defaultdict(int)
        for line in p.read_text().splitlines():
            if line.strip():
                per[int(line.split()[0])] += 1
        for k, v in per.items():
            counts[k].append(v)
    return {k: int(np.median(v)) for k, v in counts.items()}


def _load(name: str, split: str, mode: str) -> dict:
    from tastoria_ml.cv.predict_dump import pred_path

    z = np.load(pred_path(name, split, mode))
    return {k: z[k] for k in z.files}


def evaluate(name: str, mode: str = "nms") -> dict:
    countable = {c.id for c in load_classes() if c.countable}
    val = _load(name, "val", mode)
    names = [str(n) for n in val["names"]]
    cols = [k for k, n in enumerate(names) if n in countable]
    res = {"run": name, "mode": mode, "countable_classes": [names[k] for k in cols]}
    data = {}
    for split in ("val", "test"):
        pr = val if split == "val" else _load(name, split, mode)
        c = gt_counts(pr["files"], split, len(names))
        gof = group_of_pairs(split, pr["files"], names)
        data[split] = (pr, c, gof)
    pr, c, gof = data["val"]
    conf, curve = choose_conf(c, pr, cols, gof)
    res["conf_selected_on_val"] = conf
    res["val_curve"] = curve
    med = train_medians(names)
    pr, c, gof = data["test"]
    ch = pred_counts(pr, len(c), len(names), conf)
    base = np.zeros_like(c)
    for k in cols:
        base[:, k] = np.where(c[:, k] > 0, med.get(k, 1), 0)
    res["test"] = {
        "excluded_group_of_pairs": int(gof[:, cols].sum()),
        "detector": masked_metrics(c, ch, gof, cols),
        "median_baseline": masked_metrics(c, base, gof, cols),
        "per_class": {},
    }
    for k in cols:
        res["test"]["per_class"][names[k]] = {
            "detector": masked_metrics(c, ch, gof, [k]),
            "median_baseline": masked_metrics(c, base, gof, [k]),
            "train_median": med.get(k),
        }
    # by source
    src = np.array(["bd" if "mendeley_bd" in str(f) else "oi" for f in pr["files"]])
    res["test"]["by_source"] = {}
    for s in ("oi", "bd"):
        m = src == s
        res["test"]["by_source"][s] = masked_metrics(c[m], ch[m], gof[m], cols)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}__{mode}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--mode", default="nms")
    a = ap.parse_args()
    r = evaluate(a.run, a.mode)
    print(json.dumps({k: r[k] for k in ("conf_selected_on_val",)} | {"test": r["test"]["detector"],
                     "median": r["test"]["median_baseline"]}, indent=2))


if __name__ == "__main__":
    main()

