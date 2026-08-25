"""Promotional response: does payment exposure associate with brand share?

THE HONEST FRAMING, STATED FIRST
--------------------------------
Manufacturers direct payments toward prescribers who are ALREADY high-volume
and already favourable. That is the whole point of a targeting operation. So the
raw correlation between payment receipt and brand share is guaranteed to be
positive and guaranteed to overstate any causal effect. Every number this module
produces should be read as an UPPER BOUND.

Four steps, each one strictly weaker in its assumptions than the last is strong:

    1. NAIVE OLS. log-log elasticity. Reported precisely so the gap between it
       and the matched estimate is visible -- that gap IS the selection effect,
       and showing it is more persuasive than any single coefficient.

    2. PRE-TREND TEST. Before claiming a difference-in-differences design, check
       that treated and control prescribers moved in parallel BEFORE treatment.
       Three years exist for exactly this reason. If pre-trends diverge, the
       identifying assumption fails and the causal language comes out -- a
       decision pre-committed in CHARTER.md.

    3. PROPENSITY-SCORE MATCHING on pre-period volume, share, specialty, region
       and panel size, with standardised mean differences reported before and
       after. Balance is shown, not asserted.

    4. DiD on the matched cohort, with the Hill saturation curve fitted on the
       matched sample to feed sizing.py.

WHAT WOULD MAKE THIS CAUSAL AND DOES NOT EXIST HERE
---------------------------------------------------
Random or quasi-random assignment of promotional exposure. There is none.
Matching balances OBSERVED covariates only; a prescriber's unobserved enthusiasm
for the drug drives both payment receipt and prescribing, and no amount of
matching on Part D variables touches it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from src.config import params, path
from src.utils.io import get_logger, read_parquet, record, write_parquet

log = get_logger(__name__)

MATCH_COVARIATES = ["log_class_fills_pre", "brand_share_pre", "log_panel_benes",
                    "risk_score", "log_non_class_clms"]

SMD_THRESHOLD = 0.10


def build_cohort(metrics: pd.DataFrame, onset: pd.DataFrame,
                 payments: pd.DataFrame) -> pd.DataFrame:
    """Wide per-NPI frame with pre/post outcomes and a clean treatment flag."""
    p = params()
    yrs = sorted(p["years"]["all"])
    y0, y1, y2 = yrs[0], yrs[1], yrs[2]

    def slice_year(y, suffix):
        return (metrics[metrics["year"] == y]
                [["npi", "class_fills", "brand_fills", "brand_share",
                  "panel_benes", "risk_score", "non_class_clms",
                  "specialty_group", "region", "state"]]
                .rename(columns={c: f"{c}_{suffix}" for c in
                                 ["class_fills", "brand_fills", "brand_share"]}))

    df = (slice_year(y0, "y0")
          .merge(slice_year(y1, "y1")[["npi", "class_fills_y1", "brand_fills_y1",
                                       "brand_share_y1"]], on="npi")
          .merge(slice_year(y2, "y2")[["npi", "class_fills_y2", "brand_fills_y2",
                                       "brand_share_y2"]], on="npi"))

    df = df.merge(onset, on="npi", how="left")

    # Treated: first focus-brand payment arrives in the treatment year.
    # Excluded from BOTH arms: anyone already receiving payments in y0 -- their
    # pre-period is contaminated and there is no clean baseline to difference.
    treat_year = p["response_model"]["treatment_year"]
    already = df["first_any_pay_year"].notna() & (df["first_any_pay_year"] <= y0)
    df = df[~already].copy()

    df["treated"] = (df["first_focus_pay_year"] == treat_year).fillna(False)
    df["control"] = df["first_focus_pay_year"].isna()
    df = df[df["treated"] | df["control"]].copy()

    pay_amt = (payments[payments["year"] == treat_year]
               .groupby("npi")["pay_focus"].sum().rename("pay_amount"))
    df = df.merge(pay_amt, on="npi", how="left")
    df["pay_amount"] = df["pay_amount"].fillna(0.0)

    df["log_class_fills_pre"] = np.log1p(df["class_fills_y1"])
    df["brand_share_pre"] = df["brand_share_y1"].fillna(0.0)
    df["log_panel_benes"] = np.log1p(df["panel_benes"].fillna(0))
    df["log_non_class_clms"] = np.log1p(df["non_class_clms"].fillna(0))
    df["risk_score"] = df["risk_score"].fillna(df["risk_score"].median())

    df["pre_delta"] = (df["brand_share_y1"] - df["brand_share_y0"]).fillna(0.0)
    df["post_delta"] = (df["brand_share_y2"] - df["brand_share_y1"]).fillna(0.0)

    log.info("cohort: %d treated, %d control (%d excluded for pre-period payments)",
             int(df["treated"].sum()), int(df["control"].sum()), int(already.sum()))
    return df


def naive_elasticity(df: pd.DataFrame) -> dict:
    """log-log OLS. Reported to expose how much the matched estimate shrinks it."""
    d = df[df["brand_fills_y2"] > 0].copy()
    y = np.log(d["brand_fills_y2"])
    X = np.column_stack([
        np.ones(len(d)),
        np.log1p(d["pay_amount"]),
        np.log1p(d["class_fills_y1"]),
        d["brand_share_pre"],
    ])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = max(len(d) - X.shape[1], 1)
    sigma2 = float(resid @ resid) / dof
    try:
        se = np.sqrt(np.diag(sigma2 * np.linalg.inv(X.T @ X)))
    except np.linalg.LinAlgError:
        se = np.full(X.shape[1], np.nan)

    res = {"elasticity": round(float(beta[1]), 5),
           "se": round(float(se[1]), 5),
           "ci_low": round(float(beta[1] - 1.96 * se[1]), 5),
           "ci_high": round(float(beta[1] + 1.96 * se[1]), 5),
           "n": len(d)}
    log.info("naive OLS elasticity of brand fills to payments: %.4f "
             "(95%% CI %.4f to %.4f) -- SELECTION-CONTAMINATED, upper bound only",
             res["elasticity"], res["ci_low"], res["ci_high"])
    record("response_naive_ols", **res)
    return res


def standardised_mean_diff(a: pd.Series, b: pd.Series) -> float:
    sa, sb = a.std(), b.std()
    pooled = np.sqrt((sa ** 2 + sb ** 2) / 2.0)
    return float((a.mean() - b.mean()) / pooled) if pooled > 0 else 0.0


def pretrend_test(df: pd.DataFrame) -> dict:
    """Welch t-test on PRE-period share movement, treated vs control.

    The parallel-trends assumption cannot be proven, only failed to be rejected.
    A non-significant difference is weak evidence FOR the design; a significant
    one is strong evidence against it.
    """
    t = df.loc[df["treated"], "pre_delta"]
    c = df.loc[df["control"], "pre_delta"]
    if len(t) < 10 or len(c) < 10:
        return {"computable": False}

    se = np.sqrt(t.var() / len(t) + c.var() / len(c))
    diff = float(t.mean() - c.mean())
    tstat = diff / se if se > 0 else 0.0
    from scipy import stats
    dof = (t.var() / len(t) + c.var() / len(c)) ** 2 / (
        (t.var() / len(t)) ** 2 / (len(t) - 1) + (c.var() / len(c)) ** 2 / (len(c) - 1))
    pval = float(2 * (1 - stats.t.cdf(abs(tstat), dof)))

    passed = pval > 0.05
    res = {"computable": True, "treated_pre_delta": round(float(t.mean()), 5),
           "control_pre_delta": round(float(c.mean()), 5),
           "difference": round(diff, 5), "t_stat": round(float(tstat), 3),
           "p_value": round(pval, 4), "parallel_trends_holds": bool(passed),
           "smd": round(standardised_mean_diff(t, c), 4)}

    if passed:
        log.info("PRE-TREND TEST PASSED: treated and control moved in parallel before "
                 "treatment (diff %.4f share points, p=%.3f). DiD is defensible.",
                 diff, pval)
    else:
        log.warning("PRE-TREND TEST FAILED: treated and control were ALREADY diverging "
                    "before treatment (diff %.4f, p=%.4f). Per CHARTER.md the DiD "
                    "estimate must be reported as an ASSOCIATION and all causal language "
                    "removed from the README and the UI.", diff, pval)
    record("response_pretrend", **res)
    return res


def propensity_match(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """1:1 nearest-neighbour matching on the propensity logit, with a caliper."""
    cfg = params()["response_model"]
    d = df.dropna(subset=MATCH_COVARIATES).copy()

    X = StandardScaler().fit_transform(d[MATCH_COVARIATES].to_numpy(dtype=float))
    y = d["treated"].to_numpy(dtype=int)
    if y.sum() < 10 or (1 - y).sum() < 10:
        log.warning("too few treated or control units to match")
        return d.iloc[:0], pd.DataFrame()

    lr = LogisticRegression(max_iter=1000).fit(X, y)
    ps = lr.predict_proba(X)[:, 1].clip(1e-6, 1 - 1e-6)
    d["ps_logit"] = np.log(ps / (1 - ps))

    treated = d[d["treated"]].sort_values("ps_logit").reset_index(drop=True)
    control = d[~d["treated"]].sort_values("ps_logit").reset_index(drop=True)
    caliper = cfg["psm_caliper"] * d["ps_logit"].std()

    c_vals = control["ps_logit"].to_numpy()
    used = np.zeros(len(control), dtype=bool)
    pairs = []
    for _, row in treated.iterrows():
        # Nearest unused control within the caliper.
        diffs = np.abs(c_vals - row["ps_logit"])
        diffs[used] = np.inf
        j = int(np.argmin(diffs))
        if diffs[j] <= caliper:
            used[j] = True
            pairs.append((row["npi"], control.iloc[j]["npi"]))

    if not pairs:
        log.warning("no matches formed within the caliper")
        return d.iloc[:0], pd.DataFrame()

    t_ids = [a for a, _ in pairs]
    c_ids = [b for _, b in pairs]
    matched = pd.concat([d[d["npi"].isin(t_ids)], d[d["npi"].isin(c_ids)]])

    # Balance table -- SMD before and after. This is the love plot's data.
    bal = []
    for cov in MATCH_COVARIATES:
        bal.append({
            "covariate": cov,
            "smd_before": round(standardised_mean_diff(
                d.loc[d["treated"], cov], d.loc[~d["treated"], cov]), 4),
            "smd_after": round(standardised_mean_diff(
                matched.loc[matched["treated"], cov],
                matched.loc[~matched["treated"], cov]), 4),
        })
    balance = pd.DataFrame(bal)
    worst = balance["smd_after"].abs().max()
    log.info("matched %d pairs; worst post-match SMD %.3f (threshold %.2f) -- %s",
             len(pairs), worst, SMD_THRESHOLD,
             "balanced" if worst < SMD_THRESHOLD else "IMBALANCED, interpret with care")
    record("response_matching", n_pairs=len(pairs), worst_smd_after=round(float(worst), 4),
           balanced=bool(worst < SMD_THRESHOLD))
    return matched, balance


def did_estimate(matched: pd.DataFrame, pretrend: dict) -> dict:
    """DiD on the matched cohort, with state-clustered standard errors."""
    if matched.empty:
        return {"computable": False}

    t_post = matched.loc[matched["treated"], "post_delta"]
    c_post = matched.loc[~matched["treated"], "post_delta"]
    t_pre = matched.loc[matched["treated"], "pre_delta"]
    c_pre = matched.loc[~matched["treated"], "pre_delta"]

    did = float((t_post.mean() - c_post.mean()) - (t_pre.mean() - c_pre.mean()))

    # Cluster-robust SE by state: prescribers in a state share formulary and
    # payer shocks, so treating them as independent understates the SE.
    clusters = []
    for _st, grp in matched.groupby("state"):
        gt, gc = grp[grp["treated"]], grp[~grp["treated"]]
        if len(gt) < 2 or len(gc) < 2:
            continue
        clusters.append((gt["post_delta"].mean() - gc["post_delta"].mean())
                        - (gt["pre_delta"].mean() - gc["pre_delta"].mean()))
    se = float(np.std(clusters) / np.sqrt(len(clusters))) if len(clusters) > 1 else np.nan

    res = {"computable": True, "did_estimate": round(did, 5),
           "cluster_se": round(se, 5) if np.isfinite(se) else None,
           "ci_low": round(did - 1.96 * se, 5) if np.isfinite(se) else None,
           "ci_high": round(did + 1.96 * se, 5) if np.isfinite(se) else None,
           "n_clusters": len(clusters), "n_matched": len(matched),
           "interpretation": ("CAUSAL (pre-trends hold, observational caveats apply)"
                              if pretrend.get("parallel_trends_holds")
                              else "ASSOCIATION ONLY -- pre-trend test failed")}
    log.info("DiD: %+.4f share points (SE %.4f, %d state clusters) -- %s",
             did, se if np.isfinite(se) else float("nan"), len(clusters),
             res["interpretation"])
    record("response_did", **res)
    return res


def fit_saturation(matched: pd.DataFrame) -> pd.DataFrame:
    """Hill curve of share response against payment dollars, with bootstrap CI."""
    from scipy.optimize import curve_fit

    d = matched[matched["pay_amount"] >= 0].copy()
    x = d["pay_amount"].to_numpy(dtype=float)
    y = d["post_delta"].to_numpy(dtype=float)
    if len(d) < 50 or x.max() <= 0:
        log.warning("insufficient payment variation to fit a saturation curve")
        return pd.DataFrame()

    def model(xx, ceiling, half):
        return ceiling * xx / (np.maximum(half, 1e-6) + xx)

    # BOUNDS ARE REQUIRED, not cosmetic. Unbounded, curve_fit will happily
    # return a negative half-saturation constant when the underlying response is
    # negative (as it is here whenever the matched DiD comes out below zero).
    # A negative half-saturation has no interpretation -- it implies response
    # rises without limit as spend falls -- and it would flow straight into
    # sizing.py as a Hill parameter. Constrain to the feasible region and let
    # the fit fail honestly instead.
    try:
        popt, _ = curve_fit(model, x, y, p0=[0.05, max(np.median(x[x > 0]), 1.0)],
                            bounds=([0.0, 1e-3], [1.0, np.inf]), maxfev=20000)
    except (RuntimeError, ValueError):
        log.warning("saturation curve did not converge")
        return pd.DataFrame()

    if popt[0] <= 1e-4:
        log.warning("SATURATION CURVE NOT IDENTIFIABLE: the fitted ceiling is ~0, i.e. "
                    "the matched data show no positive share response to payment spend. "
                    "No inflection point is reported and sizing.py falls back to the "
                    "configured base in economics.yaml. Reporting a curve here would be "
                    "inventing a relationship the data does not contain.")
        record("response_saturation", identifiable=False, fitted_ceiling=float(popt[0]))
        return pd.DataFrame()

    # A CEILING ABOVE THE FLOOR IS NOT ENOUGH -- THE BEND MUST BE INSIDE THE DATA.
    # On a response with no curvature, curve_fit satisfies the ceiling bound by
    # pushing the half-saturation far outside the observed spend range and
    # returning the near-linear left tail of a Hill curve. Observed once on a
    # flat response: ceiling 0.0213 with half-saturation at $82,125,313 against a
    # maximum payment of $20,000 -- and a straight-faced "90% of maximum response
    # at $739,127,820" in the log.
    #
    # That is not a saturating curve, it is a line through the origin fitted on a
    # scale the data cannot see, and sizing.py would consume it as a Hill
    # parameter implying unbounded linear returns to spend. If the response does
    # not reach half its ceiling anywhere in the observed range, the saturation
    # point is not identified and the honest answer is to say so.
    x_max = float(x.max())
    if popt[1] > x_max:
        log.warning("SATURATION CURVE NOT IDENTIFIABLE: half-saturation fitted at "
                    "$%.0f, beyond the largest observed payment of $%.0f. The response "
                    "never reaches half its ceiling inside the data, so the bend is "
                    "extrapolated rather than measured. Refusing rather than reporting "
                    "an inflection point the spend range cannot support.",
                    popt[1], x_max)
        record("response_saturation", identifiable=False,
               fitted_ceiling=float(popt[0]),
               fitted_half_saturation_usd=float(popt[1]),
               max_observed_payment_usd=x_max,
               reason="half_saturation_outside_observed_range")
        return pd.DataFrame()

    rng = np.random.default_rng(0)
    boots = []
    for _ in range(200):
        idx = rng.choice(len(d), len(d), replace=True)
        try:
            b, _ = curve_fit(model, x[idx], y[idx], p0=popt,
                             bounds=([0.0, 1e-3], [1.0, np.inf]), maxfev=8000)
            boots.append(b)
        except (RuntimeError, ValueError):
            continue
    boots = np.array(boots) if boots else popt[None, :]

    grid = np.linspace(0, float(np.percentile(x, 99)), 80)
    curve = pd.DataFrame({
        "payment_usd": grid,
        "predicted_share_delta": model(grid, *popt),
        "ci_low": np.percentile([model(grid, *b) for b in boots], 2.5, axis=0),
        "ci_high": np.percentile([model(grid, *b) for b in boots], 97.5, axis=0),
    })

    ceiling, half = float(popt[0]), float(popt[1])
    log.info("saturation: ceiling %.4f share points, half-saturation at $%.0f, "
             "90%% of maximum response at $%.0f", ceiling, half, 9 * half)
    record("response_saturation", identifiable=True,
           ceiling=round(ceiling, 5), half_saturation_usd=round(half, 2),
           ninety_pct_usd=round(9 * half, 2),
           ceiling_ci=[round(float(np.percentile(boots[:, 0], 2.5)), 5),
                       round(float(np.percentile(boots[:, 0], 97.5)), 5)])
    return curve


def run() -> dict:
    proc = path("processed")
    metrics = read_parquet(proc / "mart_hcp_metrics.parquet")
    onset = read_parquet(proc / "mart_payment_onset.parquet")
    payments = read_parquet(proc / "mart_payments.parquet")

    cohort = build_cohort(metrics, onset, payments)
    naive = naive_elasticity(cohort)
    pretrend = pretrend_test(cohort)
    matched, balance = propensity_match(cohort)
    did = did_estimate(matched, pretrend)
    curve = fit_saturation(matched) if not matched.empty else pd.DataFrame()

    if not balance.empty:
        write_parquet(balance, proc / "response_balance.parquet")
    if not curve.empty:
        write_parquet(curve, proc / "response_saturation.parquet")

    # The selection gap: how much the naive estimate shrinks once matched.
    if did.get("computable"):
        log.info("SELECTION GAP -- naive OLS elasticity %.4f vs matched DiD %.4f share "
                 "points. The difference is what targeting-by-design buys the "
                 "manufacturer, and it is why the naive number must never be quoted alone.",
                 naive["elasticity"], did["did_estimate"])

    return {"naive": naive, "pretrend": pretrend, "did": did}


if __name__ == "__main__":
    run()
