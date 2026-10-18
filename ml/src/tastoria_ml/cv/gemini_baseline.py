"""Gemini zero-shot baseline for ingredient detection and counting (thiết kế v2 §7). NOT RUN YET.

Nothing in this module calls the network unless ``run`` is invoked with a real client (needs a paid
Gemini API key in ``GEMINI_API_KEY`` and ``pip install google-genai`` in the training env). Everything
else (prompt, schema, parsing, matching, metrics, cost) is pure Python / numpy and unit tested with
mocked responses.

Protocol (fixed before the first call):
  * model ID pinned (``--model``, e.g. ``gemini-2.5-flash``) and the run date stored with every response;
  * closed vocabulary: the 22 class ids of data/kb/vision_classes.yaml, as a JSON-schema enum, with the
    Vietnamese / English names and the instance definition in the prompt;
  * temperature 0, fixed ``media_resolution`` (default MEDIA_RESOLUTION_HIGH), JSON response schema;
  * boxes as Gemini's ``box_2d`` = [ymin, xmin, ymax, xmax] normalised to 0..1000;
  * prompt variant chosen on val (``--split val --prompt v1|v2``), then frozen; 3 runs on test;
  * only images whose owners agreed (for the group's fridge photos); the public test set may be used.

Metrics per run (``evaluate``):
  * box P / R / F1 at IoU 0.5 and 0.3 — one-to-one Hungarian matching per (image, class) on IoU
    (Gemini gives no scores, so there is no AP); micro over all classes plus per class;
  * list level: per image, set of predicted class ids vs set of GT class ids -> micro P / R / F1;
  * counting on countable classes with ``counting.count_metrics`` (MAE, relative MAE, exact, ±1);
  * latency p50 / p95 per request (wall clock) and cost from ``usage_metadata`` token counts times the
    prices passed on the command line (USD per 1M tokens; check the current price list before running).
  Classes Gemini returns that are outside the evaluated dataset's classes are counted separately
  (``out_of_dataset``): on public data they cannot be scored, because the GT does not contain them.

Run (after a key is available):
  export GEMINI_API_KEY=...            # paid tier; free tier may use the data for training
  PY=ml/runs/venv-cv/bin/python; export PYTHONPATH=ml/src
  $PY -m tastoria_ml.cv.gemini_baseline run --split val --prompt v1 --model gemini-2.5-flash --limit 200
  $PY -m tastoria_ml.cv.gemini_baseline run --split val --prompt v2 --model gemini-2.5-flash --limit 200
  $PY -m tastoria_ml.cv.gemini_baseline eval --split val --prompt v1 ...   # pick the better prompt on val
  for r in 0 1 2; do $PY -m tastoria_ml.cv.gemini_baseline run --split test --prompt v1 --repeat $r \\
      --model gemini-2.5-flash; done
  $PY -m tastoria_ml.cv.gemini_baseline eval --split test --prompt v1 --model gemini-2.5-flash \\
      --price-in 0.30 --price-out 2.50
Raw responses are appended to ml/runs/gemini/<model>__<split>__<prompt>__r<repeat>.jsonl (resumable);
summaries go to data/processed/cv/gemini/.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import numpy as np

from tastoria_ml.cv.classes import REPO, load_classes
from tastoria_ml.cv.counting import count_metrics

RAW = REPO / "ml" / "runs" / "gemini"
OUT = REPO / "data" / "processed" / "cv" / "gemini"
YOLO_DIR = REPO / "data" / "processed" / "cv" / "yolo"

INSTANCE_TEXT = {
    "item": "one box per single item (one egg, one tomato, one cabbage head)",
    "group": "one box around the whole bunch / bag / heap",
    "package": "one box per package or tray",
}


# ------------------------------------------------------------------ prompt + schema


def class_table() -> list[dict]:
    return [{"id": c.id, "vi": c.name_vi, "en": c.name_en, "instance": c.instance_def, "countable": c.countable}
            for c in load_classes()]


def build_prompt(classes: list[dict], variant: str = "v1") -> str:
    lines = [f"- {c['id']}: {c['vi']} / {c['en']} — {INSTANCE_TEXT.get(c['instance'], c['instance'])}"
             for c in classes]
    if variant == "v1":
        head = ("Detect the food ingredients in this photo. Use ONLY these labels:\n")
        tail = ("\nReturn a JSON list. Each element: {\"label\": <one id above>, \"box_2d\": [ymin, xmin, ymax, "
                "xmax]} with coordinates normalised to 0-1000. Ignore anything that is not in the list. "
                "If nothing from the list is visible return [].")
    elif variant == "v2":
        head = ("You are labelling ingredients inside a refrigerator / kitchen photo for a cooking app. "
                "Find every visible instance of the following classes (closed vocabulary):\n")
        tail = ("\nRules: follow the instance definition of each class; do not guess hidden objects; do not "
                "label drawings, toys or printed pictures. Output JSON only: a list of {\"label\", \"box_2d\"} "
                "where box_2d = [ymin, xmin, ymax, xmax] in 0-1000.")
    else:
        raise ValueError(variant)
    return head + "\n".join(lines) + tail


def response_schema(class_ids: list[str]) -> dict:
    return {
        "type": "ARRAY",
        "items": {
            "type": "OBJECT",
            "properties": {
                "label": {"type": "STRING", "enum": list(class_ids)},
                "box_2d": {"type": "ARRAY", "items": {"type": "INTEGER"}, "minItems": 4, "maxItems": 4},
            },
            "required": ["label", "box_2d"],
        },
    }


# ------------------------------------------------------------------ parsing


def parse_response(text: str, class_ids: set[str], width: int, height: int) -> tuple[list[dict], dict]:
    """Gemini text -> [{"label", "xyxy" (pixels)}], plus a report of what was dropped and why."""
    rep = {"json_error": False, "unknown_label": 0, "bad_box": 0, "n_raw": 0}
    t = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        data = json.loads(t) if t else []
    except json.JSONDecodeError:
        mm = re.search(r"\[.*\]", t, re.S)  # salvage the outermost list
        try:
            if mm is None:
                raise json.JSONDecodeError("no JSON list", t, 0)
            data = json.loads(mm.group(0))
        except json.JSONDecodeError:
            rep["json_error"] = True
            return [], rep
    if isinstance(data, dict):
        data = next((v for v in data.values() if isinstance(v, list)), [])
    out = []
    for o in data if isinstance(data, list) else []:
        rep["n_raw"] += 1
        if not isinstance(o, dict):
            rep["bad_box"] += 1
            continue
        lab = str(o.get("label", "")).strip()
        if lab not in class_ids:
            rep["unknown_label"] += 1
            continue
        b = o.get("box_2d")
        if not (isinstance(b, (list, tuple)) and len(b) == 4):
            rep["bad_box"] += 1
            continue
        try:
            y0, x0, y1, x1 = (float(v) for v in b)
        except (TypeError, ValueError):
            rep["bad_box"] += 1
            continue
        y0, y1 = sorted((min(max(y0, 0), 1000), min(max(y1, 0), 1000)))
        x0, x1 = sorted((min(max(x0, 0), 1000), min(max(x1, 0), 1000)))
        if x1 - x0 < 1 or y1 - y0 < 1:
            rep["bad_box"] += 1
            continue
        out.append({"label": lab, "xyxy": [x0 / 1000 * width, y0 / 1000 * height, x1 / 1000 * width,
                                           y1 / 1000 * height]})
    return out, rep


# ------------------------------------------------------------------ matching + metrics


def _iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    from tastoria_ml.cv.det_eval import iou_matrix

    return iou_matrix(a, b)


def match_hungarian(pred: np.ndarray, gt: np.ndarray, thr: float) -> int:
    """Number of one-to-one matches with IoU ≥ thr maximising total IoU (scipy if present, else greedy)."""
    if len(pred) == 0 or len(gt) == 0:
        return 0
    iou = _iou(pred, gt)
    try:
        from scipy.optimize import linear_sum_assignment

        r, c = linear_sum_assignment(-np.where(iou >= thr, iou, 0.0))
        return int((iou[r, c] >= thr).sum())
    except ImportError:  # greedy fallback
        n, used = 0, set()
        for i, j in sorted(((i, j) for i in range(iou.shape[0]) for j in range(iou.shape[1])),
                           key=lambda ij: -iou[ij]):
            if iou[i, j] < thr:
                break
            if i in used or ("g", j) in used:
                continue
            used |= {i, ("g", j)}
            n += 1
        return n


def prf(tp: int, n_pred: int, n_gt: int) -> dict:
    p = tp / n_pred if n_pred else None
    r = tp / n_gt if n_gt else None
    if p is None or r is None:
        f = None
    else:
        f = 2 * p * r / (p + r) if p + r > 0 else 0.0
    return {"tp": tp, "n_pred": n_pred, "n_gt": n_gt, "precision": p, "recall": r, "f1": f}


def evaluate_records(records: list[dict], gt: dict[str, list[dict]], eval_classes: list[str],
                     countable: set[str], price_in: float = 0.0, price_out: float = 0.0) -> dict:
    """records: [{"file", "objects": parsed, "latency_s", "usage": {"prompt_tokens", "output_tokens"}}];
    gt: file -> [{"label", "xyxy"}]."""
    ev = set(eval_classes)
    res: dict = {"n_images": len(records)}
    for thr in (0.5, 0.3):
        tot = {"tp": 0, "np": 0, "ng": 0}
        per = {c: {"tp": 0, "np": 0, "ng": 0} for c in eval_classes}
        for r in records:
            g = gt.get(r["file"], [])
            for c in eval_classes:
                pb = np.array([o["xyxy"] for o in r["objects"] if o["label"] == c]).reshape(-1, 4)
                gb = np.array([o["xyxy"] for o in g if o["label"] == c]).reshape(-1, 4)
                tp = match_hungarian(pb, gb, thr)
                for d in (tot, per[c]):
                    d["tp"] += tp
                    d["np"] += len(pb)
                    d["ng"] += len(gb)
        res[f"box_iou{thr}"] = prf(tot["tp"], tot["np"], tot["ng"])
        res[f"box_iou{thr}_per_class"] = {c: prf(v["tp"], v["np"], v["ng"]) for c, v in per.items()}
    tp = n_p = n_g = 0
    for r in records:
        ps = {o["label"] for o in r["objects"]} & ev
        gs = {o["label"] for o in gt.get(r["file"], [])} & ev
        tp, n_p, n_g = tp + len(ps & gs), n_p + len(ps), n_g + len(gs)
    res["list_level"] = prf(tp, n_p, n_g)
    cc = [c for c in eval_classes if c in countable]
    c_true = np.array([[sum(o["label"] == c for o in gt.get(r["file"], [])) for c in cc] for r in records])
    c_pred = np.array([[sum(o["label"] == c for o in r["objects"]) for c in cc] for r in records])
    res["counting"] = count_metrics(c_true, c_pred) if len(records) and cc else None
    res["out_of_dataset_objects"] = int(sum(o["label"] not in ev for r in records for o in r["objects"]))
    lat = np.array([r.get("latency_s", np.nan) for r in records], float)
    lat = lat[~np.isnan(lat)]
    res["latency_s"] = ({"p50": float(np.percentile(lat, 50)), "p95": float(np.percentile(lat, 95))}
                        if len(lat) else None)
    tin = sum(r.get("usage", {}).get("prompt_tokens", 0) for r in records)
    tout = sum(r.get("usage", {}).get("output_tokens", 0) for r in records)
    cost = tin / 1e6 * price_in + tout / 1e6 * price_out
    res["tokens"] = {"input": tin, "output": tout}
    res["cost_usd"] = {"total": cost, "per_image": cost / max(len(records), 1),
                       "price_in_per_mtok": price_in, "price_out_per_mtok": price_out}
    res["parse"] = {k: int(sum(r.get("parse", {}).get(k, 0) for r in records))
                    for k in ("json_error", "unknown_label", "bad_box", "n_raw")}
    return res


# ------------------------------------------------------------------ data + API


def yolo_gt(split: str) -> tuple[dict[str, list[dict]], dict[str, tuple[int, int]], list[str]]:
    import yaml
    from PIL import Image

    names = yaml.safe_load((YOLO_DIR / "dataset.yaml").read_text())["names"]
    gt, size = {}, {}
    for img in sorted((YOLO_DIR / "images" / split).glob("*.jpg")):
        with Image.open(img) as im:
            w, h = im.size
        size[img.name] = (w, h)
        objs = []
        lab = YOLO_DIR / "labels" / split / (img.stem + ".txt")
        for line in (lab.read_text().splitlines() if lab.exists() else []):
            if line.strip():
                k, xc, yc, bw, bh = line.split()
                xc, yc, bw, bh = (float(v) for v in (xc, yc, bw, bh))
                objs.append({"label": names[int(k)], "xyxy": [(xc - bw / 2) * w, (yc - bh / 2) * h,
                                                              (xc + bw / 2) * w, (yc + bh / 2) * h]})
        gt[img.name] = objs
    return gt, size, [names[k] for k in sorted(names)]


def raw_path(model: str, split: str, prompt: str, repeat: int) -> Path:
    return RAW / f"{model.replace('/', '_')}__{split}__{prompt}__r{repeat}.jsonl"


def call_gemini(client, model: str, image_bytes: bytes, prompt: str, schema: dict,
                media_resolution: str = "MEDIA_RESOLUTION_HIGH") -> tuple[str, dict, float]:
    """One request. ``client`` is a ``google.genai.Client`` (or a test double with the same surface)."""
    from google.genai import types  # type: ignore[import-not-found]

    cfg = types.GenerateContentConfig(temperature=0, response_mime_type="application/json",
                                      response_schema=schema, media_resolution=media_resolution)
    t0 = time.perf_counter()
    resp = client.models.generate_content(
        model=model, contents=[types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"), prompt], config=cfg)
    dt = time.perf_counter() - t0
    um = getattr(resp, "usage_metadata", None)
    usage = {"prompt_tokens": getattr(um, "prompt_token_count", 0) or 0,
             "output_tokens": (getattr(um, "candidates_token_count", 0) or 0)
             + (getattr(um, "thoughts_token_count", 0) or 0)}
    return resp.text or "", usage, dt


def run(split: str, prompt_variant: str, model: str, repeat: int = 0, limit: int | None = None,
        client=None, caller=call_gemini) -> Path:
    classes = class_table()
    prompt = build_prompt(classes, prompt_variant)
    schema = response_schema([c["id"] for c in classes])
    if client is None:
        import os

        from google import genai  # type: ignore[import-not-found]

        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    out = raw_path(model, split, prompt_variant, repeat)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        done = {json.loads(ln)["file"] for ln in out.read_text().splitlines() if ln.strip()}
    files = sorted((YOLO_DIR / "images" / split).glob("*.jpg"))
    if limit:
        rng = np.random.default_rng(0)
        files = [files[i] for i in sorted(rng.choice(len(files), size=min(limit, len(files)), replace=False))]
    with out.open("a") as f:
        for p in files:
            if p.name in done:
                continue
            text, usage, dt = caller(client, model, p.read_bytes(), prompt, schema)
            f.write(json.dumps({"file": p.name, "model": model, "date": time.strftime("%Y-%m-%d"),
                                "prompt": prompt_variant, "repeat": repeat, "text": text, "usage": usage,
                                "latency_s": dt}, ensure_ascii=False) + "\n")
            f.flush()
    return out


def evaluate_run(split: str, prompt_variant: str, model: str, repeats=(0, 1, 2), price_in: float = 0.0,
                 price_out: float = 0.0) -> dict:
    gt, size, names = yolo_gt(split)
    ids = {c["id"] for c in class_table()}
    countable = {c["id"] for c in class_table() if c["countable"]}
    per_run = []
    for r in repeats:
        p = raw_path(model, split, prompt_variant, r)
        if not p.exists():
            continue
        recs = []
        for ln in p.read_text().splitlines():
            if not ln.strip():
                continue
            j = json.loads(ln)
            w, h = size[j["file"]]
            objs, rep = parse_response(j["text"], ids, w, h)
            recs.append({"file": j["file"], "objects": objs, "parse": rep, "latency_s": j.get("latency_s"),
                         "usage": j.get("usage", {})})
        per_run.append(evaluate_records(recs, gt, names, countable, price_in, price_out))
    summary = {"model": model, "split": split, "prompt": prompt_variant, "runs": per_run}
    if per_run:
        def ms(get):
            v = np.array([get(x) for x in per_run if get(x) is not None], float)
            return {"mean": float(v.mean()), "sd": float(v.std(ddof=1)) if len(v) > 1 else None} if len(v) else None
        summary["mean_sd"] = {
            "f1_iou0.5": ms(lambda x: x["box_iou0.5"]["f1"]),
            "f1_iou0.3": ms(lambda x: x["box_iou0.3"]["f1"]),
            "list_f1": ms(lambda x: x["list_level"]["f1"]),
            "count_mae": ms(lambda x: x["counting"]["mae"] if x["counting"] else None),
        }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{model.replace('/', '_')}__{split}__{prompt_variant}.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "eval", "prompt"])
    ap.add_argument("--split", default="val")
    ap.add_argument("--prompt", default="v1")
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--repeat", type=int, default=0)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--price-in", type=float, default=0.0, help="USD per 1M input tokens")
    ap.add_argument("--price-out", type=float, default=0.0, help="USD per 1M output tokens")
    a = ap.parse_args()
    if a.cmd == "prompt":
        print(build_prompt(class_table(), a.prompt))
    elif a.cmd == "run":
        print(run(a.split, a.prompt, a.model, a.repeat, a.limit))
    else:
        print(json.dumps(evaluate_run(a.split, a.prompt, a.model, price_in=a.price_in, price_out=a.price_out)
                         .get("mean_sd"), indent=2))


if __name__ == "__main__":
    main()
