"""Food.com interactions for top-N ranking: 5-core, global time split, sparse matrices, item features.

Rules (design v2 §6.1, review ml#7):
- `rating` 0 is a review without stars. It is never a positive and never a test target, but it is kept as an
  *interaction*: the item counts as already seen by that user and is removed from the user's candidate list.
- Implicit positive = rating ≥ 4. Ratings 1–3 are interactions (seen) but not positives.
- 5-core is applied to the positive graph (users and items with ≥ 5 positives), iterated to a fixed point, on the
  whole period (common practice; the core is a property of the dataset, the split is applied after).
- Global time split on the core positives: the latest 10 % (by date) are test, the 10 % before are validation,
  the rest train. Dates are days, so a boundary day goes wholly to the later part; the realised shares are reported.
- MostPop and every model only see data before the cutoff of the phase they are evaluated on.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import scipy.sparse as sp

REPO = Path(__file__).resolve().parents[4]
FOODCOM = REPO / "data" / "processed" / "foodcom"
POS_MIN = 4


def kcore(df: pd.DataFrame, k: int = 5, user: str = "user_id", item: str = "recipe_id") -> pd.DataFrame:
    """Largest sub-table where every user and every item has ≥ k rows (iterated to a fixed point)."""
    while True:
        uc = df[user].map(df[user].value_counts())
        ic = df[item].map(df[item].value_counts())
        keep = (uc >= k) & (ic >= k)
        if keep.all():
            return df
        df = df[keep]


def time_cutoffs(dates: pd.Series, val_share: float = 0.1, test_share: float = 0.1) -> tuple[pd.Timestamp, pd.Timestamp]:
    """(d_val, d_test): train = date < d_val, validation = d_val ≤ date < d_test, test = date ≥ d_test."""
    s = np.sort(dates.to_numpy())
    n = len(s)
    d_test = pd.Timestamp(s[int(np.floor(n * (1 - test_share)))])
    d_val = pd.Timestamp(s[int(np.floor(n * (1 - test_share - val_share)))])
    return d_val, d_test


@dataclass
class Split:
    """Index-encoded interactions of one evaluation phase."""

    train: sp.csr_matrix  # users × items, 1 for a positive before the cutoff
    seen: sp.csr_matrix  # users × items, 1 for any interaction (incl. rating 0 / 1–3) before the cutoff
    targets: dict[int, np.ndarray]  # user index -> item indices of positives in the evaluation period
    n_target_pos: int  # positives in the evaluation period (all users / items)
    n_target_kept: int  # of which: warm user, warm item, not already seen
    cold_targets: dict[int, np.ndarray] = field(default_factory=dict)  # warm user -> positives on cold items
    cold_items: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))


@dataclass
class FoodcomData:
    users: np.ndarray  # user_id per user index
    items: np.ndarray  # recipe_id per item index
    pos: pd.DataFrame  # core positives with u, i, date
    inter: pd.DataFrame  # every interaction of core users on core items (incl. rating 0) with u, i, date, rating
    d_val: pd.Timestamp
    d_test: pd.Timestamp
    stats: dict

    @property
    def n_users(self) -> int:
        return len(self.users)

    @property
    def n_items(self) -> int:
        return len(self.items)

    def split(self, phase: str) -> Split:
        """phase 'val': train < d_val, evaluate on [d_val, d_test). phase 'test': train < d_test, evaluate ≥ d_test."""
        if phase == "val":
            lo, hi = self.d_val, self.d_test
        elif phase == "test":
            lo, hi = self.d_test, None
        else:
            raise ValueError(phase)
        tr = self.pos[self.pos.date < lo]
        ev = self.pos[(self.pos.date >= lo) & ((self.pos.date < hi) if hi is not None else True)]
        seen_df = self.inter[self.inter.date < lo]
        shape = (self.n_users, self.n_items)
        train = _csr(tr.u.to_numpy(), tr.i.to_numpy(), shape)
        seen = _csr(seen_df.u.to_numpy(), seen_df.i.to_numpy(), shape)
        warm_u = np.diff(train.indptr) > 0
        warm_i = np.asarray(train.sum(axis=0)).ravel() > 0
        seen_pairs = set(zip(seen_df.u.to_numpy().tolist(), seen_df.i.to_numpy().tolist(), strict=True))
        eu, ei = ev.u.to_numpy(), ev.i.to_numpy()
        not_seen = np.fromiter(((a, b) not in seen_pairs for a, b in zip(eu, ei, strict=True)), bool, len(eu))
        keep = warm_u[eu] & warm_i[ei] & not_seen
        targets = _group(eu[keep], ei[keep])
        cold = warm_u[eu] & ~warm_i[ei]
        cold_items = np.unique(ei[~warm_i[ei]])
        return Split(train, seen, targets, int(len(ev)), int(keep.sum()), _group(eu[cold], ei[cold]), cold_items)


def _csr(u: np.ndarray, i: np.ndarray, shape: tuple[int, int]) -> sp.csr_matrix:
    m = sp.csr_matrix((np.ones(len(u), dtype=np.float32), (u, i)), shape=shape)
    m.sum_duplicates()
    m.data[:] = 1.0
    return m


def _group(u: np.ndarray, i: np.ndarray) -> dict[int, np.ndarray]:
    if len(u) == 0:
        return {}
    order = np.argsort(u, kind="stable")
    u, i = u[order], i[order]
    cuts = np.flatnonzero(np.diff(u)) + 1
    return {int(g[0]): np.unique(h) for g, h in zip(np.split(u, cuts), np.split(i, cuts), strict=True)}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare(inter: pd.DataFrame, k: int = 5, val_share: float = 0.1, test_share: float = 0.1) -> FoodcomData:
    """Build the core and the cutoffs from a raw interaction table (user_id, recipe_id, date, rating)."""
    pos_all = inter[inter.rating >= POS_MIN]
    core = kcore(pos_all[["user_id", "recipe_id", "date", "rating"]], k)
    users = np.sort(core.user_id.unique())
    items = np.sort(core.recipe_id.unique())
    uidx = pd.Series(np.arange(len(users)), index=users)
    iidx = pd.Series(np.arange(len(items)), index=items)
    pos = core.assign(u=core.user_id.map(uidx).to_numpy(), i=core.recipe_id.map(iidx).to_numpy())
    sub = inter[inter.user_id.isin(uidx.index) & inter.recipe_id.isin(iidx.index)]
    sub = sub.assign(u=sub.user_id.map(uidx).to_numpy(), i=sub.recipe_id.map(iidx).to_numpy())
    d_val, d_test = time_cutoffs(pos.date, val_share, test_share)
    n = len(pos)
    stats = {
        "raw_interactions": int(len(inter)),
        "raw_positives": int(len(pos_all)),
        "raw_rating0": int((inter.rating == 0).sum()),
        "core_k": k,
        "core_users": int(len(users)),
        "core_items": int(len(items)),
        "core_positives": int(n),
        "core_interactions_all_ratings": int(len(sub)),
        "core_rating0_interactions": int((sub.rating == 0).sum()),
        "density": float(n / (len(users) * len(items))),
        "d_val": d_val.date().isoformat(),
        "d_test": d_test.date().isoformat(),
        "share_train": float((pos.date < d_val).mean()),
        "share_val": float(((pos.date >= d_val) & (pos.date < d_test)).mean()),
        "share_test": float((pos.date >= d_test).mean()),
    }
    return FoodcomData(users, items, pos.reset_index(drop=True), sub.reset_index(drop=True), d_val, d_test, stats)


def load(processed: Path = FOODCOM, k: int = 5) -> FoodcomData:
    path = processed / "interactions.parquet"
    if not path.exists():
        raise FileNotFoundError(f"{path} missing: run `uv run --package tastoria-ml python -m tastoria_ml.data.foodcom`")
    data = prepare(pd.read_parquet(path), k)
    data.stats["interactions_sha256"] = sha256_file(path)
    return data


def item_features(
    items: np.ndarray, processed: Path = FOODCOM, min_count: int = 20, identity: bool = True
) -> tuple[sp.csr_matrix, list[str]]:
    """Item × feature matrix from Food.com tags and ingredient names (each kept if on ≥ min_count core items).

    Rows are L1-normalised per block as LightFM recommends for mixed features; with `identity` the first n_items
    columns are the per-item indicator (warm hybrid). Without it the item is described by its features only, which
    is what lets a model score items never seen in training (cold start)."""
    rec = pd.read_parquet(processed / "recipes.parquet", columns=["recipe_id", "tags", "ingredients"])
    rec = rec.set_index("recipe_id").loc[items]
    toks = [
        [f"tag:{t}" for t in tg] + [f"ing:{x}" for x in ig]
        for tg, ig in zip(rec["tags"].tolist(), rec["ingredients"].tolist(), strict=True)
    ]
    counts: dict[str, int] = {}
    for ts in toks:
        for t in set(ts):
            counts[t] = counts.get(t, 0) + 1
    vocab = sorted(t for t, c in counts.items() if c >= min_count)
    col = {t: j for j, t in enumerate(vocab)}
    rows, cols = [], []
    for r, ts in enumerate(toks):
        for t in set(ts):
            if t in col:
                rows.append(r)
                cols.append(col[t])
    f = sp.csr_matrix((np.ones(len(rows), np.float32), (rows, cols)), shape=(len(items), len(vocab)))
    deg = np.asarray(f.sum(axis=1)).ravel()
    f = sp.diags(1.0 / np.maximum(deg, 1)).astype(np.float32) @ f
    names = vocab
    if identity:
        f = sp.hstack([sp.identity(len(items), dtype=np.float32, format="csr"), f], format="csr")
        names = [f"item:{x}" for x in items] + vocab
        deg = np.asarray(f.sum(axis=1)).ravel()
        f = (sp.diags(1.0 / deg).astype(np.float32) @ f).tocsr()
    return f.tocsr(), names
