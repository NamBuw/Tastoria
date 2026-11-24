"""Backward-compatible re-export shim for ``tastoria_ml.stats``."""

from __future__ import annotations

from tastoria_ml.stats import (
    bh_fdr,
    calibration_metrics,
    check_paired_assumptions,
    cliffs_delta,
    cohens_dz,
    holm,
    mcnemar,
    mean_ci,
    paired_bootstrap,
    wilcoxon,
)

__all__ = [
    "bh_fdr",
    "calibration_metrics",
    "check_paired_assumptions",
    "cliffs_delta",
    "cohens_dz",
    "holm",
    "mcnemar",
    "mean_ci",
    "paired_bootstrap",
    "wilcoxon",
]
