"""Uplift modelling: WHO moves when promoted, not just who has headroom.

    python -m src.ds.uplift

Opportunity ranks prescribers by how much they COULD grow. A visit is only
worth making where it CHANGES behaviour -- the persuadables. Uplift modelling
estimates that heterogeneous effect directly.

METHOD -- doubly-robust learner (Kennedy 2023), cross-fitted
    For each fold, fit on the others:
        e(x)    P(brand-named meal | x)             (propensity, clipped .02-.98)
        mu1(x)  E[Y | x, treated],  mu0(x)  E[Y | x, untreated]
    Pseudo-outcome per prescriber:
        phi = mu1 - mu0 + T (Y - mu1) / e - (1 - T)(Y - mu0) / (1 - e)
    then regress phi on x (gradient boosting) for the CATE tau(x). phi is
    unbiased for tau(x) if EITHER the propensity or the outcome models are right.

    Y and T as in causal.py (shrunk share change; any brand meal in 2023), with
    the same controls including the prior-year trend.

EVALUATION (on held-out folds only)
    Uplift by decile of predicted CATE: mean phi per decile -- a model with real
    signal shows a monotone staircase.
    Qini / AUUC: cumulative uplift captured as more prescribers are targeted,
    against the random diagonal.
    Overlap: the propensity distribution, because uplift is unidentified where
    nobody (or everybody) was treated.

CAVEAT carried into every display: observational, the same selection the
causal module quantifies. It ranks where promotion is ASSOCIATED with
movement; the pilot would test it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import path
from src.ds import features as F
from src.ds.causal import with_treatment
from src.ds.data import n_budget
from src.ds.shrinkage import prepared
from src.ds.tracking import log_run
from src.models.opportunity import hybrid_score
from src.utils.io import get_logger, record, write_parquet

log = get_logger(__name__)

K_FOLDS = 4
CLIP = (0.02, 0.98)


def dr_pseudo_outcome(X: np.ndarray, y: np.ndarray, t: np.ndarray, seed: int = 0):
    fold = F.folds(len(y), K_FOLDS, seed)
    phi, e = np.empty_like(y), np.empty_like(y)
    for k in range(K_FOLDS):
        tr, te = fold != k, fold == k
        ek = np.clip(F.gbm_classifier(seed).fit(X[tr], t[tr]).predict_proba(X[te])[:, 1], *CLIP)
        m1 = F.gbm(seed=seed).fit(X[tr & (t == 1)], y[tr & (t == 1)]).predict(X[te])
        m0 = F.gbm(seed=seed).fit(X[tr & (t == 0)], y[tr & (t == 0)]).predict(X[te])
        tt, yy = t[te], y[te]
        phi[te] = m1 - m0 + tt * (yy - m1) / ek - (1 - tt) * (yy - m0) / (1 - ek)
        e[te] = ek
    return phi, e, fold


def cate_out_of_fold(X: np.ndarray, phi: np.ndarray, fold: np.ndarray, seed: int = 0) -> np.ndarray:
    """Second-stage CATE, predicted only for rows the model did not train on."""
    tau = np.empty_like(phi)
    # Winsorise the pseudo-outcome: inverse-propensity terms are heavy-tailed.
    lo, hi = np.quantile(phi, [0.01, 0.99])
    target = np.clip(phi, lo, hi)
    for k in range(K_FOLDS):
        tr, te = fold != k, fold == k
        tau[te] = F.gbm(seed=seed, max_iter=150).fit(X[tr], target[tr]).predict(X[te])
    return tau


def qini(tau: np.ndarray, phi: np.ndarray, grid: int = 40) -> pd.DataFrame:
    order = np.argsort(-tau)
    cum = np.cumsum(phi[order])
    n = len(tau)
    total = cum[-1]
    rows = [{"fraction_targeted": 0.0, "uplift_model": 0.0, "uplift_random": 0.0}]
    for f in np.linspace(0, 1, grid + 1)[1:]:
        i = max(int(round(f * n)) - 1, 0)
        rows.append({"fraction_targeted": float(f), "uplift_model": float(cum[i] / n),
                     "uplift_random": float(f * total / n)})
    return pd.DataFrame(rows)


def deciles(tau: np.ndarray, phi: np.ndarray) -> pd.DataFrame:
    q = pd.qcut(pd.Series(tau).rank(method="first"), 10, labels=False) + 1
    d = pd.DataFrame({"decile": q, "tau": tau, "phi": phi})
    g = d.groupby("decile").agg(predicted=("tau", "mean"), observed=("phi", "mean"),
                                se=("phi", lambda s: s.std() / np.sqrt(len(s))), n=("phi", "size"))
    return g.reset_index()


def run() -> dict:
    _, apply_, _ = prepared()
    df = with_treatment(apply_).reset_index(drop=True)
    extra = ["log_pay_prior", "food_prior", "prior_growth_share"]
    X, _, _ = F.design(df, extra=extra)
    y = df["eb_growth_share"].to_numpy(dtype=float)
    t = df["treated"].to_numpy(dtype=float)

    phi, e, fold = dr_pseudo_outcome(X, y, t)
    tau = cate_out_of_fold(X, phi, fold)
    # VALUE-ALIGNED, as in shrinkage.py: a share-point effect on a 20-fill
    # prescriber is worth a tenth of the same effect on a 200-fill one. Ranking
    # and evaluating in fills (effect x volume) stops the uplift model from
    # rediscovering the tiny-denominator trap.
    vol = df["class_fills"].clip(lower=0).to_numpy(dtype=float)
    tau_v, phi_v = tau * vol, phi * vol
    curve = qini(tau_v, phi_v)
    dec = deciles(tau, phi)
    dec_v = deciles(tau_v, phi_v)

    # AUUC above random, normalised by the random curve's area.
    auuc = float(np.trapz(curve["uplift_model"] - curve["uplift_random"], curve["fraction_targeted"]))
    k = n_budget()
    lists = {"volume": df["class_fills"].to_numpy(dtype=float),
             "opportunity": df["opportunity"].to_numpy(dtype=float),
             "hybrid": hybrid_score(df).to_numpy(dtype=float),
             "uplift_share_points": tau,
             "uplift_value": tau_v}
    list_uplift = {name: float(phi_v[np.argsort(-s_)[:k]].sum()) for name, s_ in lists.items()}
    list_base = {name: float(np.median(vol[np.argsort(-s_)[:k]])) for name, s_ in lists.items()}

    proc = path("processed")
    write_parquet(curve, proc / "ds_uplift_qini.parquet")
    write_parquet(dec, proc / "ds_uplift_deciles.parquet")
    write_parquet(dec_v, proc / "ds_uplift_value_deciles.parquet")
    write_parquet(pd.DataFrame({"npi": df["npi"], "cate": tau.astype("float32"),
                                "propensity": e.astype("float32")}),
                  proc / "ds_uplift_scores.parquet")
    hist, edges = np.histogram(e, bins=20, range=(0, 1))
    top, bot = dec.iloc[-1], dec.iloc[0]
    res = {
        "n": int(len(df)), "treated_share": round(float(t.mean()), 4),
        "ate_dr_points": round(100 * float(phi.mean()), 3),
        "ate_dr_se_points": round(100 * float(phi.std() / np.sqrt(len(phi))), 3),
        "top_decile_observed_points": round(100 * float(top["observed"]), 3),
        "auuc_units": "branded fills per prescriber",
        "bottom_decile_observed_points": round(100 * float(bot["observed"]), 3),
        "decile_rank_corr": round(float(pd.Series(dec["predicted"]).corr(dec["observed"], method="spearman")), 3),
        "auuc_above_random": round(auuc, 6),
        "list_uplift_fills": {k_: round(v, 0) for k_, v in list_uplift.items()},
        "list_median_base": {k_: round(v, 1) for k_, v in list_base.items()},
        "value_decile_rank_corr": round(float(pd.Series(dec_v["predicted"]).corr(
            dec_v["observed"], method="spearman")), 3),
        "propensity_hist": hist.tolist(), "propensity_edges": edges.round(2).tolist(),
        "share_outside_overlap": round(float(((e <= CLIP[0]) | (e >= CLIP[1])).mean()), 4),
        "reading": "observational; ranks where promotion is associated with movement",
    }
    log.info("UPLIFT (DR-learner): average effect %+.2f pts (se %.2f). Top predicted decile "
             "shows %+.2f pts, bottom %+.2f; decile rank corr %.2f.", res["ate_dr_points"],
             res["ate_dr_se_points"], res["top_decile_observed_points"],
             res["bottom_decile_observed_points"], res["decile_rank_corr"])
    log.info("  share-point uplift picks a median %.0f-fill prescriber (the tiny-denominator "
             "trap again); value uplift picks %.0f.", list_base["uplift_share_points"],
             list_base["uplift_value"])
    log.info("  held-out fill-uplift on each %d-prescriber list: %s", k, res["list_uplift_fills"])
    record("ds_uplift", **res)
    log_run("ds_uplift", params={"learner": "DR-learner, 4-fold cross-fit", "k": k},
            metrics={k_: v for k_, v in res.items() if isinstance(v, (int, float, dict))
                     and k_ not in ("propensity_hist",)},
            artifacts=[proc / "ds_uplift_deciles.parquet", proc / "ds_uplift_qini.parquet"])
    return res


if __name__ == "__main__":
    run()
