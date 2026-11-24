"""CP-SAT cooking schedule latency & scalability benchmark (PREREG TASTORIA-ML-PREREG-2026-11-18, H5b).

Measures:
  1. Stratified `schedule.solve()` micro-benchmarks (`n >= 360` runs across dishes in {1,2,3,4} x burners in {1,2,3})
     plus a worst-case / relaxed double-solve stress slice (`n >= 60` runs: 7-8 step dishes + xao at burners=1,
     and 4-dish longest-step combinations).
  2. End-to-end `composer_eval.run.solve()` latency per confirmatory scenario (un-cached CP-SAT verification loop
     over burners in {1,2,3} matching `service.create_plan`).

Outputs in `ml/runs/research/p4_substitution_composer/`:
  - `cpsat_latency.json`
  - `cpsat_latency.csv`

Run: uv run --frozen --package tastoria-ml python -m tastoria_ml.composer_eval.cpsat_bench
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import time
from pathlib import Path

import numpy as np
import ortools

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")

from tastoria.modules.meal import composer as cmp  # noqa: E402
from tastoria.modules.meal import schedule as sch  # noqa: E402
from tastoria.modules.meal import service as msvc  # noqa: E402

from tastoria_ml.composer_eval import run as run_mod  # noqa: E402
from tastoria_ml.composer_eval import scenarios as scen_mod  # noqa: E402
from tastoria_ml.recsys import kb_catalog  # noqa: E402
from tastoria_ml.recsys.kb_catalog import Catalog  # noqa: E402

REPO = kb_catalog.REPO
RESEARCH_OUT = REPO / "ml" / "runs" / "research" / "p4_substitution_composer"
PROTOCOL_ID = "TASTORIA-ML-PREREG-2026-11-18"
SLA_TARGET_MS = 500.0
E2E_SLA_TARGET_MS = 1000.0


def _sched_of_recipe(rv) -> sch.Dish:
    return msvc._option(rv, 0.5, 2).sched


def summarize_latencies(rows: list[dict], *, sla_ms: float = SLA_TARGET_MS) -> dict:
    if not rows:
        return {"n": 0}
    lat = np.asarray([float(r["latency_ms"]) for r in rows], dtype=float)
    statuses: dict[str, int] = {}
    for r in rows:
        st_name = str(r["status"])
        statuses[st_name] = statuses.get(st_name, 0) + 1
    viols = int(sum(int(r.get("violations", 0)) for r in rows))
    p50, p95, p99 = np.percentile(lat, [50, 95, 99])
    opt_rel = sum(statuses.get(k, 0) for k in ("optimal", "feasible", "relaxed", "empty"))
    return {
        "n": int(len(rows)),
        "min_ms": float(lat.min()),
        "p50_ms": float(p50),
        "p95_ms": float(p95),
        "p99_ms": float(p99),
        "max_ms": float(lat.max()),
        "mean_ms": float(lat.mean()),
        "sd_ms": float(lat.std(ddof=1)) if len(lat) > 1 else 0.0,
        "violations": viols,
        "status_counts": statuses,
        "optimal_plus_relaxed_rate": float(opt_rel / len(rows)),
        "sla_threshold_ms": float(sla_ms),
        "sla_pass": bool(p95 <= sla_ms and viols == 0),
    }


def _sample_tray_slugs(by_slot: dict[str, list[str]], all_slugs: list[str], n_dishes: int, rng: np.random.Generator) -> list[str]:
    if n_dishes == 1:
        return [str(rng.choice(all_slugs))]
    if n_dishes == 2:
        second = "rau" if rng.random() < 0.5 else "canh"
        return [str(rng.choice(by_slot["man"])), str(rng.choice(by_slot[second]))]
    if n_dishes == 3:
        return [str(rng.choice(by_slot["man"])), str(rng.choice(by_slot["rau"])), str(rng.choice(by_slot["canh"]))]
    base = [str(rng.choice(by_slot["man"])), str(rng.choice(by_slot["rau"])), str(rng.choice(by_slot["canh"]))]
    pool = [s for s in all_slugs if s not in base]
    extra = str(rng.choice(pool))
    return base + [extra]


def _bench_one(slugs: list[str], views: run_mod.Views, burners: int, regime: str) -> dict:
    dishes = [_sched_of_recipe(views.recipes[s]) for s in slugs]
    t0 = time.perf_counter()
    sched = sch.solve(dishes, burners)
    dt_ms = (time.perf_counter() - t0) * 1000.0
    errs = sch.violations(dishes, burners, sched)
    total_steps = sum(len(d.steps) for d in dishes)
    active_steps = sum(1 for d in dishes for s in d.steps if s.active)
    burner_steps = sum(1 for d in dishes for s in d.steps if s.burner)
    return {
        "regime": regime,
        "n_dishes": len(dishes),
        "burners": int(burners),
        "total_steps": int(total_steps),
        "active_steps": int(active_steps),
        "burner_steps": int(burner_steps),
        "has_xao": bool(any(d.stir_fry for d in dishes)),
        "makespan": int(sched.makespan),
        "status": str(sched.status),
        "latency_ms": float(dt_ms),
        "violations": int(len(errs)),
        "dish_slugs": "|".join(slugs),
    }


def run_unit_benchmarks(
    cat: Catalog,
    views: run_mod.Views | None = None,
    *,
    seed: int = 20261118,
    runs_per_cell: int = 30,
    stress_runs: int = 60,
) -> tuple[list[dict], dict]:
    views = views or run_mod.build_views(cat)
    rng = np.random.default_rng(seed)

    by_slot: dict[str, list[str]] = {"man": [], "rau": [], "canh": []}
    for r in cat.recipes:
        by_slot[r.slot].append(r.slug)
    for k in by_slot:
        by_slot[k].sort()
    all_slugs = sorted(views.recipes)

    rows: list[dict] = []
    # 1. Stratified grid: dishes in {1, 2, 3, 4} x burners in {1, 2, 3}
    for n_dishes in (1, 2, 3, 4):
        for burners in (1, 2, 3):
            for _ in range(runs_per_cell):
                slugs = _sample_tray_slugs(by_slot, all_slugs, n_dishes, rng)
                rows.append(_bench_one(slugs, views, burners, "stratified"))

    # 2. Worst-case / relaxed double-solve stress slice
    step_counts = {s: len(views.recipes[s].steps) for s in all_slugs}
    long_non_xao = sorted(
        [s for s in all_slugs if views.recipes[s].method_code != "xao" and step_counts[s] >= 6],
        key=lambda s: (-step_counts[s], s),
    )
    if len(long_non_xao) < 2:
        long_non_xao = sorted([s for s in all_slugs if views.recipes[s].method_code != "xao"], key=lambda s: (-step_counts[s], s))
    long_xao = sorted(
        [s for s in all_slugs if views.recipes[s].method_code == "xao"],
        key=lambda s: (-step_counts[s], s),
    )
    longest_all = sorted(all_slugs, key=lambda s: (-step_counts[s], s))[:24]

    n_relaxed_half = stress_runs // 2
    n_4dish_half = stress_runs - n_relaxed_half
    for _ in range(n_relaxed_half):
        non_x = rng.choice(long_non_xao[:20], size=2, replace=False).tolist()
        xao_one = str(rng.choice(long_xao[:15]))
        rows.append(_bench_one([non_x[0], non_x[1], xao_one], views, 1, "stress_relaxed_b1"))

    for i in range(n_4dish_half):
        burners = (1, 2, 3)[i % 3]
        pick4 = rng.choice(longest_all, size=4, replace=False).tolist()
        rows.append(_bench_one(pick4, views, burners, "stress_4dish_long"))

    strat = [r for r in rows if r["regime"] == "stratified"]
    prod_1_3 = [r for r in strat if r["n_dishes"] in (1, 2, 3)]
    prod_2_3 = [r for r in strat if r["n_dishes"] in (2, 3)]
    stress_4_strat = [r for r in strat if r["n_dishes"] == 4]
    stress_wc = [r for r in rows if r["regime"] != "stratified"]

    by_cell = {}
    for d in (1, 2, 3, 4):
        for b in (1, 2, 3):
            cell_rows = [r for r in strat if r["n_dishes"] == d and r["burners"] == b]
            by_cell[f"d{d}_b{b}"] = summarize_latencies(cell_rows)

    summary = {
        "overall_all_runs": summarize_latencies(rows),
        "stratified_all": summarize_latencies(strat),
        "production_1_to_3_dishes": summarize_latencies(prod_1_3),
        "production_2_to_3_dishes": summarize_latencies(prod_2_3),
        "stress_4_dishes_stratified": summarize_latencies(stress_4_strat),
        "stress_worst_case": summarize_latencies(stress_wc),
        "stress_relaxed_b1": summarize_latencies([r for r in rows if r["regime"] == "stress_relaxed_b1"]),
        "stress_4dish_long": summarize_latencies([r for r in rows if r["regime"] == "stress_4dish_long"]),
        "by_cell": by_cell,
    }
    return rows, summary


def run_e2e_benchmarks(
    cat: Catalog,
    scenarios_data: dict,
    views: run_mod.Views | None = None,
    *,
    alpha: float = 16.0,
    beta: float = 2.0,
    gamma: float = 1.0,
    burners_list: tuple[int, ...] = (1, 2, 3),
    max_scenarios: int | None = None,
) -> dict:
    """Measure un-cached `create_plan`-equivalent `solve()` wall-clock latency & CP-SAT call counts."""
    views = views or run_mod.build_views(cat)
    scens = scenarios_data["scenarios"]
    if max_scenarios is not None:
        scens = scens[:max_scenarios]

    orig_solve = sch.solve
    e2e_rows: list[dict] = []
    by_burners: dict[str, list[dict]] = {str(b): [] for b in burners_list}

    for burners in burners_list:
        for s in scens:
            s_b = {**s, "burners": int(burners)}
            p = run_mod.prepare(s_b, views, cat.rice_kcal)
            run_mod._SCHED_CACHE.clear()  # cold cache per HTTP request simulation
            call_count = 0
            checked_calls: list[tuple] = []

            def _counting_solve(dishes, b, *, time_limit_s=sch.TIME_LIMIT_S):
                nonlocal call_count
                call_count += 1
                res = orig_solve(dishes, b, time_limit_s=time_limit_s)
                checked_calls.append((dishes, b, res))
                return res

            sch.solve = _counting_solve
            try:
                t0 = time.perf_counter()
                tray, two_dish = run_mod.solve(p, alpha, beta, gamma)
                dt_ms = (time.perf_counter() - t0) * 1000.0
            finally:
                sch.solve = orig_solve

            viol_count = sum(len(sch.violations(d_arg, b_arg, r_arg)) for d_arg, b_arg, r_arg in checked_calls)

            if tray is None:
                continue
            row = {
                "id": s["id"],
                "burners": int(burners),
                "persons": int(s["persons"]),
                "two_dish": bool(two_dish or len(tray.dishes) == 2),
                "cpsat_calls": int(call_count),
                "latency_ms": float(dt_ms),
                "status": "feasible" if viol_count == 0 else "violated",
                "violations": int(viol_count),
            }
            e2e_rows.append(row)
            by_burners[str(burners)].append(row)

    calls = np.asarray([r["cpsat_calls"] for r in e2e_rows], dtype=float) if e2e_rows else np.array([0.0])
    overall = summarize_latencies(e2e_rows, sla_ms=E2E_SLA_TARGET_MS)
    overall["mean_cpsat_calls"] = float(calls.mean())
    overall["p95_cpsat_calls"] = float(np.percentile(calls, 95))
    overall["max_cpsat_calls"] = int(calls.max())
    overall["sla_pass_500ms"] = bool(overall.get("p95_ms", 0.0) <= SLA_TARGET_MS and overall.get("violations", 0) == 0)
    return {
        "weights": {"alpha": alpha, "beta": beta, "gamma": gamma},
        "overall": overall,
        "by_burners": {b: summarize_latencies(rs, sla_ms=E2E_SLA_TARGET_MS) for b, rs in by_burners.items()},
        "n_requests": len(e2e_rows),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="CP-SAT cooking schedule latency & H5b benchmark")
    ap.add_argument("--seed", type=int, default=20261118)
    ap.add_argument("--runs-per-cell", type=int, default=30)
    ap.add_argument("--stress-runs", type=int, default=60)
    ap.add_argument("--alpha", type=float, default=16.0)
    ap.add_argument("--beta", type=float, default=2.0)
    ap.add_argument("--gamma", type=float, default=1.0)
    ap.add_argument("--out-research", type=Path, default=RESEARCH_OUT)
    args = ap.parse_args(argv)

    args.out_research.mkdir(parents=True, exist_ok=True)
    cat = kb_catalog.load()
    views = run_mod.build_views(cat)

    # Ensure confirmatory scenarios exist
    conf_path = scen_mod.OUT / "scenarios_confirmatory.json"
    if conf_path.exists():
        conf_data = json.loads(conf_path.read_text(encoding="utf-8"))
    else:
        conf_data = scen_mod.write_confirmatory(cat)

    # Warmup single CP-SAT call (exclude one-time OR-Tools import/init overhead, and note in report)
    sample_dish = _sched_of_recipe(views.recipes[sorted(views.recipes)[0]])
    _ = sch.solve([sample_dish], 2)

    rows, unit_summary = run_unit_benchmarks(
        cat,
        views,
        seed=args.seed,
        runs_per_cell=args.runs_per_cell,
        stress_runs=args.stress_runs,
    )
    e2e_summary = run_e2e_benchmarks(
        cat,
        conf_data,
        views,
        alpha=args.alpha,
        beta=args.beta,
        gamma=args.gamma,
    )

    h5b_passed = bool(
        unit_summary["production_1_to_3_dishes"]["sla_pass"]
        and unit_summary["overall_all_runs"]["violations"] == 0
        and e2e_summary["overall"]["violations"] == 0
    )

    payload = {
        "protocol_id": PROTOCOL_ID,
        "hypothesis": "H5b_cpsat_latency",
        "analysis_intent": "confirmatory",
        "env": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "ortools": ortools.__version__,
            "num_workers": 1,
            "random_seed": 0,
            "time_limit_s": sch.TIME_LIMIT_S,
            "serve_window_min": sch.SERVE_WINDOW_MIN,
        },
        "sla_target_ms": SLA_TARGET_MS,
        "e2e_sla_target_ms": E2E_SLA_TARGET_MS,
        "h5b_passed": h5b_passed,
        "unit_benchmarks": unit_summary,
        "e2e_solve_benchmarks": e2e_summary,
    }
    (args.out_research / "cpsat_latency.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with open(args.out_research / "cpsat_latency.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "regime", "n_dishes", "burners", "total_steps", "active_steps",
                "burner_steps", "has_xao", "makespan", "status", "latency_ms",
                "violations", "dish_slugs",
            ],
        )
        w.writeheader()
        w.writerows(rows)

    # Refresh serving.json cpsat_sla (if serving.json exists) and research manifest.json
    serving_path = run_mod.DEPLOY_COMPOSER / "serving.json"
    if serving_path.exists():
        import hashlib

        sv = json.loads(serving_path.read_text(encoding="utf-8"))
        u_prod = unit_summary["production_1_to_3_dishes"]
        sv["cpsat_sla"] = {
            "n_unit_runs": unit_summary["overall_all_runs"]["n"],
            "realistic_1_3_dish_n": u_prod["n"],
            "realistic_1_3_dish_p50_ms": u_prod["p50_ms"],
            "realistic_1_3_dish_p95_ms": u_prod["p95_ms"],
            "realistic_1_3_dish_p99_ms": u_prod["p99_ms"],
            "e2e_p95_ms": e2e_summary["overall"]["p95_ms"],
            "sla_threshold_ms": SLA_TARGET_MS,
            "h5b_passed": h5b_passed,
            "optimal_plus_relaxed_rate": u_prod["optimal_plus_relaxed_rate"],
            "violations": unit_summary["overall_all_runs"]["violations"] + e2e_summary["overall"]["violations"],
        }
        sv.pop("artifact_sha256", None)
        canon = json.dumps(sv, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        sv["artifact_sha256"] = hashlib.sha256(canon).hexdigest()
        serving_path.write_text(json.dumps(sv, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    run_mod.write_research_manifest(args.out_research)

    print(
        json.dumps(
            {
                "h5b_passed": h5b_passed,
                "unit_1_to_3_p50_ms": unit_summary["production_1_to_3_dishes"]["p50_ms"],
                "unit_1_to_3_p95_ms": unit_summary["production_1_to_3_dishes"]["p95_ms"],
                "unit_all_p95_ms": unit_summary["overall_all_runs"]["p95_ms"],
                "stress_relaxed_b1_p95_ms": unit_summary["stress_relaxed_b1"]["p95_ms"],
                "e2e_p95_ms": e2e_summary["overall"]["p95_ms"],
                "violations": unit_summary["overall_all_runs"]["violations"] + e2e_summary["overall"]["violations"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
