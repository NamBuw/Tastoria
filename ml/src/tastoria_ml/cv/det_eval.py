"""Offline detector evaluation from prediction dumps (``predict_dump``): COCO metrics, paired cluster
bootstrap, PR curves.

* COCO numbers (AP@[.5:.95], AP50, AP75, AP small/medium/large, per-class AP) come from
  ``faster-coco-eval`` (pycocotools-compatible). Boxes are axis-aligned, GT ``area`` = w·h in original
  pixels, so "small" = GT area < 32² px of the stored image (most images are ~640 px on the long side).
  Open Images group-of boxes are scored like ordinary boxes (they were trained that way).
* For the bootstrap the same COCO matching (greedy by score, best unmatched GT with IoU ≥ t, ≤ 100
  detections per image and class, 101-point interpolated precision) is re-implemented in numpy so that a
  resample is just a weight vector over images: the matching is image-local, so drawing an image twice
  duplicates its detections and its GT. ``check`` verifies it reproduces faster-coco-eval.
* Clusters for the bootstrap: an Open Images image is its own cluster; Bangladesh frames are grouped in
  blocks of 10 consecutive frames of their video (neighbouring frames are near copies).

Pure numpy except ``coco_metrics`` (faster-coco-eval) — the matching / AP / bootstrap code is unit tested
in the project env.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

IOU_THRS = np.linspace(0.5, 0.95, 10)
REC_THRS = np.linspace(0.0, 1.0, 101)
MAX_DET = 100


# ------------------------------------------------------------------ geometry + matching


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU between xyxy boxes a (n, 4) and b (m, 4)."""
    a = np.asarray(a, np.float64).reshape(-1, 4)
    b = np.asarray(b, np.float64).reshape(-1, 4)
    lt = np.maximum(a[:, None, :2], b[None, :, :2])
    rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter = np.clip(rb - lt, 0, None).prod(-1)
    area_a = (a[:, 2:] - a[:, :2]).clip(0).prod(-1)
    area_b = (b[:, 2:] - b[:, :2]).clip(0).prod(-1)
    union = area_a[:, None] + area_b[None, :] - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-12), 0.0)


def match_greedy(det: np.ndarray, scores: np.ndarray, gt: np.ndarray, thrs=IOU_THRS) -> tuple[np.ndarray, np.ndarray]:
    """COCO matching for one (image, class). Returns (order, tp[n_det, T]) with dets sorted by score."""
    order = np.argsort(-np.asarray(scores), kind="mergesort")[:MAX_DET]
    tp = np.zeros((len(order), len(thrs)), bool)
    if len(order) == 0 or len(gt) == 0:
        return order, tp
    ious = iou_matrix(det[order], gt)
    for t, thr in enumerate(thrs):
        used = np.zeros(len(gt), bool)
        for d in range(len(order)):
            cand = np.where(~used, ious[d], -1.0)
            g = int(np.argmax(cand))
            if cand[g] >= thr - 1e-10:  # COCO: iou >= t (minus float slack)
                used[g] = True
                tp[d, t] = True
    return order, tp


def interp_ap(tp: np.ndarray, w: np.ndarray, n_gt: float) -> np.ndarray:
    """101-point interpolated AP per IoU threshold. tp: (n, T) sorted by score; w: weight per det."""
    T = tp.shape[1] if tp.ndim == 2 else len(IOU_THRS)
    if n_gt <= 0:
        return np.full(T, np.nan)
    if len(tp) == 0:
        return np.zeros(T)
    wt = w[:, None]
    tpc = np.cumsum(tp * wt, 0)
    fpc = np.cumsum((~tp) * wt, 0)
    rec = tpc / n_gt
    prec = tpc / np.maximum(tpc + fpc, 1e-12)
    prec = np.maximum.accumulate(prec[::-1], 0)[::-1]  # precision envelope
    out = np.zeros(T)
    for t in range(T):
        idx = np.searchsorted(rec[:, t], REC_THRS, side="left")
        q = np.where(idx < len(rec), prec[np.minimum(idx, len(rec) - 1), t], 0.0)
        out[t] = q.mean()
    return out


# ------------------------------------------------------------------ data


def read_gt(labels_dir: Path, files: np.ndarray, hw: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """YOLO label files -> per image (boxes xyxy in original pixels, class ids)."""
    out = []
    for f, (h, w) in zip(files, hw):
        p = labels_dir / (Path(str(f)).stem + ".txt")
        rows = [ln.split() for ln in p.read_text().splitlines() if ln.strip()] if p.exists() else []
        if rows:
            a = np.array(rows, np.float64)
            c, xc, yc, bw, bh = a.T
            b = np.stack([(xc - bw / 2) * w, (yc - bh / 2) * h, (xc + bw / 2) * w, (yc + bh / 2) * h], 1)
            out.append((b, c.astype(int)))
        else:
            out.append((np.zeros((0, 4)), np.zeros(0, int)))
    return out


def clusters(files: np.ndarray, block: int = 10) -> np.ndarray:
    """Cluster id per image: Bangladesh frames -> (video, frame // block); everything else -> itself."""
    keys = []
    for f in files:
        f = str(f)
        m = re.search(r"(VID_\d+_\d+)_mp4-(\d+)", f)
        keys.append(f"{m.group(1)}/{int(m.group(2)) // block}" if m else f)
    _, inv = np.unique(np.array(keys), return_inverse=True)
    return inv


@dataclass
class Prepared:
    """Per-class matched detections for weighted (bootstrap) AP."""

    n_images: int
    n_classes: int
    tp: list  # per class: (n_det, T) bool, sorted by score
    img: list  # per class: image index per det
    gt_per_img: np.ndarray  # (n_images, n_classes) GT counts


def prepare(pred: dict, gt: list, n_classes: int) -> Prepared:
    n = len(gt)
    tps, imgs, scs = [[] for _ in range(n_classes)], [[] for _ in range(n_classes)], [[] for _ in range(n_classes)]
    gt_per = np.zeros((n, n_classes), int)
    by_img = np.argsort(pred["img"], kind="mergesort")
    starts = np.searchsorted(pred["img"][by_img], np.arange(n + 1))
    for i in range(n):
        sel = by_img[starts[i] : starts[i + 1]]
        gb, gc = gt[i]
        for c in range(n_classes):
            gt_per[i, c] = int((gc == c).sum())
            dsel = sel[pred["cls"][sel] == c]
            if len(dsel) == 0:
                continue
            order, tp = match_greedy(pred["boxes"][dsel], pred["scores"][dsel], gb[gc == c])
            tps[c].append(tp)
            imgs[c].append(np.full(len(order), i))
            scs[c].append(pred["scores"][dsel][order])
    T = len(IOU_THRS)
    P = Prepared(n, n_classes, [], [], gt_per)
    for c in range(n_classes):
        if tps[c]:
            s = np.concatenate(scs[c])
            o = np.argsort(-s, kind="mergesort")
            P.tp.append(np.concatenate(tps[c])[o])
            P.img.append(np.concatenate(imgs[c])[o])
        else:
            P.tp.append(np.zeros((0, T), bool))
            P.img.append(np.zeros(0, int))
    return P


def weighted_map(P: Prepared, w_img: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(AP per class at each IoU threshold [C, T]) for image weights ``w_img`` (None = all ones)."""
    w_img = np.ones(P.n_images) if w_img is None else np.asarray(w_img, float)
    ap = np.full((P.n_classes, len(IOU_THRS)), np.nan)
    ngt = (P.gt_per_img * w_img[:, None]).sum(0)
    for c in range(P.n_classes):
        if ngt[c] > 0:
            w = w_img[P.img[c]]
            keep = w > 0
            ap[c] = interp_ap(P.tp[c][keep], w[keep], ngt[c])
    return ap, ngt


def summary_map(ap: np.ndarray) -> tuple[float, float]:
    """(mAP50, mAP50-95) averaged over classes with GT."""
    return float(np.nanmean(ap[:, 0])), float(np.nanmean(ap.mean(1)))


def paired_cluster_bootstrap(prepared_a: list[Prepared], prepared_b: list[Prepared], cl: np.ndarray,
                             n_boot: int = 2000, seed: int = 0) -> dict:
    """Bootstrap over clusters of mean-over-seeds(A) − mean-over-seeds(B) for mAP50 and mAP50-95.

    ``prepared_a`` / ``prepared_b`` are the seeds of each arm, all on the same images. The same cluster
    resample is applied to every model (paired).
    """
    rng = np.random.default_rng(seed)
    n_cl = int(cl.max()) + 1
    members = [np.where(cl == k)[0] for k in range(n_cl)]
    n_img = len(cl)

    def arm_val(ps, w):
        vals = np.array([summary_map(weighted_map(p, w)[0]) for p in ps])
        return vals.mean(0)

    point = arm_val(prepared_a, None) - arm_val(prepared_b, None)
    diffs = np.zeros((n_boot, 2))
    for b in range(n_boot):
        draw = rng.integers(0, n_cl, n_cl)
        w = np.zeros(n_img)
        cnt = np.bincount(draw, minlength=n_cl)
        for k in np.nonzero(cnt)[0]:
            w[members[k]] += cnt[k]
        diffs[b] = arm_val(prepared_a, w) - arm_val(prepared_b, w)
    out = {}
    for j, key in enumerate(("map50", "map50_95")):
        d = diffs[:, j]
        out[key] = {
            "diff": float(point[j]),
            "ci95": [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))],
            "ci90": [float(np.percentile(d, 5)), float(np.percentile(d, 95))],
        }
    out["n_boot"], out["n_clusters"] = n_boot, n_cl
    return out


def equivalence(ci90: list[float], margin: float) -> str:
    """TOST-style reading of a 90% CI against ±margin."""
    lo, hi = ci90
    if -margin < lo and hi < margin:
        return "equivalent"
    if lo >= margin or hi <= -margin:
        return "different (outside margin)"
    if lo > 0 or hi < 0:
        return "different from 0 but not shown beyond the margin"
    return "inconclusive"


def pr_curve(P: Prepared, c: int, t: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """(recall, precision) points for class c at IoU threshold index t (unweighted)."""
    tp = P.tp[c][:, t]
    ngt = P.gt_per_img[:, c].sum()
    tpc, fpc = np.cumsum(tp), np.cumsum(~tp)
    return tpc / max(ngt, 1), tpc / np.maximum(tpc + fpc, 1)


# ------------------------------------------------------------------ COCO (faster-coco-eval)


def coco_metrics(pred: dict, gt: list, names: list[str]) -> dict:
    from faster_coco_eval import COCO, COCOeval_faster

    images, anns, aid = [], [], 1
    for i, ((b, c), (h, w)) in enumerate(zip(gt, pred["hw"])):
        images.append({"id": i, "height": int(h), "width": int(w)})
        for bb, cc in zip(b, c):
            x0, y0, x1, y1 = (float(v) for v in bb)
            anns.append({"id": aid, "image_id": i, "category_id": int(cc), "bbox": [x0, y0, x1 - x0, y1 - y0],
                         "area": (x1 - x0) * (y1 - y0), "iscrowd": 0})
            aid += 1
    cats = [{"id": k, "name": n} for k, n in enumerate(names)]
    cg = COCO()
    cg.dataset = {"images": images, "annotations": anns, "categories": cats}
    cg.createIndex()
    b = pred["boxes"]
    dets = [{"image_id": int(i), "category_id": int(c), "bbox": [float(x0), float(y0), float(x1 - x0), float(y1 - y0)],
             "score": float(s)} for i, c, (x0, y0, x1, y1), s in zip(pred["img"], pred["cls"], b, pred["scores"])]
    cd = cg.loadRes(dets)
    ev = COCOeval_faster(cg, cd, "bbox", print_function=lambda *a, **k: None)
    ev.evaluate()
    ev.accumulate()
    ev.summarize()
    st = [float(x) for x in ev.stats[:12]]
    prec = np.asarray(ev.eval["precision"])  # [T, R, K, A, M]; A: all, small, medium, large; M: 1, 10, 100

    def cls_ap(a_idx, t=None):
        p = prec[:, :, :, a_idx, -1] if t is None else prec[t : t + 1, :, :, a_idx, -1]
        out = {}
        for k, n in enumerate(names):
            v = p[:, :, k]
            v = v[v > -1]
            out[n] = float(v.mean()) if v.size else None
        return out

    area_n = {"small": 0, "medium": 0, "large": 0}
    for a in anns:
        area_n["small" if a["area"] < 32**2 else "medium" if a["area"] < 96**2 else "large"] += 1
    return {
        "AP": st[0], "AP50": st[1], "AP75": st[2], "AP_small": st[3], "AP_medium": st[4], "AP_large": st[5],
        "AR100": st[8], "AR_small": st[9], "AR_medium": st[10], "AR_large": st[11],
        "per_class_AP": cls_ap(0), "per_class_AP50": cls_ap(0, 0), "per_class_AP_small": cls_ap(1),
        "gt_by_area": area_n, "n_gt": len(anns), "n_det": len(dets),
    }
