"""Export Meal Calorie PyTorch checkpoint to opset-17 ONNX, verify parity & CPU latency.

Writes ``deploy/models/meal_calorie/{model.onnx, serving.json, metrics.json}``.
Can be invoked in ``hac_env`` with ``PYTHONPATH=/dev/shm/tastoria_stage_m3/pydeps`` for export,
and CPU latency benchmarking works in either ``hac_env`` or production ``.venv``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

from tastoria_ml.calorie import INPUT_SIZE, PAD_VALUE, PORTION_MULTIPLIERS, TARGET_COLS


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def benchmark_onnx_cpu(onnx_path: Path, *, n_warmup: int = 10, n_runs: int = 200) -> dict[str, float | int | str]:
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.intra_op_num_threads = 2
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    sess = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])
    inp_name = sess.get_inputs()[0].name
    x = (np.random.default_rng(20261017).random((1, 3, INPUT_SIZE, INPUT_SIZE), dtype=np.float32) * 255.0)
    for _ in range(n_warmup):
        sess.run(None, {inp_name: x})
    ts = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        sess.run(None, {inp_name: x})
        ts.append((time.perf_counter() - t0) * 1000.0)
    return {
        "n_warmup": n_warmup,
        "n_runs": n_runs,
        "intra_op_num_threads": 2,
        "inter_op_num_threads": 1,
        "allow_spinning": "0",
        "p50_ms": round(float(np.percentile(ts, 50)), 3),
        "p95_ms": round(float(np.percentile(ts, 95)), 3),
        "p99_ms": round(float(np.percentile(ts, 99)), 3),
        "mean_ms": round(float(np.mean(ts)), 3),
        "onnxruntime_version": ort.__version__,
    }


def export_model(
    *,
    ckpt_path: Path,
    train_summary_path: Path,
    stage_dir: Path,
    deploy_dir: Path,
    kb_csv_path: Path,
    pydeps_dir: Path | None = None,
) -> dict:
    if pydeps_dir is not None and pydeps_dir.exists() and str(pydeps_dir) not in sys.path:
        sys.path.insert(0, str(pydeps_dir))

    import onnx  # noqa: F401
    import onnxruntime as ort
    import torch
    from torch.utils.data import DataLoader

    from tastoria_ml.calorie.dataset import load_overhead_dataset, make_torch_dataset
    from tastoria_ml.calorie.model import MealCalorieNet, WithNormCalorieWrapper

    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    net = MealCalorieNet(backbone_name=ckpt["backbone_name"], pretrained=False, dropout=0.2)
    net.load_state_dict(ckpt["state_dict"])
    wrapped = WithNormCalorieWrapper(net, ckpt["target_mean"], ckpt["target_std"]).eval()

    deploy_dir.mkdir(parents=True, exist_ok=True)
    onnx_path = deploy_dir / "model.onnx"
    dummy = torch.zeros(1, 3, INPUT_SIZE, INPUT_SIZE, dtype=torch.float32)
    torch.onnx.export(
        wrapped,
        dummy,
        str(onnx_path),
        input_names=["image"],
        output_names=["pred"],
        dynamic_axes={"image": {0: "n"}, "pred": {0: "n"}},
        opset_version=17,
        dynamo=False,
    )

    # Parity on Nutrition5k validation split
    ds = load_overhead_dataset(stage_dir)
    val_df = ds.split_df("val")
    val_loader = DataLoader(make_torch_dataset(val_df, ds.images_by_id, augment=False, size=INPUT_SIZE), batch_size=32, shuffle=False)
    pt_preds = []
    xs = []
    with torch.no_grad():
        for xb, _ in val_loader:
            xs.append(xb.numpy())
            pt_preds.append(wrapped(xb).numpy())
    x_all = np.concatenate(xs, axis=0)
    pt_all = np.concatenate(pt_preds, axis=0)

    so = ort.SessionOptions()
    so.intra_op_num_threads = 2
    so.inter_op_num_threads = 1
    so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    sess = ort.InferenceSession(str(onnx_path), so, providers=["CPUExecutionProvider"])
    ort_all = np.concatenate([sess.run(None, {"image": x_all[i : i + 1]})[0] for i in range(len(x_all))], axis=0)
    max_abs_diff = float(np.abs(pt_all - ort_all).max())
    mean_abs_diff = float(np.abs(pt_all - ort_all).mean())

    latency = benchmark_onnx_cpu(onnx_path)
    if latency["p95_ms"] > 50.0:
        raise RuntimeError(f"ONNX CPU p95 latency {latency['p95_ms']} ms > 50.0 ms budget")

    train_summary = json.loads(train_summary_path.read_text(encoding="utf-8"))
    onnx_sha = sha256_file(onnx_path)
    kb_sha = sha256_file(kb_csv_path) if kb_csv_path.exists() else ""

    honest_metrics = {
        "backbone": ckpt["backbone_name"],
        "n_params": int(ckpt["n_params"]),
        "best_epoch": int(ckpt["best_epoch"]),
        "ablation_val_kcal_mae": {
            k: v["val_metrics"]["kcal"]["mae"] for k, v in train_summary["ablation"].items()
        },
        "selection_reason": train_summary["selection_reason"],
        "constant_baseline": train_summary["evaluation"]["constant_baseline"],
        "splits": train_summary["evaluation"]["splits"],
        "onnx_parity_val": {
            "n": int(len(x_all)),
            "max_abs_diff": max_abs_diff,
            "mean_abs_diff": mean_abs_diff,
        },
        "cpu_latency": latency,
    }

    serving = {
        "schema_version": "meal_calorie.serving.v1",
        "name": "meal_calorie",
        "version": f"meal_calorie_{ckpt['backbone_name']}_v1",
        "backbone": ckpt["backbone_name"],
        "license": "CC-BY-4.0 (trained on shalev396/calorie-lens-data Nutrition5k overhead)",
        "artifact_file": "model.onnx",
        "artifact_sha256": onnx_sha,
        "artifact_bytes": onnx_path.stat().st_size,
        "kb_dishes_sha256": kb_sha,
        "input": {
            "name": "image",
            "shape": [1, 3, INPUT_SIZE, INPUT_SIZE],
            "layout": "NCHW",
            "color": "RGB",
            "preprocess": "letterbox",
            "pad_value": PAD_VALUE,
            "range": "0..255_float32",
            "norm_baked_in_onnx": True,
        },
        "outputs": {
            "name": "pred",
            "shape": [1, len(TARGET_COLS)],
            "columns": list(TARGET_COLS),
            "clamped_non_negative": True,
        },
        "portion_multipliers": dict(PORTION_MULTIPLIERS),
        "honest_metrics": {
            "val_kcal_mae": train_summary["evaluation"]["splits"]["val"]["model"]["kcal"]["mae"],
            "test_kcal_mae": train_summary["evaluation"]["splits"]["test"]["model"]["kcal"]["mae"],
            "test_kcal_r2": train_summary["evaluation"]["splits"]["test"]["model"]["kcal"]["r2"],
            "test_clean_kcal_mae": train_summary["evaluation"]["splits"]["test_clean"]["model"]["kcal"]["mae"],
            "test_clean_kcal_r2": train_summary["evaluation"]["splits"]["test_clean"]["model"]["kcal"]["r2"],
            "constant_median_test_kcal_mae": train_summary["evaluation"]["splits"]["test"]["baseline_median"]["kcal"]["mae"],
            "cpu_p50_ms": latency["p50_ms"],
            "cpu_p95_ms": latency["p95_ms"],
            "onnx_parity_max_abs_diff": max_abs_diff,
        },
        "domain_shift_note": (
            "Visual ONNX model was trained on Google Nutrition5k overhead US cafeteria plates (CC BY 4.0) "
            "at fixed camera height. Without Vietnamese meal photos with weighed calories, single-view RGB "
            "predictions on Vietnamese bowls/soups (canh, pho, com) carry significant scale and hidden-oil "
            "uncertainty; prefer Tastoria KB dish lookup when the dish is selected or confirmed by the user."
        ),
    }

    (deploy_dir / "serving.json").write_text(json.dumps(serving, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (deploy_dir / "metrics.json").write_text(json.dumps(honest_metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return serving


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Export Meal Calorie ONNX and benchmark CPU latency")
    ap.add_argument("--runs-dir", type=Path, default=Path("/dev/shm/tastoria_stage_m3/runs"))
    ap.add_argument("--stage-dir", type=Path, default=Path("/dev/shm/tastoria_stage_m3/calorie_lens"))
    ap.add_argument("--deploy-dir", type=Path, default=Path("deploy/models/meal_calorie"))
    ap.add_argument("--kb-csv", type=Path, default=Path("data/processed/kb/recipe_nutrition.csv"))
    ap.add_argument("--pydeps-dir", type=Path, default=Path("/dev/shm/tastoria_stage_m3/pydeps"))
    args = ap.parse_args(argv)

    summary_path = args.runs_dir / "train_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    ckpt_path = Path(summary["selected_ckpt"])
    serving = export_model(
        ckpt_path=ckpt_path,
        train_summary_path=summary_path,
        stage_dir=args.stage_dir,
        deploy_dir=args.deploy_dir,
        kb_csv_path=args.kb_csv,
        pydeps_dir=args.pydeps_dir,
    )
    print(json.dumps(serving["honest_metrics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
