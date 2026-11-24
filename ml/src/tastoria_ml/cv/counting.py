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
YOLO_V2_DIR = REPO / "data" / "processed" / "cv" / "yolo_v2"
OUT = REPO / "data" / "processed" / "cv" / "counting"
OUT_V2 = REPO / "ml" / "runs" / "research" / "p1_detection" / "counting"
CONF_GRID = np.round(np.arange(0.05, 0.951, 0.05), 2)


def resolve_yolo_dir(dataset: str | Path = "yolo", yolo_dir: str | Path | None = None) -> Path:
    if yolo_dir is not None:
        return Path(yolo_dir)
    if str(dataset) == "yolo":
        return YOLO_DIR
    if str(dataset) == "yolo_v2":
        return YOLO_V2_DIR
    p = Path(dataset)
    if p.exists():
        return p
    raise ValueError(f"Unknown dataset '{dataset}' and path does not exist")


def countable_ids(include_proposed: bool = False) -> set[str]:
    if not include_proposed:
        return {c.id for c in load_classes() if c.countable}
    from tastoria_ml.cv.build_yolo_v2 import all_class_rows

    return {str(r["id"]) for r in all_class_rows() if r.get("countable")}


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


def gt_counts(files: np.ndarray, split: str, n_classes: int, yolo_dir: Path = YOLO_DIR) -> np.ndarray:
    out = np.zeros((len(files), n_classes), int)
    for i, f in enumerate(files):
        p = yolo_dir / "labels" / split / (Path(str(f)).stem + ".txt")
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
        mae = masked_metrics(c, ch, excluded, cols)["mae"]
        curve.append((float(t), mae if mae is not None else float("inf")))
    best = min(curve, key=lambda x: (x[1], x[0]))
    return best[0], curve


def group_of_pairs(split: str, files: np.ndarray, names: list[str]) -> np.ndarray:
    """Boolean (n_images, n_classes): True when that class has an Open Images group-of box in the image."""
    oi_split = {"val": "validation", "test": "test", "train": "train"}.get(split)
    has_oi = any(Path(str(f)).stem.startswith("openimages_v7__") for f in files)
    if oi_split is None or not has_oi:
        return np.zeros((len(files), len(names)), bool)

    from tastoria_ml.cv import openimages as oi
    from tastoria_ml.cv.classes import source_label_map

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


def train_medians(names: list[str], yolo_dir: Path = YOLO_DIR) -> dict[int, int]:
    counts = defaultdict(list)
    for p in (yolo_dir / "labels" / "train").glob("*.txt"):
        per = defaultdict(int)
        for line in p.read_text().splitlines():
            if line.strip():
                per[int(line.split()[0])] += 1
        for k, v in per.items():
            counts[k].append(v)
    return {k: int(np.median(v)) for k, v in counts.items()}


def per_pair_errors(
    c: np.ndarray,
    chat: np.ndarray,
    excluded: np.ndarray,
    cols: list[int],
    files: np.ndarray | None = None,
    mask: np.ndarray | None = None,
) -> dict[str, np.ndarray]:
    """Aligned per-(image, countable_class) error arrays and cluster IDs for paired inference."""
    c_sub = np.asarray(c[:, cols], dtype=int)
    ch_sub = np.asarray(chat[:, cols], dtype=int)
    exc_sub = np.asarray(excluded[:, cols], dtype=bool)
    if mask is None:
        m = (~exc_sub) & ((c_sub > 0) | (ch_sub > 0))
    else:
        m = np.asarray(mask, dtype=bool) & (~exc_sub)
    c_flat = c_sub[m]
    ch_flat = ch_sub[m]
    abs_err = np.abs(ch_flat - c_flat).astype(np.float64)
    out: dict[str, np.ndarray] = {
        "c": c_flat,
        "chat": ch_flat,
        "abs_err": abs_err,
        "exact": ch_flat == c_flat,
        "within1": abs_err <= 1.0,
        "mask": m,
    }
    if files is not None:
        from tastoria_ml.cv.det_eval import clusters

        cl_img = clusters(np.asarray(files))
        cl_2d = np.broadcast_to(cl_img[:, None], c_sub.shape)
        out["cluster_ids"] = cl_2d[m]
    return out


def _load(name: str, split: str, mode: str) -> dict:
    from tastoria_ml.cv.predict_dump import pred_path

    z = np.load(pred_path(name, split, mode))
    return {k: z[k] for k in z.files}


def _eval_split(
    pr: dict,
    c: np.ndarray,
    gof: np.ndarray,
    cols: list[int],
    names: list[str],
    conf: float,
    med: dict[int, int],
) -> dict:
    ch = pred_counts(pr, len(c), len(names), conf)
    med_base = np.zeros_like(c)
    zero_base = np.zeros_like(c)
    for k in cols:
        med_base[:, k] = np.where(c[:, k] > 0, med.get(k, 1), 0)
    out = {
        "excluded_group_of_pairs": int(gof[:, cols].sum()),
        "detector": masked_metrics(c, ch, gof, cols),
        "zero_baseline": masked_metrics(c, zero_base, gof, cols),
        "median_baseline": masked_metrics(c, med_base, gof, cols),
        # same pair set as the median/zero baselines (class present in GT), for a like-for-like comparison
        "detector_gt_present_pairs": masked_metrics(c, np.where(c > 0, ch, 0), gof | (c == 0), cols),
        "per_class": {},
        "by_source": {},
    }
    for k in cols:
        out["per_class"][names[k]] = {
            "detector": masked_metrics(c, ch, gof, [k]),
            "zero_baseline": masked_metrics(c, zero_base, gof, [k]),
            "median_baseline": masked_metrics(c, med_base, gof, [k]),
            "train_median": med.get(k),
        }
    src = np.array([str(f).split("__")[0] if "__" in str(f) else "unknown" for f in pr["files"]])
    for s in sorted(set(src.tolist())):
        m = src == s
        out["by_source"][s] = {
            "detector": masked_metrics(c[m], ch[m], gof[m], cols),
            "zero_baseline": masked_metrics(c[m], zero_base[m], gof[m], cols),
            "median_baseline": masked_metrics(c[m], med_base[m], gof[m], cols),
        }
    return out


def evaluate(
    name: str,
    mode: str = "nms",
    dataset: str = "yolo",
    yolo_dir: Path | None = None,
    splits: tuple[str, ...] | None = None,
    include_proposed: bool = False,
    out_dir: Path | None = None,
) -> dict:
    ydir = resolve_yolo_dir(dataset, yolo_dir)
    dest_out = out_dir if out_dir is not None else (OUT_V2 if ydir == YOLO_V2_DIR else OUT)
    if splits is None:
        splits = ("val", "test", "heldout") if ydir == YOLO_V2_DIR else ("val", "test")

    main_countable = countable_ids(include_proposed=False)
    all_countable = countable_ids(include_proposed=include_proposed)
    val = _load(name, "val", mode)
    names = [str(n) for n in val["names"]]
    cols_all = [k for k, n in enumerate(names) if n in all_countable]
    cols_main = [k for k, n in enumerate(names) if n in main_countable]

    res: dict = {
        "run": name,
        "dataset": ydir.name,
        "mode": mode,
        "include_proposed": include_proposed,
        "countable_classes": [names[k] for k in cols_all],
        "main_countable_classes": [names[k] for k in cols_main],
    }
    data = {}
    for split in splits:
        pr = val if split == "val" else _load(name, split, mode)
        c = gt_counts(pr["files"], split, len(names), yolo_dir=ydir)
        gof = group_of_pairs(split, pr["files"], names)
        data[split] = (pr, c, gof)

    pr, c, gof = data["val"]
    conf, curve = choose_conf(c, pr, cols_all, gof)
    res["conf_selected_on_val"] = conf
    res["val_curve"] = curve
    med = train_medians(names, yolo_dir=ydir)

    for split in splits:
        if split == "val":
            continue
        pr_s, c_s, gof_s = data[split]
        split_res = _eval_split(pr_s, c_s, gof_s, cols_all, names, conf, med)
        if include_proposed and cols_main != cols_all:
            split_res["main_countable"] = _eval_split(pr_s, c_s, gof_s, cols_main, names, conf, med)
        res[split] = split_res

    dest_out.mkdir(parents=True, exist_ok=True)
    (dest_out / f"{name}__{mode}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--mode", default="nms")
    ap.add_argument("--dataset", default="yolo", choices=["yolo", "yolo_v2"])
    ap.add_argument("--yolo-dir", default=None)
    ap.add_argument("--include-proposed", action="store_true")
    a = ap.parse_args()
    ydir = resolve_yolo_dir(a.dataset, a.yolo_dir)
    r = evaluate(a.run, a.mode, dataset=a.dataset, yolo_dir=ydir, include_proposed=a.include_proposed)
    summary = {"conf_selected_on_val": r["conf_selected_on_val"]}
    for split in ("test", "heldout"):
        if split in r:
            summary[split] = {
                "detector": r[split]["detector"],
                "zero_baseline": r[split]["zero_baseline"],
                "median_baseline": r[split]["median_baseline"],
            }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

