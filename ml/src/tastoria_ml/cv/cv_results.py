"""Aggregate the detector experiments into result JSONs (data/processed/cv/results/) and report figures
(docs/reports/xu-ly-anh/fig/). Reads only run summaries (data/processed/cv/detector/*.json) and the
prediction dumps (ml/runs/preds/), so it needs no GPU.

  python -m tastoria_ml.cv.cv_results grid         # CLAHE clip/tile chosen on val mAP50-95
  python -m tastoria_ml.cv.cv_results ablation     # 5 arms × 3 seeds, COCO on test, paired bootstrap
  python -m tastoria_ml.cv.cv_results compare      # YOLO11n/26n × 640/960, NMS vs NMS-free, small objects
  python -m tastoria_ml.cv.cv_results counting
  python -m tastoria_ml.cv.cv_results figures
"""

from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from tastoria_ml.cv import det_eval as de
from tastoria_ml.cv.classes import REPO
from tastoria_ml.cv.predict_dump import pred_path

DET = REPO / "data" / "processed" / "cv" / "detector"
RES = REPO / "data" / "processed" / "cv" / "results"
FIG = REPO / "docs" / "reports" / "xu-ly-anh" / "fig"
LABELS = REPO / "data" / "processed" / "cv" / "yolo" / "labels"
MARGIN = 0.015  # equivalence margin, mAP50-95 (thiết kế v2 §7)
SEEDS = (0, 1, 2)
# validated categorical palette (dataviz reference instance, light surface), fixed order
PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"


def load_pred(name: str, split: str, mode: str = "nms") -> dict:
    z = np.load(pred_path(name, split, mode))
    return {k: z[k] for k in z.files}


def prepared(name: str, split: str = "test", mode: str = "nms"):
    p = load_pred(name, split, mode)
    gt = de.read_gt(LABELS / split, p["files"], p["hw"])
    return p, gt, de.prepare(p, gt, len(p["names"]))


def _coco(args):
    name, split, mode = args
    p = load_pred(name, split, mode)
    gt = de.read_gt(LABELS / split, p["files"], p["hw"])
    return de.coco_metrics(p, gt, [str(n) for n in p["names"]])


def coco_cached(name: str, split: str = "test", mode: str = "nms") -> dict:
    RES.mkdir(parents=True, exist_ok=True)
    cache = RES / "coco" / f"{name}__{split}__{mode}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    m = _coco((name, split, mode))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(m, indent=1))
    return m


def mean_sd(v) -> dict:
    v = np.asarray(v, float)
    return {"mean": float(v.mean()), "sd": float(v.std(ddof=1)) if len(v) > 1 else None, "values": v.tolist()}


# ------------------------------------------------------------------ CLAHE grid


def grid() -> dict:
    rows = []
    for f in sorted(DET.glob("grid20_clahe_c*.json")):
        j = json.loads(f.read_text())
        m = re.search(r"c([\d.]+)_t(\d+)", f.stem)
        val_coco = coco_cached(j["name"], "val")
        rows.append({"run": j["name"], "clip": float(m.group(1)), "tile": int(m.group(2)),
                     "val_map50_95_ultralytics": j["eval"]["val"]["map50_95"],
                     "val_map50_ultralytics": j["eval"]["val"]["map50"],
                     "val_AP_coco": val_coco["AP"], "val_AP50_coco": val_coco["AP50"]})
    best = max(rows, key=lambda r: r["val_AP_coco"])
    out = {"criterion": "val COCO AP@[.5:.95] after 20 epochs, YOLO26n 640, seed 0 (test not looked at)",
           "rows": rows, "chosen": {"clip": best["clip"], "tile": best["tile"]}}
    (RES / "clahe_grid.json").write_text(json.dumps(out, indent=2))
    return out


# ------------------------------------------------------------------ ablation


def arm_runs(arm: str) -> list[str]:
    tag = arm.replace("@", "_")
    return [f"abl60_{tag}_s{s}" for s in SEEDS if (DET / f"abl60_{tag}_s{s}.json").exists()]


def _prep_job(name):
    return prepared(name)[2]


def ablation(arms: list[str], n_boot: int = 2000) -> dict:
    out = {"margin_map50_95": MARGIN, "arms": {}, "vs_none": {}}
    runs = {a: arm_runs(a) for a in arms}
    for a, rs in runs.items():
        ms = [coco_cached(r) for r in rs]
        js = [json.loads((DET / f"{r}.json").read_text()) for r in rs]
        out["arms"][a] = {
            "runs": rs,
            "test_AP50": mean_sd([m["AP50"] for m in ms]),
            "test_AP": mean_sd([m["AP"] for m in ms]),
            "test_map50_ultralytics": mean_sd([j["eval"]["test"]["map50"] for j in js]),
            "test_map50_95_ultralytics": mean_sd([j["eval"]["test"]["map50_95"] for j in js]),
            "val_map50_95_ultralytics": mean_sd([j["eval"]["val"]["map50_95"] for j in js]),
            "best_epoch": [j["best_epoch"] for j in js],
            "epochs_run": [j["epochs_run"] for j in js],
            "train_minutes": [round(j["train_seconds"] / 60, 1) for j in js],
        }
    with ProcessPoolExecutor(6) as ex:
        P = dict(zip([r for a in arms for r in runs[a]], ex.map(_prep_job, [r for a in arms for r in runs[a]])))
    files = load_pred(runs[arms[0]][0], "test")["files"]
    cl = de.clusters(files)
    base = [P[r] for r in runs["none"]]
    for a in arms:
        if a == "none":
            continue
        b = de.paired_cluster_bootstrap([P[r] for r in runs[a]], base, cl, n_boot=n_boot)
        b["verdict_map50_95"] = de.equivalence(b["map50_95"]["ci90"], MARGIN)
        out["vs_none"][a] = b
        print(a, b["map50_95"], b["verdict_map50_95"], flush=True)
    out["n_clusters"] = int(cl.max() + 1)
    (RES / "ablation.json").write_text(json.dumps(out, indent=2))
    return out


# ------------------------------------------------------------------ detector comparison


def compare(runs: list[str]) -> dict:
    out = {}
    for r in runs:
        j = json.loads((DET / f"{r}.json").read_text())
        row = {"model": j["model"], "imgsz": j["imgsz"], "seed": j["seed"], "best_epoch": j["best_epoch"],
               "epochs_run": j["epochs_run"], "train_minutes": round(j["train_seconds"] / 60, 1),
               "val_map50_95_ultralytics": j["eval"]["val"]["map50_95"]}
        for mode in ("nms", "e2e"):
            if pred_path(r, "test", mode).exists():
                row[f"test_{mode}"] = coco_cached(r, "test", mode)
                row[f"val_{mode}_AP"] = coco_cached(r, "val", mode)["AP"]
        lat = DET / f"{r}_latency2.json"
        if lat.exists():
            row["latency"] = json.loads(lat.read_text())
        out[r] = row
    (RES / "detector_compare.json").write_text(json.dumps(out, indent=2))
    return out


# ------------------------------------------------------------------ figures


def _style():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "axes.edgecolor": INK2,
        "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2, "axes.grid": True,
        "grid.color": GRID, "grid.linewidth": 0.8, "axes.spines.top": False, "axes.spines.right": False,
        "font.size": 10, "axes.titlesize": 11, "lines.linewidth": 2, "savefig.dpi": 150,
        "font.family": "DejaVu Sans",
    })
    return plt


def fig_pr(name: str, out: Path, mode: str = "nms") -> None:
    plt = _style()
    p, gt, P = prepared(name, "test", mode)
    names = [str(n) for n in p["names"]]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
    groups = [names[:7], names[7:]]
    for ax, grp in zip(axes, groups):
        for k, n in enumerate(grp):
            c = names.index(n)
            r, pr = de.pr_curve(P, c, 0)
            env = np.maximum.accumulate(pr[::-1])[::-1] if len(pr) else pr
            ap = de.weighted_map(P)[0][c, 0]
            ax.plot(r, env, color=PALETTE[k % len(PALETTE)], label=f"{n} (AP50 {ap:.2f})")
        ax.set_xlabel("Recall")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1.02)
        ax.legend(fontsize=8, frameon=False, loc="upper right")
    axes[0].set_ylabel("Precision (bao trên)")
    fig.suptitle(f"Đường precision–recall theo lớp, IoU 0,5, tập test ({name})", fontsize=11)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def confusion(p: dict, gt: list, conf: float, n_cls: int, iou: float = 0.5) -> np.ndarray:
    """(n_cls + 1)² matrix, rows = GT class (+ background), cols = predicted (+ missed)."""
    M = np.zeros((n_cls + 1, n_cls + 1), int)
    for i, (gb, gc) in enumerate(gt):
        k = (p["img"] == i) & (p["scores"] >= conf)
        db, dc = p["boxes"][k], p["cls"][k].astype(int)
        used_g, used_d = set(), set()
        if len(db) and len(gb):
            ious = de.iou_matrix(db, gb)
            pairs = sorted(((ious[a, b], a, b) for a in range(len(db)) for b in range(len(gb)) if ious[a, b] >= iou),
                           reverse=True)
            for _, a, b in pairs:
                if a in used_d or b in used_g:
                    continue
                used_d.add(a)
                used_g.add(b)
                M[gc[b], dc[a]] += 1
        for b in range(len(gb)):
            if b not in used_g:
                M[gc[b], n_cls] += 1
        for a in range(len(db)):
            if a not in used_d:
                M[n_cls, dc[a]] += 1
    return M


def fig_confusion(name: str, conf: float, out: Path) -> dict:
    plt = _style()
    p, gt, _ = prepared(name)
    names = [str(n) for n in p["names"]]
    M = confusion(p, gt, conf, len(names))
    R = M / np.maximum(M.sum(1, keepdims=True), 1)
    fig, ax = plt.subplots(figsize=(8.2, 7))
    ax.grid(False)
    im = ax.imshow(R, cmap="Blues", vmin=0, vmax=1)
    lab = names + ["nền"]
    ax.set_xticks(range(len(lab)), lab, rotation=60, ha="right", fontsize=8)
    ax.set_yticks(range(len(lab)), lab, fontsize=8)
    for i in range(len(lab)):
        for j in range(len(lab)):
            if M[i, j] and (i < len(names)):
                ax.text(j, i, f"{R[i, j]:.2f}", ha="center", va="center", fontsize=6,
                        color="white" if R[i, j] > 0.5 else INK)
    ax.set_xlabel("Dự đoán (cột 'nền' = bỏ sót)")
    ax.set_ylabel("Thật (hàng 'nền' = dự đoán thừa)")
    ax.set_title(f"Ma trận nhầm lẫn, test, conf ≥ {conf:.2f}, IoU ≥ 0,5 (chuẩn hoá theo hàng)")
    fig.colorbar(im, ax=ax, fraction=0.04)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
    return {"conf": conf, "matrix": M.tolist(), "labels": lab}


def fig_examples(name: str, conf: float, out: Path, n: int = 6, seed: int = 3) -> None:
    import cv2

    plt = _style()
    p, gt, _ = prepared(name)
    names = [str(n_) for n_ in p["names"]]
    files = p["files"]
    rng = np.random.default_rng(seed)
    oi = [i for i, f in enumerate(files) if "openimages" in str(f) and len(gt[i][1])]
    bd = [i for i, f in enumerate(files) if "mendeley" in str(f) and len(gt[i][1])]
    pick = list(rng.choice(oi, n - 2, replace=False)) + list(rng.choice(bd, 2, replace=False))
    fig, axes = plt.subplots(2, 3, figsize=(13, 8))
    for ax, i in zip(axes.ravel(), pick):
        im = cv2.cvtColor(cv2.imread(str(REPO / "data/processed/cv/yolo/images/test" / str(files[i]))),
                          cv2.COLOR_BGR2RGB)
        ax.imshow(im)
        ax.grid(False)
        ax.set_xticks([])
        ax.set_yticks([])
        for b in gt[i][0]:
            ax.add_patch(plt.Rectangle((b[0], b[1]), b[2] - b[0], b[3] - b[1], fill=False, ec="#ffffff",
                                       lw=2.5, ls="--"))
        k = (p["img"] == i) & (p["scores"] >= conf)
        for b, c, s in zip(p["boxes"][k], p["cls"][k], p["scores"][k]):
            col = PALETTE[int(c) % len(PALETTE)]
            ax.add_patch(plt.Rectangle((b[0], b[1]), b[2] - b[0], b[3] - b[1], fill=False, ec=col, lw=2))
            ax.text(b[0], b[1] - 2, f"{names[int(c)]} {s:.2f}", color="white", fontsize=7,
                    bbox={"facecolor": col, "edgecolor": "none", "pad": 1})
        gtc = {}
        for c in gt[i][1]:
            gtc[names[c]] = gtc.get(names[c], 0) + 1
        ax.set_title(", ".join(f"{k_}×{v}" for k_, v in gtc.items())[:60], fontsize=8)
    fig.suptitle(f"Ví dụ trên test ({name}, conf ≥ {conf:.2f}): nét đứt trắng = nhãn thật, khung màu = dự đoán",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def fig_ablation(ab: dict, out: Path) -> None:
    plt = _style()
    arms = list(ab["arms"])
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    for ax, key, title in ((axes[0], "test_AP50", "AP50 (test)"), (axes[1], "test_AP", "AP@[.5:.95] (test)")):
        for k, a in enumerate(arms):
            v = ab["arms"][a][key]
            ax.bar(k, v["mean"], width=0.6, color=PALETTE[k], edgecolor="#fcfcfb", linewidth=2)
            ax.errorbar(k, v["mean"], yerr=v["sd"] or 0, color=INK, capsize=4, lw=1.2)
            ax.scatter([k] * len(v["values"]), v["values"], color=INK, s=12, zorder=3)
            ax.text(k, v["mean"] + (v["sd"] or 0) + 0.003, f"{v['mean']:.3f}", ha="center", fontsize=8, color=INK)
        lo = min(min(ab["arms"][a][key]["values"]) for a in arms)
        hi = max(max(ab["arms"][a][key]["values"]) for a in arms)
        ax.set_ylim(lo - 0.02, hi + 0.015)
        ax.set_xticks(range(len(arms)), [a.split("@")[0] for a in arms])
        ax.set_title(title + ", trung bình ± sd, 3 seed")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def fig_ablation_ci(ab: dict, out: Path) -> None:
    plt = _style()
    arms = [a for a in ab["vs_none"]]
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    for k, a in enumerate(arms):
        b = ab["vs_none"][a]["map50_95"]
        ax.plot([b["ci95"][0] * 100, b["ci95"][1] * 100], [k, k], color=PALETTE[k + 1], lw=2)
        ax.plot([b["ci90"][0] * 100, b["ci90"][1] * 100], [k, k], color=PALETTE[k + 1], lw=6, alpha=0.6)
        ax.scatter([b["diff"] * 100], [k], color=INK, s=24, zorder=3)
    ax.axvspan(-MARGIN * 100, MARGIN * 100, color="#f0efec", zorder=0)
    ax.axvline(0, color=INK2, lw=1)
    ax.set_yticks(range(len(arms)), [a.split("@")[0] for a in arms])
    ax.set_xlabel("Chênh AP@[.5:.95] so với none (điểm %), vạch dày = CI90, mảnh = CI95; nền xám = biên ±1,5")
    ax.set_title("Bootstrap cụm có cặp trên test (2.000 lần)")
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def fig_preprocess(out: Path, clahe: str) -> None:
    """One Open Images and one Bangladesh test image under every arm (aug: two sampled casts)."""
    import cv2

    from tastoria_ml.cv.colorcast import apply_gains, cast_gains
    from tastoria_ml.cv.preprocess import apply_arm
    from tastoria_ml.cv.train_detector import parse_arm

    plt = _style()
    files = sorted((REPO / "data/processed/cv/yolo/images/test").glob("*.jpg"))
    pick = [f for f in files if "openimages" in f.name][40:41] + [f for f in files if "mendeley" in f.name][100:101]
    _, clip, g = parse_arm(clahe)
    cols = [
        ("none (gốc)", lambda x: x),
        ("gray-world", lambda x: apply_arm(x, "gw")),
        (f"CLAHE-L {clip:g}/{g[0]}×{g[0]}", lambda x: apply_arm(x, "clahe", clip, g)),
        ("gray-world + CLAHE-L", lambda x: apply_arm(x, "gw_clahe", clip, g)),
        ("aug: ám ấm (t=+0,5)", lambda x: apply_gains(x, cast_gains(0.5, 0.0, 0.0))),
        ("aug: ám lạnh, tối (t=−0,5, e=−0,3)", lambda x: apply_gains(x, cast_gains(-0.5, 0.1, -0.3))),
    ]
    fig, axes = plt.subplots(len(pick), len(cols), figsize=(2.9 * len(cols), 2.3 * len(pick)))
    for r, f in enumerate(pick):
        im = cv2.cvtColor(cv2.imread(str(f)), cv2.COLOR_BGR2RGB)
        for c, (t, fn) in enumerate(cols):
            ax = axes[r, c]
            ax.imshow(fn(im))
            ax.set_xticks([])
            ax.set_yticks([])
            ax.grid(False)
            if r == 0:
                ax.set_title(t, fontsize=8)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


def main(cmd: str, *args: str) -> None:
    RES.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    if cmd == "grid":
        print(json.dumps(grid(), indent=2))
    elif cmd == "ablation":
        print(json.dumps(ablation(list(args)), indent=2)[:4000])
    elif cmd == "compare":
        print(json.dumps(compare(list(args)), indent=2)[:3000])


if __name__ == "__main__":
    main(*sys.argv[1:])
