"""Candidate scorers for "thiếu nguyên liệu i, dùng gì thay?" over the KB ingredients of the same food group.

Corpus and vocabulary
  * Food.com: one sentence per recipe = its ingredient strings (already normalised by the dataset), each string one
    token (spaces → "_").
  * KB (data/kb/recipes): one sentence per dish; a Vietnamese ingredient is written as its *canonical English
    token* — the most frequent of its `synonyms.en` in Food.com — when one exists, else as "vi:<name_vi>".
  * VN → vector: mean of the vectors of all its English synonyms present in the vocabulary; else its own "vi:" token
    if that survived min_count; else no vector (not covered).

Scorers (higher = better substitute; candidates = same food group, not the ingredient itself):
  word2vec   cosine of the VN vectors (gensim Word2Vec, sg = 1, window ≥ longest list, shrink_windows = False)
  nutrient   cosine of standardised log(1 + x) vectors of energy, protein, lipid, glucid, fiber, sodium per 100 g
             (Resolver: FCT 2007 / USDA); missing nutrients imputed by the column mean
  pmi        cosine of PPMI context rows (second-order co-occurrence: substitutes share contexts, Teng et al. 2012
             use co-occurrence for the complement network); `pmi_direct` is first-order PPMI, used as the
             complement filter ("không phải cặp bổ sung")
  curated    the curated table score in the dish context (FR-17-04 order: slot+method, slot, method, any)
  random     uniform within the group
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp

from tastoria_ml.recsys.kb_catalog import REPO, Catalog

FOODCOM = REPO / "data" / "processed" / "foodcom"


def tok(s: str) -> str:
    return s.strip().lower().replace(" ", "_")


def foodcom_sentences(processed: Path = FOODCOM) -> list[list[str]]:
    rec = pd.read_parquet(processed / "recipes.parquet", columns=["ingredients"])
    return [[tok(x) for x in ing] for ing in rec["ingredients"].tolist() if len(ing)]


@dataclass
class Mapping:
    """VN ingredient → English tokens present in the corpus (with Food.com counts)."""

    en_tokens: dict[str, list[str]]
    canonical: dict[str, str | None]
    counts: Counter = field(default_factory=Counter)


def build_mapping(cat: Catalog, fc_sentences: list[list[str]]) -> Mapping:
    counts = Counter(t for s in fc_sentences for t in set(s))
    en, canon = {}, {}
    for name, ing in cat.ingredients.items():
        toks = [tok(e) for e in ing.synonyms.en]
        present = [t for t in dict.fromkeys(toks) if counts.get(t, 0) > 0]
        en[name] = present
        canon[name] = max(present, key=lambda t: counts[t]) if present else None
    return Mapping(en, canon, counts)


def kb_sentences(cat: Catalog, mp: Mapping) -> list[list[str]]:
    out = []
    for r in cat.recipes:
        out.append([mp.canonical.get(ln.name) or f"vi:{ln.name}" for ln in r.ingredients])
    return out


def longest(sentences: list[list[str]]) -> int:
    return max(len(s) for s in sentences)


class W2V:
    def __init__(self, dim: int = 100, min_count: int = 5, epochs: int = 10, negative: int = 10, kb_repeat: int = 1,
                 seed: int = 0, workers: int = 8):
        self.kw = dict(dim=dim, min_count=min_count, epochs=epochs, negative=negative, kb_repeat=kb_repeat)
        self.seed, self.workers = seed, workers

    def fit(self, fc: list[list[str]], kb: list[list[str]], mp: Mapping, cat: Catalog) -> W2V:
        from gensim.models import Word2Vec

        sents = fc + kb * int(self.kw["kb_repeat"])
        self.window = longest(sents)
        self.model = Word2Vec(
            sentences=sents,
            vector_size=int(self.kw["dim"]),
            window=self.window,
            shrink_windows=False,
            sg=1,
            min_count=int(self.kw["min_count"]),
            negative=int(self.kw["negative"]),
            epochs=int(self.kw["epochs"]),
            seed=self.seed,
            workers=self.workers,
        )
        wv = self.model.wv
        self.vec: dict[str, np.ndarray] = {}
        self.source: dict[str, str] = {}
        for name in cat.ingredients:
            toks = [t for t in mp.en_tokens.get(name, []) if t in wv.key_to_index]
            if toks:
                self.vec[name] = np.mean([wv[t] for t in toks], axis=0)
                self.source[name] = "en"
            elif f"vi:{name}" in wv.key_to_index:
                self.vec[name] = wv[f"vi:{name}"]
                self.source[name] = "vi"
        return self

    def score(self, missing: str, cands: list[str]) -> dict[str, float]:
        v = self.vec.get(missing)
        if v is None:
            return {}
        out = {}
        for c in cands:
            w = self.vec.get(c)
            if w is not None:
                out[c] = float(v @ w / (np.linalg.norm(v) * np.linalg.norm(w) + 1e-12))
        return out


class Nutrient:
    COLS = ("energy_kcal", "protein_g", "lipid_g", "glucid_g", "fiber_g", "sodium_mg")

    def fit(self, cat: Catalog, kb_dir: Path | None = None) -> Nutrient:
        from tastoria_ml.kb.nutrition import Resolver

        kb_dir = kb_dir or REPO / "data" / "kb"
        res = Resolver.from_dirs(kb_dir, REPO / "data" / "processed")
        rows, names = [], []
        for name in cat.ingredients:
            try:
                c = res.resolve(name).comp
            except KeyError:
                c = None
            if c is None:
                continue
            rows.append([getattr(c, k) for k in self.COLS])
            names.append(name)
        a = np.array(rows, dtype=float)
        a = np.log1p(np.where(np.isnan(a), np.nan, np.maximum(a, 0)))
        mu = np.nanmean(a, axis=0)
        a = np.where(np.isnan(a), mu, a)
        sd = a.std(axis=0)
        a = (a - a.mean(axis=0)) / np.where(sd > 0, sd, 1)
        self.vec = {n: a[i] for i, n in enumerate(names)}
        return self

    def score(self, missing: str, cands: list[str]) -> dict[str, float]:
        v = self.vec.get(missing)
        if v is None:
            return {}
        return {c: float(v @ self.vec[c] / (np.linalg.norm(v) * np.linalg.norm(self.vec[c]) + 1e-12)) for c in cands if c in self.vec}


class PMI:
    """PPMI over ingredient co-occurrence in the same corpus (VN ingredient = union of its tokens)."""

    def fit(self, fc: list[list[str]], kb: list[list[str]], mp: Mapping, cat: Catalog, min_count: int = 5) -> PMI:
        sents = fc + kb
        counts = Counter(t for s in sents for t in set(s))
        vocab = sorted(t for t, c in counts.items() if c >= min_count)
        col = {t: j for j, t in enumerate(vocab)}
        rows, cols = [], []
        for r, s in enumerate(sents):
            for t in set(s):
                if t in col:
                    rows.append(r)
                    cols.append(col[t])
        X = sp.csr_matrix((np.ones(len(rows), np.float32), (rows, cols)), shape=(len(sents), len(vocab)))
        co = (X.T @ X).tocoo()
        n = float(len(sents))
        df = np.asarray(X.sum(axis=0)).ravel()
        keep = co.row != co.col
        pmi = np.log((co.data[keep] * n) / (df[co.row[keep]] * df[co.col[keep]]))
        pos = pmi > 0
        M = sp.csr_matrix((pmi[pos], (co.row[keep][pos], co.col[keep][pos])), shape=(len(vocab), len(vocab)))
        self.M, self.col, self.df, self.n = M, col, df, n
        self.idx: dict[str, list[int]] = {}
        for name in cat.ingredients:
            toks = [t for t in mp.en_tokens.get(name, []) if t in col] or ([f"vi:{name}"] if f"vi:{name}" in col else [])
            if toks:
                self.idx[name] = [col[t] for t in toks]
        self._rows = {}
        return self

    def _row(self, name: str) -> np.ndarray | None:
        if name not in self.idx:
            return None
        if name not in self._rows:
            self._rows[name] = np.asarray(self.M[self.idx[name]].mean(axis=0)).ravel()
        return self._rows[name]

    def score(self, missing: str, cands: list[str]) -> dict[str, float]:
        v = self._row(missing)
        if v is None:
            return {}
        out = {}
        for c in cands:
            w = self._row(c)
            if w is not None:
                out[c] = float(v @ w / (np.linalg.norm(v) * np.linalg.norm(w) + 1e-12))
        return out

    def direct(self, a: str, b: str) -> float:
        """First-order PPMI between two VN ingredients (max over their tokens); 0 when unseen together."""
        if a not in self.idx or b not in self.idx:
            return 0.0
        return float(self.M[self.idx[a]][:, self.idx[b]].max()) if self.M[self.idx[a]][:, self.idx[b]].nnz else 0.0


class Curated:
    def __init__(self, pairs: list) -> None:
        self.pairs = pairs

    def score(self, missing: str, cands: list[str], slot: str | None = None, method: str | None = None) -> dict[str, float]:
        out: dict[str, float] = {}
        for p in self.pairs:
            if p.ingredient != missing or p.substitute not in cands:
                continue
            if p.context_slot not in (None, slot) and slot is not None:
                continue
            if p.context_method not in (None, method) and method is not None:
                continue
            specific = (p.context_slot is not None) + (p.context_method is not None)
            out[p.substitute] = max(out.get(p.substitute, -1.0), p.score + 0.001 * specific)
        return out


def candidates(cat: Catalog, missing: str, exclude: set[str] | None = None) -> list[str]:
    g = cat.ingredients[missing].food_group
    ex = (exclude or set()) | {missing}
    return sorted(n for n, i in cat.ingredients.items() if i.food_group == g and n not in ex)


def rank(scores: dict[str, float], cands: list[str]) -> list[str]:
    """Scored candidates by score (ties by name); unscored candidates are not returned (the method abstains)."""
    return [c for c, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0])) if c in set(cands)]


def random_hit_prob(n: int, m: int, k: int) -> float:
    """P(top-k of a uniform random order of n candidates contains ≥ 1 of m relevant ones)."""
    if m <= 0 or n <= 0:
        return 0.0
    k = min(k, n)
    return 1.0 - math.comb(n - m, k) / math.comb(n, k) if n - m >= k else 1.0


def random_mrr(n: int, m: int) -> float:
    """E[1 / rank of the first relevant item] for a uniform random order."""
    if m <= 0:
        return 0.0
    # P(first relevant at rank r) = C(n − r, m − 1) / C(n, m)
    tot = math.comb(n, m)
    return sum(math.comb(n - r, m - 1) / tot / r for r in range(1, n - m + 2))
