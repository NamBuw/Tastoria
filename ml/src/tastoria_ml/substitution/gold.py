"""Scorer for the human gold set of data/kb/substitution_eval (README there): runs once the answer files exist.

Files read: queries.yaml, answers_<A>.yaml, answers_<B>.yaml (independent annotators), answers_adjudicated.yaml.
Method rankings: data/processed/substitution/eval_rankings.json (written by `substitution.run`), i.e. for every
query and method the ranked candidate list the method returns (empty = the method abstains).

Reported per split (dev / test) and method:
  Hit@1, Hit@3 — share of queries with a non-empty `acceptable` set whose top-k contains an acceptable answer
  MRR          — mean 1 / rank of the first acceptable answer (0 when none in the list)
  coverage     — share of all queries for which the method returns ≥ 1 candidate
  refusals     — queries marked `none: true`: how many the method leaves empty (correct refusal), kept apart
Pairwise on the same queries: McNemar on Hit@3, paired bootstrap on reciprocal rank; Holm over the pairs.
Annotator agreement before adjudication: mean Jaccard of the acceptable sets, agreement on `none`, top-1 match.

Run: uv run --package tastoria-ml python -m tastoria_ml.substitution.gold [--split test]
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

import numpy as np
import yaml

from tastoria_ml.recsys import stats
from tastoria_ml.recsys.kb_catalog import REPO

EVAL_DIR = REPO / "data" / "kb" / "substitution_eval"
RANKINGS = REPO / "data" / "processed" / "substitution" / "eval_rankings.json"


def load_answers(path: Path) -> dict[str, dict]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    out = {}
    for a in raw.get("answers") or []:
        acc = list(a.get("acceptable") or [])
        none = bool(a.get("none", False))
        if none and acc:
            raise ValueError(f"{path}: {a['id']} has both none: true and acceptable answers")
        out[a["id"]] = {"acceptable": acc, "none": none}
    return out


def load_queries(path: Path = EVAL_DIR / "queries.yaml") -> list[dict]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))["queries"]


def annotator_agreement(a: dict[str, dict], b: dict[str, dict]) -> dict[str, float]:
    ids = sorted(set(a) & set(b))
    jac, none_same, top1 = [], [], []
    for q in ids:
        x, y = set(a[q]["acceptable"]), set(b[q]["acceptable"])
        none_same.append(a[q]["none"] == b[q]["none"])
        if x or y:
            jac.append(len(x & y) / len(x | y))
        if a[q]["acceptable"] and b[q]["acceptable"]:
            top1.append(a[q]["acceptable"][0] == b[q]["acceptable"][0])
    return {
        "n_common": len(ids),
        "mean_jaccard": float(np.mean(jac)) if jac else float("nan"),
        "none_agreement": float(np.mean(none_same)) if none_same else float("nan"),
        "top1_match": float(np.mean(top1)) if top1 else float("nan"),
    }


def per_query(ranked: list[str], acceptable: list[str]) -> dict[str, float]:
    acc = set(acceptable)
    rr = 0.0
    for r, c in enumerate(ranked, 1):
        if c in acc:
            rr = 1.0 / r
            break
    return {"hit1": float(bool(set(ranked[:1]) & acc)), "hit3": float(bool(set(ranked[:3]) & acc)), "rr": rr}


def evaluate(rankings: dict[str, dict[str, list[str]]], gold: dict[str, dict], queries: list[dict], split: str | None) -> dict:
    qs = [q for q in queries if split is None or q["split"] == split]
    methods = sorted({m for r in rankings.values() for m in r})
    out = {"split": split or "all", "n_queries": len(qs), "methods": {}, "pairs": {}}
    answered = [q for q in qs if q["id"] in gold and gold[q["id"]]["acceptable"]]
    refusals = [q for q in qs if q["id"] in gold and gold[q["id"]]["none"]]
    out["n_with_answers"] = len(answered)
    out["n_none"] = len(refusals)
    per: dict[str, dict[str, np.ndarray]] = {}
    for m in methods:
        rows = [per_query(rankings[q["id"]].get(m, []), gold[q["id"]]["acceptable"]) for q in answered]
        per[m] = {k: np.array([r[k] for r in rows]) for k in ("hit1", "hit3", "rr")}
        cov = np.mean([bool(rankings[q["id"]].get(m)) for q in qs]) if qs else float("nan")
        out["methods"][m] = {
            "hit@1": float(per[m]["hit1"].mean()) if rows else float("nan"),
            "hit@3": float(per[m]["hit3"].mean()) if rows else float("nan"),
            "mrr": float(per[m]["rr"].mean()) if rows else float("nan"),
            "hit@3_ci": list(stats.mean_ci(per[m]["hit3"])[1:]) if len(rows) > 1 else None,
            "coverage": float(cov),
            "correct_refusals": int(sum(not rankings[q["id"]].get(m) for q in refusals)),
        }
    pairs = list(itertools.combinations(methods, 2))
    raw_p = []
    for a, b in pairs:
        mc = stats.mcnemar(per[a]["hit3"].astype(bool), per[b]["hit3"].astype(bool)) if len(answered) else {"p": float("nan")}
        bs = stats.paired_bootstrap(per[a]["rr"], per[b]["rr"], n_boot=5000, seed=5) if len(answered) else {"p": float("nan")}
        out["pairs"][f"{a} vs {b}"] = {"mcnemar_hit@3": mc, "bootstrap_rr": bs}
        raw_p.append(mc["p"])
    if raw_p and not any(np.isnan(raw_p)):
        for (a, b), adj in zip(pairs, stats.holm(raw_p), strict=True):
            out["pairs"][f"{a} vs {b}"]["mcnemar_p_holm"] = float(adj)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--split", choices=["dev", "test", "all"], default="dev")
    ap.add_argument("--eval-dir", type=Path, default=EVAL_DIR)
    ap.add_argument("--rankings", type=Path, default=RANKINGS)
    a = ap.parse_args(argv)
    adj = a.eval_dir / "answers_adjudicated.yaml"
    if not adj.exists():
        print(f"chưa có đáp án: {adj} không tồn tại — xem {a.eval_dir / 'README.md'}", file=sys.stderr)
        return 2
    queries = load_queries(a.eval_dir / "queries.yaml")
    gold = load_answers(adj)
    raw = [p for p in sorted(a.eval_dir.glob("answers_*.yaml")) if p.name != "answers_adjudicated.yaml"]
    agree = annotator_agreement(load_answers(raw[0]), load_answers(raw[1])) if len(raw) >= 2 else None
    rankings = json.loads(a.rankings.read_text(encoding="utf-8"))["rankings"]
    res = evaluate(rankings, gold, queries, None if a.split == "all" else a.split)
    res["annotator_agreement"] = agree
    out = a.rankings.parent / f"gold_{res['split']}.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float) + "\n", encoding="utf-8")
    print(json.dumps({m: {k: v[k] for k in ("hit@1", "hit@3", "mrr", "coverage")} for m, v in res["methods"].items()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
