"""Uncertainty and sensitivity around the headline claims.

    python -m src.models.robustness

Three things the project asserted without evidence until now:

  1. CONFIDENCE INTERVALS. Every headline was a point estimate. "Flagged
     prescribers grew 1.50x faster" invites exactly one question -- is that
     distinguishable from 1.2x? -- and a point estimate cannot answer it.
     Bootstrapped here over the holdout frame.

  2. TAU SENSITIVITY. The entire opportunity score hangs on a frontier quantile
     of 0.80, chosen because it reads as "a strong comparable prescriber". If a
     five-point change in tau reshuffles the deciles, the ranking is an artefact
     of a hyperparameter and the disagreement finding evaporates. The model is
     refit across a grid and the rankings are compared.

  3. PROPER MATCHING. The headline "1.50x vs volume-matched controls" stratified
     on volume decile ALONE. Meanwhile response.py already contains propensity
     scoring with caliper matching and an SMD balance table. The right tool was
     in the repo and the headline was not using it. It does now, and the balance
     is reported rather than assumed.

None of this changes the analysis. It establishes how much of the analysis
survives being pushed on -- which is the difference between a result and a
number.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from src.config import params, path
from src.models import opportunity as opp
from src.utils.io import get_logger, read_parquet, record, write_parquet

log = get_logger(__name__)

N_BOOT = 400
TAU_GRID = (0.65, 0.70, 0.75, 0.80, 0.85, 0.90)
MATCH_COVARIATES = ["log_class_fills", "brand_share", "log_panel_benes",
                    "risk_score", "log_non_class_clms"]


# --------------------------------------------------------------------------- #
# 1. Bootstrap confidence intervals
# --------------------------------------------------------------------------- #

def _metrics(df: pd.DataFrame, n_budget: int) -> dict[str, float]:
    """The three headline quantities, computed on one (possibly resampled) frame."""
    total_abs = df.loc[df["brand_growth_abs"] > 0, "brand_growth_abs"].sum()
    total_share = df.loc[df["share_growth"] > 0, "share_growth"].sum()

    out: dict[str, float] = {}
    for rule, col in (("opportunity", "opportunity"), ("volume", "class_fills")):
        top = df.nlargest(n_budget, col)
        out[f"{rule}_abs"] = (float(top["brand_growth_abs"].clip(lower=0).sum() / total_abs)
                              if total_abs > 0 else np.nan)
        out[f"{rule}_share"] = (float(top["share_growth"].clip(lower=0).sum() / total_share)
                                if total_share > 0 else np.nan)

    out["share_ratio"] = (out["opportunity_share"] / out["volume_share"]
                          if out["volume_share"] else np.nan)
    out["abs_ratio"] = (out["opportunity_abs"] / out["volume_abs"]
                        if out["volume_abs"] else np.nan)

    lift = df.groupby("opportunity_decile")["brand_growth_abs"].mean()
    out["spearman"] = float(pd.Series(lift.index).corr(
        pd.Series(lift.to_numpy()), method="spearman")) if len(lift) > 2 else np.nan
    return out


def bootstrap_headlines(df: pd.DataFrame, n_boot: int = N_BOOT) -> pd.DataFrame:
    """Percentile bootstrap over prescribers.

    Resampling PRESCRIBERS, not deciles: the sampling unit is the thing that
    would differ in another draw of the world. Percentile intervals rather than
    normal-theory ones because the capture ratios are bounded and skewed, so a
    symmetric interval would put mass in impossible regions.
    """
    n_budget = max(int(0.20 * len(df)), 1)
    rng = np.random.default_rng(0)

    point = _metrics(df, n_budget)
    draws: list[dict[str, float]] = []
    for i in range(n_boot):
        idx = rng.integers(0, len(df), len(df))
        draws.append(_metrics(df.iloc[idx], n_budget))
        if (i + 1) % 100 == 0:
            log.info("  bootstrap %d/%d", i + 1, n_boot)

    boot = pd.DataFrame(draws)
    rows = []
    for metric, value in point.items():
        col = boot[metric].dropna()
        if col.empty:
            continue
        lo, hi = np.percentile(col, [2.5, 97.5])
        rows.append({
            "metric": metric,
            "estimate": round(float(value), 4),
            "ci_low": round(float(lo), 4),
            "ci_high": round(float(hi), 4),
            "se": round(float(col.std()), 4),
            # For the ratios, "beats 1.0" is the question that matters.
            "excludes_one": bool(lo > 1.0) if metric.endswith("_ratio") else None,
        })

    out = pd.DataFrame(rows)
    for r in out.itertuples(index=False):
        log.info("  %-18s %.3f  [%.3f, %.3f]%s", r.metric, r.estimate,
                 r.ci_low, r.ci_high,
                 "  excludes 1.0" if r.excludes_one else
                 ("  SPANS 1.0" if r.excludes_one is False else ""))

    share = out[out["metric"] == "share_ratio"]
    if len(share):
        s = share.iloc[0]
        if s["excludes_one"]:
            log.info("share-growth advantage is significant: %.2fx [%.2f, %.2f]",
                     s["estimate"], s["ci_low"], s["ci_high"])
        else:
            log.warning("SHARE-GROWTH ADVANTAGE IS NOT SIGNIFICANT: %.2fx [%.2f, %.2f] "
                        "spans 1.0. The headline must be reported with this interval, "
                        "not as a point estimate.",
                        s["estimate"], s["ci_low"], s["ci_high"])

    record("bootstrap_headlines", n_boot=n_boot, n_budget=n_budget,
           **{r["metric"]: [r["ci_low"], r["estimate"], r["ci_high"]]
              for r in rows})
    return out


# --------------------------------------------------------------------------- #
# 2. Tau sensitivity
# --------------------------------------------------------------------------- #

def tau_sensitivity(metrics: pd.DataFrame, benchmarks: pd.DataFrame,
                    grid: tuple[float, ...] = TAU_GRID) -> pd.DataFrame:
    """Refit the frontier across a grid of tau and compare the rankings.

    The question is not whether the SCORES change -- they must, tau moves the
    frontier by construction. It is whether the ORDERING changes, because the
    ordering is what the call plan consumes. Spearman against the tau=0.80
    baseline answers that directly.
    """
    fit_year = params()["years"]["train_end"]
    train = metrics[(metrics["year"] == fit_year) & (metrics["class_fills"] > 0)].copy()
    log.info("tau sensitivity: refitting on %s prescribers across %d values",
             f"{len(train):,}", len(grid))

    scores: dict[float, pd.Series] = {}
    deciles: dict[float, pd.Series] = {}
    for tau in grid:
        model, enc, _ = opp.fit_potential(train, tau=tau)
        scored = opp.score_opportunity(train, benchmarks, model, enc)
        scores[tau] = scored.set_index("npi")["opportunity"]
        deciles[tau] = scored.set_index("npi")["opportunity_decile"]
        log.info("  tau=%.2f fitted", tau)

    base = params()["opportunity_model"]["tau"]
    ref_score, ref_dec = scores[base], deciles[base]

    rows = []
    for tau in grid:
        s, d = scores[tau].reindex(ref_score.index), deciles[tau].reindex(ref_dec.index)
        rho = float(ref_score.corr(s, method="spearman"))
        same = float((d == ref_dec).mean())
        within1 = float((d - ref_dec).abs().le(1).mean())
        top_stable = float(
            ((d >= 8) & (ref_dec >= 8)).sum() / max((ref_dec >= 8).sum(), 1))
        rows.append({
            "tau": tau,
            "spearman_vs_base": round(rho, 4),
            "same_decile_pct": round(same, 4),
            "within_one_decile_pct": round(within1, 4),
            "top3_decile_retained": round(top_stable, 4),
        })
        log.info("  tau=%.2f  rho=%.3f  same decile %.1f%%  within 1 %.1f%%  "
                 "top-3 retained %.1f%%",
                 tau, rho, 100 * same, 100 * within1, 100 * top_stable)

    out = pd.DataFrame(rows)
    off = out[out["tau"] != base]

    # Graded, not binary. Sensitivity is a function of how far you move, and
    # collapsing that into pass/fail throws away the only useful information:
    # the NEAR band is the range a reasonable analyst might have picked instead,
    # while the FAR band tests values that stop meaning "a strong prescriber"
    # at all. Robustness inside the near band is the claim worth making.
    near = off[(off["tau"] - base).abs() <= 0.05]
    far = off[(off["tau"] - base).abs() > 0.05]

    near_rho = float(near["spearman_vs_base"].min()) if len(near) else 1.0
    near_top = float(near["top3_decile_retained"].min()) if len(near) else 1.0
    far_rho = float(far["spearman_vs_base"].min()) if len(far) else 1.0
    far_top = float(far["top3_decile_retained"].min()) if len(far) else 1.0

    robust_near = near_rho >= 0.95 and near_top >= 0.90
    log.info("tau +/-0.05 (a defensible alternative choice): rho >= %.3f, "
             "top-3 retention >= %.0f%%", near_rho, 100 * near_top)
    log.info("tau +/-0.15 (past where 'strong prescriber' still means anything): "
             "rho >= %.3f, top-3 retention >= %.0f%%", far_rho, 100 * far_top)

    if robust_near:
        log.info("VERDICT: the ranking is robust to tau within the range anyone would "
                 "reasonably have chosen. It degrades gracefully beyond that -- worst "
                 "case still rho %.3f -- so tau is a tuning choice, not the finding. "
                 "Report the near band; do not claim invariance.", far_rho)
    else:
        log.warning("VERDICT: the ranking moves materially even for a small change in "
                    "tau (rho %.3f at +/-0.05). The disagreement finding is partly an "
                    "artefact of the chosen quantile and must be reported as such.",
                    near_rho)

    record("tau_sensitivity", grid=list(grid), base=base,
           near_band_spearman=round(near_rho, 4),
           near_band_top3_retention=round(near_top, 4),
           far_band_spearman=round(far_rho, 4),
           far_band_top3_retention=round(far_top, 4),
           robust_within_near_band=bool(robust_near))
    return out


# --------------------------------------------------------------------------- #
# 3. Propensity-matched comparison (replacing single-variable stratification)
# --------------------------------------------------------------------------- #

def _smd(a: pd.Series, b: pd.Series) -> float:
    pooled = np.sqrt((a.std() ** 2 + b.std() ** 2) / 2.0)
    return float((a.mean() - b.mean()) / pooled) if pooled > 0 else 0.0


def propensity_matched_growth(df: pd.DataFrame, caliper: float = 0.2) -> dict:
    """Match flagged to unflagged on a propensity score, then compare growth.

    Replaces stratification on volume decile alone. Matching on one covariate
    and calling the groups comparable is the criticism this removes -- and the
    machinery already existed in response.py, it simply was not being used for
    the headline.
    """
    d = df.copy()
    d["log_class_fills"] = np.log1p(d["class_fills"].clip(lower=0))
    d["log_panel_benes"] = np.log1p(d.get("panel_benes", pd.Series(0, index=d.index)).fillna(0))
    d["log_non_class_clms"] = np.log1p(d.get("non_class_clms", pd.Series(0, index=d.index)).fillna(0))
    d["brand_share"] = d["brand_share"].fillna(0.0)
    d["risk_score"] = d.get("risk_score", pd.Series(1.0, index=d.index)).fillna(1.0)

    covs = [c for c in MATCH_COVARIATES if c in d.columns and d[c].notna().any()]
    d = d.dropna(subset=covs)
    if d["flagged"].sum() < 30 or (~d["flagged"]).sum() < 30:
        return {"computable": False}

    X = StandardScaler().fit_transform(d[covs].to_numpy(dtype=float))
    y = d["flagged"].to_numpy(dtype=int)
    ps = LogisticRegression(max_iter=1000).fit(X, y).predict_proba(X)[:, 1]
    d["ps_logit"] = np.log(np.clip(ps, 1e-6, 1 - 1e-6) / (1 - np.clip(ps, 1e-6, 1 - 1e-6)))

    treated = d[d["flagged"]].sort_values("ps_logit").reset_index(drop=True)
    control = d[~d["flagged"]].sort_values("ps_logit").reset_index(drop=True)
    cvals = control["ps_logit"].to_numpy()
    used = np.zeros(len(control), dtype=bool)
    cap = caliper * d["ps_logit"].std()

    ti, ci = [], []
    for i, row in treated.iterrows():
        diffs = np.abs(cvals - row["ps_logit"])
        diffs[used] = np.inf
        j = int(np.argmin(diffs))
        if diffs[j] <= cap:
            used[j] = True
            ti.append(i)
            ci.append(j)

    if not ti:
        return {"computable": False}

    mt, mc = treated.loc[ti], control.loc[ci]

    balance = [{"covariate": c,
                "smd_before": round(_smd(d.loc[d["flagged"], c], d.loc[~d["flagged"], c]), 4),
                "smd_after": round(_smd(mt[c], mc[c]), 4)} for c in covs]
    worst = max(abs(b["smd_after"]) for b in balance)

    t_growth = float(mt["brand_growth_abs"].mean())
    c_growth = float(mc["brand_growth_abs"].mean())
    diff = mt["brand_growth_abs"].to_numpy() - mc["brand_growth_abs"].to_numpy()
    se = float(diff.std(ddof=1) / np.sqrt(len(diff)))

    res = {
        "computable": True,
        "n_pairs": len(ti),
        "n_covariates": len(covs),
        "worst_smd_after": round(worst, 4),
        "balanced": bool(worst < 0.10),
        "flagged_mean_growth": round(t_growth, 3),
        "control_mean_growth": round(c_growth, 3),
        "growth_ratio": round(t_growth / c_growth, 3) if c_growth > 0 else None,
        "paired_difference": round(float(diff.mean()), 3),
        "paired_se": round(se, 3),
        "ci_low": round(float(diff.mean() - 1.96 * se), 3),
        "ci_high": round(float(diff.mean() + 1.96 * se), 3),
        "balance": balance,
    }
    log.info("propensity-matched on %d covariates: %s pairs, worst SMD %.3f (%s)",
             len(covs), f"{len(ti):,}", worst,
             "balanced" if res["balanced"] else "IMBALANCED")
    log.info("  flagged %.2f vs matched control %.2f fills (%.2fx); paired difference "
             "%+.2f [%.2f, %.2f]",
             t_growth, c_growth, res["growth_ratio"] or 0,
             res["paired_difference"], res["ci_low"], res["ci_high"])
    if res["ci_low"] <= 0:
        log.warning("  the paired difference CI includes zero -- the matched advantage "
                    "is not statistically distinguishable from none.")
    record("propensity_matched", **{k: v for k, v in res.items() if k != "balance"})
    return res


# --------------------------------------------------------------------------- #

def run() -> dict:
    proc = path("processed")
    frame = read_parquet(proc / "backtest_frame.parquet")
    metrics = read_parquet(proc / "mart_hcp_metrics.parquet")
    benchmarks = read_parquet(proc / "mart_peer_benchmarks.parquet")

    # backtest_frame carries only the columns the back-test needed; matching
    # wants the practice covariates too.
    fit_year = params()["years"]["train_end"]
    extra = metrics[metrics["year"] == fit_year][
        ["npi", "panel_benes", "risk_score", "non_class_clms", "brand_share"]]
    frame = frame.merge(extra, on="npi", how="left", suffixes=("", "_m"))
    if "brand_share" not in frame.columns and "brand_share_m" in frame.columns:
        frame["brand_share"] = frame["brand_share_m"]
    if "share_growth" not in frame.columns:
        frame["share_growth"] = 0.0

    log.info("=" * 70)
    log.info("1/3  BOOTSTRAP CONFIDENCE INTERVALS")
    log.info("=" * 70)
    boot = bootstrap_headlines(frame)
    write_parquet(boot, proc / "robustness_bootstrap.parquet")

    log.info("=" * 70)
    log.info("2/3  TAU SENSITIVITY")
    log.info("=" * 70)
    taus = tau_sensitivity(metrics, benchmarks)
    write_parquet(taus, proc / "robustness_tau.parquet")

    log.info("=" * 70)
    log.info("3/3  PROPENSITY-MATCHED GROWTH")
    log.info("=" * 70)
    matched = propensity_matched_growth(frame)
    if matched.get("computable"):
        write_parquet(pd.DataFrame(matched["balance"]),
                      proc / "robustness_balance.parquet")

    return {"bootstrap": boot, "tau": taus, "matched": matched}


if __name__ == "__main__":
    run()
