"""Problem 2 (CV Produce Freshness & Probability Calibration) M1.2b study orchestrator.

Implements confirmatory (H2a, H2b) and exploratory (#3 kiem_tra abstention, #4 shortcut
and grouping leakage audit) analyses per ``TASTORIA-ML-PREREG-2026-11-18``, benchmarks
6 model families across 3 seeds x 5 StratifiedGroupKFold splits on ``d8dedup4`` (2,366
independent groups) using a shared zero-leakage ``(fit_k, cal_k, te_k)`` partition,
and exports a calibrated PIL+NumPy-compatible ONNX model to ``deploy/models/freshness/``.

Run on 171.226.10.153:
  CUDA_VISIBLE_DEVICES="" ml/runs/venv-cv/bin/python -m tastoria_ml.cv.freshness_study --phase cpu --n-jobs 4
  ml/runs/venv-cv/bin/python -m tastoria_ml.cv.freshness_study --phase gpu
  CUDA_VISIBLE_DEVICES="" ml/runs/venv-cv/bin/python -m tastoria_ml.cv.freshness_study --phase analyze
  ml/runs/venv-cv/bin/python -m tastoria_ml.cv.freshness_study --phase export
"""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import csv
import datetime as dt
import hashlib
import json
import math
import os
import platform
import time
from pathlib import Path

import numpy as np
import pandas as pd

from tastoria_ml import stats as mstats
from tastoria_ml.cv import calibration as cal
from tastoria_ml.cv.classes import REPO
from tastoria_ml.cv.freshness import (
    LABELS,
    N_FOLDS,
    OUT as LEGACY_OUT,
    SIZE,
    WORK,
    features,
    folds,
    get_groups,
    load_cache,
    load_table,
    merge_groups,
)

PROTOCOL_ID = "TASTORIA-ML-PREREG-2026-11-18"
SEEDS = (0, 1, 2)
GROUPS_KIND = "d8dedup4"
CPU_MODELS = ("dummy", "logreg", "rbf_svm")
CNN_MODELS = ("mobilenet_v3_small", "efficientnet_b0", "resnet18")
ALL_MODELS = CPU_MODELS + CNN_MODELS

RESEARCH_DIR = REPO / "ml" / "runs" / "research" / "p2_freshness"
OOF_DIR = RESEARCH_DIR / "oof"
DEPLOY_FRESHNESS_DIR = REPO / "deploy" / "models" / "freshness"
Z_MDE_80 = 1.959963984540054 + 0.8416212335729143  # ~2.801585


def _mde_dz(n_eff: int) -> float:
    return float(Z_MDE_80 / math.sqrt(n_eff)) if n_eff > 0 else float("nan")


def _load_table_and_groups(groups_kind: str = GROUPS_KIND) -> tuple[pd.DataFrame, np.ndarray]:
    """Load table and grouping vector without requiring X224.npy when phash cache exists."""
    table_csv = WORK / "table.csv"
    df = pd.read_csv(table_csv) if table_csv.exists() else load_table()
    if groups_kind == "lot":
        return df, df.lot.values
    if groups_kind == "d8dedup4" and (WORK / "phash_d8_pairs.npy").exists():
        pairs = np.load(WORK / "phash_d8_pairs.npy")
        return df, merge_groups(df.lot.values, pairs[pairs[:, 2] <= 4])
    if groups_kind == "dedup4" and (WORK / "phash_pairs.npy").exists():
        pairs = np.load(WORK / "phash_pairs.npy")
        return df, merge_groups(df.lot.values, pairs[pairs[:, 2] <= 4])
    return df, get_groups(groups_kind)


def make_zero_leakage_splits(
    df: pd.DataFrame,
    groups: np.ndarray,
    seed: int,
    n_folds: int = N_FOLDS,
    cal_n_splits: int = 7,
) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Build deterministic zero-leakage ``(fit_k, cal_k, te_k)`` partitions grouped by ``groups``.

    For each outer fold ``k`` from ``freshness.folds(df, repeat=seed, groups=groups)``,
    ``tr_k`` is split deterministically by ``groups[tr_k]`` via ``StratifiedGroupKFold``
    (``n_splits=cal_n_splits``, taking fold 0 ≈ 14.3% of ``tr_k`` as ``cal_k`` and the
    remaining ≈ 85.7% as ``fit_k``). Disjointness across ``fit_k``, ``cal_k``, and
    ``te_k`` groups is asserted unconditionally.
    """
    from sklearn.model_selection import StratifiedGroupKFold

    if cal_n_splits < 2:
        raise ValueError("cal_n_splits must be >= 2")
    outer_f = folds(df, repeat=seed, groups=groups)
    strat = (df.dataset.astype(str) + "/" + df.produce.astype(str) + "/" + df.label3.astype(str)).astype("category").cat.codes.values

    splits: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for k in range(n_folds):
        tr_k = np.where(outer_f != k)[0]
        te_k = np.where(outer_f == k)[0]
        eff_splits = min(cal_n_splits, max(2, int(len(np.unique(groups[tr_k])))))
        sgk_in = StratifiedGroupKFold(
            n_splits=eff_splits,
            shuffle=True,
            random_state=1000 + seed * 10 + k,
        )
        _, cal_rel = next(sgk_in.split(np.zeros(len(tr_k)), strat[tr_k], groups[tr_k]))
        cal_k = np.sort(tr_k[cal_rel])
        fit_k = np.sort(np.delete(tr_k, cal_rel))

        g_fit = set(groups[fit_k].tolist())
        g_cal = set(groups[cal_k].tolist())
        g_te = set(groups[te_k].tolist())
        if not g_fit.isdisjoint(g_cal):
            raise AssertionError(f"Group leakage between fit_k and cal_k (seed={seed}, fold={k})")
        if not g_fit.isdisjoint(g_te):
            raise AssertionError(f"Group leakage between fit_k and te_k (seed={seed}, fold={k})")
        if not g_cal.isdisjoint(g_te):
            raise AssertionError(f"Group leakage between cal_k and te_k (seed={seed}, fold={k})")

        splits.append((fit_k, cal_k, te_k))
    return splits


def _eval_logits_summary(logits: np.ndarray, y: np.ndarray, n_bins: int = 10) -> dict:
    probs = cal.softmax(logits)
    pred = np.argmax(probs, axis=1)
    cm = mstats.calibration_metrics(y, probs, n_bins=n_bins)
    return {
        "n": int(len(y)),
        "accuracy": cal.accuracy(y, pred),
        "macro_f1": cal.macro_f1(y, pred, n_classes=len(LABELS)),
        "qwk": cal.qwk(y, pred, n_classes=len(LABELS)),
        "mae_level": cal.mae_level(y, pred),
        "ece": float(cm["ece"]),
        "ece_adaptive": float(cm["ece_adaptive"]),
        "brier": float(cm["brier"]),
        "nll": float(cm["nll"]),
    }


def _save_model_seed_artifacts(
    model_name: str,
    seed: int,
    y: np.ndarray,
    groups: np.ndarray,
    splits: list[tuple[np.ndarray, np.ndarray, np.ndarray]],
    cal_logits_per_fold: list[np.ndarray],
    te_logits_per_fold: list[np.ndarray],
    extra_fold_meta: list[dict],
    runtime_sec: float,
    preprocess: str = "grabcut",
    tag_suffix: str = "",
) -> dict:
    OOF_DIR.mkdir(parents=True, exist_ok=True)
    n_samples = len(y)
    n_classes = len(LABELS)
    raw_oof = np.empty((n_samples, n_classes), dtype=np.float64)
    cal_y_per_fold = [y[cal_k] for _, cal_k, _ in splits]
    te_idx_per_fold = [te_k for _, _, te_k in splits]

    for k, (_, _, te_k) in enumerate(splits):
        raw_oof[te_k] = te_logits_per_fold[k]

    res_temp = cal.fit_and_apply_fold_calibration(
        cal_logits_per_fold=cal_logits_per_fold,
        cal_y_per_fold=cal_y_per_fold,
        test_logits_per_fold=te_logits_per_fold,
        test_indices_per_fold=te_idx_per_fold,
        n_samples=n_samples,
        method="temperature",
    )
    res_vec = cal.fit_and_apply_fold_calibration(
        cal_logits_per_fold=cal_logits_per_fold,
        cal_y_per_fold=cal_y_per_fold,
        test_logits_per_fold=te_logits_per_fold,
        test_indices_per_fold=te_idx_per_fold,
        n_samples=n_samples,
        method="vector",
    )
    res_platt = cal.fit_and_apply_fold_calibration(
        cal_logits_per_fold=cal_logits_per_fold,
        cal_y_per_fold=cal_y_per_fold,
        test_logits_per_fold=te_logits_per_fold,
        test_indices_per_fold=te_idx_per_fold,
        n_samples=n_samples,
        method="platt",
    )

    stem = f"{model_name}{tag_suffix}_s{seed}"
    np.save(OOF_DIR / f"{stem}_raw_logits.npy", raw_oof.astype(np.float32))
    np.save(OOF_DIR / f"{stem}_cal_temp_logits.npy", res_temp["cal_logits"].astype(np.float32))
    np.save(OOF_DIR / f"{stem}_cal_vec_logits.npy", res_vec["cal_logits"].astype(np.float32))

    split_sizes = [
        {"fold": k, "n_fit": int(len(fit_k)), "n_cal": int(len(cal_k)), "n_te": int(len(te_k))}
        for k, (fit_k, cal_k, te_k) in enumerate(splits)
    ]
    meta = {
        "protocol_id": PROTOCOL_ID,
        "model": model_name,
        "tag_suffix": tag_suffix,
        "seed": int(seed),
        "groups_kind": GROUPS_KIND,
        "n_groups": int(len(np.unique(groups))),
        "preprocess": preprocess,
        "runtime_sec": float(runtime_sec),
        "split_sizes": split_sizes,
        "extra_fold_meta": extra_fold_meta,
        "fold_params_temp": res_temp["fold_params"],
        "fold_params_vec": res_vec["fold_params"],
        "fold_params_platt": res_platt["fold_params"],
        "metrics_raw": _eval_logits_summary(raw_oof, y),
        "metrics_cal_temp": _eval_logits_summary(res_temp["cal_logits"], y),
        "metrics_cal_vec": _eval_logits_summary(res_vec["cal_logits"], y),
        "metrics_cal_platt": _eval_logits_summary(res_platt["cal_logits"], y),
    }
    (OOF_DIR / f"{stem}_fold_params.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


# ------------------------------------------------------------------ CPU models


def run_cpu_models(
    seeds: tuple[int, ...] = SEEDS,
    models: tuple[str, ...] = CPU_MODELS,
    n_jobs: int = 4,
    groups_kind: str = GROUPS_KIND,
) -> dict:
    """Run ``dummy``, ``logreg``, and ``rbf_svm`` across seeds on shared zero-leakage splits."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GridSearchCV, GroupKFold
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC

    df, groups = _load_table_and_groups(groups_kind)
    y = df.y.values.astype(np.int64)
    feat = features()

    summary: dict[str, list[dict]] = {m: [] for m in models}
    for seed in seeds:
        splits = make_zero_leakage_splits(df, groups, seed=seed)
        for model_name in models:
            t0 = time.perf_counter()
            cal_logits_list: list[np.ndarray] = []
            te_logits_list: list[np.ndarray] = []
            extra_meta: list[dict] = []

            for k, (fit_k, cal_k, te_k) in enumerate(splits):
                if model_name == "dummy":
                    counts = np.bincount(y[fit_k], minlength=len(LABELS)).astype(np.float64)
                    prior = np.clip(counts / counts.sum(), 1e-12, 1.0)
                    log_prior = np.log(prior)
                    z_cal = np.tile(log_prior, (len(cal_k), 1))
                    z_te = np.tile(log_prior, (len(te_k), 1))
                    extra_meta.append({"fold": k, "prior": prior.tolist()})
                elif model_name == "logreg":
                    gs = GridSearchCV(
                        make_pipeline(
                            StandardScaler(),
                            LogisticRegression(max_iter=2000, random_state=seed),
                        ),
                        {"logisticregression__C": [0.01, 0.1, 1.0, 10.0]},
                        cv=GroupKFold(3),
                        scoring="f1_macro",
                        n_jobs=n_jobs,
                    )
                    gs.fit(feat[fit_k], y[fit_k], groups=groups[fit_k])
                    z_cal = np.log(np.clip(gs.predict_proba(feat[cal_k]), 1e-12, 1.0))
                    z_te = np.log(np.clip(gs.predict_proba(feat[te_k]), 1e-12, 1.0))
                    extra_meta.append({
                        "fold": k,
                        "best_params": gs.best_params_,
                        "best_cv_f1_macro": float(gs.best_score_),
                    })
                elif model_name == "rbf_svm":
                    gs = GridSearchCV(
                        make_pipeline(
                            StandardScaler(),
                            SVC(kernel="rbf", probability=True, random_state=seed),
                        ),
                        {"svc__C": [1, 10, 100], "svc__gamma": ["scale", 0.01, 0.003]},
                        cv=GroupKFold(3),
                        scoring="f1_macro",
                        n_jobs=n_jobs,
                    )
                    gs.fit(feat[fit_k], y[fit_k], groups=groups[fit_k])
                    z_cal = np.log(np.clip(gs.predict_proba(feat[cal_k]), 1e-12, 1.0))
                    z_te = np.log(np.clip(gs.predict_proba(feat[te_k]), 1e-12, 1.0))
                    extra_meta.append({
                        "fold": k,
                        "best_params": gs.best_params_,
                        "best_cv_f1_macro": float(gs.best_score_),
                    })
                else:
                    raise ValueError(f"Unsupported CPU model: {model_name!r}")

                cal_logits_list.append(z_cal)
                te_logits_list.append(z_te)

            dt_sec = time.perf_counter() - t0
            meta = _save_model_seed_artifacts(
                model_name=model_name,
                seed=seed,
                y=y,
                groups=groups,
                splits=splits,
                cal_logits_per_fold=cal_logits_list,
                te_logits_per_fold=te_logits_list,
                extra_fold_meta=extra_meta,
                runtime_sec=dt_sec,
                preprocess="grabcut_81dim",
            )
            summary[model_name].append(meta)
            m_raw = meta["metrics_raw"]
            m_cal = meta["metrics_cal_temp"]
            print(
                f"[{model_name}] seed={seed} ({dt_sec:.1f}s) | "
                f"raw f1={m_raw['macro_f1']:.4f} qwk={m_raw['qwk']:.4f} ece={m_raw['ece']:.4f} | "
                f"temp_cal ece={m_cal['ece']:.4f} nll={m_cal['nll']:.4f}",
                flush=True,
            )

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "protocol_id": PROTOCOL_ID,
        "phase": "cpu",
        "groups_kind": groups_kind,
        "seeds": list(seeds),
        "models": list(models),
        "n_jobs": int(n_jobs),
        "runs": summary,
    }
    (RESEARCH_DIR / "p2_cpu_runs.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


# ------------------------------------------------------------------ GPU CNN models


def _build_cnn_backbone(arch: str, pretrained: bool = True, num_classes: int = 3):
    import torchvision
    from torch import nn

    weights = "IMAGENET1K_V1" if pretrained else None
    if arch == "mobilenet_v3_small":
        net = torchvision.models.mobilenet_v3_small(weights=weights)
        net.classifier[3] = nn.Linear(net.classifier[3].in_features, num_classes)
        return net
    if arch == "efficientnet_b0":
        net = torchvision.models.efficientnet_b0(weights=weights)
        net.classifier[1] = nn.Linear(net.classifier[1].in_features, num_classes)
        return net
    if arch == "resnet18":
        net = torchvision.models.resnet18(weights=weights)
        net.fc = nn.Linear(net.fc.in_features, num_classes)
        return net
    raise ValueError(f"Unknown CNN architecture: {arch!r}")


def _train_single_cnn_fold(
    arch: str,
    xm: np.ndarray,
    y: np.ndarray,
    fit_idx: np.ndarray,
    cal_idx: np.ndarray | None,
    te_idx: np.ndarray | None,
    epochs: int,
    batch: int,
    fold_seed: int,
    dev,
) -> tuple[object, np.ndarray | None, np.ndarray | None, dict]:
    import torch
    from torch import nn

    torch.manual_seed(fold_seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(fold_seed)
    rng = np.random.default_rng(fold_seed)

    mean = torch.tensor([0.485, 0.456, 0.406], device=dev).view(1, 3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225], device=dev).view(1, 3, 1, 1)

    def _to_tensor(idx: np.ndarray, train: bool):
        x = torch.from_numpy(np.ascontiguousarray(xm[idx])).to(dev).permute(0, 3, 1, 2).float() / 255.0
        if train:
            if float(torch.rand(1).item()) < 0.5:
                x = x.flip(3)
            if float(torch.rand(1).item()) < 0.5:
                x = x.flip(2)
            x = x * (1.0 + 0.2 * (torch.rand(len(idx), 1, 1, 1, device=dev) - 0.5))
        return (x.clamp(0.0, 1.0) - mean) / std

    def _eval_logits(model, idx: np.ndarray) -> np.ndarray:
        model.eval()
        chunks = []
        with torch.no_grad():
            for i in range(0, len(idx), 256):
                sub = idx[i : i + 256]
                chunks.append(model(_to_tensor(sub, False)).detach().cpu().numpy())
        return np.concatenate(chunks, axis=0) if chunks else np.empty((0, len(LABELS)), dtype=np.float32)

    net = _build_cnn_backbone(arch, pretrained=True, num_classes=len(LABELS)).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-4)
    steps = max(1, epochs * int(math.ceil(len(fit_idx) / batch)))
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=1e-3, total_steps=steps)

    best_state = None
    best_cal_nll = float("inf")
    best_epoch = epochs - 1

    for ep in range(epochs):
        net.train()
        perm = rng.permutation(fit_idx)
        for i in range(0, len(perm), batch):
            idx = np.sort(perm[i : i + batch])
            loss = nn.functional.cross_entropy(
                net(_to_tensor(idx, True)),
                torch.from_numpy(y[idx]).to(dev),
            )
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()

        if cal_idx is not None and len(cal_idx) > 0:
            z_cal_ep = _eval_logits(net, cal_idx)
            nll_ep = cal.nll_from_logits(z_cal_ep, y[cal_idx])
            if nll_ep < best_cal_nll:
                best_cal_nll = nll_ep
                best_epoch = ep
                best_state = copy.deepcopy(net.state_dict())

    if best_state is not None:
        net.load_state_dict(best_state)

    z_cal = _eval_logits(net, cal_idx) if cal_idx is not None else None
    z_te = _eval_logits(net, te_idx) if te_idx is not None else None
    meta = {
        "best_epoch": int(best_epoch),
        "best_cal_nll": float(best_cal_nll) if math.isfinite(best_cal_nll) else None,
        "max_cuda_mem_gib": float(torch.cuda.max_memory_allocated() / (2**30)) if torch.cuda.is_available() else 0.0,
    }
    return net, z_cal, z_te, meta


def run_gpu_models(
    seeds: tuple[int, ...] = SEEDS,
    models: tuple[str, ...] = CNN_MODELS,
    preprocess: str = "grabcut",
    epochs: int = 12,
    batch: int = 32,
    groups_kind: str = GROUPS_KIND,
    tag_suffix: str = "",
) -> dict:
    """Train CNN backbones under ``GpuGuard`` on shared zero-leakage ``d8dedup4`` splits."""
    from tastoria_ml.cv.train_detector import GpuGuard

    if preprocess not in ("grabcut", "letterbox"):
        raise ValueError(f"preprocess must be 'grabcut' or 'letterbox', got {preprocess!r}")

    with GpuGuard(f"freshness_study_{preprocess}"):
        import torch

        dev = torch.device("cuda")
        df, X, M = load_cache()
        _, groups = _load_table_and_groups(groups_kind)
        y = df.y.values.astype(np.int64)
        xm = np.where(M[..., None], np.asarray(X), np.uint8(128)) if preprocess == "grabcut" else np.asarray(X)

        summary: dict[str, list[dict]] = {m: [] for m in models}
        for seed in seeds:
            splits = make_zero_leakage_splits(df, groups, seed=seed)
            for arch in models:
                t0 = time.perf_counter()
                cal_logits_list: list[np.ndarray] = []
                te_logits_list: list[np.ndarray] = []
                extra_meta: list[dict] = []

                for k, (fit_k, cal_k, te_k) in enumerate(splits):
                    fold_seed = 10000 + seed * 100 + k
                    net, z_cal, z_te, fmeta = _train_single_cnn_fold(
                        arch=arch,
                        xm=xm,
                        y=y,
                        fit_idx=fit_k,
                        cal_idx=cal_k,
                        te_idx=te_k,
                        epochs=epochs,
                        batch=batch,
                        fold_seed=fold_seed,
                        dev=dev,
                    )
                    del net
                    torch.cuda.empty_cache()
                    fmeta["fold"] = k
                    fmeta["fold_seed"] = fold_seed
                    extra_meta.append(fmeta)
                    cal_logits_list.append(z_cal)
                    te_logits_list.append(z_te)

                dt_sec = time.perf_counter() - t0
                meta = _save_model_seed_artifacts(
                    model_name=arch,
                    seed=seed,
                    y=y,
                    groups=groups,
                    splits=splits,
                    cal_logits_per_fold=cal_logits_list,
                    te_logits_per_fold=te_logits_list,
                    extra_fold_meta=extra_meta,
                    runtime_sec=dt_sec,
                    preprocess=preprocess,
                    tag_suffix=tag_suffix,
                )
                summary[arch].append(meta)
                m_raw = meta["metrics_raw"]
                m_cal = meta["metrics_cal_temp"]
                print(
                    f"[{arch}{tag_suffix}] seed={seed} ({dt_sec:.1f}s) | "
                    f"raw f1={m_raw['macro_f1']:.4f} qwk={m_raw['qwk']:.4f} ece={m_raw['ece']:.4f} | "
                    f"temp_cal ece={m_cal['ece']:.4f} nll={m_cal['nll']:.4f}",
                    flush=True,
                )

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    out = {
        "protocol_id": PROTOCOL_ID,
        "phase": "gpu",
        "preprocess": preprocess,
        "tag_suffix": tag_suffix,
        "epochs": int(epochs),
        "batch": int(batch),
        "groups_kind": groups_kind,
        "seeds": list(seeds),
        "models": list(models),
        "runs": summary,
    }
    fname = f"p2_gpu_runs{tag_suffix}.json"
    (RESEARCH_DIR / fname).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def run_shortcut_audit(
    arch: str = "mobilenet_v3_small",
    seeds: tuple[int, ...] = SEEDS,
    epochs: int = 12,
    batch: int = 32,
) -> dict:
    """Exploratory #4 shortcut control: train on AgriFreshNET-only vs combined, eval on AgriFreshNET."""
    from tastoria_ml.cv.train_detector import GpuGuard

    with GpuGuard(f"freshness_shortcut_{arch}"):
        import torch

        dev = torch.device("cuda")
        df, X, M = load_cache()
        _, groups = _load_table_and_groups(GROUPS_KIND)
        y = df.y.values.astype(np.int64)
        xm = np.where(M[..., None], np.asarray(X), np.uint8(128))
        is_agri = (df.dataset.values == "agrifreshnet")
        agri_idx = np.where(is_agri)[0]

        seed_runs = []
        for seed in seeds:
            splits = make_zero_leakage_splits(df, groups, seed=seed)
            cal_list, te_list, te_agri_folds = [], [], []
            for k, (fit_k, cal_k, te_k) in enumerate(splits):
                fit_agri = fit_k[is_agri[fit_k]]
                cal_agri = cal_k[is_agri[cal_k]]
                te_agri = te_k[is_agri[te_k]]
                fold_seed = 20000 + seed * 100 + k
                net, z_cal, z_te, _ = _train_single_cnn_fold(
                    arch=arch,
                    xm=xm,
                    y=y,
                    fit_idx=fit_agri,
                    cal_idx=cal_agri,
                    te_idx=te_agri,
                    epochs=epochs,
                    batch=batch,
                    fold_seed=fold_seed,
                    dev=dev,
                )
                del net
                torch.cuda.empty_cache()
                cal_list.append(z_cal)
                te_list.append(z_te)
                te_agri_folds.append(te_agri)

            # Map back to agri_idx local index space
            pos_map = {int(orig_i): pos for pos, orig_i in enumerate(agri_idx)}
            te_local_folds = [np.array([pos_map[int(i)] for i in f], dtype=np.int64) for f in te_agri_folds]
            raw_agri = np.empty((len(agri_idx), len(LABELS)), dtype=np.float64)
            for k, loc in enumerate(te_local_folds):
                raw_agri[loc] = te_list[k]

            res_t = cal.fit_and_apply_fold_calibration(
                cal_list,
                [y[cal_k[is_agri[cal_k]]] for _, cal_k, _ in splits],
                te_list,
                te_local_folds,
                n_samples=len(agri_idx),
                method="temperature",
            )
            np.save(OOF_DIR / f"{arch}_agri_only_s{seed}_raw_logits.npy", raw_agri.astype(np.float32))
            np.save(OOF_DIR / f"{arch}_agri_only_s{seed}_cal_temp_logits.npy", res_t["cal_logits"].astype(np.float32))
            seed_runs.append({
                "seed": seed,
                "metrics_raw_agri": _eval_logits_summary(raw_agri, y[agri_idx]),
                "metrics_cal_temp_agri": _eval_logits_summary(res_t["cal_logits"], y[agri_idx]),
            })

    out = {
        "analysis_intent": "exploratory",
        "protocol_id": PROTOCOL_ID,
        "arch": arch,
        "n_agrifreshnet": int(len(agri_idx)),
        "seed_runs": seed_runs,
    }
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    (RESEARCH_DIR / "p2_shortcut_audit.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


# ------------------------------------------------------------------ statistical analysis


def _load_oof_across_seeds(model_name: str, seeds: tuple[int, ...], tag_suffix: str = "") -> dict | None:
    raw_list, temp_list, vec_list, metas = [], [], [], []
    for s in seeds:
        stem = f"{model_name}{tag_suffix}_s{s}"
        p_raw = OOF_DIR / f"{stem}_raw_logits.npy"
        p_tmp = OOF_DIR / f"{stem}_cal_temp_logits.npy"
        p_vec = OOF_DIR / f"{stem}_cal_vec_logits.npy"
        p_meta = OOF_DIR / f"{stem}_fold_params.json"
        if not (p_raw.exists() and p_tmp.exists() and p_vec.exists()):
            return None
        raw_list.append(np.load(p_raw).astype(np.float64))
        temp_list.append(np.load(p_tmp).astype(np.float64))
        vec_list.append(np.load(p_vec).astype(np.float64))
        if p_meta.exists():
            metas.append(json.loads(p_meta.read_text(encoding="utf-8")))
    return {
        "seeds": list(seeds),
        "raw_logits": raw_list,
        "cal_temp_logits": temp_list,
        "cal_vec_logits": vec_list,
        "metas": metas,
    }


def _per_sample_losses(probs: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    y_oh = np.zeros_like(probs)
    y_oh[np.arange(len(y)), y] = 1.0
    brier = np.sum((probs - y_oh) ** 2, axis=1)
    p_clip = np.clip(probs, 1e-12, 1.0)
    nll = -np.log(p_clip[np.arange(len(y)), y])
    pred = np.argmax(probs, axis=1)
    acc = (pred == y).astype(np.float64)
    mae = np.abs(pred - y).astype(np.float64)
    return acc, mae, brier, nll


def _group_aggregate(values: np.ndarray, inv: np.ndarray, k: int) -> np.ndarray:
    sums = np.bincount(inv, weights=values, minlength=k).astype(np.float64)
    cnts = np.bincount(inv, minlength=k).astype(np.float64)
    return sums / np.maximum(cnts, 1.0)


def _paired_arm_comparison(
    y: np.ndarray,
    groups: np.ndarray,
    probs_a: np.ndarray,
    probs_b: np.ndarray,
    acc_a_unit: np.ndarray,
    acc_b_unit: np.ndarray,
    mae_a_unit: np.ndarray,
    mae_b_unit: np.ndarray,
    brier_a_unit: np.ndarray,
    brier_b_unit: np.ndarray,
    nll_a_unit: np.ndarray,
    nll_b_unit: np.ndarray,
    n_boot: int = 2000,
    seed: int = 0,
) -> dict:
    _, inv = np.unique(groups, return_inverse=True)
    k = int(inv.max()) + 1

    pred_a = np.argmax(probs_a, axis=1)
    pred_b = np.argmax(probs_b, axis=1)

    macro_f1_cmp = cal.cluster_bootstrap_metric(
        y, pred_a, pred_b, groups, lambda yt, yp: cal.macro_f1(yt, yp, 3), n_boot=n_boot, seed=seed
    )
    qwk_cmp = cal.cluster_bootstrap_metric(
        y, pred_a, pred_b, groups, lambda yt, yp: cal.qwk(yt, yp, 3), n_boot=n_boot, seed=seed + 1
    )
    ece_cmp = cal.cluster_bootstrap_metric(
        y, probs_a, probs_b, groups, lambda yt, pr: float(mstats.calibration_metrics(yt, pr, 10)["ece"]),
        n_boot=n_boot, seed=seed + 2,
    )
    ece_ad_cmp = cal.cluster_bootstrap_metric(
        y, probs_a, probs_b, groups, lambda yt, pr: float(mstats.calibration_metrics(yt, pr, 10)["ece_adaptive"]),
        n_boot=n_boot, seed=seed + 3,
    )

    acc_boot = mstats.paired_bootstrap(acc_a_unit, acc_b_unit, n_boot=n_boot, seed=seed, clusters=groups)
    mae_boot = mstats.paired_bootstrap(mae_a_unit, mae_b_unit, n_boot=n_boot, seed=seed, clusters=groups)
    brier_boot = mstats.paired_bootstrap(brier_a_unit, brier_b_unit, n_boot=n_boot, seed=seed, clusters=groups)
    nll_boot = mstats.paired_bootstrap(nll_a_unit, nll_b_unit, n_boot=n_boot, seed=seed, clusters=groups)

    # Group-level aggregated paired diagnostics (k=2,366 independent groups)
    acc_ga, acc_gb = _group_aggregate(acc_a_unit, inv, k), _group_aggregate(acc_b_unit, inv, k)
    nll_ga, nll_gb = _group_aggregate(nll_a_unit, inv, k), _group_aggregate(nll_b_unit, inv, k)
    brier_ga, brier_gb = _group_aggregate(brier_a_unit, inv, k), _group_aggregate(brier_b_unit, inv, k)

    # Group-level binary correctness for McNemar (caveat: cluster-mean > 0.5 or majority-correct)
    mcnemar_img = mstats.mcnemar(pred_a == y, pred_b == y)

    return {
        "n_images": int(len(y)),
        "n_clusters": int(k),
        "macro_f1": macro_f1_cmp,
        "qwk": qwk_cmp,
        "accuracy_cluster_boot": acc_boot,
        "mae_level_cluster_boot": mae_boot,
        "ece": ece_cmp,
        "ece_adaptive": ece_ad_cmp,
        "brier_cluster_boot": brier_boot,
        "nll_cluster_boot": nll_boot,
        "group_level_nll": {
            "assumptions": mstats.check_paired_assumptions(nll_ga, nll_gb),
            "wilcoxon": mstats.wilcoxon(nll_ga, nll_gb),
            "cohens_dz": mstats.cohens_dz(nll_ga, nll_gb, n_boot=n_boot, seed=seed),
        },
        "group_level_brier": {
            "assumptions": mstats.check_paired_assumptions(brier_ga, brier_gb),
            "wilcoxon": mstats.wilcoxon(brier_ga, brier_gb),
            "cohens_dz": mstats.cohens_dz(brier_ga, brier_gb, n_boot=n_boot, seed=seed),
        },
        "group_level_accuracy": {
            "assumptions": mstats.check_paired_assumptions(acc_ga, acc_gb),
            "wilcoxon": mstats.wilcoxon(acc_ga, acc_gb),
            "cohens_dz": mstats.cohens_dz(acc_ga, acc_gb, n_boot=n_boot, seed=seed),
        },
        "mcnemar_image_level": mcnemar_img,
    }


def _descriptives(values: np.ndarray) -> dict:
    v = np.asarray(values, dtype=np.float64)
    q25, q50, q75 = np.percentile(v, [25.0, 50.0, 75.0])
    return {
        "n": int(len(v)),
        "missing": int(np.sum(~np.isfinite(v))),
        "mean": float(np.mean(v)),
        "sd": float(np.std(v, ddof=1)),
        "median": float(q50),
        "iqr": float(q75 - q25),
        "q25": float(q25),
        "q75": float(q75),
        "min": float(np.min(v)),
        "max": float(np.max(v)),
    }


def analyze_study(seeds: tuple[int, ...] = SEEDS, n_boot: int = 2000, groups_kind: str = GROUPS_KIND) -> dict:
    """Run full H2a, H2b, Exploratory #3, and Exploratory #4 analysis on available OOF logits."""
    df, groups = _load_table_and_groups(groups_kind)
    y = df.y.values.astype(np.int64)
    n_clusters = int(len(np.unique(groups)))
    mde_dz = _mde_dz(n_clusters)
    _, inv = np.unique(groups, return_inverse=True)

    available: dict[str, dict] = {}
    for m in ALL_MODELS:
        loaded = _load_oof_across_seeds(m, seeds)
        if loaded is not None:
            available[m] = loaded

    if not available:
        raise FileNotFoundError(f"No OOF logits found in {OOF_DIR} for models {ALL_MODELS}")

    # Compute per-seed summaries and seed-averaged unit arrays / probabilities
    arm_summaries: dict[str, dict] = {}
    arm_units: dict[str, dict] = {}

    for m, data in available.items():
        arm_summaries[m] = {}
        arm_units[m] = {}
        for cal_kind, key in (("raw", "raw_logits"), ("temp", "cal_temp_logits"), ("vec", "cal_vec_logits")):
            seed_metrics = []
            probs_seeds = []
            acc_s, mae_s, brier_s, nll_s = [], [], [], []
            for z_s in data[key]:
                p_s = cal.softmax(z_s)
                probs_seeds.append(p_s)
                seed_metrics.append(_eval_logits_summary(z_s, y))
                a_i, m_i, b_i, n_i = _per_sample_losses(p_s, y)
                acc_s.append(a_i)
                mae_s.append(m_i)
                brier_s.append(b_i)
                nll_s.append(n_i)

            p_mean = np.mean(probs_seeds, axis=0)
            pred_mean = np.argmax(p_mean, axis=1)
            acc_u = np.mean(acc_s, axis=0)
            mae_u = np.mean(mae_s, axis=0)
            brier_u = np.mean(brier_s, axis=0)
            nll_u = np.mean(nll_s, axis=0)

            seed_agg = {}
            for k_met in ("accuracy", "macro_f1", "qwk", "mae_level", "ece", "ece_adaptive", "brier", "nll"):
                vals = np.array([sm[k_met] for sm in seed_metrics], dtype=np.float64)
                seed_agg[k_met] = {"mean": float(vals.mean()), "sd": float(vals.std(ddof=1)) if len(vals) > 1 else 0.0}

            # Single-arm cluster CIs on seed-averaged predictions/probs
            ci_f1 = cal.cluster_bootstrap_single(y, pred_mean, groups, lambda yt, yp: cal.macro_f1(yt, yp, 3), n_boot=n_boot, seed=0)
            ci_qwk = cal.cluster_bootstrap_single(y, pred_mean, groups, lambda yt, yp: cal.qwk(yt, yp, 3), n_boot=n_boot, seed=1)
            ci_ece = cal.cluster_bootstrap_single(
                y, p_mean, groups, lambda yt, pr: float(mstats.calibration_metrics(yt, pr, 10)["ece"]), n_boot=n_boot, seed=2
            )
            ci_ece_ad = cal.cluster_bootstrap_single(
                y, p_mean, groups, lambda yt, pr: float(mstats.calibration_metrics(yt, pr, 10)["ece_adaptive"]), n_boot=n_boot, seed=3
            )
            acc_mean, acc_lo, acc_hi = mstats.mean_ci(acc_u, n_boot=n_boot, seed=0, clusters=groups)
            brier_mean, brier_lo, brier_hi = mstats.mean_ci(brier_u, n_boot=n_boot, seed=0, clusters=groups)
            nll_mean, nll_lo, nll_hi = mstats.mean_ci(nll_u, n_boot=n_boot, seed=0, clusters=groups)

            arm_summaries[m][cal_kind] = {
                "per_seed": seed_metrics,
                "seed_mean_sd": seed_agg,
                "seed_averaged_cluster_ci": {
                    "accuracy": {"point": acc_mean, "lo": acc_lo, "hi": acc_hi},
                    "macro_f1": ci_f1,
                    "qwk": ci_qwk,
                    "ece": ci_ece,
                    "ece_adaptive": ci_ece_ad,
                    "brier": {"point": brier_mean, "lo": brier_lo, "hi": brier_hi},
                    "nll": {"point": nll_mean, "lo": nll_lo, "hi": nll_hi},
                },
                "group_nll_descriptives": _descriptives(_group_aggregate(nll_u, inv, n_clusters)),
                "group_brier_descriptives": _descriptives(_group_aggregate(brier_u, inv, n_clusters)),
            }
            arm_units[m][cal_kind] = {
                "probs": p_mean,
                "acc": acc_u,
                "mae": mae_u,
                "brier": brier_u,
                "nll": nll_u,
            }

    # H2a Confirmatory: CNNs vs RBF-SVM (and vs LogReg) on Macro-F1 & QWK, plus controls
    h2a_contrasts: list[dict] = []
    cnn_avail = [m for m in CNN_MODELS if m in available]
    baselines = [b for b in ("rbf_svm", "logreg") if b in available]
    for idx_c, cnn_m in enumerate(cnn_avail):
        for base_m in baselines:
            ua = arm_units[cnn_m]["raw"]
            ub = arm_units[base_m]["raw"]
            cmp = _paired_arm_comparison(
                y, groups,
                ua["probs"], ub["probs"],
                ua["acc"], ub["acc"],
                ua["mae"], ub["mae"],
                ua["brier"], ub["brier"],
                ua["nll"], ub["nll"],
                n_boot=n_boot,
                seed=100 + idx_c,
            )
            h2a_contrasts.append({
                "contrast": f"{cnn_m}_vs_{base_m}",
                "model_a": cnn_m,
                "model_b": base_m,
                "primary_for_holm": (base_m == "rbf_svm"),
                **cmp,
            })

    # Apply Holm-Bonferroni within H2a confirmatory family (Macro-F1 and QWK p-values)
    if h2a_contrasts:
        p_f1 = [c["macro_f1"]["p"] for c in h2a_contrasts]
        p_qwk = [c["qwk"]["p"] for c in h2a_contrasts]
        h_f1 = mstats.holm(p_f1)
        h_qwk = mstats.holm(p_qwk)
        for c, pf, pq in zip(h2a_contrasts, h_f1, h_qwk, strict=True):
            c["macro_f1"]["p_holm"] = float(pf)
            c["qwk"]["p_holm"] = float(pq)

    controls = {}
    if "dummy" in arm_summaries:
        d_m = arm_summaries["dummy"]["raw"]["seed_mean_sd"]
        controls["dummy_negative"] = {
            "macro_f1": d_m["macro_f1"]["mean"],
            "qwk": d_m["qwk"]["mean"],
            "nll": d_m["nll"]["mean"],
            "passes_negative_control": bool(abs(d_m["qwk"]["mean"]) < 1e-6 and d_m["macro_f1"]["mean"] < 0.25),
        }
    if "rbf_svm" in arm_summaries:
        s_m = arm_summaries["rbf_svm"]["raw"]["seed_mean_sd"]
        controls["rbf_svm_positive"] = {
            "macro_f1": s_m["macro_f1"]["mean"],
            "qwk": s_m["qwk"]["mean"],
            "passes_positive_control_qwk_gt_0_75": bool(s_m["qwk"]["mean"] > 0.75),
        }

    # H2b Confirmatory: Calibrated (temp & vec) vs Uncalibrated (raw)
    h2b_contrasts: list[dict] = []
    for idx_m, m in enumerate([mod for mod in ALL_MODELS if mod != "dummy" and mod in available]):
        for cal_kind in ("temp", "vec"):
            ua = arm_units[m][cal_kind]
            ub = arm_units[m]["raw"]
            cmp = _paired_arm_comparison(
                y, groups,
                ua["probs"], ub["probs"],
                ua["acc"], ub["acc"],
                ua["mae"], ub["mae"],
                ua["brier"], ub["brier"],
                ua["nll"], ub["nll"],
                n_boot=n_boot,
                seed=200 + idx_m,
            )
            f1_lo = cmp["macro_f1"]["lo"]
            qwk_lo = cmp["qwk"]["lo"]
            cmp["non_degradation_check"] = {
                "margin": -0.005,
                "macro_f1_diff": cmp["macro_f1"]["diff"],
                "macro_f1_ci_lo": f1_lo,
                "qwk_diff": cmp["qwk"]["diff"],
                "qwk_ci_lo": qwk_lo,
                "passes_point": bool(cmp["macro_f1"]["diff"] >= -0.005 and cmp["qwk"]["diff"] >= -0.005),
                "passes_ci_lo": bool(f1_lo >= -0.005 and qwk_lo >= -0.005),
            }
            h2b_contrasts.append({
                "contrast": f"{m}_{cal_kind}_vs_raw",
                "model": m,
                "calibration_method": cal_kind,
                **cmp,
            })

    if h2b_contrasts:
        for metric_key, sub_key in (("ece", "p"), ("ece_adaptive", "p"), ("brier_cluster_boot", "p"), ("nll_cluster_boot", "p")):
            p_raw = [c[metric_key][sub_key] for c in h2b_contrasts]
            p_adj = mstats.holm(p_raw)
            for c, pa in zip(h2b_contrasts, p_adj, strict=True):
                c[metric_key]["p_holm"] = float(pa)

    # Select winning model among CNNs (or best available model if phase=cpu only)
    candidate_pool = cnn_avail if cnn_avail else [m for m in available if m != "dummy"]
    best_model = max(
        candidate_pool,
        key=lambda m: (
            arm_summaries[m]["temp"]["seed_mean_sd"]["macro_f1"]["mean"],
            -arm_summaries[m]["temp"]["seed_mean_sd"]["nll"]["mean"],
        ),
    )

    # Exploratory #3: Selective abstention curve (kiem_tra) on winning model (temp-calibrated vs raw)
    probs_best_cal = arm_units[best_model]["temp"]["probs"]
    probs_best_raw = arm_units[best_model]["raw"]["probs"]
    ds_labels = df.dataset.values
    abst_maxprob = cal.selective_abstention_curve(
        probs_best_cal, y, groups, score_type="max_prob", n_boot=n_boot, seed=300, dataset_labels=ds_labels
    )
    abst_entropy = cal.selective_abstention_curve(
        probs_best_cal, y, groups, score_type="entropy", n_boot=n_boot, seed=301, dataset_labels=ds_labels
    )
    abst_raw_maxprob = cal.selective_abstention_curve(
        probs_best_raw, y, groups, score_type="max_prob", n_boot=n_boot, seed=302, dataset_labels=ds_labels
    )

    # Recommended tau >= 0.60 maximizing selective accuracy subject to AgriFreshNET coverage >= 0.75 (or best >= 0.60)
    agri_pts = abst_maxprob["by_dataset"].get("agrifreshnet", {}).get("points", [])
    overall_pts = abst_maxprob["overall"]["points"]
    if len(agri_pts) == len(overall_pts):
        eligible = [
            (op, ap)
            for op, ap in zip(overall_pts, agri_pts, strict=True)
            if op["tau"] >= 0.60 and ap["coverage"] >= 0.75 and math.isfinite(ap["selective_error"])
        ]
    else:
        eligible = []
    if eligible:
        rec_op, rec_ap = min(eligible, key=lambda pair: pair[1]["selective_error"])
    else:
        rec_op = next((pt for pt in overall_pts if abs(pt["tau"] - 0.60) < 1e-6), overall_pts[0])
        rec_ap = next((pt for pt in agri_pts if abs(pt["tau"] - rec_op["tau"]) < 1e-6), None)

    # Exploratory #4: Per-dataset breakdown, Cliff's delta, BH-FDR tests, shortcut audit, and grouping sensitivity
    from scipy import stats as sp_stats

    ds_stratified = {}
    exp4_pvals: list[float] = []
    exp4_keys: list[tuple[str, str, str]] = []
    agri_mask = ds_labels == "agrifreshnet"
    spin_mask = ds_labels == "local_spinach_leaf"
    for m in available:
        ds_stratified[m] = {}
        for cal_kind in ("raw", "temp", "vec"):
            pr = arm_units[m][cal_kind]["probs"]
            nll_u = arm_units[m][cal_kind]["nll"]
            brier_u = arm_units[m][cal_kind]["brier"]

            # Group-level NLL/Brier per dataset so Cliff's delta & Mann-Whitney operate on independent groups
            _, inv_a = np.unique(groups[agri_mask], return_inverse=True)
            _, inv_s = np.unique(groups[spin_mask], return_inverse=True)
            nll_ga = _group_aggregate(nll_u[agri_mask], inv_a, int(inv_a.max()) + 1)
            nll_gs = _group_aggregate(nll_u[spin_mask], inv_s, int(inv_s.max()) + 1)
            brier_ga = _group_aggregate(brier_u[agri_mask], inv_a, int(inv_a.max()) + 1)
            brier_gs = _group_aggregate(brier_u[spin_mask], inv_s, int(inv_s.max()) + 1)

            mw_nll = sp_stats.mannwhitneyu(nll_ga, nll_gs, alternative="two-sided")
            mw_brier = sp_stats.mannwhitneyu(brier_ga, brier_gs, alternative="two-sided")
            exp4_pvals.extend([float(mw_nll.pvalue), float(mw_brier.pvalue)])
            exp4_keys.extend([(m, cal_kind, "p_mw_nll"), (m, cal_kind, "p_mw_brier")])

            ds_stratified[m][cal_kind] = {
                "agrifreshnet": {
                    **_eval_logits_summary(np.log(np.clip(pr[agri_mask], 1e-12, 1.0)), y[agri_mask]),
                    "n_clusters": int(inv_a.max()) + 1,
                },
                "local_spinach_leaf": {
                    **_eval_logits_summary(np.log(np.clip(pr[spin_mask], 1e-12, 1.0)), y[spin_mask]),
                    "n_clusters": int(inv_s.max()) + 1,
                    "binary_f1_tuoi_vs_dung_ngay": float(
                        2.0 * np.sum((np.argmax(pr[spin_mask], 1) == 2) & (y[spin_mask] == 2))
                        / max(1, np.sum(np.argmax(pr[spin_mask], 1) == 2) + np.sum(y[spin_mask] == 2))
                    ),
                },
                "cliffs_delta_group_nll_agri_vs_spinach": mstats.cliffs_delta(nll_ga, nll_gs),
                "cliffs_delta_group_brier_agri_vs_spinach": mstats.cliffs_delta(brier_ga, brier_gs),
                "p_mw_nll": float(mw_nll.pvalue),
                "p_mw_brier": float(mw_brier.pvalue),
            }

    if exp4_pvals:
        exp4_q = mstats.bh_fdr(exp4_pvals)
        for (m, cal_kind, pkey), qv in zip(exp4_keys, exp4_q, strict=True):
            qkey = pkey.replace("p_mw_", "q_bh_")
            ds_stratified[m][cal_kind][qkey] = float(qv)

    # Check letterbox ablation if present
    letterbox_info = None
    lb_loaded = _load_oof_across_seeds(best_model, seeds, tag_suffix="_letterbox")
    if lb_loaded is not None:
        lb_raw_probs = np.mean([cal.softmax(z) for z in lb_loaded["raw_logits"]], axis=0)
        lb_temp_probs = np.mean([cal.softmax(z) for z in lb_loaded["cal_temp_logits"]], axis=0)
        a_lb, m_lb, b_lb, n_lb = _per_sample_losses(lb_temp_probs, y)
        ug = arm_units[best_model]["temp"]
        letterbox_info = {
            "arch": best_model,
            "raw_metrics": _eval_logits_summary(np.log(np.clip(lb_raw_probs, 1e-12, 1.0)), y),
            "temp_metrics": _eval_logits_summary(np.log(np.clip(lb_temp_probs, 1e-12, 1.0)), y),
            "temp_vs_grabcut_temp": _paired_arm_comparison(
                y, groups,
                lb_temp_probs, ug["probs"],
                a_lb, ug["acc"],
                m_lb, ug["mae"],
                b_lb, ug["brier"],
                n_lb, ug["nll"],
                n_boot=n_boot,
                seed=400,
            ),
        }

    # Grouping sensitivity from prior baseline JSONs (read-only historical reference)
    grouping_sensitivity = {}
    for gk in ("lot", "dedup4", "d8dedup4"):
        p_sum = LEGACY_OUT / f"summary_{gk}.json"
        if p_sum.exists():
            grouping_sensitivity[gk] = json.loads(p_sum.read_text(encoding="utf-8"))
    p_leak = LEGACY_OUT / "leakage_d8.json"
    if p_leak.exists():
        grouping_sensitivity["leakage_d8"] = json.loads(p_leak.read_text(encoding="utf-8"))

    shortcut_audit = None
    p_sc = RESEARCH_DIR / "p2_shortcut_audit.json"
    if p_sc.exists():
        shortcut_audit = json.loads(p_sc.read_text(encoding="utf-8"))

    confirmatory = {
        "protocol_id": PROTOCOL_ID,
        "analysis_intent": "confirmatory",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "groups_kind": groups_kind,
        "n_images": int(len(y)),
        "n_clusters": n_clusters,
        "seeds": list(seeds),
        "mde_80pct_alpha05_dz": mde_dz,
        "observed_power_computed": False,
        "best_model": best_model,
        "models_evaluated": list(available.keys()),
        "controls": controls,
        "arm_summaries": arm_summaries,
        "h2a_discrimination": h2a_contrasts,
    }
    calibration_doc = {
        "protocol_id": PROTOCOL_ID,
        "analysis_intent": "confirmatory",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "groups_kind": groups_kind,
        "n_images": int(len(y)),
        "n_clusters": n_clusters,
        "mde_80pct_alpha05_dz": mde_dz,
        "observed_power_computed": False,
        "h2b_calibration": h2b_contrasts,
    }
    exploratory = {
        "protocol_id": PROTOCOL_ID,
        "analysis_intent": "exploratory",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "best_model": best_model,
        "exploratory_3_kiem_tra_abstention": {
            "calibrated_max_prob": abst_maxprob,
            "calibrated_entropy": abst_entropy,
            "uncalibrated_max_prob": abst_raw_maxprob,
            "recommended_operating_point": {
                "tau": float(rec_op["tau"]),
                "overall": rec_op,
                "agrifreshnet": rec_ap,
            },
        },
        "exploratory_4_shortcut_and_leakage": {
            "per_dataset_stratified": ds_stratified,
            "letterbox_vs_grabcut": letterbox_info,
            "agrifreshnet_only_shortcut_audit": shortcut_audit,
            "grouping_sensitivity_reference": grouping_sensitivity,
        },
    }

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    (RESEARCH_DIR / "p2_confirmatory_results.json").write_text(json.dumps(confirmatory, indent=2), encoding="utf-8")
    (RESEARCH_DIR / "p2_calibration_results.json").write_text(json.dumps(calibration_doc, indent=2), encoding="utf-8")
    (RESEARCH_DIR / "p2_exploratory_results.json").write_text(json.dumps(exploratory, indent=2), encoding="utf-8")

    # Summary CSV table
    csv_path = RESEARCH_DIR / "p2_model_summary.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow([
            "model", "calibration", "acc_mean", "acc_sd", "macro_f1_mean", "macro_f1_sd",
            "qwk_mean", "qwk_sd", "ece_mean", "ece_sd", "ece_adaptive_mean", "brier_mean", "nll_mean",
        ])
        for m, kinds in arm_summaries.items():
            for ck in ("raw", "temp", "vec"):
                sm = kinds[ck]["seed_mean_sd"]
                w.writerow([
                    m, ck,
                    f"{sm['accuracy']['mean']:.6f}", f"{sm['accuracy']['sd']:.6f}",
                    f"{sm['macro_f1']['mean']:.6f}", f"{sm['macro_f1']['sd']:.6f}",
                    f"{sm['qwk']['mean']:.6f}", f"{sm['qwk']['sd']:.6f}",
                    f"{sm['ece']['mean']:.6f}", f"{sm['ece']['sd']:.6f}",
                    f"{sm['ece_adaptive']['mean']:.6f}",
                    f"{sm['brier']['mean']:.6f}", f"{sm['nll']['mean']:.6f}",
                ])

    manifest = {
        "protocol_id": PROTOCOL_ID,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "python": platform.python_version(),
        "host": platform.node(),
        "groups_kind": groups_kind,
        "n_images": int(len(y)),
        "n_clusters": n_clusters,
        "mde_dz": mde_dz,
        "observed_power_computed": False,
        "best_model": best_model,
        "models_evaluated": list(available.keys()),
        "artifacts": {
            "confirmatory": "ml/runs/research/p2_freshness/p2_confirmatory_results.json",
            "calibration": "ml/runs/research/p2_freshness/p2_calibration_results.json",
            "exploratory": "ml/runs/research/p2_freshness/p2_exploratory_results.json",
            "summary_csv": "ml/runs/research/p2_freshness/p2_model_summary.csv",
        },
    }
    (RESEARCH_DIR / "p2_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


# ------------------------------------------------------------------ ONNX export + serving.json


def _benchmark_onnx_latency(
    onnx_path: Path,
    sample_x: np.ndarray,
    concurrency: int = 1,
    n_warmup: int = 10,
    n_iters: int = 100,
) -> dict:
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.intra_op_num_threads = 2
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    sess = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])

    def _run_one(i: int) -> float:
        x_in = sample_x[i % len(sample_x) : i % len(sample_x) + 1]
        t0 = time.perf_counter()
        sess.run(None, {"image": x_in})
        return (time.perf_counter() - t0) * 1000.0

    for i in range(n_warmup):
        _run_one(i)

    if concurrency <= 1:
        times = [_run_one(i) for i in range(n_iters)]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as ex:
            times = list(ex.map(_run_one, range(n_iters)))

    arr = np.asarray(times, dtype=np.float64)
    return {
        "concurrency": int(concurrency),
        "n_iters": int(n_iters),
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "mean": float(np.mean(arr)),
    }


def export_calibrated_onnx(
    arch: str | None = None,
    epochs: int = 12,
    batch: int = 32,
    seed: int = 0,
    recommended_tau: float | None = None,
) -> dict:
    """Train winning CNN on unmasked letterbox crops (zero skew with backend), calibrate T*, export ONNX."""
    from sklearn.model_selection import StratifiedGroupKFold

    from tastoria_ml.cv.train_detector import GpuGuard

    if arch is None:
        p_conf = RESEARCH_DIR / "p2_confirmatory_results.json"
        if p_conf.exists():
            arch = json.loads(p_conf.read_text(encoding="utf-8"))["best_model"]
        else:
            arch = "mobilenet_v3_small"

    if recommended_tau is None:
        p_exp = RESEARCH_DIR / "p2_exploratory_results.json"
        if p_exp.exists():
            recommended_tau = float(
                json.loads(p_exp.read_text(encoding="utf-8"))["exploratory_3_kiem_tra_abstention"][
                    "recommended_operating_point"
                ]["tau"]
            )
        else:
            recommended_tau = 0.60

    # Derive CV mean/median temperature across folds/seeds if available
    cv_temps = []
    for s in SEEDS:
        p_fp = OOF_DIR / f"{arch}_letterbox_s{s}_fold_params.json"
        if not p_fp.exists():
            p_fp = OOF_DIR / f"{arch}_s{s}_fold_params.json"
        if p_fp.exists():
            fp = json.loads(p_fp.read_text(encoding="utf-8"))
            cv_temps.extend([float(x["temperature"]) for x in fp.get("fold_params_temp", [])])

    with GpuGuard(f"freshness_export_{arch}"):
        import torch

        dev = torch.device("cuda")
        df, X, _ = load_cache()
        _, groups = _load_table_and_groups(GROUPS_KIND)
        y = df.y.values.astype(np.int64)
        xm = np.asarray(X)  # Unmasked letterbox 224x224 (pad=128) -> 100% compatible with PIL+NumPy backend

        # 90% fit / 10% unseen calibration split grouped by d8dedup4
        strat = (df.dataset.astype(str) + "/" + df.produce.astype(str) + "/" + df.label3.astype(str)).astype("category").cat.codes.values
        sgk = StratifiedGroupKFold(n_splits=10, shuffle=True, random_state=777 + seed)
        fit_idx, cal_idx = next(sgk.split(np.zeros(len(df)), strat, groups))
        assert set(groups[fit_idx]).isdisjoint(set(groups[cal_idx]))

        net, z_cal_unseen, _, train_meta = _train_single_cnn_fold(
            arch=arch,
            xm=xm,
            y=y,
            fit_idx=fit_idx,
            cal_idx=cal_idx,
            te_idx=None,
            epochs=epochs,
            batch=batch,
            fold_seed=30000 + seed,
            dev=dev,
        )
        net = net.eval().cpu()

    import onnxruntime as ort
    import torch

    temp_holdout = cal.fit_temperature(z_cal_unseen, y[cal_idx])
    unseen_raw_metrics = _eval_logits_summary(z_cal_unseen, y[cal_idx])
    unseen_cal_metrics = _eval_logits_summary(cal.apply_temperature(z_cal_unseen, temp_holdout), y[cal_idx])

    class CalibratedWithNorm(torch.nn.Module):
        """Input: uint8-range float RGB NCHW [0..255], pad=128; outputs (probs, logits)."""

        def __init__(self, m, temperature: float):
            super().__init__()
            self.m = m
            self.register_buffer("mean", torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1) * 255.0)
            self.register_buffer("std", torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1) * 255.0)
            self.register_buffer("temperature", torch.tensor(float(temperature), dtype=torch.float32))

        def forward(self, x):
            logits = self.m((x - self.mean) / self.std)
            probs = torch.softmax(logits / self.temperature, dim=1)
            return probs, logits

    DEPLOY_FRESHNESS_DIR.mkdir(parents=True, exist_ok=True)
    onnx_path = DEPLOY_FRESHNESS_DIR / "model.onnx"
    wrapped = CalibratedWithNorm(net, temp_holdout).eval()
    dummy = torch.zeros(1, 3, SIZE, SIZE, dtype=torch.float32)
    torch.onnx.export(
        wrapped,
        dummy,
        str(onnx_path),
        input_names=["image"],
        output_names=["probs", "logits"],
        dynamic_axes={"image": {0: "n"}, "probs": {0: "n"}, "logits": {0: "n"}},
        opset_version=17,
        dynamo=False,
    )

    # Parity check on unseen calibration images
    n_parity = min(100, len(cal_idx))
    x_parity = torch.from_numpy(np.ascontiguousarray(xm[cal_idx[:n_parity]])).permute(0, 3, 1, 2).float()
    with torch.no_grad():
        ref_probs, ref_logits = wrapped(x_parity)
        ref_probs_np = ref_probs.numpy()
        ref_logits_np = ref_logits.numpy()

    so = ort.SessionOptions()
    so.intra_op_num_threads = 2
    so.inter_op_num_threads = 1
    sess = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])
    got_probs, got_logits = [], []
    x_np = x_parity.numpy()
    for i in range(n_parity):
        p_i, l_i = sess.run(["probs", "logits"], {"image": x_np[i : i + 1]})
        got_probs.append(p_i)
        got_logits.append(l_i)
    got_probs_np = np.concatenate(got_probs, axis=0)
    got_logits_np = np.concatenate(got_logits, axis=0)

    lat_c1 = _benchmark_onnx_latency(onnx_path, x_np, concurrency=1, n_warmup=10, n_iters=100)
    lat_c5 = _benchmark_onnx_latency(onnx_path, x_np, concurrency=5, n_warmup=10, n_iters=100)
    sha256 = hashlib.sha256(onnx_path.read_bytes()).hexdigest()

    version = f"freshness_{arch}_cal_v1"
    preprocess_version = "letterbox224_rgb_pad128_v1"
    (DEPLOY_FRESHNESS_DIR / "version").write_text(f"{version}\n", encoding="utf-8")
    (DEPLOY_FRESHNESS_DIR / "preprocess_version").write_text(f"{preprocess_version}\n", encoding="utf-8")

    # Gather OOF metrics if analyzed
    oof_cal_metrics = {}
    oof_raw_metrics = {}
    p_conf = RESEARCH_DIR / "p2_confirmatory_results.json"
    if p_conf.exists():
        conf_doc = json.loads(p_conf.read_text(encoding="utf-8"))
        arm_m = conf_doc.get("arm_summaries", {}).get(arch, {})
        if "temp" in arm_m:
            oof_cal_metrics = arm_m["temp"]["seed_mean_sd"]
        if "raw" in arm_m:
            oof_raw_metrics = arm_m["raw"]["seed_mean_sd"]

    serving = {
        "schema_version": "freshness.serving.v1",
        "name": "freshness",
        "version": version,
        "architecture": arch,
        "artifact_file": "model.onnx",
        "sha256": sha256,
        "protocol_id": PROTOCOL_ID,
        "classes": list(LABELS),
        "backend_classes": ["tuoi", "dung_som", "dung_ngay", "kiem_tra"],
        "input": {
            "name": "image",
            "layout": "NCHW",
            "color": "RGB",
            "dtype": "float32",
            "imgsz": SIZE,
            "resize_mode": "letterbox_center",
            "pad_value": 128,
            "range": [0.0, 255.0],
            "normalization_in_onnx": True,
            "imagenet_mean": [0.485, 0.456, 0.406],
            "imagenet_std": [0.229, 0.224, 0.225],
            "grabcut_required": False,
        },
        "output": {
            "probs_name": "probs",
            "probs_index": 0,
            "logits_name": "logits",
            "logits_index": 1,
            "onnx_output_shape": ["batch", 3],
            "calibration_applied_in_onnx": True,
        },
        "calibration": {
            "method": "temperature_scaling",
            "temperature": float(temp_holdout),
            "cv_mean_temperature": float(np.mean(cv_temps)) if cv_temps else None,
            "cv_median_temperature": float(np.median(cv_temps)) if cv_temps else None,
            "fitted_on": "d8dedup4_10pct_unseen_holdout",
            "n_fit": int(len(fit_idx)),
            "n_cal_holdout": int(len(cal_idx)),
        },
        "abstention": {
            "rule": "max_prob_lt_tau",
            "tau": float(recommended_tau),
            "abstain_class": "kiem_tra",
            "abstain_probs": [0.0, 0.0, 0.0, 1.0],
            "accept_probs_append": 0.0,
            "p_trust_image": 0.60,
            "urgency_multipliers": {"tuoi": 0.25, "dung_som": 0.65, "dung_ngay": 0.90, "kiem_tra": 1.20},
            "u_check": 1.0,
        },
        "scope": {
            "apply_only_if_has_freshness_model": True,
            "public_data_only": True,
            "supported_public_produces": sorted(df.produce.unique().tolist()),
        },
        "latency_ms": {"c1": lat_c1, "c5": lat_c5},
        "parity": {
            "n_images": int(n_parity),
            "max_abs_prob_diff": float(np.max(np.abs(ref_probs_np - got_probs_np))),
            "max_abs_logit_diff": float(np.max(np.abs(ref_logits_np - got_logits_np))),
            "argmax_agreement": float(np.mean(np.argmax(ref_probs_np, 1) == np.argmax(got_probs_np, 1))),
        },
        "metrics": {
            "oof_uncalibrated": oof_raw_metrics,
            "oof_calibrated": oof_cal_metrics,
            "holdout_10pct_uncalibrated": unseen_raw_metrics,
            "holdout_10pct_calibrated": unseen_cal_metrics,
        },
    }
    metrics_doc = {
        "protocol_id": PROTOCOL_ID,
        "version": version,
        "architecture": arch,
        "sha256": sha256,
        "train_meta": train_meta,
        "serving": serving,
    }
    (DEPLOY_FRESHNESS_DIR / "serving.json").write_text(json.dumps(serving, indent=2), encoding="utf-8")
    (DEPLOY_FRESHNESS_DIR / "metrics.json").write_text(json.dumps(metrics_doc, indent=2), encoding="utf-8")

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    lat_doc = {
        "protocol_id": PROTOCOL_ID,
        "arch": arch,
        "onnx_bytes": onnx_path.stat().st_size,
        "sha256": sha256,
        "latency_ms": {"c1": lat_c1, "c5": lat_c5},
        "parity": serving["parity"],
    }
    (RESEARCH_DIR / "p2_latency_results.json").write_text(json.dumps(lat_doc, indent=2), encoding="utf-8")
    return serving


# ------------------------------------------------------------------ CLI


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Problem 2 Freshness & Calibration Study (M1.2b)")
    ap.add_argument(
        "--phase",
        choices=["cpu", "gpu", "analyze", "export", "all"],
        default="cpu",
        help="Execution phase",
    )
    ap.add_argument("--n-jobs", type=int, default=4, help="Worker count for CPU GridSearchCV")
    ap.add_argument("--preprocess", choices=["grabcut", "letterbox"], default="grabcut")
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--n-boot", type=int, default=2000)
    ap.add_argument("--arch", default=None, help="Override winning CNN arch for export/letterbox")
    ap.add_argument("--letterbox-ablation", action="store_true", help="Also run unmasked letterbox CNN during gpu/all")
    ap.add_argument("--shortcut-audit", action="store_true", help="Also run AgriFreshNET-only shortcut audit")
    args = ap.parse_args(argv)

    if args.phase in ("cpu", "all"):
        run_cpu_models(n_jobs=args.n_jobs)
    if args.phase in ("gpu", "all"):
        run_gpu_models(preprocess=args.preprocess, epochs=args.epochs, batch=args.batch)
        if args.letterbox_ablation:
            lb_arch = args.arch or "mobilenet_v3_small"
            run_gpu_models(
                models=(lb_arch,),
                preprocess="letterbox",
                epochs=args.epochs,
                batch=args.batch,
                tag_suffix="_letterbox",
            )
    if args.shortcut_audit:
        run_shortcut_audit(arch=args.arch or "mobilenet_v3_small", epochs=args.epochs, batch=args.batch)
    if args.phase in ("analyze", "all"):
        analyze_study(n_boot=args.n_boot)
    if args.phase in ("export", "all"):
        export_calibrated_onnx(arch=args.arch, epochs=args.epochs, batch=args.batch)


if __name__ == "__main__":
    main()
