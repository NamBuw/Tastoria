"""Taste ranking ŝ(u, r) and its per-user, per-slot percentile ŝ' (design v2 §6.1, "Phục vụ").

`Ranker` is the plug point for the trained models of the ML report (biased MF, LightFM, LambdaMART exported to NumPy
and registered in mlops). Until one is deployed, `BaselineRanker` serves BR-CONSENT-03's fallback for everyone:

    ŝ = 0.5 · popularity_r + 0.5 · content_r (+ 0.25 · own_r with a personalization consent)

  * popularity_r — shrunk item average of the interactions of all consenting users:
                   (positive + k·½) / (positive + negative + k), k = 5; positive = liked + cooked,
                   negative = disliked + swapped as "không hợp gu" (BR-SWAP-01);
  * content_r    — cosine between the recipe vector and the mean vector of the user's 5 favourite dishes
                   (features: main/side non-staple ingredients, cooking method, tags; design v2 §6.1 bậc 3);
  * own_r        — the user's own signal on the recipe in [−1, 1], read only with a current consent (FR-15-17).

ŝ carries taste only: no stock, urgency or energy signal (those live in the composer objective).
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from tastoria.modules.catalog.schemas import RecipeView
from tastoria.modules.events.schemas import RecipeSignal

SHRINK_K = 5.0


@dataclass(frozen=True)
class RankContext:
    user_id: uuid.UUID
    favorites: Sequence[RecipeView]
    popularity: dict[uuid.UUID, RecipeSignal] = field(default_factory=dict)
    personal: dict[uuid.UUID, RecipeSignal] | None = None  # None without a personalization consent


class Ranker(Protocol):
    version_id: uuid.UUID | None  # model_versions.id of the deployed ranker; None for the baseline

    def score(self, ctx: RankContext, recipes: Sequence[RecipeView]) -> dict[uuid.UUID, float]: ...


def features(r: RecipeView) -> dict[str, float]:
    f = {f"ing:{ln.ingredient.id}": 1.0 for ln in r.lines if ln.role != "seasoning" and not ln.ingredient.is_staple}
    f[f"method:{r.method_code}"] = 1.0
    f.update({f"tag:{t}": 0.5 for t in r.tag_codes})
    return f


def _cos(a: dict[str, float], b: dict[str, float]) -> float:
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def _profile(favs: Iterable[RecipeView]) -> dict[str, float]:
    favs = list(favs)
    acc: dict[str, float] = {}
    for r in favs:
        for k, v in features(r).items():
            acc[k] = acc.get(k, 0.0) + v / len(favs)
    return acc


def _shrunk(sig: RecipeSignal | None) -> float:
    pos, neg = (sig.positive, sig.negative) if sig else (0, 0)
    return (pos + SHRINK_K * 0.5) / (pos + neg + SHRINK_K)


class BaselineRanker:
    version_id: uuid.UUID | None = None

    def score(self, ctx: RankContext, recipes: Sequence[RecipeView]) -> dict[uuid.UUID, float]:
        prof = _profile(ctx.favorites)
        out = {}
        for r in recipes:
            s = 0.5 * _shrunk(ctx.popularity.get(r.id)) + 0.5 * _cos(features(r), prof)
            if ctx.personal is not None and (sig := ctx.personal.get(r.id)) is not None:
                total = sig.positive + sig.negative
                s += 0.25 * (sig.positive - sig.negative) / total if total else 0.0
            out[r.id] = s
        return out


def percentiles(scores: dict[uuid.UUID, float]) -> dict[uuid.UUID, float]:
    """ŝ' ∈ [0, 1]: rank of each score among the given ones (ties share their mean rank); one item → 1."""
    if not scores:
        return {}
    if len(scores) == 1:
        return {k: 1.0 for k in scores}
    ordered = sorted(scores.items(), key=lambda kv: kv[1])
    out: dict[uuid.UUID, float] = {}
    i = 0
    n = len(ordered)
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        rank = (i + j) / 2 / (n - 1)
        for k in range(i, j + 1):
            out[ordered[k][0]] = rank
        i = j + 1
    return out
