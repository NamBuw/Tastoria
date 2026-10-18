"""PNG figures for docs/reports/hoc-may/ (read only the JSON results; never recompute numbers).

Colours: fixed categorical order of the dataviz reference palette (light surface); a model keeps its colour in
every figure. One y-axis per chart; legends whenever there are ≥ 2 series.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

REPO = Path(__file__).resolve().parents[4]
FIG = REPO / "docs" / "reports" / "hoc-may" / "fig"
PROC = REPO / "data" / "processed"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e6e5e0", "#fcfcfb"
MODEL_ORDER = [
    "MostPop", "ItemKNN", "EASE", "BPR-MF (NumPy)", "BPR (implicit)", "ALS (implicit)", "LightFM WARP",
    "LightFM WARP (chỉ id, không đặc trưng)",
]
COLOR = {m: SERIES[i] for i, m in enumerate(MODEL_ORDER)}

plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10, "lines.linewidth": 2,
    "legend.frameon": False,
})


def _load(rel: str):
    p = PROC / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _save(fig, name: str) -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG / name, dpi=150, bbox_inches="tight")
    plt.close(fig)


def foodcom() -> None:
    test = _load("recsys/test.json")
    if test:
        labels = [m for m in MODEL_ORDER if m in test["models"]]
        mean = [test["models"][m]["ndcg@10"]["mean"] for m in labels]
        sd = [test["models"][m]["ndcg@10"]["sd"] for m in labels]
        fig, ax = plt.subplots(figsize=(7, 3.6))
        y = np.arange(len(labels))[::-1]
        ax.barh(y, mean, xerr=sd, color=[COLOR[m] for m in labels], height=0.6, error_kw={"ecolor": INK2, "capsize": 3})
        ax.set_yticks(y, labels)
        for yy, v in zip(y, mean, strict=True):
            ax.text(v, yy + 0.32, f"{v:.4f}", fontsize=8, color=INK2)
        ax.set_xlabel("NDCG@10 trên tập test (trung bình ± sd qua seed)")
        ax.set_title("Food.com, chia theo thời gian toàn cục, xếp hạng trên toàn bộ món", fontsize=10, loc="left")
        _save(fig, "foodcom_test_ndcg.png")
    tun = _load("recsys/tuning.json")
    if tun:
        rows = [r for r in tun["rows"] if r["model"] == "BPR-MF (NumPy)"]
        if rows:
            dims = sorted({r["params"]["dim"] for r in rows})
            lams = sorted({r["params"]["lam"] for r in rows})
            fig, axes = plt.subplots(1, 2, figsize=(9, 3.4))
            for ax, lr in zip(axes, sorted({r["params"]["lr"] for r in rows}), strict=False):
                M = np.full((len(dims), len(lams)), np.nan)
                for r in rows:
                    if r["params"]["lr"] != lr:
                        continue
                    i, j = dims.index(r["params"]["dim"]), lams.index(r["params"]["lam"])
                    M[i, j] = np.nanmax([M[i, j], r["ndcg@10"]])
                im = ax.imshow(M, cmap="Blues", aspect="auto", origin="lower")
                ax.set_xticks(range(len(lams)), [f"{x:g}" for x in lams])
                ax.set_yticks(range(len(dims)), dims)
                ax.set_xlabel("λ")
                ax.set_ylabel("số chiều d")
                ax.set_title(f"BPR-MF (NumPy), lr = {lr:g}: NDCG@10 validation (epoch tốt nhất)", fontsize=9, loc="left")
                ax.grid(False)
                for i in range(len(dims)):
                    for j in range(len(lams)):
                        if not np.isnan(M[i, j]):
                            ax.text(j, i, f"{M[i, j]:.4f}", ha="center", va="center", fontsize=7,
                                    color="white" if M[i, j] > np.nanmean(M) else INK)
                fig.colorbar(im, ax=ax, shrink=0.8)
            _save(fig, "foodcom_bpr_sensitivity.png")
            fig, ax = plt.subplots(figsize=(6.5, 3.4))
            for k, d in enumerate(dims):
                best_lam = max(lams, key=lambda lam: max((r["ndcg@10"] for r in rows if r["params"]["dim"] == d and r["params"]["lam"] == lam and r["params"]["lr"] == 0.05), default=-1))
                pts = sorted((r["params"]["epochs"], r["ndcg@10"]) for r in rows if r["params"]["dim"] == d and r["params"]["lam"] == best_lam and r["params"]["lr"] == 0.05)
                if pts:
                    ax.plot(*zip(*pts, strict=True), color=SERIES[k], marker="o", markersize=3, label=f"d = {d}, λ = {best_lam:g}")
            mp = next((r["ndcg@10"] for r in tun["rows"] if r["model"] == "MostPop"), None)
            if mp:
                ax.axhline(mp, color=INK2, linestyle="--", linewidth=1)
                ax.text(ax.get_xlim()[1], mp, " MostPop", va="center", fontsize=8, color=INK2)
            ax.set_xlabel("epoch")
            ax.set_ylabel("NDCG@10 validation")
            ax.set_title("BPR-MF (NumPy), lr = 0.05: điểm validation theo epoch", fontsize=10, loc="left")
            ax.legend(fontsize=8)
            _save(fig, "foodcom_bpr_epochs.png")
    curve = _load("recsys/curve.json")
    if curve:
        fig, ax = plt.subplots(figsize=(6.5, 3.6))
        for m in MODEL_ORDER:
            rs = [r for r in curve["rows"] if r["model"] == m]
            if not rs:
                continue
            fr = sorted({r["frac"] for r in rs})
            mu = [np.mean([r["ndcg@10"] for r in rs if r["frac"] == f]) for f in fr]
            ax.plot([100 * f for f in fr], mu, color=COLOR[m], marker="o", markersize=4, label=m)
        ax.set_xticks([25, 50, 75, 100])
        ax.set_xlabel("% người dùng huấn luyện được giữ")
        ax.set_ylabel("NDCG@10 test")
        ax.set_title("Đường cong học (trung bình 3 mẫu người; LightFM 1 mẫu)", fontsize=10, loc="left")
        ax.legend(fontsize=7, ncol=2)
        _save(fig, "foodcom_learning_curve.png")
    err = _load("recsys/errors.json")
    if err:
        fig, ax = plt.subplots(figsize=(7.5, 3.6))
        labels = [m for m in MODEL_ORDER if m in err["models"] and "chỉ id" not in m]
        x = np.arange(len(err["bins"]))
        w = 0.8 / len(labels)
        for k, m in enumerate(labels):
            v = [b["ndcg@10"] for b in err["models"][m]["by_activity"]]
            ax.bar(x + (k - len(labels) / 2 + 0.5) * w, v, width=w * 0.92, color=COLOR[m], label=m)
        ax.set_xticks(x, [f"{b}\n(n={n})" for b, n in zip(err["bins"], err["users_per_bin"], strict=True)], fontsize=8)
        ax.set_xlabel("số tương tác dương của người dùng trước mốc test")
        ax.set_ylabel("NDCG@10 test")
        ax.set_title("Phân tích lỗi theo mức hoạt động của người dùng", fontsize=10, loc="left")
        ax.legend(fontsize=7, ncol=2)
        _save(fig, "foodcom_by_activity.png")


def survey() -> None:
    s = _load("recsys/survey_sim.json")
    if not s:
        return
    scen = ["warm", "item_cold", "user_cold"]
    names = list(s["scenarios"]["warm"]["models"])
    fig, axes = plt.subplots(1, 3, figsize=(11, 3.8), sharey=True)
    for ax, sc in zip(axes, scen, strict=True):
        ms = s["scenarios"][sc]["models"]
        y = np.arange(len(names))[::-1]
        v = [ms[n]["ndcg@5"]["mean"] for n in names]
        e = [ms[n]["ndcg@5"]["sd"] for n in names]
        for k, (yy, vv, ee) in enumerate(zip(y, v, e, strict=True)):  # dots, not bars: the axis does not start at 0
            ax.errorbar(vv, yy, xerr=ee, fmt="o", color=SERIES[k % 8], ecolor=INK2, capsize=2, markersize=6)
        ax.set_yticks(y, names, fontsize=8)
        ax.set_xlim(0.5, 1.0)
        ax.set_title(sc, fontsize=10, loc="left")
        ax.set_xlabel("NDCG@5 có bậc")
    fig.suptitle("MÔ PHỎNG — kiểm đường ống khảo sát, không phải kết quả", fontsize=10, x=0.01, ha="left", color="#d03b3b")
    _save(fig, "survey_sim_ndcg.png")


def composer() -> None:
    s = _load("composer_eval/summary.json")
    if not s:
        return
    tab = s["grid_tuning"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
    for ax, (key, xlabel) in zip(axes, (("taste_loss", "giảm gu trung bình (ŝ', đơn vị [0,1])"), ("kcal_dev", "|ΔE|/E trung bình")), strict=True):
        betas = sorted({t["beta"] for t in tab})
        for k, b in enumerate(betas):
            pts = [t for t in tab if t["beta"] == b]
            ax.scatter([t[key] for t in pts], [t["urgency"] for t in pts], s=14, color=SERIES[k], label=f"β = {b:g}", alpha=0.85)
        front = s["pareto_tuning"]
        fr = sorted(front, key=lambda t: t[key])
        ax.scatter([t[key] for t in fr], [t["urgency"] for t in fr], s=40, facecolors="none", edgecolors=INK, linewidths=1, label="mặt Pareto (3 tiêu chí)")
        if s.get("chosen"):
            c = s["chosen"]
            ax.scatter([c[key]], [c["urgency"]], marker="*", s=180, color="#d03b3b", label=f"chọn: α={c['alpha']:g}, β={c['beta']:g}, γ={c['gamma']:g}", zorder=5)
        lim = 0.2 if key == "taste_loss" else 0.15
        ax.axvline(lim, color=INK2, linestyle="--", linewidth=1)
        ax.set_xlabel(xlabel)
        ax.set_title("ràng buộc " + ("gu ≤ 0,2" if key == "taste_loss" else "|ΔE|/E ≤ 15%"), fontsize=9, loc="left")
    axes[0].set_ylabel("U(m) trung bình (đồ gấp được dùng)")
    axes[1].legend(fontsize=7, loc="lower right")
    fig.suptitle("Lưới (α, β, γ) trên 75 kịch bản chỉnh (tủ lạnh tổng hợp; gu là đại lượng thay thế)", fontsize=10, x=0.01, ha="left")
    _save(fig, "composer_pareto.png")


def substitution() -> None:
    s = _load("substitution/results.json")
    if not s:
        return
    names = [n for n in s["test"]]
    fig, ax = plt.subplots(figsize=(7, 3.2))
    y = np.arange(len(names))[::-1]
    v = [s["test"][n]["agreement@3"]["mean"] if isinstance(s["test"][n]["agreement@3"], dict) else s["test"][n]["agreement@3"] for n in names]
    e = [s["test"][n]["agreement@3"]["sd"] if isinstance(s["test"][n]["agreement@3"], dict) else 0 for n in names]
    ax.barh(y, v, xerr=e, color=[SERIES[i] for i in range(len(names))], height=0.6, error_kw={"ecolor": INK2, "capsize": 3})
    ax.set_yticks(y, names, fontsize=8)
    for yy, val in zip(y, v, strict=True):
        ax.text(val, yy + 0.32, f"{val:.2f}", fontsize=8, color=INK2)
    ax.set_xlabel("đồng thuận@3 với bảng tra (nguyên liệu test)")
    ax.set_title("Thay thế nguyên liệu: đồng thuận với bảng tra do nhóm soạn — KHÔNG phải độ chính xác", fontsize=9, loc="left")
    _save(fig, "substitution_agreement.png")


def main() -> int:
    foodcom()
    survey()
    composer()
    substitution()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
