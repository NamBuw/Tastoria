# Milestone M2 — Blind Held-Out VN & Multi-Domain Calorie Ablation Report (`G-16`)

## 1. SOTA Training Job Status
- **`task_4790_cal_v4_out`**: {"status": "COMPLETED & REJECTED by Parsimony Gate", "reason": "Higher Nutrition5k MAE (47.39 vs 45.47 v3) and mass MAE (31.43g vs 27.46g v3); kept v3 weights in deploy/models/meal_calorie/model.onnx"}
- **`task_4789_dish_v5_siglip2`**: {"host": "153 -> 121", "status": "COMPLETED & REJECTED by Parsimony Gate (kept SigLIP2-B/16 v3 FP32 in deploy/models/dish_classifier/)"}
- **`next_gen_cpu_roadmap`**: "Distill SigLIP2-SO400M + DINOv3-L offline into DINOv3-ConvNeXt-Tiny Static INT8 QDQ (AVX-512 VNNI ~20-28ms CPU) + Spatial Depth Factorized Calorie v5 (no external VLM calls, PDPL compliant)"
- **High-Res Mobile Photo (`3024x4032`, 1001296 bytes)**: sanitize_p50=60.04ms, dish_cls_p50=119.36ms, e2e_p50=223.01ms, e2e_p95=245.46ms

## 2. Blind Held-Out Splits (Strictly Zero-Leakage vs Train & `app/assets/food`)
### `Nutrition5k test_clean` (n=457)
| Model | Kcal MAE | Kcal MAPE (%) | Mass MAE (g) | R² | Within-20% | CPU p95 (ms) |
|---|---:|---:|---:|---:|---:|---:|
| `v3` | 47.01 | 19.33 | 28.47 | 0.8732 | 65.13% | 38.77 |
| `v4_rejected` | 49.15 | 21.47 | 32.24 | 0.8780 | 60.26% | 39.69 |
- Paired bootstrap (v4 - v3): delta_mae=+2.14 kcal, 95% CI [-0.63, +5.01]

### `mmfood_100k_unseen` (n=160, disambig=68.75%, ood=2.5%, raps=8.54, e2e_p95=194.41ms)
| Arm | N | Kcal MAE | Kcal RMSE | Kcal MAPE (%) | Within-20% | 80% CI Cov |
|---|---:|---:|---:|---:|---:|---:|
| `visual_v3` | 160 | 123.01 | 167.01 | 24.75% | 53.12% | 77.50% |
| `visual_v4_rejected` | 160 | 115.65 | 164.66 | 21.57% | 60.62% | 78.75% |
| `legacy_cascade` | 160 | 225.54 | 313.45 | 37.61% | 31.25% | 26.88% |
| `m2_fusion` | 160 | 128.16 | 175.82 | 25.71% | 51.25% | 77.50% |
- Paired bootstrap (M2 - Legacy): delta_mae=-97.38 kcal, 95% CI [-126.39, -71.21], p_non_inferior=0.0
- Paired bootstrap (M2 - Visual_v3): delta_mae=+5.14 kcal, 95% CI [-0.64, +11.24]
- **Domain Pareto Frontier Note (`mmfood_100k_unseen`)**: `m2_fusion` (128.16 kcal) vs `visual_v3` (123.01 kcal) has paired bootstrap `delta_mae=+5.14` kcal (95% CI `[-0.64, +11.24]`, straddling zero), while beating `legacy_cascade` (225.54 kcal) and matching 80% CI coverage (77.50% vs `visual_v3` 77.50%). Empirical Pareto sweep (`vn_disagree_gamma` 0.0 -> 1.0) proves a ~123.2 kcal `mmfood_100k_unseen` floor that trades off 1-serving VN home dishes linearly.

### `hoagmin_vn_valid` — Classifier-to-KB Proxy Eval (n=250, disambig=9.2%, ood=0.0%, raps=1.71, e2e_p95=184.7ms)
> **Classifier-to-KB Proxy Eval**: Ground-truth calories come from `kb.estimate_recognized(dish_id, portion="vua")` (the same KB lookup used by `legacy_cascade` / `m2_fusion`), not independent weighed meal measurements.
- Classifier v3 Top-1: **94.4%**, Top-3: **98.4%**, Macro-F1: `0.5976`, mean margin (correct vs wrong): `0.9517` vs `0.4892`
| Arm | N | Kcal MAE | Kcal RMSE | Kcal MAPE (%) | Within-20% | 80% CI Cov |
|---|---:|---:|---:|---:|---:|---:|
| `visual_v3` | 250 | 55.26 | 76.99 | 12.48% | 81.60% | 94.00% |
| `visual_v4_rejected` | 250 | 55.69 | 74.60 | 12.61% | 78.80% | 94.80% |
| `legacy_cascade` | 250 | 5.20 | 22.04 | 1.16% | 98.80% | 98.40% |
| `m2_fusion` | 250 | 11.53 | 36.97 | 2.68% | 97.20% | 99.60% |
- Paired bootstrap (M2 - Legacy): delta_mae=+6.33 kcal, 95% CI [+2.95, +10.50], p_non_inferior=1.0
- Paired bootstrap (M2 - Visual_v3): delta_mae=-43.73 kcal, 95% CI [-49.95, -38.18]

### `vn103_validation` — Classifier-to-KB Proxy Eval (n=250, disambig=14.0%, ood=0.0%, raps=2.12, e2e_p95=192.29ms)
> **Classifier-to-KB Proxy Eval**: Ground-truth calories come from `kb.estimate_recognized(dish_id, portion="vua")` (the same KB lookup used by `legacy_cascade` / `m2_fusion`), not independent weighed meal measurements.
- Classifier v3 Top-1: **92.4%**, Top-3: **96.8%**, Macro-F1: `0.7143`, mean margin (correct vs wrong): `0.9258` vs `0.5478`
| Arm | N | Kcal MAE | Kcal RMSE | Kcal MAPE (%) | Within-20% | 80% CI Cov |
|---|---:|---:|---:|---:|---:|---:|
| `visual_v3` | 250 | 55.64 | 80.86 | 16.56% | 71.60% | 90.80% |
| `visual_v4_rejected` | 250 | 54.88 | 77.60 | 16.01% | 76.80% | 90.80% |
| `legacy_cascade` | 250 | 7.19 | 22.28 | 2.08% | 97.60% | 98.40% |
| `m2_fusion` | 250 | 11.33 | 32.50 | 3.41% | 96.80% | 99.60% |
- Paired bootstrap (M2 - Legacy): delta_mae=+4.14 kcal, 95% CI [+1.09, +7.70], p_non_inferior=0.9985
- Paired bootstrap (M2 - Visual_v3): delta_mae=-44.31 kcal, 95% CI [-50.63, -38.53]

## 3. Separate Curated OOD Live Benchmark (`app/assets/food/*.webp`, NOT Blind)
- N=12, disambiguation_rate=41.67%, Top-1=66.67%
| Arm | N | Kcal MAE | Kcal MAPE (%) | Within-20% | 80% CI Cov |
|---|---:|---:|---:|---:|---:|
| `visual_v3` | 12 | 140.25 | 74.70% | 33.33% | 41.67% |
| `visual_v4_rejected` | 12 | 124.86 | 55.62% | 25.00% | 50.00% |
| `legacy_cascade` | 12 | 28.34 | 17.80% | 83.33% | 83.33% |
| `m2_fusion` | 12 | 24.63 | 14.61% | 91.67% | 91.67% |
