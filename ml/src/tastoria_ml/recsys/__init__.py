"""Taste ranking experiments for the Machine Learning course (design v2 §6.1).

- `data`     Food.com 5-core, global time split, sparse matrices, item features
- `metrics`  full-catalog top-K ranking metrics (HR, NDCG, Recall) and graded NDCG / per-user AUC
- `stats`    paired bootstrap by user, Holm correction, Wilcoxon / McNemar helpers
- `models`   implicit-feedback rankers (MostPop, ItemKNN, BPR-MF in NumPy, implicit BPR/ALS, LightFM WARP, EASE)
- `foodcom`  experiment driver for Food.com (tuning on validation, seeds, bootstrap, curves, cold start)
- `survey`   explicit-rating pipeline for the Vietnamese survey (nested CV by user), validated on a simulation
"""
