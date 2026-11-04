"""The evaluation suite: baseline ladder, ranking metrics, gain curves.

    python -m src.ds.evaluation

PRE-DECLARED (fixed before any result below was read):

    k               the 60-rep list size (what the field force can cover)
    PRIMARY metric  value capture @ k -- share of all positive "share-driven
                    fills" (shrunk share-point change x volume, shrinkage.py)
                    that the top-k list contains. Volume-aware, noise-robust,
                    and immune to regression-to-the-mean gaming.
    GUARDRAIL       absolute-growth capture >= 90% of the volume rule's
                    (the brand team's floor, as in challenger.recommend_rule)

Secondary, for comparability with the literature: precision@k (share of the
list in the realised top decile of share-driven fills), NDCG@k, absolute and
shrunk-share capture, net branded fills.

THE LADDER (every rule scored on the same 2023 state, judged on 2023 -> 2024)

    random            the floor any ranking must beat
    volume            today's rule
    momentum          last year's branded growth -- the naive "who is rising"
    frontier          this project's opportunity score
    hybrid            the recommended 50/50 blend
    gbm_abs           gradient boosting on absolute branded growth
    gbm_share_raw     gradient boosting on raw share change (the exploit)
    gbm_value         gradient boosting on the value-aligned target
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import path
from src.ds import features as F
from src.ds.data import n_budget
from src.ds.shrinkage import prepared
from src.ds.tracking import log_run
from src.models.opportunity import hybrid_score
from src.utils.io import get_logger, record, write_parquet

log = get_logger(__name__)

N_BOOT = 100
GUARDRAIL = 0.90
GAIN_GRID = np.round(np.concatenate([np.linspace(0, 0.1, 21)[1:], np.linspace(0.1, 1, 19)[1:]]), 4)


def ndcg_at_k(score: np.ndarray, relevance: np.ndarray, k: int) -> float:
    rel = np.clip(relevance, 0, None)
    disc = 1.0 / np.log2(np.arange(2, k + 2))
    top = np.argsort(-score, kind="stable")[:k]
    ideal = np.sort(rel)[::-1][:k]
    idcg = float((ideal * disc).sum())
    return float((rel[top] * disc).sum() / idcg) if idcg > 0 else 0.0


def metrics_at_k(score: np.ndarray, frame: pd.DataFrame, k: int) -> dict[str, float]:
    top = np.argsort(-score, kind="stable")[:k]
    ga = frame["growth_abs"].to_numpy(dtype=float)
    ge = frame["eb_growth_share"].to_numpy(dtype=float)
    gv = frame["eb_share_fills"].to_numpy(dtype=float)
    cut = np.quantile(gv, 0.9)
    return {
        "value_capture": float(np.clip(gv[top], 0, None).sum() / np.clip(gv, 0, None).sum()),
        "abs_capture": float(np.clip(ga[top], 0, None).sum() / np.clip(ga, 0, None).sum()),
        "eb_share_capture": float(np.clip(ge[top], 0, None).sum() / np.clip(ge, 0, None).sum()),
        "precision_at_k": float((gv[top] >= cut).mean()),
        "ndcg_at_k": ndcg_at_k(score, gv, k),
        "net_brand_fill_growth": float(ga[top].sum()),
        "median_base_class_fills": float(np.median(frame["class_fills"].to_numpy()[top])),
    }


def scores(train: pd.DataFrame, apply_: pd.DataFrame, seed: int = 0) -> dict[str, np.ndarray]:
    """Every rule's score on the holdout state."""
    Xtr, enc, _ = F.design(train)
    Xap, _, _ = F.design(apply_, enc)
    out = {
        "random": np.random.default_rng(seed).random(len(apply_)),
        "volume": apply_["class_fills"].to_numpy(dtype=float),
        "momentum": apply_["prior_growth_abs"].fillna(0).to_numpy(dtype=float),
        "frontier": apply_["opportunity"].to_numpy(dtype=float),
        "hybrid": hybrid_score(apply_).to_numpy(dtype=float),
    }
    for name, target in (("gbm_abs", "growth_abs"), ("gbm_share_raw", "growth_share"),
                         ("gbm_value", "eb_share_fills")):
        out[name] = F.gbm(seed=seed).fit(Xtr, train[target].to_numpy(dtype=float)).predict(Xap)
    return out


def ladder(sc: dict[str, np.ndarray], apply_: pd.DataFrame, k: int,
           n_boot: int = N_BOOT) -> pd.DataFrame:
    rows = [{"rule": r, **metrics_at_k(s, apply_, k)} for r, s in sc.items()]
    df = pd.DataFrame(rows)
    # Bootstrap the primary metric (prescribers resampled; k scaled with them).
    rng = np.random.default_rng(1)
    boot = {r: [] for r in sc}
    n = len(apply_)
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        sub = apply_.iloc[idx]
        for r, s in sc.items():
            boot[r].append(metrics_at_k(s[idx], sub, k)["value_capture"])
    df["value_capture_lo"] = [float(np.percentile(boot[r], 2.5)) for r in df["rule"]]
    df["value_capture_hi"] = [float(np.percentile(boot[r], 97.5)) for r in df["rule"]]
    vol_abs = float(df.loc[df["rule"] == "volume", "abs_capture"].iloc[0])
    df["abs_vs_volume"] = df["abs_capture"] / vol_abs
    df["passes_guardrail"] = df["abs_vs_volume"] >= GUARDRAIL
    return df.sort_values("value_capture", ascending=False).reset_index(drop=True)


def gain_curves(sc: dict[str, np.ndarray], apply_: pd.DataFrame) -> pd.DataFrame:
    """Cumulative capture vs share of prescribers targeted, every rule."""
    ga = np.clip(apply_["growth_abs"].to_numpy(dtype=float), 0, None)
    gv = np.clip(apply_["eb_share_fills"].to_numpy(dtype=float), 0, None)
    n = len(apply_)
    rows = []
    for r, s in sc.items():
        order = np.argsort(-s, kind="stable")
        ca, cv = np.cumsum(ga[order]) / ga.sum(), np.cumsum(gv[order]) / gv.sum()
        for f in GAIN_GRID:
            i = max(int(round(f * n)) - 1, 0)
            rows.append({"rule": r, "fraction_targeted": float(f),
                         "abs_gain": float(ca[i]), "value_gain": float(cv[i]),
                         "value_lift": float(cv[i] / f)})
    return pd.DataFrame(rows)


def run() -> dict:
    train, apply_, _ = prepared()
    for frame in (train, apply_):
        frame["eb_share_fills"] = frame["eb_growth_share"] * frame["class_fills"].clip(lower=0)
    k = n_budget()
    sc = scores(train, apply_)
    lad = ladder(sc, apply_, k)
    gains = gain_curves(sc, apply_)
    proc = path("processed")
    write_parquet(lad, proc / "ds_ladder.parquet")
    write_parquet(gains, proc / "ds_gain_curves.parquet")

    t = lad.set_index("rule")
    ok = lad[lad["passes_guardrail"]]
    best = str(ok.iloc[0]["rule"]) if len(ok) else "volume"
    res = {
        "k": k,
        "primary_metric": "value_capture_at_k",
        "guardrail": f"abs capture >= {GUARDRAIL:.0%} of volume's",
        "winner_under_guardrail": best,
        "winner_unconstrained": str(lad.iloc[0]["rule"]),
        "ladder": lad.round(4).to_dict(orient="records"),
        "frontier_vs_random_value_lift": round(float(t.loc["frontier", "value_capture"]
                                                     / max(t.loc["random", "value_capture"], 1e-9)), 2),
        "gbm_value_vs_frontier": round(float(t.loc["gbm_value", "value_capture"]
                                             / max(t.loc["frontier", "value_capture"], 1e-9)), 3),
        "hybrid_value_capture": round(float(t.loc["hybrid", "value_capture"]), 4),
    }
    log.info("LADDER at k=%d (primary: value capture; guardrail: abs >= 90%% of volume):", k)
    for r in lad.itertuples(index=False):
        log.info("  %-14s value %5.1f%% [%4.1f, %4.1f]  abs %5.1f%%  P@k %.3f  NDCG %.3f  %s",
                 r.rule, 100 * r.value_capture, 100 * r.value_capture_lo, 100 * r.value_capture_hi,
                 100 * r.abs_capture, r.precision_at_k, r.ndcg_at_k,
                 "" if r.passes_guardrail else "(fails guardrail)")
    log.info("WINNER under the guardrail: %s", best)
    record("ds_evaluation", **res)
    log_run("ds_evaluation", params={"k": k, "primary": "value_capture", "guardrail": GUARDRAIL,
                                     "n_boot": N_BOOT},
            metrics={f"{r['rule']}.{m}": r[m] for r in res["ladder"]
                     for m in ("value_capture", "abs_capture", "precision_at_k", "ndcg_at_k")},
            artifacts=[proc / "ds_ladder.parquet"])
    return res


if __name__ == "__main__":
    run()
