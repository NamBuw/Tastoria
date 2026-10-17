"""Freshness classifier on PUBLIC data: classic features + SVM vs MobileNetV3-Small (thiết kế v2 §7).

Data: data/processed/freshness/manifest.csv (Local Spinach Leaf v3 + AgriFreshNET v1, both CC BY 4.0).
Augmented copies (``aug_*``) and ``label_conflict`` rows are dropped; only originals are used.
Labels: label3 ordinal tuoi (0) < dung_som (1) < dung_ngay (2). Spinach has no middle level.

Groups for the split ("lot"):
  AgriFreshNET  produce + capture date read from the file name (IMG_YYYYMMDD_...), i.e. one shooting
                session; files without a date fall back to their manifest group_id;
  Local Spinach no lot or date is published: each image is its own group (risk of near-duplicates across
                folds; recorded as a limitation).
Split: StratifiedGroupKFold, 5 folds × 3 repeats (different shuffles) for the SVM, 5 folds × 1 repeat for
the CNN (GPU budget); both arms share the folds of repeat 0 so their out-of-fold predictions are paired.

Shared input: each image is letterboxed to 224×224 and a foreground mask is computed once with GrabCut
(rectangle = central 90%); both arms see the same masked pixels (background set to mid-gray for the CNN,
excluded from the hand-crafted features).

Classic features: HSV histogram (H 18, S 8, V 8 bins, foreground only), uniform LBP (P=8, R=1; P=16, R=2)
histograms, GLCM (distances 1, 3; 4 angles) contrast / dissimilarity / homogeneity / energy /
correlation / ASM on the foreground bounding box, foreground fraction, mean and std of Lab.
SVM: RBF, C and gamma chosen by an inner GroupKFold(3) on the training folds.

Run (training env):
  python -m tastoria_ml.cv.freshness cache   # letterbox + GrabCut cache (CPU, parallel)
  python -m tastoria_ml.cv.freshness svm
  python -m tastoria_ml.cv.freshness cnn     # GPU: memory fraction 0.15, fixed batch
  python -m tastoria_ml.cv.freshness report
"""

from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from tastoria_ml.cv.classes import REPO

MANIFEST = REPO / "data" / "processed" / "freshness" / "manifest.csv"
WORK = REPO / "ml" / "runs" / "freshness"
OUT = REPO / "data" / "processed" / "cv" / "freshness"
LABELS = ["tuoi", "dung_som", "dung_ngay"]
SIZE = 224
N_FOLDS = 5
SEED = 0


# ------------------------------------------------------------------ data


def load_table() -> pd.DataFrame:
    df = pd.read_csv(MANIFEST)
    df = df[(df.is_augmented.astype(str) == "False") & (df.label_conflict.astype(str) == "False")].copy()
    df = df.reset_index(drop=True)

    def lot(row) -> str:
        if row.dataset == "agrifreshnet":
            m = re.search(r"(20\d{6})[_-]", Path(row.path).name)
            if m:
                return f"agrifreshnet/{row.produce}/{m.group(1)}"
        return row.group_id

    df["lot"] = df.apply(lot, axis=1)
    df["y"] = df.label3.map({k: i for i, k in enumerate(LABELS)})
    return df


def _letterbox_and_mask(path: str) -> tuple[np.ndarray, np.ndarray]:
    import cv2
    from PIL import Image, ImageOps

    with Image.open(REPO / path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((SIZE, SIZE))
        a = np.asarray(im)
    h, w = a.shape[:2]
    canvas = np.full((SIZE, SIZE, 3), 128, np.uint8)
    y0, x0 = (SIZE - h) // 2, (SIZE - w) // 2
    canvas[y0 : y0 + h, x0 : x0 + w] = a
    mask = np.zeros((SIZE, SIZE), np.uint8)
    rect = (x0 + int(0.05 * w), y0 + int(0.05 * h), max(int(0.9 * w), 1), max(int(0.9 * h), 1))
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR), mask, rect, bgd, fgd, 3, cv2.GC_INIT_WITH_RECT)
        fg = (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)
    except cv2.error:
        fg = np.zeros((SIZE, SIZE), bool)
    inside = np.zeros((SIZE, SIZE), bool)
    inside[y0 : y0 + h, x0 : x0 + w] = True
    frac = fg.sum() / max(inside.sum(), 1)
    if frac < 0.05 or frac > 0.98:  # GrabCut failed: fall back to the central rectangle
        fg = np.zeros((SIZE, SIZE), bool)
        fg[rect[1] : rect[1] + rect[3], rect[0] : rect[0] + rect[2]] = True
    return canvas, fg


def build_cache(workers: int = 12) -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    df = load_table()
    t = time.time()
    with ProcessPoolExecutor(workers) as ex:
        res = list(ex.map(_letterbox_and_mask, df.path.tolist(), chunksize=32))
    X = np.stack([r[0] for r in res])
    M = np.stack([r[1] for r in res])
    np.save(WORK / "X224.npy", X)
    np.save(WORK / "M224.npy", M)
    df.to_csv(WORK / "table.csv", index=False)
    print(f"cache {X.shape} in {time.time() - t:.0f}s; mean fg fraction {M.mean():.3f}")


def load_cache() -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    return pd.read_csv(WORK / "table.csv"), np.load(WORK / "X224.npy", mmap_mode="r"), np.load(WORK / "M224.npy")


def folds(df: pd.DataFrame, repeat: int) -> np.ndarray:
    """Fold id (0..4) per row for one repeat."""
    from sklearn.model_selection import StratifiedGroupKFold

    # stratify on dataset×produce×label so every fold sees every produce/level
    strat = (df.dataset + "/" + df.produce + "/" + df.label3).astype("category").cat.codes
    sgk = StratifiedGroupKFold(n_splits=N_FOLDS, shuffle=True, random_state=SEED + repeat)
    f = np.full(len(df), -1)
    for k, (_, te) in enumerate(sgk.split(np.zeros(len(df)), strat, df.lot)):
        f[te] = k
    return f


# ------------------------------------------------------------------ metrics


def metrics(y: np.ndarray, p: np.ndarray) -> dict:
    from sklearn.metrics import accuracy_score, cohen_kappa_score, confusion_matrix, f1_score

    labels = [0, 1, 2]
    return {
        "n": int(len(y)),
        "accuracy": float(accuracy_score(y, p)),
        "macro_f1": float(f1_score(y, p, labels=labels, average="macro", zero_division=0)),
        "qwk": float(cohen_kappa_score(y, p, labels=labels, weights="quadratic")),
        "mae_level": float(np.abs(y - p).mean()),
        "confusion": confusion_matrix(y, p, labels=labels).tolist(),
    }


def breakdown(df: pd.DataFrame, pred: np.ndarray) -> dict:
    out = {"all": metrics(df.y.values, pred)}
    for (ds, prod), g in df.groupby(["dataset", "produce"]):
        out[f"{ds}/{prod}"] = metrics(g.y.values, pred[g.index.values])
    return out


# ------------------------------------------------------------------ classic arm


def _features_one(args) -> np.ndarray:
    import cv2
    from skimage.feature import graycomatrix, graycoprops, local_binary_pattern

    img, fg = args
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32)
    m = fg.astype(bool)
    if m.sum() < 50:
        m = np.ones_like(m)
    f = []
    for ch, bins, rng in ((0, 18, 180), (1, 8, 256), (2, 8, 256)):
        h, _ = np.histogram(hsv[..., ch][m], bins=bins, range=(0, rng))
        f.append(h / m.sum())
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    for P, R in ((8, 1), (16, 2)):
        lbp = local_binary_pattern(gray, P, R, method="uniform")
        h, _ = np.histogram(lbp[m], bins=P + 2, range=(0, P + 2))
        f.append(h / m.sum())
    ys, xs = np.where(m)
    crop = gray[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]
    q = (crop // 8).astype(np.uint8)  # 32 gray levels
    glcm = graycomatrix(q, distances=[1, 3], angles=[0, np.pi / 4, np.pi / 2, 3 * np.pi / 4], levels=32,
                        symmetric=True, normed=True)
    for prop in ("contrast", "dissimilarity", "homogeneity", "energy", "correlation", "ASM"):
        f.append(graycoprops(glcm, prop).mean(axis=1))
    f.append([m.mean()])
    f.append(lab[m].mean(0) / 255.0)
    f.append(lab[m].std(0) / 255.0)
    return np.concatenate([np.ravel(x) for x in f]).astype(np.float32)


def features(workers: int = 12) -> np.ndarray:
    p = WORK / "features.npy"
    if p.exists():
        return np.load(p)
    _, X, M = load_cache()
    with ProcessPoolExecutor(workers) as ex:
        F = np.stack(list(ex.map(_features_one, ((np.asarray(X[i]), M[i]) for i in range(len(M))), chunksize=64)))
    np.save(p, F)
    return F


def run_svm(repeats: int = 3) -> dict:
    from sklearn.model_selection import GridSearchCV, GroupKFold
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from sklearn.svm import SVC

    df, _, _ = load_cache()
    F = features()
    res = {"repeats": []}
    preds0 = None
    for r in range(repeats):
        f = folds(df, r)
        pred = np.full(len(df), -1)
        chosen = []
        for k in range(N_FOLDS):
            tr, te = np.where(f != k)[0], np.where(f == k)[0]
            gs = GridSearchCV(
                make_pipeline(StandardScaler(), SVC(kernel="rbf")),
                {"svc__C": [1, 10, 100], "svc__gamma": ["scale", 0.01, 0.003]},
                cv=GroupKFold(3), scoring="f1_macro", n_jobs=9,
            )
            gs.fit(F[tr], df.y.values[tr], groups=df.lot.values[tr])
            pred[te] = gs.predict(F[te])
            chosen.append(gs.best_params_)
        m = breakdown(df, pred)
        res["repeats"].append({"overall": m["all"], "params": chosen})
        if r == 0:
            preds0 = pred
            res["per_produce_repeat0"] = {k: v for k, v in m.items() if k != "all"}
        print(f"svm repeat {r}: macro-F1 {m['all']['macro_f1']:.4f} qwk {m['all']['qwk']:.4f}", flush=True)
    np.save(WORK / "svm_pred_r0.npy", preds0)
    res["summary"] = _summary([x["overall"] for x in res["repeats"]])
    return res


def _summary(ms: list[dict]) -> dict:
    out = {}
    for k in ("accuracy", "macro_f1", "qwk", "mae_level"):
        v = np.array([m[k] for m in ms])
        out[k] = {"mean": float(v.mean()), "sd": float(v.std(ddof=1)) if len(v) > 1 else None}
    return out


# ------------------------------------------------------------------ CNN arm


def run_cnn(epochs: int = 10, batch: int = 64, repeats: int = 1, smoke: bool = False) -> dict:
    from tastoria_ml.cv.train_detector import GpuGuard

    # same shared-GPU rules as the detector: ≥ 10 GB free, fraction 0.15, lock, watchdog at < 3 GB
    with GpuGuard("freshness_cnn_smoke" if smoke else "freshness_cnn"):
        return _run_cnn(epochs, batch, repeats, smoke)


def _run_cnn(epochs: int, batch: int, repeats: int, smoke: bool) -> dict:
    import torch
    import torchvision
    from torch import nn

    dev = torch.device("cuda")
    torch.manual_seed(SEED)
    df, X, M = load_cache()
    Xm = np.where(M[..., None], np.asarray(X), np.uint8(128))  # shared mask: background mid-gray
    mean = torch.tensor([0.485, 0.456, 0.406], device=dev).view(1, 3, 1, 1)
    std = torch.tensor([0.229, 0.224, 0.225], device=dev).view(1, 3, 1, 1)

    def to_t(idx, train):
        x = torch.from_numpy(Xm[idx]).to(dev).permute(0, 3, 1, 2).float() / 255.0
        if train:
            if torch.rand(1).item() < 0.5:
                x = x.flip(3)
            if torch.rand(1).item() < 0.5:
                x = x.flip(2)
            x = x * (1 + 0.2 * (torch.rand(len(idx), 1, 1, 1, device=dev) - 0.5))  # brightness ±10%
        return ((x.clamp(0, 1) - mean) / std)

    res = {"repeats": [], "epochs": epochs, "batch": batch}
    preds0 = None
    for r in range(repeats):
        f = folds(df, r)
        pred = np.full(len(df), -1)
        for k in range(N_FOLDS):
            tr, te = np.where(f != k)[0], np.where(f == k)[0]
            if smoke:
                tr, te = tr[:512], te[:256]
            net = torchvision.models.mobilenet_v3_small(weights="IMAGENET1K_V1")
            net.classifier[3] = nn.Linear(net.classifier[3].in_features, 3)
            net = net.to(dev)
            opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-4)
            steps = epochs * int(np.ceil(len(tr) / batch))
            sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=1e-3, total_steps=steps)
            rng = np.random.default_rng(SEED + 100 * r + k)
            for ep in range(epochs):
                net.train()
                perm = rng.permutation(tr)
                for i in range(0, len(perm), batch):
                    idx = np.sort(perm[i : i + batch])
                    loss = nn.functional.cross_entropy(net(to_t(idx, True)), torch.from_numpy(df.y.values[idx]).to(dev))
                    opt.zero_grad()
                    loss.backward()
                    opt.step()
                    sched.step()
            net.eval()
            with torch.no_grad():
                for i in range(0, len(te), 256):
                    idx = te[i : i + 256]
                    pred[idx] = net(to_t(idx, False)).argmax(1).cpu().numpy()
            print(f"cnn r{r} fold {k}: acc {np.mean(pred[te] == df.y.values[te]):.4f} "
                  f"max_mem {torch.cuda.max_memory_allocated() / 2**30:.2f} GiB", flush=True)
            if smoke:
                return {"smoke": True}
        m = breakdown(df, pred)
        res["repeats"].append({"overall": m["all"]})
        if r == 0:
            preds0 = pred
            res["per_produce_repeat0"] = {k: v for k, v in m.items() if k != "all"}
    np.save(WORK / "cnn_pred_r0.npy", preds0)
    res["summary"] = _summary([x["overall"] for x in res["repeats"]])
    return res


# ------------------------------------------------------------------ paired comparison


def paired_bootstrap(n_boot: int = 2000) -> dict:
    """Cluster bootstrap over lots of Δ macro-F1 and Δ QWK (CNN − SVM) on repeat-0 OOF predictions."""
    from sklearn.metrics import cohen_kappa_score, f1_score

    df, _, _ = load_cache()
    ps, pc = np.load(WORK / "svm_pred_r0.npy"), np.load(WORK / "cnn_pred_r0.npy")
    y = df.y.values
    lots = df.lot.values
    uniq, inv = np.unique(lots, return_inverse=True)
    members = [np.where(inv == i)[0] for i in range(len(uniq))]
    rng = np.random.default_rng(SEED)
    d_f1, d_k = [], []
    for _ in range(n_boot):
        idx = np.concatenate([members[i] for i in rng.integers(0, len(uniq), len(uniq))])
        d_f1.append(f1_score(y[idx], pc[idx], average="macro") - f1_score(y[idx], ps[idx], average="macro"))
        d_k.append(cohen_kappa_score(y[idx], pc[idx], weights="quadratic")
                   - cohen_kappa_score(y[idx], ps[idx], weights="quadratic"))
    q = lambda v: [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))]  # noqa: E731
    return {
        "n_lots": int(len(uniq)),
        "delta_macro_f1_cnn_minus_svm": {"point": float(f1_score(y, pc, average="macro") - f1_score(y, ps, average="macro")), "ci95": q(d_f1)},
        "delta_qwk_cnn_minus_svm": {"point": float(cohen_kappa_score(y, pc, weights="quadratic") - cohen_kappa_score(y, ps, weights="quadratic")), "ci95": q(d_k)},
        "n_boot": n_boot,
    }


def _log_mlflow(name: str, res: dict) -> None:
    import mlflow

    mlruns = REPO / "ml" / "mlruns"
    mlflow.set_tracking_uri(f"sqlite:///{mlruns / 'mlflow.db'}")
    exp = "tastoria-freshness-public"
    if mlflow.get_experiment_by_name(exp) is None:
        mlflow.create_experiment(exp, artifact_location=(mlruns / "artifacts").as_uri())
    mlflow.set_experiment(exp)
    with mlflow.start_run(run_name=name):
        mlflow.set_tag("data", "public only (Local Spinach Leaf v3 + AgriFreshNET v1)")
        for k, v in res["summary"].items():
            mlflow.log_metric(f"{k}_mean", v["mean"])
        mlflow.log_dict(res, f"{name}.json")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["cache", "svm", "cnn", "cnn-smoke", "report", "log"])
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.step == "cache":
        build_cache()
    elif a.step == "svm":
        res = run_svm()
        (OUT / "svm.json").write_text(json.dumps(res, indent=2))
        _log_mlflow("svm_hsv_lbp_glcm", res)
    elif a.step == "cnn-smoke":
        print(run_cnn(epochs=1, smoke=True))
    elif a.step == "cnn":
        res = run_cnn()
        (OUT / "cnn.json").write_text(json.dumps(res, indent=2))
        _log_mlflow("mobilenetv3_small", res)
    elif a.step == "log":  # re-log saved results to MLflow
        _log_mlflow("svm_hsv_lbp_glcm", json.loads((OUT / "svm.json").read_text()))
        _log_mlflow("mobilenetv3_small", json.loads((OUT / "cnn.json").read_text()))
    elif a.step == "report":
        df, _, M = load_cache()
        out = {
            "data": "PUBLIC ONLY: Local Spinach Leaf v3 + AgriFreshNET v1 originals; team-collected lots still required",
            "n_images": int(len(df)),
            "n_lots": int(df.lot.nunique()),
            "images_per_label": df.label3.value_counts().to_dict(),
            "mean_foreground_fraction": float(M.mean()),
            "svm": json.loads((OUT / "svm.json").read_text())["summary"],
            "cnn": json.loads((OUT / "cnn.json").read_text())["summary"],
            "paired_bootstrap_repeat0": paired_bootstrap(),
        }
        (OUT / "summary.json").write_text(json.dumps(out, indent=2, ensure_ascii=False))
        print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
