"""Empirical-Bayes brand share: the fix for tiny denominators.

    python -m src.ds.shrinkage

THE PROBLEM
-----------
A prescriber writing 2 class fills, 1 of them the brand, has a raw share of
50%; next year 2 of 2 is 100% -- "+50 share points". The ML challenger trained
on raw share change learned exactly that: it topped share capture by choosing
prescribers with a median of 35 class fills, and delivered almost no volume.
The consulting fix was to exclude the rule and add a guardrail. The modelling
fix is to stop the noise reaching the model.

THE MODEL
---------
Beta-binomial, per specialty group g:

    brand_i ~ Binomial(n_i, p_i),     p_i ~ Beta(a_g, b_g)
    shrunk share  = (brand_i + a_g) / (n_i + a_g + b_g)

(a_g, b_g) by the method of moments on prescribers with n >= 20, separating the
binomial noise from the true between-prescriber variance. A 2-fill prescriber
is pulled almost all the way to their specialty's mean; a 2,000-fill
prescriber barely moves. n is OBSERVED class volume, the denominator raw share
already uses.

THE TEST
--------
Retrain the share-growth challenger on the shrunk change and re-run the 60-rep
head-to-head. If shrinkage works, the micro-prescriber exploit disappears
without any rule being excluded.

WHAT IT FOUND
-------------
Shrinkage alone is not enough. Share genuinely varies between prescribers
(the fitted prior is worth only a few pseudo-fills), so a small prescriber's
shrunk share still moves a lot. Weighting each change by its precision does not
help either, which identifies the real cause: REGRESSION TO THE MEAN. A
prescriber at an unusually low share drifts back up whoever calls, and a share-
change target rewards finding them. The fix is to align the target with what a
call buys -- shrunk share-point change x volume, i.e. branded fills moved by
share -- after which the model stops chasing micro-prescribers.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import path
from src.ds import features as F
from src.ds.data import n_budget, panels
from src.ds.tracking import log_run
from src.utils.io import get_logger, record, write_parquet

log = get_logger(__name__)

MIN_N_FOR_PRIOR = 20
PRECISION_CAP = 2_000
KAPPA_BOUNDS = (1.0, 5_000.0)


def fit_prior(brand: np.ndarray, n: np.ndarray) -> tuple[float, float]:
    """Method-of-moments Beta(a, b) from binomial counts, noise removed."""
    ok = n >= MIN_N_FOR_PRIOR
    if ok.sum() < 30:
        ok = n > 0
    p = brand[ok] / n[ok]
    w = n[ok]
    m = float(np.average(p, weights=w))
    var_obs = float(np.average((p - m) ** 2, weights=w))
    noise = float(np.average(m * (1 - m) / n[ok], weights=w))
    var_true = max(var_obs - noise, 1e-6)
    kappa = float(np.clip(m * (1 - m) / var_true - 1, *KAPPA_BOUNDS))
    m = float(np.clip(m, 1e-4, 1 - 1e-4))
    return m * kappa, (1 - m) * kappa


def fit_priors(frame: pd.DataFrame, brand: str, n: str, group: str = "specialty_group") -> pd.DataFrame:
    rows = []
    for g, d in frame.groupby(group):
        a, b = fit_prior(d[brand].to_numpy(dtype=float).clip(0), d[n].to_numpy(dtype=float).clip(0))
        rows.append({group: g, "a": a, "b": b, "prior_mean": a / (a + b), "kappa": a + b,
                     "n_prescribers": len(d)})
    return pd.DataFrame(rows)


def shrink(frame: pd.DataFrame, priors: pd.DataFrame, brand: str, n: str,
           group: str = "specialty_group") -> np.ndarray:
    pr = frame[[group]].merge(priors, on=group, how="left")
    a = pr["a"].fillna(priors["a"].median()).to_numpy()
    b = pr["b"].fillna(priors["b"].median()).to_numpy()
    br = frame[brand].to_numpy(dtype=float).clip(0)
    nn = frame[n].to_numpy(dtype=float).clip(0)
    br = np.minimum(br, nn)
    return (br + a) / (nn + a + b)


def add_eb(frame: pd.DataFrame, priors: pd.DataFrame) -> pd.DataFrame:
    """Shrunk share now and next year, and the shrunk change."""
    out = frame.copy()
    out["eb_share"] = shrink(out, priors, "brand_fills", "class_fills_observed")
    nxt = out[["specialty_group", "brand_fills_next", "class_obs_next"]]
    out["eb_share_next"] = shrink(nxt, priors, "brand_fills_next", "class_obs_next")
    out["eb_growth_share"] = out["eb_share_next"] - out["eb_share"]
    return out


def prepared(train: pd.DataFrame | None = None, apply_: pd.DataFrame | None = None):
    """Panels with shrunk-share columns. Priors are fitted on the TRAIN state only."""
    if train is None or apply_ is None:
        train, apply_ = panels()
    priors = fit_priors(train, "brand_fills", "class_fills_observed")
    return add_eb(train, priors), add_eb(apply_, priors), priors


def head_to_head(train: pd.DataFrame, apply_: pd.DataFrame, k: int) -> pd.DataFrame:
    """Raw-share vs shrunk-share challenger, same budget, same features."""
    Xtr, enc, _ = F.design(train)
    Xap, _, _ = F.design(apply_, enc)
    tot_abs = apply_.loc[apply_["growth_abs"] > 0, "growth_abs"].sum()
    tot_eb = apply_.loc[apply_["eb_growth_share"] > 0, "eb_growth_share"].sum()
    rows = []
    # Precision weight: binomial variance of a share falls as 1/n, so a
    # prescriber's change is weighted by how many fills it is measured on
    # (capped, so one hospital system cannot dominate the fit).
    w = train["class_fills_observed"].to_numpy(dtype=float).clip(1, PRECISION_CAP)
    # Value-aligned target: shrunk share-point change times the prescriber's
    # volume -- branded fills attributable to share movement, which is what a
    # call is supposed to buy.
    for frame in (train, apply_):
        frame["eb_share_fills"] = frame["eb_growth_share"] * frame["class_fills"].clip(lower=0)
    for name, target, weight in (("ml_share_raw", "growth_share", None),
                                 ("ml_share_eb", "eb_growth_share", None),
                                 ("ml_share_eb_weighted", "eb_growth_share", w),
                                 ("ml_share_value_aligned", "eb_share_fills", None)):
        model = F.gbm().fit(Xtr, train[target].to_numpy(dtype=float), sample_weight=weight)
        score = model.predict(Xap)
        top = apply_.iloc[np.argsort(-score)[:k]]
        rows.append({
            "rule": name,
            "median_base_class_fills": float(top["class_fills"].median()),
            "abs_capture": float(top["growth_abs"].clip(lower=0).sum() / tot_abs),
            "eb_share_capture": float(top["eb_growth_share"].clip(lower=0).sum() / tot_eb),
            "net_brand_fill_growth": float(top["growth_abs"].sum()),
        })
    return pd.DataFrame(rows)


def funnel_sample(frame: pd.DataFrame, n: int = 3000, seed: int = 0) -> pd.DataFrame:
    s = frame[frame["class_fills_observed"] > 0].sample(min(n, len(frame)), random_state=seed)
    return pd.DataFrame({
        "class_fills_observed": s["class_fills_observed"].to_numpy(),
        "raw_share": (s["brand_fills"] / s["class_fills_observed"]).clip(0, 1).to_numpy(),
        "eb_share": s["eb_share"].to_numpy(),
        "specialty_group": s["specialty_group"].astype(str).to_numpy(),
    })


def run() -> dict:
    train, apply_, priors = prepared()
    k = n_budget()
    h2h = head_to_head(train, apply_, k)
    proc = path("processed")
    write_parquet(priors, proc / "ds_shrinkage_priors.parquet")
    write_parquet(h2h, proc / "ds_shrinkage_h2h.parquet")
    write_parquet(funnel_sample(apply_), proc / "ds_shrinkage_funnel.parquet")

    t = h2h.set_index("rule")
    raw, eb, wt = t.loc["ml_share_raw"], t.loc["ml_share_eb"], t.loc["ml_share_eb_weighted"]
    va = t.loc["ml_share_value_aligned"]
    # Noise check: how much of raw share change is binomial noise for small prescribers.
    small = apply_["class_fills_observed"] < 20
    res = {
        "n_budget": k,
        "priors": priors.round(4).to_dict(orient="records"),
        "raw_ml_median_base": round(float(raw["median_base_class_fills"]), 1),
        "eb_ml_median_base": round(float(eb["median_base_class_fills"]), 1),
        "raw_ml_abs_capture": round(float(raw["abs_capture"]), 4),
        "eb_ml_abs_capture": round(float(eb["abs_capture"]), 4),
        "weighted_ml_median_base": round(float(wt["median_base_class_fills"]), 1),
        "weighted_ml_abs_capture": round(float(wt["abs_capture"]), 4),
        "weighted_ml_eb_share_capture": round(float(wt["eb_share_capture"]), 4),
        "weighted_ml_net_fills": round(float(wt["net_brand_fill_growth"]), 0),
        "median_prior_strength": round(float(priors["kappa"].median()), 2),
        "aligned_ml_median_base": round(float(va["median_base_class_fills"]), 1),
        "aligned_ml_abs_capture": round(float(va["abs_capture"]), 4),
        "aligned_ml_eb_share_capture": round(float(va["eb_share_capture"]), 4),
        "aligned_ml_net_fills": round(float(va["net_brand_fill_growth"]), 0),
        # Regression to the mean: low current share predicts a rise whoever calls.
        "mean_reversion_corr": round(float(np.corrcoef(
            apply_["eb_share"], apply_["eb_growth_share"])[0, 1]), 3),
        "raw_ml_net_fills": round(float(raw["net_brand_fill_growth"]), 0),
        "eb_ml_net_fills": round(float(eb["net_brand_fill_growth"]), 0),
        "sd_raw_change_small": round(float(apply_.loc[small, "growth_share"].std()), 4),
        "sd_eb_change_small": round(float(apply_.loc[small, "eb_growth_share"].std()), 4),
        "sd_raw_change_large": round(float(apply_.loc[~small, "growth_share"].std()), 4),
        "sd_eb_change_large": round(float(apply_.loc[~small, "eb_growth_share"].std()), 4),
    }
    log.info("SHRINKAGE: raw-share ML picks a median %.0f-fill prescriber (abs capture %.1f%%); "
             "shrunk-share ML picks %.0f (abs capture %.1f%%). Small-prescriber share-change "
             "s.d. %.3f -> %.3f.", res["raw_ml_median_base"], 100 * res["raw_ml_abs_capture"],
             res["eb_ml_median_base"], 100 * res["eb_ml_abs_capture"],
             res["sd_raw_change_small"], res["sd_eb_change_small"])
    log.info("  + precision weighting: median %.0f-fill prescriber, abs capture %.1f%%, "
             "net fills %+.0f. Prior strength is only %.1f pseudo-fills -- share genuinely "
             "varies between prescribers, so shrinkage alone cannot remove the noise.",
             res["weighted_ml_median_base"], 100 * res["weighted_ml_abs_capture"],
             res["weighted_ml_net_fills"], res["median_prior_strength"])
    log.info("  what is left is REGRESSION TO THE MEAN (corr(share, change) = %.2f). "
             "Value-aligned target (shrunk share change x volume): median %.0f-fill "
             "prescriber, abs capture %.1f%%, shrunk-share capture %.1f%%, net fills %+.0f.",
             res["mean_reversion_corr"], res["aligned_ml_median_base"],
             100 * res["aligned_ml_abs_capture"], 100 * res["aligned_ml_eb_share_capture"],
             res["aligned_ml_net_fills"])
    record("ds_shrinkage", **res)
    log_run("ds_shrinkage", params={"min_n_for_prior": MIN_N_FOR_PRIOR, "k": k},
            metrics={k_: v for k_, v in res.items() if k_ != "priors"},
            artifacts=[proc / "ds_shrinkage_h2h.parquet"])
    return res


if __name__ == "__main__":
    run()
