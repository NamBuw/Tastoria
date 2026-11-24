# Preregistration Research Protocol — Tastoria Machine Learning Studies (Milestone 1)

- **Protocol ID**: `TASTORIA-ML-PREREG-2026-11-18`
- **Registration Date**: `2026-11-18` (Milestone M1.1, prior to executing M1.2–M1.3 confirmatory experiments)
- **Authors / Maintainers**: Tastoria ML Research Team (`ml/src/tastoria_ml/`)
- **Compute Environment (R5)**: `171.226.10.153` (`NVIDIA L40S` GPU, `.venv` Python 3.12 with `numpy==2.5.4`, `scipy==1.18.1`, `scikit-learn==1.9.1`, `lightgbm>=4.6`, `implicit>=0.7.2`, `lightfm-next==1.19.0`, `gensim==4.4.0`, `ortools>=9.12`; `ml/runs/venv-cv` with `torch==2.8.0+cu126`, `ultralytics==8.4.215`, `onnxruntime==1.32.0`, `mlflow==3.18.0`).
- **Reporting Standards**: `docs/reports/hoc-may/reporting_guideline_plan.json` (`TRIPOD+AI 2024`, `STARD 2015`, `STARD-AI 2025`), governed by K-Dense scientific workflow standards (`arXiv:2609.00065`).

---

## 1. Purpose, Governance & Anti-HARKing Boundaries

This protocol preregisters the confirmatory hypotheses, independent evaluation units, negative/sanity controls, statistical inference procedures, multiplicity families, and exploratory boundaries for Tastoria's four ML problem domains:
- **P1**: Computer Vision Ingredient Detection & Counting (`yolo` v1 vs. `yolo_v2`)
- **P2**: Produce Freshness Classification & Probability Calibration
- **P3**: Meal Recommender Systems (Food.com implicit feedback & Vietnamese explicit survey + Ranker export)
- **P4**: Ingredient Substitution (`pgvector` embeddings) & Combinatorial Tray Composer (Pareto weights & CP-SAT schedule latency)

### 1.1 Confirmatory vs. Exploratory Boundary Rules
1. **Prior / Baseline Observations (Read-Only)**: Artifacts already generated and inspected in `data/processed/` and `ml/runs/` prior to `2026-11-18` (Section 2) are locked as **read-only baseline records**. They MUST NOT be retroactively framed as newly tested confirmatory predictions.
2. **Confirmatory Hypotheses (H1–H5)**: Hypotheses, primary endpoints, independent sampling units, comparator baselines, negative/sanity controls, and Holm–Bonferroni inferential families are fixed in Section 3 **before** running M1.2a, M1.2b, M1.3a, and M1.3b experiments. All confirmatory outcomes MUST be reported regardless of direction (positive, null, negative, or indeterminate).
3. **Exploratory & Gap Analyses**: Subgroup breakdowns, error root-cause audits, hyperparameter ablations, and post-hoc discoveries (Section 4) are explicitly labeled `analysis_intent = "exploratory"` (and `protocol_status = "post_hoc"` or `"amended_before_analysis"` in `consistency_manifest.json`) and adjusted via Benjamini–Hochberg FDR (`bh_fdr`).
4. **Reused-Dataset Rule**: Whenever an analysis re-evaluates an already-inspected split (e.g., v1 `yolo` test, `Food.com` `test.json`, or `SEED=20261018` `composer_eval` 75 test scenarios), it is classified as baseline verification or exploratory audit (`analysis_intent = "exploratory"`) unless evaluated on an untouched held-out split (`yolo_v2` `val`/`heldout`), newly trained multi-architecture / out-of-fold calibrated models (P2), nested CV rankers or newly trained M1.3a models/ablations (P3), updated `232`-ingredient catalog evaluations (P4a), or a newly generated, untouched synthetic test split (`n >= 75` fresh scenarios, distinct seed, P4b).

---

## 2. Prior / Baseline Observations (Read-Only Reference State on `2026-11-18`)

All counts and metrics below are directly verified from `data/processed/` and `ml/runs/` on `121` and `153`:

| Domain | Artifact / Dataset Verified | Exact Verified Counts, Splits & Prior Baseline Values | Known Gaps / Caveats |
|---|---|---|---|
| **P1 (v1)** | `data/processed/cv/dataset_stats.json`, `data/processed/cv/detector/*.json`, `data/processed/cv/results/counting.json` | **13 classes** (`ca, tom, trung, ca_chua, ca_rot, khoai_tay, bap_cai, sup_lo, bi_do, bi_dao, muop_dang, dau_que, nam`; 9 of 22 main classes lacked data). `train=11,091` (58,658 boxes), `val=897` (3,725), `test=2,035` (7,946) = **14,023 images** (`openimages_v7` + `mendeley_bd`; 386 pHash `<=4` drops). `yolo26n_640_none` test `mAP50=0.4238`, `mAP50-95=0.2777`. Counting (`abl60_none_s{0,1,2}`): `nms` MAE=`1.717±0.138` (`n_pairs=[1991,1960,2046]`, `435` OI `IsGroupOf==1` pairs excluded); `e2e` MAE=`1.711±0.104`. CPU ONNX `abl60_none_s0` (`Xeon Gold 6542Y`, 2 threads, `n=100`): `raw` p50=`27.11ms`/p95=`27.77ms`, `e2e` p50=`26.14ms`/p95=`31.22ms`. | `train_detector.py:45,309` pins `ultralytics==8.4.173`, whereas `153` `venv-cv` has `8.4.215`; `train_detector.py:37` hardcodes v1 `yolo/` dir. `gemini_baseline.py` not yet run. |
| **P1 (v2)** | `data/processed/cv/yolo_v2/`, `data/processed/cv/dataset_stats_v2.json` | **30 classes** with boxes (15 main incl. `thit_bo` & `dau_phu` + 15 proposed). **7 VN main classes with 0 boxes**: `thit_lon, thit_ga, su_su, muop, rau_cai, rau_muong, gia_do`. `train=15,865`, `val=1,485`, `test=2,035` (frozen v1 test, only 13 v1 classes have GT boxes), `heldout=1,253` (`lvis_v1`+`rpc_checkout`+`omorros_kitchen`) = **20,638 images** (`15,311` `ok` license, `5,327` `non_commercial`; 418 pHash `<=4` drops). | **Zero `yolo_v2` detector runs exist.** License split (`5,327` NC) must be tracked in `serving.json`. |
| **P2** | `data/processed/freshness/manifest.csv`, `ml/runs/freshness/table.csv`, `data/processed/cv/freshness/summary_d8dedup4.json` | `18,159` manifest rows (`8,943` `is_augmented`, `34` `label_conflict` excluded) -> **`9,182` originals** (`agrifreshnet=5,183` across 8 produces; `local_spinach_leaf=3,999` across 3 leafy greens). `label3`: `tuoi=3,809`, `dung_som=1,643` (100% AgriFreshNET; 0 in Local Spinach), `dung_ngay=3,730`. Groupings: `lot=4,318`, `dedup4=3,326`, **`d8dedup4=2,366` groups**. 81-dim classic features (`HSV 34 + LBP 28 + GLCM 12 + fg 1 + Lab mean/std 6`). Prior 3x5 `StratifiedGroupKFold` (`d8dedup4`): RBF-SVM `acc=0.8084±0.0020`, `macro_f1=0.7656±0.0015`, `qwk=0.8373±0.0029`; MobileNetV3-Small `acc=0.8627±0.0064`, `macro_f1=0.8284±0.0071`, `qwk=0.8984±0.0040` (`r0` Δ`macro_f1=+0.0690` 95% CI `[+0.0362, +0.1058]`). | No OOF logits/probs saved; **no Temperature/Platt calibration**; no `ECE`/`Brier`/`NLL`; uncalibrated ONNX not staged in `deploy/models/freshness/`. Backend expects 4 classes (`tuoi, dung_som, dung_ngay, kiem_tra`, `U_CHECK=1.0`, `M={0.25,0.65,0.9,1.2}`) vs 3 public classes. |
| **P3** | `data/processed/recsys/{manifest,test,cold,survey_sim}.json` | **Food.com**: raw `231,637` recipes, `226,570` users, `1,132,367` interactions (`1,003,724` pos `>=4`, `60,847` rating `0`); 5-core **`16,043 x 37,851`**, **`498,607` pos** (`529,087` all-rating incl. `10,058` rating `0`, density `0.0008211`), `d_val=2010-06-24`, `d_test=2012-04-01`, `4,834` test users (`39,103` warm unseen targets), `599` cold items (`422` warm users, `3,831` cold targets), `1,882` item features. 8 test variants (`MostPop` `0.01738`, `EASE` `0.01773`, `p_holm=1.0`). **VN Survey (`SIMULATED=true`, `seed=20261018`)**: `90` synthetic users, `180` KB dishes (`171` published + `9` draft in backend DB), `3,326` ratings (`1-5`), `724` `never_eaten` (`45` shown/user = `10` anchors + `35` random), 7 models + 1 meta-selector across `warm/item_cold/user_cold`. | VN survey is **synthetic (`SIMULATED=true`)** — never interpret as real VN human taste. No exported Ranker artifact in `deploy/models/ranker/`. |
| **P4** | `data/kb/{ingredients,substitution_pairs}.yaml`, `substitution_eval/queries.yaml`, `data/processed/substitution/results.json`, `data/processed/composer_eval/summary.json` | **Substitution**: **`232` KB ingredients** (`230` in `ingredients.yaml` + `2` in `make_ahead.yaml`; stale `results.json` used `225`), **`197` pairs** across `107` source ingredients (`119` total unique ingredients across pairs; `32` `dev` / `75` `test`), **`90` queries** (`27` `dev` / `63` `test`) with **`0` human answers**. Prior best: `Word2Vec` `MRR=0.5224±0.0131`, `agree@3=0.5467±0.0094`. **Composer**: **`150` synthetic scenarios** (`SEED=20261018`: `75` `tuning` [`71` feasible] / `75` `test` [`75` feasible]), `180` KB dishes (`75` man, `55` rau, `50` canh), `cat.X.shape=(180, 160)`, 200 grid triples `(α,β,γ)`, prior/post-hoc baseline audit (`analysis_intent = "exploratory"`) selected `(64.0, 0.0, 0.5)` (`taste_loss=0.196`, `511` audited trays, `0` violations; `|ΔE|/E <= 0.15` pass rate `89.3%` for `α=64`, `90.7%` for `α=16`, `McNemar p = 0.039` vs provisional `(1.0, 1.0, 0.5)`). | `results.json` stale (`225` vs `232` ingredients). No `Hybrid Fusion` method or `100d` `pgvector` embeddings export. Composer lacks CP-SAT solve-time benchmark, uses `favorites` cosine taste proxy, and its `SEED=20261018` `75`-scenario test results are already inspected (locked as exploratory baseline audit). |

---

## 3. Confirmatory Hypotheses (H1–H5), Controls & Rival Explanations

Every confirmatory hypothesis fixes its independent evaluation unit, primary estimand, comparator, negative/positive controls, rival explanations, falsifier, and Holm–Bonferroni family before M1.2–M1.3 execution.

### H1 — P1: 30-Class `yolo_v2` Multi-Architecture Detection & Counting
- **Hypothesis**:
  - **H1a (Detection)**: On `yolo_v2` (`30` covered classes; `15,865` train / `1,485` val / `1,253` heldout), higher-capacity or alternative detector architectures (`yolo26s`, `yolo11n`) achieve higher `AP@[.5:.95]` than `yolo26n` on `val` and untouched `heldout`, while preserving parity (`TOST` equivalence margin `±0.015` `AP@[.5:.95]`) with v1 `yolo26n` on the frozen 13-class `test` split (`n=2,035`).
  - **H1b (Counting)**: Threshold-tuned (`val`-selected `conf`) detector counts achieve lower Counting MAE than both the `zero_baseline` (predict `0`) and the `median_baseline` (per-class median on `train`) across `(image, countable_class)` pairs on `test`/`heldout`.
- **Independent Unit**: Detection = cluster ID (`(video, frame // 10)` for Mendeley Bangladesh video frames; 1 image = 1 cluster for Open Images / LVIS / RPC / Omorros). Counting = `(image, countable_class)` pair with `c > 0` or `c_hat > 0` (excluding Open Images `IsGroupOf == "1"`).
- **Controls**:
  - *Negative Control*: Untrained/random-weight or label-shuffled sanity check (`AP ≈ 0`, Counting MAE worse than `zero_baseline`); `zero_baseline` and `median_baseline` for counting.
  - *Positive / Sanity Control*: `yolo26n` on frozen v1 `test` must reproduce prior `mAP50 ≈ 0.42` / `mAP50-95 ≈ 0.28` within seed tolerance.
- **Rival Explanations & Falsifiers**:
  1. *Near-duplicate leakage*: Inflated `heldout` AP caused by similar images across splits -> prevented by pHash `<= 4` dedupe (`test -> heldout -> val -> train`); audited via cluster-level bootstrap.
  2. *Capacity-latency tradeoff / overfitting*: Higher `AP` on `val` fails to generalize to `heldout` or breaches CPU ONNX latency budget (`p95 > 100 ms` at `c=1`).
  3. *Class-dilution regression*: Expanding from `13` to `30` classes degrades 13-class v1 `test` AP -> **Falsifier**: 95% cluster-bootstrap CI of `ΔAP(v2 - v1)` on frozen v1 `test` falls below `-0.015`.
  4. *Indeterminate Result*: 95% CI spans `0` and extends outside `[-0.015, +0.015]` on v1 `test`, or `heldout` difference CI includes `0`.

### H2 — P2: Produce Freshness Multi-Architecture Discrimination & Post-Hoc Calibration
- **Hypothesis**:
  - **H2a (Discrimination)**: On `n=2,366` `d8dedup4` independent groups (`9,182` original images, 5-fold `StratifiedGroupKFold` × multiple fixed seeds), pretrained CNN backbones (`MobileNetV3-Small`, `EfficientNet-B0`, `ResNet-18`) outperform the classic 81-dim `RBF-SVM` / `LogisticRegression` baselines on `Macro-F1` and `Quadratic Weighted Kappa (QWK)`.
  - **H2b (Calibration)**: Out-of-fold post-hoc calibration (Temperature Scaling and/or Platt/Vector Scaling, fit strictly on validation/inner folds without test leakage) significantly reduces `ECE` (uniform and adaptive) and `Brier` / `NLL` compared to uncalibrated softmax logits, without degrading `Macro-F1` or `QWK` beyond `-0.005`.
- **Independent Unit**: Connected-component deduplicated group under D8 dihedral pHash `<= 4` (`n=2,366` independent groups; cluster-level bootstrap / group-level paired test). Never treat the `9,182` individual images or `18,159` augmented rows as independent replicates.
- **Controls**:
  - *Negative Control*: Stratified majority-class / uniform-probability dummy predictor (`Macro-F1 ≈ 0.20`, `QWK = 0.0`, `NLL ≈ ln(3) = 1.099`) and uncalibrated raw logits.
  - *Positive Control*: Classic 81-dim `RBF-SVM` must clear dummy baseline (`QWK > 0.75`).
- **Rival Explanations & Falsifiers**:
  1. *Capture-session / source shortcutting*: CNN learns dataset background (`Local Spinach` vs `AgriFreshNET`, since `Local Spinach` has `0` `dung_som` rows) rather than produce spoilage -> tested via stratified per-dataset reporting (`AgriFreshNET`-only vs `Local Spinach`-only).
  2. *Calibration overfitting*: Fitting temperature on OOF test predictions artificially lowers `ECE` -> prevented by nested/cross-fitted OOF temperature estimation; **Falsifier**: calibrated `ECE` >= uncalibrated `ECE` or `Macro-F1` drops > `0.005`.
  3. *Indeterminate Result*: Paired group-bootstrap 95% CI for `ΔECE` or `ΔMacro-F1` straddles `0`.

### H3 — P3: Recommender Systems & Exportable Learned Ranker
- **Hypothesis**:
  - **H3a (VN Survey — `SIMULATED=true`)**: Across `n=90` users (`180` KB recipes, 5 outer folds × 5 seeds, `warm`/`item_cold`/`user_cold`), the learned `LambdaMART` / hybrid ranker outperforms the non-personalized `ShrunkMean` baseline (`primary`) and `Random` on `NDCG@5` (graded) and `AUC_pairs`.
  - **H3b (Food.com Temporal Validation — Confirmatory vs. Read-Only Baseline Boundary)**: The 8 already-inspected Food.com baseline models in `data/processed/recsys/{test,cold}.json` (`Random`, `MostPop`, `ItemKNN`, `EASE`, `ALS`, `BPR`, `LightFM`) are locked as a **read-only reference benchmark** (`analysis_intent = "exploratory"` / baseline reproduction; e.g., warm `MostPop` `0.01738` vs `EASE` `0.01773`, `p_holm=1.0`). Confirmatory `H3b` status is reserved strictly for **newly implemented/trained M1.3a Food.com models or ablations not yet evaluated on `test.json`/`cold.json`** (e.g., a newly trained hybrid/learned ranker or hyperparameter/feature ablation tuned strictly on `val` [`2010-06-24`–`2012-04-01`] before single-pass evaluation on `test` [`n=4,834` warm users] and `cold` [`n=422` cold-item users, `n=599` cold items]), testing whether the new M1.3a model/ablation outperforms `Random` (`sanity`), outperforms `MostPop` / content-only on `cold` items (`n=599`), and improves over `MostPop` on warm `NDCG@10`.
- **Independent Unit**: User (`n=4,834` Food.com warm test; `n=422` Food.com cold; `n=90` VN survey users, averaged across seeds per user before paired inference so seeds do not inflate $n$).
- **Controls**:
  - *Negative Control*: `Random` scorer and `ShrunkMean` (item-only popularity/mean without personalization).
  - *Positive Control*: On synthetic/planted structure (`test_recsys_core.py`) and Food.com, `EASE`/`ALS`/`ItemKNN` must exceed `Random` by large margin (`p_holm < 0.001`).
- **Mandatory Scope Disclaimer**: All VN Survey numbers are tagged `SIMULATED=true` (generated from the latent model in `survey.py`); H3a validates ranking/export pipeline behavior and feature-to-ranker calibration, NOT real Vietnamese user preferences.
- **Rival Explanations & Falsifiers**:
  1. *Popularity confounding*: Temporal cutoff favors items trending right before `d_test` (`MostPop` `0.01738` vs `EASE` `0.01773`) -> audited via popularity concentration (top-1% share) and cold-item split (`599` items where `MostPop = 0`).
  2. *Hyperparameter overfitting to single seed/val period*: Evaluated across multiple seeds and reported with 95% user-paired bootstrap CIs; **Falsifier**: `LambdaMART` fails to exceed `ShrunkMean` (`p_holm >= 0.05` or negative diff) on VN survey, or fails cold-item gain over content/random on Food.com.

### H4 — P4a: Ingredient Substitution Hybrid Fusion & `100d` Embeddings
- **Hypothesis**: On the current **`232`-ingredient** KB catalog (`197` curated pairs, `75` held-out test ingredients, `63` held-out test queries), `Hybrid Fusion` combining `Word2Vec` + `Nutrient Cosine` + `PMI` (plus optional `Curated` fallback evaluated separately from unsupervised signals) achieves higher `MRR` and `Agreement@3` than individual unsupervised signals (`Word2Vec`, `Nutrient`, `PMI`, `Random`) and matches or exceeds the `225`-ingredient baseline (`Word2Vec` `MRR=0.5224`).
- **Independent Unit**: Held-out test ingredient (`n=75`) / held-out test query (`n=63`, aggregated over 5 training seeds per query before paired comparison).
- **Controls**:
  - *Negative Control*: `Random` within-food-group baseline (`MRR ≈ 0.304`) and `Word2Vec + PPMI <= 2.0` filter (previously shown harmful).
  - *Positive Control*: `Word2Vec` must exceed `Random` (`p_holm < 0.05`).
- **Rival Explanations & Falsifiers**:
  1. *Curated-table circularity*: `Agreement@3` rewards reproducing human-curated pairs (`197` pairs) rather than true culinary substitutability (`0` human answers in `queries.yaml`). Therefore, `Curated` lookup is reported separately from pure representation methods (`Hybrid` without lookup vs `Hybrid + Curated`), and results are explicitly qualified as *curated-table agreement*, not independent human accuracy.
  2. *Dimension compression loss*: Compressing `200d` -> `100d` normalized vectors for `pgvector` degrades retrieval -> tested via `200d` vs `100d` ablation (`TOST` or paired diff). **Falsifier**: `Hybrid Fusion` fails to improve `MRR` over best single signal (`p_holm >= 0.05`).

### H5 — P4b: Tray Composer Pareto Weights & CP-SAT Solver Latency
- **Hypothesis**:
  - **H5a (Pareto Trade-off on Untouched Held-Out Split & Ranker Integration)**: The prior `SEED=20261018` 75-scenario test comparison (`89.3%` pass rate for `α=64`, `90.7%` for `α=16`, `McNemar p = 0.039` vs provisional `(1.0, 1.0, 0.5)`) is locked as a **prior/post-hoc baseline audit (`analysis_intent = "exploratory"`)** and MUST NOT be re-used as a confirmatory test. Confirmatory `H5a` evaluation is preregistered on a **newly generated, untouched held-out synthetic scenario split** (fresh generation seed distinct from `SEED=20261018`, `n >= 75` fresh feasible scenarios generated in M1.3b) and/or **Ranker-integrated Composer evaluation** (`180` KB dishes, `0` feasibility violations): Pareto-calibrated knee weights selected strictly on the `71` feasible `tuning` scenarios significantly increase urgency saving `U(m)` over `taste-only (0, 0, 0)` and `provisional (1.0, 1.0, 0.5)` while keeping `|ΔE|/E <= 0.15` pass rate above `90%` and achieving lower `taste_loss` than `(64.0, 0.0, 0.5)`.
  - **H5b (CP-SAT Latency)**: OR-Tools CP-SAT cooking schedule optimization meets real-time serving SLA (`p95 <= 500 ms` across realistic 2–3 dish trays and 1–3 burners).
- **Independent Unit**: Fresh untouched synthetic test scenario (`n >= 75` independent M1.3b test scenarios; `n >= 100` benchmark solver runs).
- **Controls**:
  - *Negative Control*: `taste-only (0, 0, 0)` and random feasible tray baseline.
  - *Positive Control*: `(64.0, 0.0, 0.5)` ceiling confirms `U(m)` upper bound (`~0.326`).
- **Rival Explanations & Falsifiers**:
  1. *Taste-proxy artifact*: `favorites` cosine is a synthetic proxy (`0.2` loss cap is arbitrary) -> explicitly flagged as synthetic proxy pending real survey data; Ranker-integrated Composer evaluated separately against `favorites` proxy.
  2. *Mean-hiding tail failure*: Mean `|ΔE|/E` can stay low while tail exceedance `> 15%` rises (observed in the prior `SEED=20261018` exploratory baseline audit) -> require both mean and McNemar exceedance rate reporting on the untouched M1.3b test split. **Falsifier**: On the untouched M1.3b test split (`n >= 75`), tuned knee weights violate `|ΔE|/E <= 0.15` on `>= 10%` of scenarios (pass rate `< 90%`) or fail to increase `U(m)` over `provisional (1.0, 1.0, 0.5)` (`p_holm >= 0.05`), or CP-SAT `p95 > 500 ms`.

---

## 4. Exploratory & Gap Analysis Registry (`analysis_intent = "exploratory"`)

All analyses below are preregistered as **exploratory / diagnostic** and adjusted with **Benjamini–Hochberg FDR (`bh_fdr`)** within each domain:
1. **P1 — 7 Zero-Box VN Classes Root-Cause Analysis**: Quantify label/source scarcity for `thit_lon, thit_ga, su_su, muop, rau_cai, rau_muong, gia_do` across Open Images, LVIS, RPC, and Omorros; inspect `5,327` NC vs `15,311` commercial-ok split impact on class AP; optional `gemini_baseline.py` cost/error comparison (`box_2d`, no confidence scores).
2. **P1 — Preprocessing & Size-Stratified Ablations**: `none` vs `gray-world` vs `CLAHE` vs `combined` and small/medium/large COCO area AP on `yolo_v2` `val`.
3. **P2 — 3-Class vs. 4-Class `kiem_tra` Abstention Mapping**: Evaluate calibrated max-probability / entropy thresholds `(τ)` mapping 3 public classes `{tuoi, dung_som, dung_ngay}` to backend's 4th `kiem_tra` state (`U_CHECK=1.0`), measuring coverage vs. error-rate reduction (risk-coverage / selective prediction curve).
4. **P2 — Cross-Dataset Shortcut Audit**: Per-source breakdown (`AgriFreshNET` 3-class vs `Local Spinach` 2-class), lighting/camera domain gap, and `lot` vs `dedup4` vs `d8dedup4` leakage sensitivity.
5. **P3 — Food.com Cold-Start (`599` items) & User Activity Bins**: Error/NDCG stratification by user history length and item popularity deciles; feature ablation (`LightFM` with vs without 1,882 tags/ingredients); **`180` KB vs `171` published DB recipe** alignment check.
6. **P4 — Substitution Cross-Language & Dimension Ablations**: Coverage gap on the updated 232-ingredient catalog (prior stale baseline: 49/225 VN ingredients absent from Food.com), `200d` vs `100d` embedding fidelity, and per-food-group MRR breakdown.

---

## 5. Blocking, Stratification & Leakage Prevention

- **P1 CV**: `yolo_v2` splits deduplicated via 64-bit pHash (`Hamming <= 4`) strictly in priority `test -> heldout -> val -> train` (`418` near-duplicates dropped). Mendeley Bangladesh split strictly by video (`VID_20250228_135247` = `val`, `VID_20250228_124329` = `test`, 8 other videos = `train`). Confidence threshold `conf` tuned exclusively on `val`, never on `test` or `heldout`.
- **P2 Freshness**: Augmented copies (`8,943`) and label conflicts (`34`) excluded before splitting (`9,182` originals). `StratifiedGroupKFold(n_splits=5)` grouped by `d8dedup4` (`2,366` dihedral-pHash components) and stratified on `dataset/produce/label3`. Temperature/Platt calibration fit strictly out-of-fold (on inner training/validation folds) before scoring held-out fold logits.
- **P3 RecSys**: Food.com global temporal cutoffs (`d_val=2010-06-24`, `d_test=2012-04-01`) eliminate future leakage; `rating == 0` and `rating in {1,2,3}` treated as `seen` (masked from candidate list) but never `positive`. VN Survey uses 5-fold nested CV across `warm`, `item_cold`, and `user_cold` regimes.
- **P4 Substitution & Composer**: `substitution_pairs.yaml` split by ingredient (`32 dev / 75 test`, `SPLIT_SEED=20261018`); `queries.yaml` split (`27 dev / 63 test`); `composer_eval` split (`75 tuning / 75 test`, `SEED=20261018`). All tuning/weight selection runs strictly on `dev`/`tuning`.
- **Seeds & Determinism**: Record exact seeds (`0, 1, 2, ...` / `20261018`), `OPENBLAS_NUM_THREADS=1`, and environment package versions in `ml/runs/research/` JSON metadata.

---

## 6. Statistical Analysis Plan (`tastoria_ml.stats`)

All quantitative inference across P1–P4 uses the shared pure-NumPy/SciPy module `ml/src/tastoria_ml/stats.py` (re-exported via `tastoria_ml.recsys.stats`):

1. **Per-Group Descriptives**: Report `n` (units & clusters), `mean`, `SD`, `median`, `IQR`, missingness, and floor/ceiling counts prior to hypothesis testing.
2. **Paired & Cluster Inference**:
   - Continuous/ordinal unit metrics: `stats.paired_bootstrap(a, b, n_boot>=2000, seed=0, clusters=...)` (cluster resampling for P1 `(video, frame//10)` and P2 `d8dedup4` groups; unit resampling for P3 users and P4 queries/scenarios) + `stats.wilcoxon(a, b)` (when paired differences are approximately symmetric).
   - Binary paired outcomes (e.g., `|ΔE|/E <= 0.15` pass/fail, `Hit@3` per query): exact two-sided `stats.mcnemar(a, b)` reporting `a_only`, `b_only`, exact `p`, paired risk difference + Newcombe 95% CI, and discordant odds ratio (Haldane `+0.5` guard).
3. **Assumption Diagnostics**: Run `stats.check_paired_assumptions(a, b)` on within-unit paired differences (`n`, `n_nonzero`, `frac_zero`, Shapiro/D'Agostino `normality_p`, `skewness`, `excess_kurtosis`, `symmetry_flag`). **Rule**: Never use Shapiro `p > 0.05` as proof of normality or as an automatic switch; choose the estimator from the scientific estimand and dependency structure.
4. **Mandatory Effect Sizes & 95% CIs**: Every `p`-value MUST be accompanied by an effect size and 95% CI:
   - Paired differences: raw `diff` + 95% bootstrap CI, `cohens_dz` (`d_z`, Hedges' `g_z` + 95% CI), or non-parametric `rank_biserial` ($r_{\text{rb}}$) & `hodges_lehmann` + 95% CI.
   - Unpaired contrasts: `cliffs_delta`.
   - Calibration: `calibration_metrics(y_true, probs, n_bins=10)` reporting `ece`, `ece_adaptive`, `brier`, `nll` (`1e-12` clip), and bin reliability arrays alongside 95% group-bootstrap CIs.
   - Reporting convention: exact `p`-values (`p = .034`, `p < .001` only if `< .001`; never `p = .000` or `"ns"`). Non-significance (`p >= .05`) MUST NOT be interpreted as "no effect" or equivalence; equivalence requires explicit TOST (`±0.015` AP margin in H1a).
5. **Multiplicity Control**:
   - **Confirmatory comparisons**: **Holm–Bonferroni** (`stats.holm`) within each prespecified problem family (`α = 0.05` FWER), reporting both raw `p` and `p_holm`.
   - **Exploratory sweeps**: **Benjamini–Hochberg FDR** (`stats.bh_fdr`, `q = 0.05`), reporting both raw `p` and `q_bh`.
6. **Ban on Post-Hoc Observed Power & MDE Sensitivity Plan**:
   - **STRICTLY PROHIBITED**: Calculating post-hoc "observed power" from observed effect sizes and `p`-values.
   - **Required Alternative (Minimum Detectable Effect, MDE at 80% power, two-sided `α = 0.05`)**: Report MDE in standardized `d_z` units ($d_{\text{MDE}} \approx (z_{1-\alpha/2} + z_{0.80}) / \sqrt{n_{\text{eff}}} \approx 2.802 / \sqrt{n_{\text{eff}}}$) alongside 95% CIs:
     - **P1** (`test` `n ≈ 2,000` independent image/block clusters): MDE `d_z ≈ 0.063`.
     - **P2** (`d8dedup4` `n = 2,366` groups): MDE `d_z ≈ 0.058`.
     - **P3 Food.com** (`n = 4,834` warm users): MDE `d_z ≈ 0.040`; (`n = 422` cold users): MDE `d_z ≈ 0.136`.
     - **P3 VN Survey** (`n = 90` synthetic users): MDE `d_z ≈ 0.295` (small-sample limitation; small effects `d_z < 0.30` are underpowered and must be interpreted via 95% CIs).
     - **P4 Substitution** (`n = 63` test queries / `n = 75` test ingredients): MDE `d_z ≈ 0.353` / `0.324`.
     - **P4 Composer** (`n = 75` test scenarios): MDE `d_z ≈ 0.324`.

---

## 7. Reporting Guideline Mapping (`TRIPOD+AI 2024`, `STARD 2015`, `STARD-AI 2025`)

Selected via `select_reporting_guidelines.py` on `153` (recorded verbatim in `docs/reports/hoc-may/reporting_guideline_plan.json`):
- **`tripod-ai-2024`** (`prediction_model --ai`): Governs P1–P4 predictive modeling, data/predictor provenance, OOF validation, discrimination + calibration reporting, subgroup fairness/gaps, and code/model manifest release.
- **`stard-2015` + `stard-ai-2025`** (`diagnostic_accuracy --ai`): Governs P1 detection/counting and P2 freshness accuracy, dataset/model provenance (`5,327` NC split, `ultralytics==8.4.215`, ONNX SHA-256), indeterminate/abstention (`kiem_tra`) handling, and failure/generalizability reporting.

---

## 8. Protocol Deviation Log

> This preregistered protocol MUST NOT be silently edited after M1.2–M1.3 execution begins. Record every amendment or post-hoc departure below.

| Date (UTC) | Affected Section / IDs | Original Plan | Change Applied | Reason | Owner | Target Results Known? | Bias / Interpretation Impact | Original Planned Analysis Still Reported? |
|---|---|---|---|---|---|---|---|---|
| `2026-11-18` | Initial Protocol Lock | — | Protocol `TASTORIA-ML-PREREG-2026-11-18` locked at M1.1 | Preregistration before M1.2–M1.3 experiments | `teamwork_worker_m1_1_1` | No (baseline read-only only) | None | N/A |
| `2026-11-18T19:30Z` | § 3 H1 (P1 Confirmatory Training Budget) | Initial M1.2a pipeline run capped confirmatory `yolo_v2` runs (`v2_yolo26s_640_none_s0`, `v2_yolo26n_640_none_s0`, `v2_yolo11n_640_none_s0`) at 25 epochs (`patience=8`). | Extended confirmatory training from 25-epoch `last.pt` checkpoints to true convergence (`epochs >= 100` ceiling, `patience = 20` on `val mAP50-95`, `v2_yolo26n` via checkpoint resume and `v2_yolo26s`/`v2_yolo11n` via warm-start continuation from `last.pt`). Archived 25-epoch outputs under `snapshots_ep25/` and report both 25-epoch and converged metrics in `p1_study` artifacts. | 25-epoch runs had not converged (`v2_yolo26n` `best_epoch=24`, `val mAP50-95=0.351`, frozen v1 `test mAP50-95=0.260`; `v2_yolo26s` `test=0.269`; `v2_yolo11n` `test=0.261` vs v1 59-epoch `0.278`), and user directed training to true convergence. | `teamwork_worker_m1_2a_5` | Yes (25-epoch `val`/`test`/`heldout` metrics observed prior to extension: `v2_yolo26s` `0.401/0.269/0.319`, `v2_yolo26n` `0.351/0.260/0.268`, `v2_yolo11n` `0.347/0.261/0.272`) | Discloses post-observation epoch extension transparently; `val`/`heldout`/`test` splits remain unchanged and `conf` remains tuned solely on `val`. | Yes (both `snapshots_ep25` 25-epoch results and converged results are reported in `p1_confirmatory_results.json` and `p1_runs_summary.csv`) |
