"""Problem 1 (CV Ingredient Detection & Counting) M1.2a study orchestrator and artifact generator.

Implements confirmatory (H1a, H1b) and exploratory analyses per TASTORIA-ML-PREREG-2026-11-18,
benchmarks ONNX CPU latency (c=1 and c=5), exports the best validated 30-class Detector v2 to
deploy/models/detector_v2/, and writes structured artifacts to ml/runs/research/p1_detection/.

Run on 171.226.10.153 using ml/runs/venv-cv/bin/python:
  python -m tastoria_ml.cv.p1_study neg-control
  python -m tastoria_ml.cv.p1_study all
"""

from __future__ import annotations

import argparse
import ast
import csv
import datetime as dt
import hashlib
import json
import math
import shutil
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
import yaml

from tastoria_ml import stats as mstats
from tastoria_ml.cv import counting as ct
from tastoria_ml.cv import det_eval as de
from tastoria_ml.cv import onnx_latency as ol
from tastoria_ml.cv import predict_dump
from tastoria_ml.cv.classes import REPO, VISION_CLASSES, load_classes

PROTOCOL_ID = "TASTORIA-ML-PREREG-2026-11-18"
YOLO_V1_DIR = REPO / "data" / "processed" / "cv" / "yolo"
YOLO_V2_DIR = REPO / "data" / "processed" / "cv" / "yolo_v2"
MANIFEST_V2 = REPO / "data" / "processed" / "cv" / "manifest_v2.csv"
STATS_V2 = REPO / "data" / "processed" / "cv" / "dataset_stats_v2.json"
V1_DET_DIR = REPO / "data" / "processed" / "cv" / "detector"
RESEARCH_DIR = REPO / "ml" / "runs" / "research" / "p1_detection"
RUN_META_DIR = RESEARCH_DIR / "detector_runs"
SNAPSHOT_EP25_DIR = RESEARCH_DIR / "snapshots_ep25"
COCO_CACHE_DIR = RESEARCH_DIR / "coco"
COUNTING_DIR = RESEARCH_DIR / "counting"
DEPLOY_V2_DIR = REPO / "deploy" / "models" / "detector_v2"

TOST_MARGIN = 0.015
Z_MDE_80 = 1.959963984540054 + 0.8416212335729143  # ~2.801585


def _mde_dz(n_eff: int) -> float:
    return float(Z_MDE_80 / math.sqrt(n_eff)) if n_eff > 0 else float("nan")


def _load_v2_names() -> list[str]:
    doc = yaml.safe_load((YOLO_V2_DIR / "dataset.yaml").read_text(encoding="utf-8"))
    names = doc["names"]
    return [str(names[i]) for i in range(len(names))]


def _load_v1_names() -> list[str]:
    doc = yaml.safe_load((YOLO_V1_DIR / "dataset.yaml").read_text(encoding="utf-8"))
    names = doc["names"]
    return [str(names[i]) for i in range(len(names))]


def _load_pred(run: str, split: str, mode: str = "nms") -> dict:
    p = predict_dump.pred_path(run, split, mode)
    z = np.load(p)
    return {k: z[k] for k in z.files}


def _load_manifest_v2() -> dict[str, dict[str, str]]:
    """Map yolo_v2 image filename (e.g. lvis_v1__val__100604.jpg) -> manifest_v2 row."""
    rows: dict[str, dict[str, str]] = {}
    with MANIFEST_V2.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            src = row["source"]
            oid = row["original_id"].replace("/", "__")
            fname = f"{src}__{oid}.jpg"
            rows[fname] = row
    return rows


def _subset_pred_and_gt(
    pred: dict,
    gt: list[tuple[np.ndarray, np.ndarray]],
    keep_idx: list[int],
) -> tuple[dict, list[tuple[np.ndarray, np.ndarray]]]:
    idx_map = {old_i: new_i for new_i, old_i in enumerate(keep_idx)}
    img_arr = np.asarray(pred["img"], dtype=np.int64)
    mask = np.isin(img_arr, keep_idx)
    remapped_img = np.array([idx_map[int(i)] for i in img_arr[mask]], dtype=np.int32)
    sub_pred = {
        "files": np.asarray(pred["files"])[keep_idx],
        "hw": np.asarray(pred["hw"])[keep_idx],
        "boxes": np.asarray(pred["boxes"])[mask],
        "scores": np.asarray(pred["scores"])[mask],
        "cls": np.asarray(pred["cls"])[mask],
        "img": remapped_img,
        "names": pred["names"],
    }
    sub_gt = [gt[i] for i in keep_idx]
    return sub_pred, sub_gt


def coco_cached(
    run: str,
    split: str,
    mode: str = "nms",
    yolo_dir: Path = YOLO_V2_DIR,
    remap_to_v1: bool = False,
    pred_path_override: Path | None = None,
    cache_prefix: str | None = None,
) -> dict:
    COCO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "__v1_13c" if remap_to_v1 else ""
    key = cache_prefix or run
    cache = COCO_CACHE_DIR / f"{key}__{split}__{mode}{suffix}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    if pred_path_override is not None:
        z = np.load(pred_path_override)
        pred = {k: z[k] for k in z.files}
    else:
        pred = _load_pred(run, split, mode)
    if remap_to_v1:
        v1_names = _load_v1_names()
        pred = de.remap_pred_classes(pred, pred["names"], v1_names)
        gt = de.read_gt(YOLO_V1_DIR / "labels" / split, pred["files"], pred["hw"])
        names = v1_names
    else:
        gt = de.read_gt(yolo_dir / "labels" / split, pred["files"], pred["hw"])
        names = [str(n) for n in pred["names"]]
    m = de.coco_metrics(pred, gt, names)
    cache.write_text(json.dumps(m, indent=2, ensure_ascii=False), encoding="utf-8")
    return m


# ------------------------------------------------------------------ Negative Control


def run_negative_control() -> dict:
    """Create and evaluate an untrained random-weight YOLO26n (nc=30) negative control."""
    import torch
    import ultralytics
    from ultralytics import YOLO

    from tastoria_ml.cv.train_detector import GpuGuard

    name = "v2_neg_random_yolo26n"
    RUN_META_DIR.mkdir(parents=True, exist_ok=True)
    out_json = RUN_META_DIR / f"{name}.json"
    run_dir = REPO / "ml" / "runs" / "detect" / name
    best_pt = run_dir / "weights" / "best.pt"
    v2_names = _load_v2_names()

    if not best_pt.exists():
        best_pt.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as td:
            cfg_src = Path(ultralytics.__file__).resolve().parent / "cfg" / "models" / "26" / "yolo26.yaml"
            cfg_txt = cfg_src.read_text(encoding="utf-8")
            # Override nc to 30 so ultralytics builds a 30-class random-init YOLO26n
            lines = []
            replaced = False
            for ln in cfg_txt.splitlines():
                if ln.startswith("nc:"):
                    lines.append("nc: 30")
                    replaced = True
                else:
                    lines.append(ln)
            if not replaced:
                lines.insert(0, "nc: 30")
            tmp_cfg = Path(td) / "yolo26n.yaml"
            tmp_cfg.write_text("\n".join(lines) + "\n", encoding="utf-8")
            torch.manual_seed(0)
            m = YOLO(str(tmp_cfg))
            names_dict = {i: n for i, n in enumerate(v2_names)}
            m.model.names = names_dict
            ckpt = {
                "epoch": -1,
                "best_fitness": 0.0,
                "model": m.model.half(),
                "ema": None,
                "updates": None,
                "optimizer": None,
                "train_args": {"imgsz": 640, "model": "yolo26n.yaml", "data": str(YOLO_V2_DIR / "dataset.yaml")},
                "date": dt.datetime.now(dt.UTC).isoformat(),
                "version": ultralytics.__version__,
            }
            torch.save(ckpt, best_pt)

    res = {}
    with GpuGuard(name):
        bm = YOLO(str(best_pt))
        for split in ("val", "test", "heldout"):
            eval_yaml = YOLO_V2_DIR / ("dataset_heldout.yaml" if split == "heldout" else "dataset.yaml")
            eval_split = "test" if split == "heldout" else split
            mt = bm.val(
                data=str(eval_yaml),
                split=eval_split,
                imgsz=640,
                batch=16,
                device=0,
                plots=False,
                verbose=False,
                project=str(REPO / "ml" / "runs" / "detect"),
                name=f"{name}_eval_{split}",
                exist_ok=True,
            )
            res[split] = {
                "map50": float(mt.box.map50),
                "map50_95": float(mt.box.map),
                "precision": float(mt.box.mp),
                "recall": float(mt.box.mr),
                "per_class": {},
            }
            img_dir = YOLO_V2_DIR / "images" / split
            p_out = predict_dump.pred_path(name, split, "nms")
            if not p_out.exists():
                predict_dump.dump(best_pt, img_dir, p_out, 640, mode="nms", batch=16)

    summary = {
        "name": name,
        "dataset": "yolo_v2",
        "model": "yolo26n.yaml (random-init, 0 epochs)",
        "ultralytics": ultralytics.__version__,
        "imgsz": 640,
        "batch": 16,
        "epochs_requested": 0,
        "epochs_run": 0,
        "best_epoch": 0,
        "patience": 0,
        "seed": 0,
        "preprocess_arm": "none",
        "train_seconds": 0.0,
        "eval": res,
        "weights": str(best_pt.relative_to(REPO)),
    }
    out_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


# ------------------------------------------------------------------ Helpers for Stats & Evaluation


def _paired_cluster_stats(
    pred_a: dict,
    pred_b: dict,
    gt: list[tuple[np.ndarray, np.ndarray]],
    cl: np.ndarray,
    conf_a: float,
    conf_b: float,
    n_boot: int = 2000,
    seed: int = 0,
) -> dict:
    """Compute paired cluster bootstrap for mAP50/mAP50-95 + tastoria_ml.stats on per-cluster F1."""
    n_classes = len(pred_a["names"])
    pa = de.prepare(pred_a, gt, n_classes)
    pb = de.prepare(pred_b, gt, n_classes)
    cb = de.paired_cluster_bootstrap([pa], [pb], cl, n_boot=n_boot, seed=seed)

    img_a = de.per_image_detection_metrics(pred_a, gt, conf=conf_a, iou=0.5)
    img_b = de.per_image_detection_metrics(pred_b, gt, conf=conf_b, iou=0.5)
    cl_a = de.aggregate_cluster_metrics(img_a, cl)
    cl_b = de.aggregate_cluster_metrics(img_b, cl)

    f1_a = cl_a["f1"]
    f1_b = cl_b["f1"]
    assump = mstats.check_paired_assumptions(f1_a, f1_b)
    boot_f1 = mstats.paired_bootstrap(f1_a, f1_b, n_boot=n_boot, seed=seed)
    wil = mstats.wilcoxon(f1_a, f1_b)
    dz = mstats.cohens_dz(f1_a, f1_b, n_boot=n_boot, seed=seed)
    n_cl = int(len(f1_a))
    return {
        "n_images": int(len(gt)),
        "n_clusters": n_cl,
        "mde_dz_80pct": _mde_dz(n_cl),
        "map_cluster_bootstrap": cb,
        "per_cluster_f1_at_val_conf": {
            "conf_a": float(conf_a),
            "conf_b": float(conf_b),
            "mean_a": float(np.mean(f1_a)),
            "sd_a": float(np.std(f1_a, ddof=1)),
            "mean_b": float(np.mean(f1_b)),
            "sd_b": float(np.std(f1_b, ddof=1)),
            "assumptions": assump,
            "paired_bootstrap": boot_f1,
            "wilcoxon": wil,
            "cohens_dz": dz,
        },
    }


def _choose_val_conf_from_pred(pred_val: dict, gt_val: list[tuple[np.ndarray, np.ndarray]]) -> tuple[float, float]:
    """Select conf on val maximizing macro-F1 over covered classes (n_gt > 0), matching backend rule."""
    n_classes = len(pred_val["names"])
    # Pre-match all detections above 0.05 at IoU 0.5 per class
    scores = np.asarray(pred_val["scores"], dtype=np.float64)
    p_img = np.asarray(pred_val["img"], dtype=np.int64)
    p_cls = np.asarray(pred_val["cls"], dtype=np.int64)
    p_box = np.asarray(pred_val["boxes"], dtype=np.float64).reshape(-1, 4)

    n_gt_cls = np.zeros(n_classes, dtype=int)
    det_tp_scores: list[list[tuple[float, bool]]] = [[] for _ in range(n_classes)]

    by_img = np.argsort(p_img, kind="mergesort")
    starts = np.searchsorted(p_img[by_img], np.arange(len(gt_val) + 1))

    for i, (gb, gc) in enumerate(gt_val):
        sel = by_img[starts[i] : starts[i + 1]]
        for c in range(n_classes):
            g_c = gb[gc == c]
            n_gt_cls[c] += len(g_c)
            dsel = sel[p_cls[sel] == c]
            dsel = dsel[scores[dsel] >= 0.05]
            if len(dsel) == 0:
                continue
            order, tp_mat = de.match_greedy(p_box[dsel], scores[dsel], g_c, thrs=(0.5,))
            sc_sorted = scores[dsel][order]
            for s_val, ok in zip(sc_sorted, tp_mat[:, 0]):
                det_tp_scores[c].append((float(s_val), bool(ok)))

    covered_cls = [c for c in range(n_classes) if n_gt_cls[c] > 0]
    best_t, best_f1 = 0.25, -1.0
    for t in np.round(np.arange(0.05, 0.951, 0.01), 2):
        f1s = []
        for c in covered_cls:
            tp = sum(1 for s, ok in det_tp_scores[c] if s >= t and ok)
            fp = sum(1 for s, ok in det_tp_scores[c] if s >= t and not ok)
            p = tp / (tp + fp) if (tp + fp) else 0.0
            r = tp / n_gt_cls[c]
            f1 = 2 * p * r / (p + r) if (p + r) else 0.0
            f1s.append(f1)
        mf1 = float(np.mean(f1s)) if f1s else 0.0
        if mf1 > best_f1:
            best_f1 = mf1
            best_t = float(t)
    return best_t, best_f1


# ------------------------------------------------------------------ Confirmatory & Exploratory Analyses


def run_eval_and_stats() -> dict:
    """Compute all H1a, H1b, exploratory, counting, gap analysis, and CSV/JSON summaries."""
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    v2_names = _load_v2_names()
    v1_names = _load_v1_names()
    manifest = _load_manifest_v2()

    run_files = sorted(RUN_META_DIR.glob("*.json"))
    runs_meta = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in run_files}
    v1_meta = json.loads((V1_DET_DIR / "yolo26n_640_none.json").read_text(encoding="utf-8"))

    # Confirmatory primary models
    confirmatory_runs = [
        r for r in (
            "v2_yolo26n_640_none_s0",
            "v2_yolo26s_640_none_s0",
            "v2_yolo11n_640_none_s0",
            "v2_yolov8n_640_none_s0",
        )
        if r in runs_meta
    ]
    abl_runs = [
        r for r in (
            "v2_abl25_none",
            "v2_abl25_gw",
            "v2_abl25_clahe",
            "v2_abl25_gw_clahe",
            "v2_abl25_aug",
            "v2_abl15_none",
            "v2_abl15_gw",
            "v2_abl15_clahe",
            "v2_abl15_gw_clahe",
            "v2_abl15_aug",
            "v2_abl12_none",
            "v2_abl12_gw",
            "v2_abl12_clahe",
            "v2_abl12_gw_clahe",
            "v2_abl12_aug",
            "v2_abl10_none",
            "v2_abl10_gw",
            "v2_abl10_clahe",
            "v2_abl10_gw_clahe",
            "v2_abl10_aug",
        )
        if r in runs_meta
    ]

    # Load ground truth per v2 split once
    val_ref = _load_pred(confirmatory_runs[0], "val", "nms")
    gt_val = de.read_gt(YOLO_V2_DIR / "labels" / "val", val_ref["files"], val_ref["hw"])
    cl_val = de.clusters(val_ref["files"])

    held_ref = _load_pred(confirmatory_runs[0], "heldout", "nms")
    gt_held = de.read_gt(YOLO_V2_DIR / "labels" / "heldout", held_ref["files"], held_ref["hw"])
    cl_held = de.clusters(held_ref["files"])

    v1_ref_pred_path = predict_dump.pred_path("yolo26n_640_none", "test", "nms")
    if not v1_ref_pred_path.exists():
        v1_best_pt = REPO / "ml" / "runs" / "detect" / "yolo26n_640_none" / "weights" / "best.pt"
        if v1_best_pt.exists():
            import torch
            from tastoria_ml.cv import train_detector as td

            dev: int | str = "cpu"
            if torch.cuda.is_available():
                try:
                    if td.gpu_free_mb()[0] >= 4096:
                        dev = 0
                except Exception:
                    dev = "cpu"
            predict_dump.dump(
                v1_best_pt, YOLO_V1_DIR / "images" / "test", v1_ref_pred_path, 640, mode="nms", device=dev, batch=16
            )

    test_v1_ref = _load_pred("yolo26n_640_none", "test", "nms")
    gt_test_v1 = de.read_gt(YOLO_V1_DIR / "labels" / "test", test_v1_ref["files"], test_v1_ref["hw"])
    cl_test_v1 = de.clusters(test_v1_ref["files"])

    # Compute val-selected conf and COCO metrics for all v2 runs
    val_confs: dict[str, float] = {}
    coco_all: dict[str, dict] = {}
    for r in confirmatory_runs + abl_runs + (["v2_neg_random_yolo26n"] if "v2_neg_random_yolo26n" in runs_meta else []):
        coco_all[r] = {}
        pr_val = _load_pred(r, "val", "nms")
        conf_r, mf1_r = _choose_val_conf_from_pred(pr_val, gt_val)
        val_confs[r] = conf_r
        for sp in ("val", "heldout", "test"):
            if predict_dump.pred_path(r, sp, "nms").exists():
                coco_all[r][f"{sp}_nms"] = coco_cached(r, sp, "nms", YOLO_V2_DIR)
            if predict_dump.pred_path(r, sp, "e2e").exists():
                coco_all[r][f"{sp}_e2e"] = coco_cached(r, sp, "e2e", YOLO_V2_DIR)
        if predict_dump.pred_path(r, "test", "nms").exists() and r in confirmatory_runs:
            coco_all[r]["test_v1_13c_nms"] = coco_cached(r, "test", "nms", YOLO_V1_DIR, remap_to_v1=True)

    # Positive control: v1 yolo26n_640_none on frozen v1 test
    v1_test_coco = coco_cached("yolo26n_640_none", "test", "nms", YOLO_V1_DIR, remap_to_v1=False)
    v1_val_serving_conf = float(json.loads((REPO / "deploy/models/detector/serving.json").read_text())["conf"])

    # ---------------- H1a Confirmatory ----------------
    h1a_arch_contrasts = {}
    base_run = "v2_yolo26n_640_none_s0"
    pr_base_val = _load_pred(base_run, "val", "nms")
    pr_base_held = _load_pred(base_run, "heldout", "nms")

    for sp_name, pr_base, gt_sp, cl_sp in (
        ("heldout", pr_base_held, gt_held, cl_held),
        ("val", pr_base_val, gt_val, cl_val),
    ):
        contrasts = []
        raw_p_map = []
        raw_p_f1 = []
        for alt in confirmatory_runs:
            if alt == base_run:
                continue
            pr_alt = _load_pred(alt, sp_name, "nms")
            st_res = _paired_cluster_stats(
                pr_alt, pr_base, gt_sp, cl_sp, val_confs[alt], val_confs[base_run], n_boot=2000, seed=0
            )
            contrasts.append((f"{alt}_vs_{base_run}", st_res))
            raw_p_map.append(st_res["map_cluster_bootstrap"]["map50_95"]["p"])
            raw_p_f1.append(st_res["per_cluster_f1_at_val_conf"]["paired_bootstrap"]["p"])
        holm_map = mstats.holm(raw_p_map).tolist() if raw_p_map else []
        holm_f1 = mstats.holm(raw_p_f1).tolist() if raw_p_f1 else []
        h1a_arch_contrasts[sp_name] = {}
        for idx, (cname, st_res) in enumerate(contrasts):
            st_res["map_cluster_bootstrap"]["map50_95"]["p_holm"] = float(holm_map[idx])
            st_res["per_cluster_f1_at_val_conf"]["paired_bootstrap"]["p_holm"] = float(holm_f1[idx])
            h1a_arch_contrasts[sp_name][cname] = st_res

    # H1a v1 13-class parity TOST on frozen v1 test
    h1a_v1_parity = {}
    parity_p_vals = []
    parity_keys = []
    for r in confirmatory_runs:
        pr_v2_test = _load_pred(r, "test", "nms")
        pr_remapped = de.remap_pred_classes(pr_v2_test, pr_v2_test["names"], v1_names)
        # Ensure identical file order check
        assert np.array_equal(pr_remapped["files"], test_v1_ref["files"]), f"file order mismatch for {r}"
        st_par = _paired_cluster_stats(
            pr_remapped, test_v1_ref, gt_test_v1, cl_test_v1, val_confs[r], v1_val_serving_conf, n_boot=2000, seed=0
        )
        ci90 = st_par["map_cluster_bootstrap"]["map50_95"]["ci90"]
        st_par["tost_margin"] = TOST_MARGIN
        st_par["tost_verdict"] = de.equivalence(ci90, TOST_MARGIN)
        h1a_v1_parity[r] = st_par
        parity_keys.append(r)
        parity_p_vals.append(st_par["map_cluster_bootstrap"]["map50_95"]["p"])
    if parity_p_vals:
        holm_par = mstats.holm(parity_p_vals).tolist()
        for k, hp in zip(parity_keys, holm_par):
            h1a_v1_parity[k]["map_cluster_bootstrap"]["map50_95"]["p_holm"] = float(hp)

    # ---------------- H1b Counting & Confirmatory ----------------
    counting_runs = {}
    for r in confirmatory_runs + (["v2_neg_random_yolo26n"] if "v2_neg_random_yolo26n" in runs_meta else []):
        for mode in (["nms", "e2e"] if "26" in runs_meta[r]["model"] and predict_dump.pred_path(r, "heldout", "e2e").exists() else ["nms"]):
            key = f"{r}__{mode}"
            counting_runs[key] = ct.evaluate(
                r, mode=mode, dataset="yolo_v2", yolo_dir=YOLO_V2_DIR,
                splits=("val", "test", "heldout"), include_proposed=True, out_dir=COUNTING_DIR,
            )

    # Paired H1b confirmatory stats on test & heldout (main_countable & all_v2_countable)
    h1b_confirmatory = {}
    med_v2 = ct.train_medians(v2_names, yolo_dir=YOLO_V2_DIR)
    main_c_ids = ct.countable_ids(include_proposed=False)
    all_c_ids = ct.countable_ids(include_proposed=True)
    cols_main = [i for i, n in enumerate(v2_names) if n in main_c_ids]
    cols_all = [i for i, n in enumerate(v2_names) if n in all_c_ids]

    for sp_name in ("heldout", "test"):
        h1b_confirmatory[sp_name] = {}
        ref_pr = _load_pred(confirmatory_runs[0], sp_name, "nms")
        c_gt = ct.gt_counts(ref_pr["files"], sp_name, len(v2_names), yolo_dir=YOLO_V2_DIR)
        gof = ct.group_of_pairs(sp_name, ref_pr["files"], v2_names)

        # Build family for Holm across models × baselines (primary all_v2_countable on heldout / main_countable on test)
        holm_p_list = []
        holm_refs = []
        for r in confirmatory_runs:
            c_res = counting_runs[f"{r}__nms"]
            conf_cnt = float(c_res["conf_selected_on_val"])
            pr_sp = _load_pred(r, sp_name, "nms")
            chat_det = ct.pred_counts(pr_sp, len(c_gt), len(v2_names), conf_cnt)
            chat_zero = np.zeros_like(c_gt)
            chat_med = np.zeros_like(c_gt)
            for k in cols_all:
                chat_med[:, k] = np.where(c_gt[:, k] > 0, med_v2.get(k, 1), 0)

            h1b_confirmatory[sp_name][r] = {"conf_selected_on_val": conf_cnt}
            for scope_name, cols in (("all_v2_countable", cols_all), ("main_countable", cols_main)):
                mask_union = (c_gt > 0) | (chat_det > 0)
                mask_gt = c_gt > 0

                e_det_u = ct.per_pair_errors(c_gt, chat_det, gof, cols, files=ref_pr["files"], mask=mask_union[:, cols])
                e_zero_u = ct.per_pair_errors(c_gt, chat_zero, gof, cols, files=ref_pr["files"], mask=mask_union[:, cols])
                e_med_u = ct.per_pair_errors(c_gt, chat_med, gof, cols, files=ref_pr["files"], mask=mask_union[:, cols])

                e_det_g = ct.per_pair_errors(c_gt, chat_det, gof, cols, files=ref_pr["files"], mask=mask_gt[:, cols])
                e_med_g = ct.per_pair_errors(c_gt, chat_med, gof, cols, files=ref_pr["files"], mask=mask_gt[:, cols])

                def _pair_stats(ea: dict, eb: dict) -> dict:
                    if len(ea["abs_err"]) == 0:
                        return {"n_pairs": 0}
                    cl_ids = ea["cluster_ids"]
                    n_cl = int(len(np.unique(cl_ids)))
                    return {
                        "n_pairs": int(len(ea["abs_err"])),
                        "n_clusters": n_cl,
                        "mde_dz_80pct": _mde_dz(n_cl),
                        "mae_a": float(ea["abs_err"].mean()),
                        "mae_b": float(eb["abs_err"].mean()),
                        "exact_a": float(ea["exact"].mean()),
                        "exact_b": float(eb["exact"].mean()),
                        "assumptions": mstats.check_paired_assumptions(ea["abs_err"], eb["abs_err"]),
                        "paired_bootstrap": mstats.paired_bootstrap(
                            ea["abs_err"], eb["abs_err"], n_boot=2000, seed=0, clusters=cl_ids
                        ),
                        "wilcoxon": mstats.wilcoxon(ea["abs_err"], eb["abs_err"]),
                        "cohens_dz": mstats.cohens_dz(ea["abs_err"], eb["abs_err"], n_boot=2000, seed=0),
                        "mcnemar_exact": mstats.mcnemar(ea["exact"], eb["exact"]),
                    }

                vs_zero = _pair_stats(e_det_u, e_zero_u)
                vs_med_union = _pair_stats(e_det_u, e_med_u)
                vs_med_gt_only = _pair_stats(e_det_g, e_med_g)
                h1b_confirmatory[sp_name][r][scope_name] = {
                    "vs_zero_baseline_union": vs_zero,
                    "vs_median_baseline_union": vs_med_union,
                    "vs_median_baseline_gt_present": vs_med_gt_only,
                }
                if (sp_name == "heldout" and scope_name == "all_v2_countable") or (
                    sp_name == "test" and scope_name == "main_countable"
                ):
                    for cmp_dict in (vs_zero, vs_med_gt_only):
                        if "paired_bootstrap" in cmp_dict:
                            holm_p_list.append(cmp_dict["paired_bootstrap"]["p"])
                            holm_refs.append(cmp_dict["paired_bootstrap"])

        if holm_p_list:
            h_adj = mstats.holm(holm_p_list).tolist()
            for d_ref, hp in zip(holm_refs, h_adj):
                d_ref["p_holm"] = float(hp)

    # ---------------- Controls ----------------
    neg_summary = None
    if "v2_neg_random_yolo26n" in runs_meta:
        neg_val = coco_all["v2_neg_random_yolo26n"]["val_nms"]
        neg_held = coco_all["v2_neg_random_yolo26n"]["heldout_nms"]
        neg_cnt = counting_runs["v2_neg_random_yolo26n__nms"]
        neg_summary = {
            "run": "v2_neg_random_yolo26n",
            "val_coco": {"AP": neg_val["AP"], "AP50": neg_val["AP50"]},
            "heldout_coco": {"AP": neg_held["AP"], "AP50": neg_held["AP50"]},
            "heldout_counting_detector_mae": neg_cnt["heldout"]["detector"]["mae"],
            "heldout_counting_zero_mae": neg_cnt["heldout"]["zero_baseline"]["mae"],
            "passed": (neg_val["AP50"] < 0.01 and neg_held["AP50"] < 0.01),
        }

    pos_control = {
        "run": "yolo26n_640_none",
        "split": "yolo_v1_test",
        "ultralytics_eval": v1_meta["eval"]["test"],
        "coco_eval": {"AP": v1_test_coco["AP"], "AP50": v1_test_coco["AP50"], "AP75": v1_test_coco["AP75"]},
        "expected_map50_approx": 0.4238,
        "expected_map50_95_approx": 0.2777,
        "passed": abs(v1_test_coco["AP50"] - 0.4217) < 0.02 and abs(v1_test_coco["AP"] - 0.2728) < 0.02,
    }

    # 25-epoch baseline snapshots (preserved prior to continuation to true convergence)
    ep25_snapshots: dict[str, dict] = {}
    if SNAPSHOT_EP25_DIR.exists():
        for r in confirmatory_runs:
            meta_p = SNAPSHOT_EP25_DIR / "detector_runs" / f"{r}.json"
            if not meta_p.exists():
                continue
            s_meta = json.loads(meta_p.read_text(encoding="utf-8"))
            s_preds_dir = SNAPSHOT_EP25_DIR / "preds"
            s_coco: dict[str, dict] = {}
            s_conf = None
            val_npz = s_preds_dir / f"{r}__val__nms.npz"
            if val_npz.exists():
                z_v = np.load(val_npz)
                s_conf, _ = _choose_val_conf_from_pred({k: z_v[k] for k in z_v.files}, gt_val)
            for sp in ("val", "heldout", "test"):
                npz_p = s_preds_dir / f"{r}__{sp}__nms.npz"
                if npz_p.exists():
                    s_coco[f"{sp}_nms"] = coco_cached(
                        r, sp, "nms", YOLO_V2_DIR, pred_path_override=npz_p, cache_prefix=f"{r}__ep25"
                    )
            test_npz = s_preds_dir / f"{r}__test__nms.npz"
            if test_npz.exists():
                s_coco["test_v1_13c_nms"] = coco_cached(
                    r, "test", "nms", YOLO_V1_DIR, remap_to_v1=True,
                    pred_path_override=test_npz, cache_prefix=f"{r}__ep25",
                )
            ep25_snapshots[r] = {
                "meta": s_meta,
                "coco": s_coco,
                "val_selected_conf": s_conf,
            }

    confirmatory_out = {
        "protocol_id": PROTOCOL_ID,
        "generated_utc": dt.datetime.now(dt.UTC).isoformat(),
        "analysis_intent": "confirmatory",
        "controls": {
            "negative_control": neg_summary,
            "positive_sanity_control": pos_control,
        },
        "models_training_metadata": {
            r: {
                k: runs_meta[r].get(k)
                for k in (
                    "model", "imgsz", "batch", "epochs_requested", "epochs_run",
                    "stage1_epochs", "stage2_epochs", "continuation_mode",
                    "best_epoch", "patience", "seed", "workers", "train_seconds",
                    "peak_cuda_reserved_gib", "preprocess_arm",
                )
            }
            for r in confirmatory_runs
        },
        "models_coco": {r: coco_all[r] for r in confirmatory_runs},
        "val_selected_conf": {r: val_confs[r] for r in confirmatory_runs},
        "ep25_baseline_snapshots": ep25_snapshots,
        "h1a_detection": {
            "architecture_comparisons": h1a_arch_contrasts,
            "v1_test_13c_parity": h1a_v1_parity,
        },
        "h1b_counting": h1b_confirmatory,
    }
    (RESEARCH_DIR / "p1_confirmatory_results.json").write_text(
        json.dumps(confirmatory_out, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    counting_out = {
        "protocol_id": PROTOCOL_ID,
        "generated_utc": dt.datetime.now(dt.UTC).isoformat(),
        "runs": counting_runs,
        "paired_confirmatory_stats": h1b_confirmatory,
    }
    (RESEARCH_DIR / "p1_counting_results.json").write_text(
        json.dumps(counting_out, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ---------------- Exploratory Analyses (bh_fdr) ----------------
    exploratory_p: list[float] = []
    exploratory_refs: list[dict] = []

    # 1. Preprocessing ablations
    abl_section: dict = {"runs": {}, "vs_none": {}}
    if abl_runs:
        for r in abl_runs:
            abl_section["runs"][r] = {
                "arm": runs_meta[r]["preprocess_arm"],
                "epochs_run": runs_meta[r].get("epochs_run"),
                "val_coco": coco_all[r].get("val_nms"),
                "heldout_coco": coco_all[r].get("heldout_nms"),
                "val_conf": val_confs[r],
            }
        base_abl = next((r for r in abl_runs if r.endswith("_none")), None)
        if base_abl is not None:
            for sp_name, gt_sp, cl_sp in (("val", gt_val, cl_val), ("heldout", gt_held, cl_held)):
                abl_section["vs_none"][sp_name] = {}
                pr_b = _load_pred(base_abl, sp_name, "nms")
                for r in abl_runs:
                    if r == base_abl:
                        continue
                    pr_a = _load_pred(r, sp_name, "nms")
                    st_abl = _paired_cluster_stats(
                        pr_a, pr_b, gt_sp, cl_sp, val_confs[r], val_confs[base_abl], n_boot=2000, seed=0
                    )
                    abl_section["vs_none"][sp_name][r] = st_abl
                    exploratory_p.append(st_abl["map_cluster_bootstrap"]["map50_95"]["p"])
                    exploratory_refs.append(st_abl["map_cluster_bootstrap"]["map50_95"])

    # 2. NMS vs E2E head comparison on YOLO26 models
    nms_vs_e2e: dict = {}
    for r in confirmatory_runs:
        if "26" not in runs_meta[r]["model"]:
            continue
        nms_vs_e2e[r] = {}
        for sp_name, gt_sp, cl_sp in (("val", gt_val, cl_val), ("heldout", gt_held, cl_held)):
            if not predict_dump.pred_path(r, sp_name, "e2e").exists():
                continue
            pr_nms = _load_pred(r, sp_name, "nms")
            pr_e2e = _load_pred(r, sp_name, "e2e")
            st_mode = _paired_cluster_stats(
                pr_e2e, pr_nms, gt_sp, cl_sp, val_confs[r], val_confs[r], n_boot=2000, seed=0
            )
            nms_vs_e2e[r][sp_name] = st_mode
            exploratory_p.append(st_mode["map_cluster_bootstrap"]["map50_95"]["p"])
            exploratory_refs.append(st_mode["map_cluster_bootstrap"]["map50_95"])

    # 3. Per-source and License (ok vs non_commercial) breakdown
    # Use best confirmatory model by val AP (determined dynamically)
    best_conf_run = max(confirmatory_runs, key=lambda r: coco_all[r]["val_nms"]["AP"])
    by_source_split: dict = {}
    by_license_split: dict = {}
    for sp_name, gt_sp in (("val", gt_val), ("heldout", gt_held)):
        pr_sp = _load_pred(best_conf_run, sp_name, "nms")
        f_names = [str(f) for f in pr_sp["files"]]
        # By source
        src_groups: dict[str, list[int]] = defaultdict(list)
        lic_groups: dict[str, list[int]] = defaultdict(list)
        for i, fn in enumerate(f_names):
            src_groups[fn.split("__")[0]].append(i)
            lic = manifest.get(fn, {}).get("license_flag", "unknown")
            lic_groups[lic].append(i)

        by_source_split[sp_name] = {}
        for src_name, idxs in sorted(src_groups.items()):
            sub_p, sub_g = _subset_pred_and_gt(pr_sp, gt_sp, idxs)
            m_sub = de.coco_metrics(sub_p, sub_g, v2_names)
            by_source_split[sp_name][src_name] = {"n_images": len(idxs), **m_sub}

        by_license_split[sp_name] = {}
        img_m = de.per_image_detection_metrics(pr_sp, gt_sp, conf=val_confs[best_conf_run], iou=0.5)
        for lic_name, idxs in sorted(lic_groups.items()):
            sub_p, sub_g = _subset_pred_and_gt(pr_sp, gt_sp, idxs)
            m_sub = de.coco_metrics(sub_p, sub_g, v2_names)
            by_license_split[sp_name][lic_name] = {
                "n_images": len(idxs),
                "mean_image_f1": float(img_m["f1"][idxs].mean()),
                **m_sub,
            }
        if "ok" in lic_groups and "non_commercial" in lic_groups:
            f1_ok = img_m["f1"][lic_groups["ok"]]
            f1_nc = img_m["f1"][lic_groups["non_commercial"]]
            by_license_split[sp_name]["cliffs_delta_ok_vs_nc_f1"] = float(mstats.cliffs_delta(f1_ok, f1_nc))

    if exploratory_p:
        q_vals = mstats.bh_fdr(exploratory_p).tolist()
        for ref, qv in zip(exploratory_refs, q_vals):
            ref["q_bh"] = float(qv)

    exploratory_out = {
        "protocol_id": PROTOCOL_ID,
        "generated_utc": dt.datetime.now(dt.UTC).isoformat(),
        "analysis_intent": "exploratory",
        "primary_inspected_model": best_conf_run,
        "preprocessing_ablations": abl_section,
        "nms_vs_e2e_head": nms_vs_e2e,
        "by_source": by_source_split,
        "by_license": by_license_split,
    }
    (RESEARCH_DIR / "p1_exploratory_results.json").write_text(
        json.dumps(exploratory_out, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ---------------- Gap Analysis (7 zero-box VN classes + NC license + split coverage) ----------------
    vc_raw = yaml.safe_load(VISION_CLASSES.read_text(encoding="utf-8"))
    all_vc = {r["id"]: r for r in vc_raw["classes"] + vc_raw["proposed_classes"]}
    stats_v2 = json.loads(STATS_V2.read_text(encoding="utf-8"))
    zero_box_classes = []
    for cid in stats_v2["classes_without_data"]:
        row = all_vc[cid]
        zero_box_classes.append({
            "id": cid,
            "name_vi": row["name_vi"],
            "name_en": row["name_en"],
            "dish_main_count": row.get("dish_main_count"),
            "countable": row.get("countable"),
            "instance_def": row.get("instance_def"),
            "public_data": row.get("public_data", {}),
            "pending_public": row.get("pending_public", []),
            "fallback_parent": row.get("fallback_parent"),
            "reason": row.get("reason"),
        })

    # Per-split, per-license image & box counts directly from manifest_v2.csv
    lic_by_split: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    src_lic_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in manifest.values():
        lic_by_split[row["split"]][row["license_flag"]] += 1
        src_lic_counts[row["source"]][row["license_flag"]] += 1

    # Class-level NC box share in train/val/heldout
    nc_class_exposure: dict[str, dict] = {}
    for cid in v2_names:
        c_idx = v2_names.index(cid)
        total_b = 0
        nc_b = 0
        for fn, row in manifest.items():
            sp = row["split"]
            if sp == "test":
                continue
            lp = YOLO_V2_DIR / "labels" / sp / (Path(fn).stem + ".txt")
            if lp.exists():
                cnt = sum(1 for ln in lp.read_text().splitlines() if ln.strip() and int(ln.split()[0]) == c_idx)
                total_b += cnt
                if row["license_flag"] == "non_commercial":
                    nc_b += cnt
        nc_class_exposure[cid] = {
            "train_val_heldout_boxes": total_b,
            "non_commercial_boxes": nc_b,
            "non_commercial_fraction": round(nc_b / total_b, 4) if total_b else 0.0,
        }

    gap_out = {
        "protocol_id": PROTOCOL_ID,
        "generated_utc": dt.datetime.now(dt.UTC).isoformat(),
        "zero_box_vn_main_classes": zero_box_classes,
        "total_dishes_impacted_sum_over_7_classes": sum(x["dish_main_count"] or 0 for x in zero_box_classes),
        "split_missing_classes": {
            "val_zero_gt": [cid for cid in v2_names if cid not in stats_v2["boxes_per_split_class"]["val"]],
            "heldout_zero_gt": [cid for cid in v2_names if cid not in stats_v2["boxes_per_split_class"]["heldout"]],
            "test_zero_gt_expected_non_v1": [cid for cid in v2_names if cid not in stats_v2["boxes_per_split_class"]["test"]],
        },
        "license_split": {
            "total": stats_v2["images_per_license_flag"],
            "by_split": {k: dict(v) for k, v in lic_by_split.items()},
            "by_source": {k: dict(v) for k, v in src_lic_counts.items()},
            "per_class_nc_box_share": nc_class_exposure,
            "nc_dependent_classes_over_50pct": [
                cid for cid, d in nc_class_exposure.items() if d["non_commercial_fraction"] >= 0.5
            ],
        },
    }
    (RESEARCH_DIR / "p1_gap_analysis.json").write_text(
        json.dumps(gap_out, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # ---------------- CSV Summaries ----------------
    summary_csv = RESEARCH_DIR / "p1_runs_summary.csv"
    with summary_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow([
            "run", "dataset", "model", "arm", "imgsz", "batch", "epochs_run", "best_epoch",
            "train_seconds", "peak_cuda_gib", "val_AP", "val_AP50", "val_AP_small",
            "heldout_AP", "heldout_AP50", "heldout_AP_small", "test_v1_13c_AP", "test_v1_13c_AP50",
            "val_selected_conf", "stage",
        ])
        for r in confirmatory_runs + abl_runs + (["v2_neg_random_yolo26n"] if "v2_neg_random_yolo26n" in runs_meta else []):
            meta = runs_meta[r]
            vm = coco_all[r].get("val_nms", {})
            hm = coco_all[r].get("heldout_nms", {})
            tm = coco_all[r].get("test_v1_13c_nms", {})
            stage = (
                "converged" if r in confirmatory_runs
                else ("negative_control" if "neg_" in r else "ablation_ep12")
            )
            w.writerow([
                r, meta.get("dataset"), meta.get("model"), meta.get("preprocess_arm"),
                meta.get("imgsz"), meta.get("batch"), meta.get("epochs_run"), meta.get("best_epoch"),
                meta.get("train_seconds"), meta.get("peak_cuda_reserved_gib"),
                round(vm.get("AP", float("nan")), 5) if vm else "",
                round(vm.get("AP50", float("nan")), 5) if vm else "",
                round(vm.get("AP_small", float("nan")), 5) if vm else "",
                round(hm.get("AP", float("nan")), 5) if hm else "",
                round(hm.get("AP50", float("nan")), 5) if hm else "",
                round(hm.get("AP_small", float("nan")), 5) if hm else "",
                round(tm.get("AP", float("nan")), 5) if tm else "",
                round(tm.get("AP50", float("nan")), 5) if tm else "",
                val_confs.get(r, ""),
                stage,
            ])
        for r, snap in ep25_snapshots.items():
            s_meta = snap["meta"]
            vm = snap["coco"].get("val_nms", {})
            hm = snap["coco"].get("heldout_nms", {})
            tm = snap["coco"].get("test_v1_13c_nms", {})
            w.writerow([
                f"{r}__ep25", s_meta.get("dataset"), s_meta.get("model"), s_meta.get("preprocess_arm"),
                s_meta.get("imgsz"), s_meta.get("batch"), s_meta.get("epochs_run"), s_meta.get("best_epoch"),
                s_meta.get("train_seconds"), s_meta.get("peak_cuda_reserved_gib"),
                round(vm.get("AP", float("nan")), 5) if vm else "",
                round(vm.get("AP50", float("nan")), 5) if vm else "",
                round(vm.get("AP_small", float("nan")), 5) if vm else "",
                round(hm.get("AP", float("nan")), 5) if hm else "",
                round(hm.get("AP50", float("nan")), 5) if hm else "",
                round(hm.get("AP_small", float("nan")), 5) if hm else "",
                round(tm.get("AP", float("nan")), 5) if tm else "",
                round(tm.get("AP50", float("nan")), 5) if tm else "",
                snap.get("val_selected_conf", ""),
                "ep25_snapshot",
            ])

    per_cls_csv = RESEARCH_DIR / "p1_per_class_ap.csv"
    with per_cls_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["run", "split", "class_id", "n_gt", "AP", "AP50", "AP_small"])
        for r in confirmatory_runs:
            for sp in ("val", "heldout"):
                cm = coco_all[r].get(f"{sp}_nms")
                if not cm:
                    continue
                gt_cnts = stats_v2["boxes_per_split_class"][sp]
                for cid in v2_names:
                    w.writerow([
                        r, sp, cid, gt_cnts.get(cid, 0),
                        "" if cm["per_class_AP"][cid] is None else round(cm["per_class_AP"][cid], 5),
                        "" if cm["per_class_AP50"][cid] is None else round(cm["per_class_AP50"][cid], 5),
                        "" if cm["per_class_AP_small"][cid] is None else round(cm["per_class_AP_small"][cid], 5),
                    ])

    return {
        "confirmatory": confirmatory_out,
        "exploratory": exploratory_out,
        "counting": counting_out,
        "gap": gap_out,
        "confirmatory_runs": confirmatory_runs,
    }


# ------------------------------------------------------------------ Latency Benchmarking


def run_latency_bench(runs: list[str] | None = None, n: int = 100, threads: int = 2) -> dict:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    if runs is None:
        runs = [
            p.stem for p in sorted(RUN_META_DIR.glob("v2_*_s0.json"))
            if "neg_" not in p.stem
        ]
    cpu = subprocess.check_output(["bash", "-c", "lscpu | grep 'Model name' | head -1"], text=True).split(":")[-1].strip()
    out: dict = {
        "protocol_id": PROTOCOL_ID,
        "generated_utc": dt.datetime.now(dt.UTC).isoformat(),
        "cpu": cpu,
        "threads": threads,
        "n_images": n,
        "runs": {},
    }
    for r in runs:
        meta = json.loads((RUN_META_DIR / f"{r}.json").read_text(encoding="utf-8"))
        imgsz = int(meta["imgsz"])
        modes = ["raw", "e2e"] if "26" in meta["model"] else ["raw"]
        r_res: dict = {"model": meta["model"], "imgsz": imgsz}
        for mode in modes:
            onnx_p = ol.export(r, imgsz, mode)
            r_res[f"{mode}_c1"] = ol.bench(
                onnx_p, imgsz, mode, n=n, threads=threads, yolo_dir=YOLO_V2_DIR, expected_nc=30
            )
            r_res[f"{mode}_c5"] = ol.bench_concurrent(
                onnx_p, imgsz, mode, concurrency=5, n=n, threads=threads, yolo_dir=YOLO_V2_DIR, expected_nc=30
            )
        out["runs"][r] = r_res

    # Reference v1 baseline ONNX latency (read-only)
    v1_onnx = REPO / "deploy" / "models" / "detector" / "model.onnx"
    if v1_onnx.exists():
        out["v1_baseline_reference"] = {
            "raw_c1": ol.bench(v1_onnx, 640, "raw", n=n, threads=threads, yolo_dir=YOLO_V1_DIR, expected_nc=13),
            "raw_c5": ol.bench_concurrent(v1_onnx, 640, "raw", concurrency=5, n=n, threads=threads, yolo_dir=YOLO_V1_DIR, expected_nc=13),
        }

    (RESEARCH_DIR / "p1_latency_results.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out


# ------------------------------------------------------------------ Export Best Detector v2


def _letterbox_rgb(img_rgb, size: int) -> tuple[np.ndarray, tuple[float, int, int, int, int]]:
    w, h = img_rgb.size
    scale = min(size / w, size / h)
    nw, nh = round(w * scale), round(h * scale)
    dw, dh = (size - nw) // 2, (size - nh) // 2
    from PIL import Image

    canvas = Image.new("RGB", (size, size), (114, 114, 114))
    canvas.paste(img_rgb.resize((nw, nh), Image.Resampling.BILINEAR), (dw, dh))
    arr = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
    return arr, (scale, dw, dh, w, h)


def _decode_raw_like_backend(
    raw: np.ndarray,
    lb: tuple[float, int, int, int, int],
    conf: float,
    iou: float,
) -> list[tuple[int, float, np.ndarray]]:
    """Exact pure-NumPy decode + greedy per-class NMS matching backend scan/detector.py."""
    scale, dw, dh, orig_w, orig_h = lb
    preds = raw[0].T  # (8400, 4 + nc)
    scores_mat = preds[:, 4:]
    cls_ids = scores_mat.argmax(axis=1)
    confs = scores_mat[np.arange(len(preds)), cls_ids]
    keep = confs >= conf
    if not np.any(keep):
        return []
    boxes = preds[keep, :4]
    cls_ids = cls_ids[keep]
    confs = confs[keep]

    cx, cy, bw, bh = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    x1 = (cx - bw / 2 - dw) / scale
    y1 = (cy - bh / 2 - dh) / scale
    x2 = (cx + bw / 2 - dw) / scale
    y2 = (cy + bh / 2 - dh) / scale
    xyxy = np.stack([
        np.clip(x1, 0, orig_w),
        np.clip(y1, 0, orig_h),
        np.clip(x2, 0, orig_w),
        np.clip(y2, 0, orig_h),
    ], axis=1)

    order = np.argsort(-confs, kind="mergesort")
    xyxy = xyxy[order]
    cls_ids = cls_ids[order]
    confs = confs[order]

    out: list[tuple[int, float, np.ndarray]] = []
    for c in np.unique(cls_ids):
        c_idx = np.where(cls_ids == c)[0]
        b_c = xyxy[c_idx]
        s_c = confs[c_idx]
        areas = np.maximum(0.0, b_c[:, 2] - b_c[:, 0]) * np.maximum(0.0, b_c[:, 3] - b_c[:, 1])
        suppressed = np.zeros(len(c_idx), dtype=bool)
        for i in range(len(c_idx)):
            if suppressed[i]:
                continue
            out.append((int(c), float(s_c[i]), b_c[i]))
            if i + 1 >= len(c_idx):
                break
            xx1 = np.maximum(b_c[i, 0], b_c[i + 1 :, 0])
            yy1 = np.maximum(b_c[i, 1], b_c[i + 1 :, 1])
            xx2 = np.minimum(b_c[i, 2], b_c[i + 1 :, 2])
            yy2 = np.minimum(b_c[i, 3], b_c[i + 1 :, 3])
            inter = np.maximum(0.0, xx2 - xx1) * np.maximum(0.0, yy2 - yy1)
            union = areas[i] + areas[i + 1 :] - inter
            ious = np.where(union > 0, inter / np.maximum(union, 1e-12), 0.0)
            suppressed[i + 1 :] |= ious > iou
    out.sort(key=lambda x: -x[1])
    return out


def export_best_detector_v2(
    conf_data: dict,
    latency_data: dict,
    gap_data: dict,
    force_run: str | None = None,
) -> dict:
    """Select best validated 30-class model, export raw ONNX [1, 34, 8400], tune conf on val, write serving.json."""
    import onnxruntime as ort
    from PIL import Image

    candidates = list(conf_data["models_coco"].keys())
    if force_run:
        best_run = force_run
    else:
        eligible = []
        for r in candidates:
            val_ap = conf_data["models_coco"][r]["val_nms"]["AP"]
            lat_r = latency_data["runs"].get(r, {}).get("raw_c1", {})
            p95_model = lat_r.get("model_ms", {}).get("p95", float("inf"))
            parity_ci90 = conf_data["h1a_detection"]["v1_test_13c_parity"][r]["map_cluster_bootstrap"]["map50_95"]["ci90"]
            if p95_model <= 100.0 and parity_ci90[0] >= -TOST_MARGIN:
                eligible.append((val_ap, r))
        if not eligible:
            # Fall back to fastest passing latency or highest val AP
            eligible = [(conf_data["models_coco"][r]["val_nms"]["AP"], r) for r in candidates]
        best_run = max(eligible, key=lambda x: x[0])[1]

    meta = json.loads((RUN_META_DIR / f"{best_run}.json").read_text(encoding="utf-8"))
    imgsz = int(meta["imgsz"])
    raw_onnx_src = ol.export(best_run, imgsz, "raw")
    DEPLOY_V2_DIR.mkdir(parents=True, exist_ok=True)
    dst_onnx = DEPLOY_V2_DIR / "model.onnx"
    shutil.copy2(raw_onnx_src, dst_onnx)

    # Verify ONNX contract strictly
    so = ort.SessionOptions()
    so.intra_op_num_threads = 2
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(str(dst_onnx), so, providers=["CPUExecutionProvider"])
    in_shape = tuple(sess.get_inputs()[0].shape)
    out_shape = tuple(sess.get_outputs()[0].shape)
    assert in_shape == (1, 3, imgsz, imgsz), f"Unexpected ONNX input shape {in_shape}"
    assert out_shape == (1, 34, 8400), f"Unexpected ONNX output shape {out_shape}"
    ort_meta = sess.get_modelmeta().custom_metadata_map
    assert ort_meta.get("end2end") == "False", f"Expected end2end='False', got {ort_meta.get('end2end')}"
    names_map = ast.literal_eval(ort_meta["names"])
    classes_30 = [names_map[i] for i in range(30)]
    assert classes_30 == _load_v2_names(), "ONNX names metadata mismatch with yolo_v2/dataset.yaml"

    # Tune serving confidence threshold strictly on yolo_v2 val using ONNX + backend post-processing
    val_imgs = sorted((YOLO_V2_DIR / "images" / "val").glob("*.jpg"))
    grid = np.round(np.arange(0.05, 0.951, 0.01), 2)
    min_conf = float(grid[0])
    nms_iou = 0.7
    iou_match = 0.5
    preds_cls: list[list[tuple[float, bool]]] = [[] for _ in range(30)]
    n_gt = np.zeros(30, dtype=int)

    t0 = time.time()
    for img_p in val_imgs:
        with Image.open(img_p) as im:
            rgb = im.convert("RGB")
        x, lb = _letterbox_rgb(rgb, imgsz)
        orig_w, orig_h = lb[3], lb[4]
        raw_out = sess.run(None, {sess.get_inputs()[0].name: x})[0]
        dets = _decode_raw_like_backend(raw_out, lb, conf=min_conf, iou=nms_iou)

        lbl_p = YOLO_V2_DIR / "labels" / "val" / (img_p.stem + ".txt")
        gts_by_c: dict[int, list[np.ndarray]] = defaultdict(list)
        if lbl_p.exists():
            for ln in lbl_p.read_text().splitlines():
                if ln.strip():
                    c, xc, yc, bw, bh = ln.split()[:5]
                    xc, yc, bw, bh = map(float, (xc, yc, bw, bh))
                    gts_by_c[int(c)].append(
                        np.array([(xc - bw / 2) * orig_w, (yc - bh / 2) * orig_h, (xc + bw / 2) * orig_w, (yc + bh / 2) * orig_h])
                    )
        for c in range(30):
            g_arr = np.array(gts_by_c[c]).reshape(-1, 4) if gts_by_c[c] else np.zeros((0, 4))
            n_gt[c] += len(g_arr)
            used = np.zeros(len(g_arr), dtype=bool)
            for dc, ds, db in dets:
                if dc != c:
                    continue
                tp = False
                if len(g_arr) > 0:
                    ious = de.iou_matrix(db[None, :], g_arr)[0]
                    ious[used] = -1.0
                    j = int(np.argmax(ious))
                    if ious[j] >= iou_match:
                        used[j] = True
                        tp = True
                preds_cls[c].append((ds, tp))
    conf_seconds = time.time() - t0

    def _at_conf(t: float) -> tuple[dict[str, dict], float, float]:
        per_cls = {}
        covered_f1s = []
        all_f1s = []
        for c in range(30):
            tp = sum(1 for s, ok in preds_cls[c] if s >= t and ok)
            fp = sum(1 for s, ok in preds_cls[c] if s >= t and not ok)
            gt_n = int(n_gt[c])
            p = tp / (tp + fp) if (tp + fp) else 0.0
            r = tp / gt_n if gt_n else 0.0
            f1 = 2 * p * r / (p + r) if (p + r) else 0.0
            per_cls[classes_30[c]] = {
                "precision": p,
                "recall": r,
                "f1": f1,
                "tp": tp,
                "fp": fp,
                "gt": gt_n,
                "covered_in_val": gt_n > 0,
            }
            all_f1s.append(f1)
            if gt_n > 0:
                covered_f1s.append(f1)
        return per_cls, float(np.mean(covered_f1s)), float(np.mean(all_f1s))

    curve = []
    for t in grid:
        _, mf1_cov, mf1_all = _at_conf(float(t))
        curve.append({"conf": float(t), "macro_f1": round(mf1_cov, 4), "macro_f1_all30": round(mf1_all, 4)})
    best_pt_c = max(curve, key=lambda x: (x["macro_f1"], -x["conf"]))
    best_conf = float(best_pt_c["conf"])
    per_cls_best, mf1_cov_best, mf1_all_best = _at_conf(best_conf)

    sha256 = hashlib.sha256(dst_onnx.read_bytes()).hexdigest()
    lat_run = latency_data["runs"][best_run]
    val_m = conf_data["models_coco"][best_run]["val_nms"]
    held_m = conf_data["models_coco"][best_run]["heldout_nms"]
    v1_13c_m = conf_data["models_coco"][best_run]["test_v1_13c_nms"]

    nc_share = gap_data["license_split"]["per_class_nc_box_share"]
    serving = {
        "conf": best_conf,
        "iou": nms_iou,
        "imgsz": imgsz,
        "sha256": sha256,
        "model": meta["model"],
        "version": best_run,
        "preprocess_version": meta["preprocess_arm"],
        "onnx": "model.onnx",
        "onnx_bytes": dst_onnx.stat().st_size,
        "onnx_output_shape": list(out_shape),
        "classes": classes_30,
        "n_classes": 30,
        "nc_license_classes": sorted(gap_data["license_split"]["nc_dependent_classes_over_50pct"]),
        "license_split": {
            "total_images": gap_data["license_split"]["total"],
            "by_source": gap_data["license_split"]["by_source"],
            "per_class_nc_box_share": nc_share,
            "note": "5,327 of 20,638 yolo_v2 training/eval images carry non-commercial licenses (LVIS NC / RPC Checkout).",
        },
        "latency_ms": {
            "c1": {
                "model_ms": lat_run["raw_c1"]["model_ms"],
                "total_ms": lat_run["raw_c1"]["total_ms"],
            },
            "c5": {
                "model_ms": lat_run["raw_c5"]["model_ms"],
                "total_ms": lat_run["raw_c5"]["total_ms"],
                "throughput_img_s": lat_run["raw_c5"]["throughput_img_s"],
            },
        },
        "metrics": {
            "val": {
                "mAP50": val_m["AP50"],
                "mAP50_95": val_m["AP"],
                "AP_small": val_m["AP_small"],
                "AP_medium": val_m["AP_medium"],
                "AP_large": val_m["AP_large"],
                "macro_f1_covered_28": mf1_cov_best,
                "macro_f1_all_30": mf1_all_best,
            },
            "heldout": {
                "mAP50": held_m["AP50"],
                "mAP50_95": held_m["AP"],
                "AP_small": held_m["AP_small"],
                "AP_medium": held_m["AP_medium"],
                "AP_large": held_m["AP_large"],
            },
            "v1_test_13c": {
                "mAP50": v1_13c_m["AP50"],
                "mAP50_95": v1_13c_m["AP"],
                "tost_verdict_vs_v1": conf_data["h1a_detection"]["v1_test_13c_parity"][best_run]["tost_verdict"],
            },
        },
        "selection": "argmax macro-F1 over covered val classes (n_gt > 0, 28/30; dau_phu & ot have 0 val GT), IoU >= 0.5",
        "split": str(YOLO_V2_DIR / "images" / "val"),
        "n_images": len(val_imgs),
        "macro_f1": mf1_cov_best,
        "macro_f1_all30": mf1_all_best,
        "per_class_at_conf": per_cls_best,
        "f1_curve": curve,
        "seconds": round(conf_seconds, 1),
        "note": "Public data only (30 covered classes; 7 VN classes have 0 boxes; 5,327 images are non-commercial).",
    }
    (DEPLOY_V2_DIR / "serving.json").write_text(
        json.dumps(serving, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return serving


def write_manifest(serving: dict) -> dict:
    import onnxruntime as ort
    import scipy
    import torch
    import ultralytics

    artifacts = {}
    for p in sorted(RESEARCH_DIR.glob("p1_*.*")) + [DEPLOY_V2_DIR / "model.onnx", DEPLOY_V2_DIR / "serving.json"]:
        if p.exists():
            artifacts[str(p.relative_to(REPO))] = {
                "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
    manifest = {
        "protocol_id": PROTOCOL_ID,
        "generated_utc": dt.datetime.now(dt.UTC).isoformat(),
        "environment": {
            "python": subprocess.check_output(["python3", "--version"], text=True).strip(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "torch": torch.__version__,
            "ultralytics": ultralytics.__version__,
            "onnxruntime": ort.__version__,
        },
        "selected_detector_v2": {
            "version": serving["version"],
            "model": serving["model"],
            "conf": serving["conf"],
            "iou": serving["iou"],
            "imgsz": serving["imgsz"],
            "onnx_sha256": serving["sha256"],
        },
        "artifacts": artifacts,
    }
    (RESEARCH_DIR / "p1_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["neg-control", "eval", "latency", "export", "all"])
    ap.add_argument("--force-run", default=None)
    a = ap.parse_args(argv)

    if a.cmd == "neg-control":
        print(json.dumps(run_negative_control(), indent=2))
    elif a.cmd == "eval":
        res = run_eval_and_stats()
        print("eval complete:", res["confirmatory_runs"])
    elif a.cmd == "latency":
        res = run_latency_bench()
        print("latency complete:", list(res["runs"]))
    elif a.cmd == "export":
        conf_d = json.loads((RESEARCH_DIR / "p1_confirmatory_results.json").read_text(encoding="utf-8"))
        lat_d = json.loads((RESEARCH_DIR / "p1_latency_results.json").read_text(encoding="utf-8"))
        gap_d = json.loads((RESEARCH_DIR / "p1_gap_analysis.json").read_text(encoding="utf-8"))
        serv = export_best_detector_v2(conf_d, lat_d, gap_d, force_run=a.force_run)
        write_manifest(serv)
        print("exported:", serv["version"], "conf=", serv["conf"], "sha256=", serv["sha256"])
    elif a.cmd == "all":
        run_negative_control()
        ev = run_eval_and_stats()
        lat = run_latency_bench(runs=ev["confirmatory_runs"])
        serv = export_best_detector_v2(ev["confirmatory"], lat, ev["gap"], force_run=a.force_run)
        man = write_manifest(serv)
        print("p1_study all complete:", man["selected_detector_v2"])


if __name__ == "__main__":
    main()
