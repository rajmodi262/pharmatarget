"""Potential and opportunity model -- the analytical centrepiece.

THE ARGUMENT
------------
The industry default is to rank prescribers by observed prescription volume and
call the top deciles. That rule is structurally wrong. A cardiologist writing
400 class fills a year at 91% brand share has almost nothing left to win; an
internist writing 120 fills at 6% share, in a county with high stroke
prevalence and an elderly panel, has a great deal. Volume ranking cannot tell
those two apart, because volume is the wrong quantity. The right one is:

    opportunity = (what this prescriber could reasonably reach)
                -  (what they currently give us)

METHOD -- peer-frontier quantile regression
-------------------------------------------
1. Fit a gradient-boosted QUANTILE regression at tau = 0.80 predicting log class
   volume from market and practice covariates only. The conditional mean would
   answer "what does a typical prescriber like this write?"; the 80th percentile
   answers "what does a strong prescriber like this write?", which is the
   achievable frontier and the quantity a targeting model actually needs.

2. potential_class = exp(prediction).

3. achievable_share = the 75th percentile of brand share inside the
   prescriber's (specialty group x census region) peer cell, computed in SQL 04
   with a fallback for thin cells.

4. opportunity = potential_class * achievable_share - brand_fills, floored at 0.

WHY NOT STOCHASTIC FRONTIER ANALYSIS
------------------------------------
SFA is the textbook approach and would be defensible. It requires assuming a
distribution for the inefficiency term (half-normal or exponential) and is
awkward with the strong specialty interactions here. Quantile GBM reaches the
same frontier interpretation without that distributional assumption and handles
the interactions natively. ``crosscheck_against_sfa()`` fits a linear frontier
approximation on a sample and reports rank correlation, so the claim that the
two agree is measured rather than asserted.

LEAKAGE
-------
No feature may contain class or brand volume. The panel-size proxy is
``non_class_clms`` -- total Part D claims with the therapeutic class netted out
(see SQL 04). ``assert_no_leakage()`` runs on every fit and raises rather than
warns, because a leaked target here would silently invalidate the back-test and
every number that depends on it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.inspection import permutation_importance
from sklearn.metrics import make_scorer, mean_pinball_loss
from sklearn.preprocessing import OneHotEncoder

from src.config import params, path
from src.utils.io import get_logger, read_parquet, record, write_parquet

log = get_logger(__name__)

# Practice and market covariates. Deliberately explicit: a new feature has to be
# added here by hand, which forces the leakage question to be asked each time.
NUMERIC_FEATURES = [
    # Practice scale (from CMS)
    "log_panel_benes",
    "log_non_class_clms",
    "risk_score",
    "log_age65_cnt",
    "pct_panel_65",
    # Local market (from Census Gazetteer x CDC PLACES)
    "log_zip3_population",
    "log_pop_density",
    "prev_stroke",
    "prev_chd",
    "prev_bp",
]
CATEGORICAL_FEATURES = ["specialty_group", "region"]

# Features the model can run without. If the geography build did not supply
# PLACES prevalence, the model still fits -- it just leans harder on practice
# size, which is the exact failure mode gate G2 watches for. Dropping a
# covariate is logged loudly rather than silently tolerated.
OPTIONAL_FEATURES = {"log_zip3_population", "log_pop_density",
                     "prev_stroke", "prev_chd", "prev_bp"}

# The feature list actually in use, resolved once by fit_potential() and read by
# every scoring path. Module-level so predict/SHAP/cross-check cannot silently
# disagree with the fit about which columns the design matrix contains.
_FEATURES: list[str] = list(NUMERIC_FEATURES)

# Anything whose name contains one of these is target-adjacent and must never
# reach the design matrix.
FORBIDDEN_TOKENS = ("class_fills", "brand", "share", "growth", "opportunity",
                    "decile", "class_clms", "class_cost", "class_drug_rows")

# Explicit exemptions from the substring check. `non_class_clms` is total Part D
# claims with the therapeutic class REMOVED -- it is the panel-size proxy and is
# the opposite of a leak -- but it contains the substring 'class_clms'. Rather
# than loosen the token list (which would let a real leak through), each
# exemption is named here and has to be justified in this comment.
EXEMPT_FEATURES = {"log_non_class_clms"}

LEAK_CORRELATION_THRESHOLD = 0.97


def active_features(df: pd.DataFrame) -> list[str]:
    """Which numeric features are actually usable on this data.

    A feature is dropped when it is absent or entirely null -- which happens
    when the geography build ran without CDC PLACES. Dropping is announced, not
    silent: a model quietly missing every market covariate looks fine in the
    logs and fails gate G2 for reasons nobody can see.
    """
    usable, dropped = [], []
    for col in NUMERIC_FEATURES:
        source = {"log_zip3_population": "zip3_population",
                  "log_pop_density": "zip3_pop_density"}.get(col, col)
        base = source.replace("log_", "") if source.startswith("log_") else source
        present = (base in df.columns) and df[base].notna().any()
        if present:
            usable.append(col)
        elif col in OPTIONAL_FEATURES:
            dropped.append(col)
        else:
            raise ValueError(
                f"Required feature '{col}' is missing or all-null. The mart did "
                f"not build correctly -- check src/sql/04_mart_hcp_metrics.sql.")
    if dropped:
        log.warning("DROPPING %d market covariate(s) -- not present in the data: %s. "
                    "The potential model will lean harder on practice size; check "
                    "the SHAP output before trusting gate G2.", len(dropped), dropped)
    return usable


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Derive model inputs. Logs are applied to every heavy-tailed count."""
    out = df.copy()
    out["log_panel_benes"] = np.log1p(out["panel_benes"].fillna(0))
    out["log_non_class_clms"] = np.log1p(out["non_class_clms"].fillna(0))
    out["log_age65_cnt"] = np.log1p(out["age65_cnt"].fillna(0))
    if "zip3_population" in out:
        out["log_zip3_population"] = np.log1p(out["zip3_population"].fillna(0))
    if "zip3_pop_density" in out:
        out["log_pop_density"] = np.log1p(out["zip3_pop_density"].fillna(0))
    out["risk_score"] = out["risk_score"].fillna(out["risk_score"].median())
    for col in ("pct_panel_65", "prev_stroke", "prev_chd", "prev_bp"):
        if col in out.columns and out[col].notna().any():
            out[col] = out[col].fillna(out[col].median())
    for col in CATEGORICAL_FEATURES:
        out[col] = out[col].fillna("Unknown").astype(str)
    return out


def assert_no_leakage(X: pd.DataFrame, y: pd.Series, feature_names: list[str]) -> None:
    """Raise if any feature is target-derived. Raises, never warns.

    Two independent checks: a name check that catches the obvious mistake, and a
    correlation check that catches the subtle one (a feature that is a
    near-deterministic function of the target under a different name).
    """
    for name in feature_names:
        if name in EXEMPT_FEATURES:
            continue
        low = name.lower()
        for token in FORBIDDEN_TOKENS:
            if token in low:
                raise ValueError(
                    f"Leakage: feature '{name}' contains forbidden token '{token}'. "
                    f"The potential model must not see class or brand volume. "
                    f"If this is a false positive, add it to EXEMPT_FEATURES with "
                    f"a written justification."
                )

    arr = np.asarray(X, dtype=float)
    yv = np.asarray(y, dtype=float)
    for j, name in enumerate(feature_names):
        col = arr[:, j]
        if np.std(col) < 1e-12:
            continue
        r = abs(np.corrcoef(col, yv)[0, 1])
        if r > LEAK_CORRELATION_THRESHOLD:
            raise ValueError(
                f"Leakage: feature '{name}' correlates with the target at r={r:.4f}, "
                f"above the {LEAK_CORRELATION_THRESHOLD} threshold. "
                f"It is almost certainly a transform of class volume."
            )
    log.info("leakage check passed: %d features, max |r| with target = %.3f",
             len(feature_names),
             max((abs(np.corrcoef(arr[:, j], yv)[0, 1])
                  for j in range(arr.shape[1]) if np.std(arr[:, j]) > 1e-12), default=0.0))


def fit_potential(train: pd.DataFrame, tau: float | None = None) -> tuple:
    """Fit the tau-quantile frontier. Returns (model, encoder, feature_names)."""
    global _FEATURES
    cfg = params()["opportunity_model"]
    tau = tau if tau is not None else cfg["tau"]

    feat = build_features(train)
    _FEATURES = active_features(feat)
    enc = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    cat = enc.fit_transform(feat[CATEGORICAL_FEATURES])
    cat_names = list(enc.get_feature_names_out(CATEGORICAL_FEATURES))

    X = np.hstack([feat[_FEATURES].to_numpy(dtype=float), cat])
    names = _FEATURES + cat_names
    y = np.log1p(feat["class_fills"].to_numpy(dtype=float))

    assert_no_leakage(pd.DataFrame(X, columns=names), pd.Series(y), names)

    # Histogram-based boosting, not the exact-split GradientBoostingRegressor.
    # At 1.4M prescribers x 21 features the exact splitter takes the better part
    # of an hour per fit, and the back-test refits from scratch on purpose. The
    # histogram implementation bins the features first and finishes in minutes
    # with the same quantile-loss objective -- a different implementation of the
    # same estimator, not a different model.
    model = HistGradientBoostingRegressor(
        loss="quantile",
        quantile=tau,
        max_iter=cfg["n_estimators"],
        max_depth=cfg["max_depth"],
        learning_rate=cfg["learning_rate"],
        min_samples_leaf=cfg["min_samples_leaf"],
        random_state=cfg["random_state"],
        early_stopping=False,
    )
    model.fit(X, y)

    # Coverage check: by construction ~tau of observations should sit BELOW the
    # fitted frontier. A wildly different figure means the quantile loss did not
    # converge and the "frontier" interpretation is unearned.
    coverage = float((y <= model.predict(X)).mean())
    log.info("frontier fit: tau=%.2f, in-sample coverage=%.3f (target %.2f), n=%d",
             tau, coverage, tau, len(y))
    if abs(coverage - tau) > 0.10:
        log.warning("coverage is %.3f against a target of %.2f -- the quantile fit is "
                    "poorly converged and the frontier reading is weak.", coverage, tau)

    record("potential_model", tau=tau, n_train=int(len(y)),
           in_sample_coverage=round(coverage, 4), n_features=len(names))
    return model, enc, names


def predict_potential(model, enc, df: pd.DataFrame) -> np.ndarray:
    feat = build_features(df)
    cat = enc.transform(feat[CATEGORICAL_FEATURES])
    X = np.hstack([feat[_FEATURES].to_numpy(dtype=float), cat])
    return np.expm1(model.predict(X)).clip(min=0.0)


def score_opportunity(df: pd.DataFrame, benchmarks: pd.DataFrame,
                      model, enc) -> pd.DataFrame:
    """Attach potential, achievable share, opportunity and both deciles."""
    out = df.copy()
    out["potential_class"] = predict_potential(model, enc, out)

    # A prescriber already above their modelled frontier is not an error -- the
    # frontier is a quantile, so 20% of prescribers sit above it by definition.
    # Their potential floors at what they already achieve.
    out["potential_class"] = np.maximum(out["potential_class"], out["class_fills"])

    out = out.merge(
        benchmarks[["specialty_group", "region", "year", "achievable_share"]],
        on=["specialty_group", "region", "year"], how="left",
    )
    out["achievable_share"] = out["achievable_share"].fillna(out["achievable_share"].median())

    out["potential_brand"] = out["potential_class"] * out["achievable_share"]
    out["opportunity"] = (out["potential_brand"] - out["brand_fills"]).clip(lower=0.0)
    out["opportunity_pct_of_potential"] = (
        out["opportunity"] / out["potential_brand"].replace(0, np.nan)
    ).fillna(0.0)

    # DECILE WITHIN THE ADDRESSABLE UNIVERSE, not the whole Part D file.
    #
    # 1.38M prescribers appear in Part D; roughly 267k write anticoagulants.
    # Deciling across all of them puts every non-writer in deciles 1-8 and
    # makes the bands meaningless -- "decile 9" would mean "writes the class at
    # all" rather than "is worth a visit". Pharma deciling has always been
    # within the market being sold into, and this is that.
    #
    # Prescribers outside the class get decile 0, which every downstream band
    # treats as no-call. They are retained rather than dropped so the map still
    # has full geographic coverage.
    in_market = out["class_fills"] > 0
    out["in_market"] = in_market

    out["opportunity_decile"] = 0
    out["volume_decile"] = 0
    if in_market.any():
        out.loc[in_market, "opportunity_decile"] = _decile(out.loc[in_market, "opportunity"])
        out.loc[in_market, "volume_decile"] = _decile(out.loc[in_market, "class_fills"])
    out["decile_shift"] = out["opportunity_decile"] - out["volume_decile"]

    log.info("  %s of %s prescribers are in-market (write the class); deciles are "
             "computed within that universe",
             f"{int(in_market.sum()):,}", f"{len(out):,}")
    return out


def _decile(series: pd.Series) -> pd.Series:
    """Rank into ten equal-count buckets, 10 = highest.

    Ties are broken by rank order rather than by value edges. Deciling on raw
    values with qcut fails whenever a metric has mass at zero -- and opportunity
    has a lot of mass at zero, because well-served prescribers score exactly 0.
    """
    ranks = series.rank(method="first", ascending=True)
    return (np.ceil(ranks / len(ranks) * 10).clip(1, 10)).astype(int)


def disagreement_matrix(scored: pd.DataFrame) -> pd.DataFrame:
    """Volume decile x opportunity decile. Exhibit E1 -- the complication.

    In-market prescribers only. Including the out-of-class population would put
    a million prescribers in cell (0,0) and swamp the pattern the exhibit exists
    to show.
    """
    scored = scored[scored.get("in_market", scored["class_fills"] > 0)].copy()
    mat = (scored.groupby(["volume_decile", "opportunity_decile"])
                 .agg(hcp_count=("npi", "count"),
                      class_fills=("class_fills", "sum"),
                      opportunity=("opportunity", "sum"))
                 .reset_index())
    total = len(scored)
    agree = int((scored["volume_decile"] == scored["opportunity_decile"]).sum())
    within1 = int((scored["decile_shift"].abs() <= 1).sum())
    disagree_band = total - within1

    stats = {
        "n_hcps": total,
        "exact_agreement": agree,
        "exact_agreement_pct": round(agree / total, 4),
        "within_one_decile_pct": round(within1 / total, 4),
        "disagree_by_2plus_pct": round(disagree_band / total, 4),
        # The headline: prescribers the volume rule would skip that the
        # opportunity rule would call on, and vice versa.
        "volume_low_opportunity_high": int(((scored["volume_decile"] <= 4) &
                                            (scored["opportunity_decile"] >= 7)).sum()),
        "volume_high_opportunity_low": int(((scored["volume_decile"] >= 7) &
                                            (scored["opportunity_decile"] <= 4)).sum()),
    }
    log.info("disagreement: %.1f%% of prescribers move by 2+ deciles; "
             "%d are low-volume/high-opportunity, %d are high-volume/low-opportunity",
             100 * stats["disagree_by_2plus_pct"],
             stats["volume_low_opportunity_high"],
             stats["volume_high_opportunity_low"])
    record("disagreement", **stats)
    return mat


def crosscheck_against_sfa(train: pd.DataFrame, model, enc, n: int = 20_000) -> float:
    """Rank-correlate the quantile frontier against a linear SFA approximation.

    Not a full maximum-likelihood SFA -- a corrected-OLS frontier, which is the
    standard cheap approximation: fit OLS, then shift the intercept up by the
    largest positive residual so the line envelops the data from above. If the
    two rankings agree, the choice of quantile GBM is a convenience rather than
    a load-bearing assumption, which is exactly what you want to be able to say.
    """
    sample = train.sample(min(n, len(train)), random_state=0)
    feat = build_features(sample)
    X = feat[NUMERIC_FEATURES].to_numpy(dtype=float)
    X = np.hstack([np.ones((len(X), 1)), X])
    y = np.log1p(feat["class_fills"].to_numpy(dtype=float))

    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    beta[0] += np.percentile(resid, 95)   # shift to an upper envelope
    sfa_pred = X @ beta

    gbm_pred = np.log1p(predict_potential(model, enc, sample))
    rho = float(pd.Series(sfa_pred).corr(pd.Series(gbm_pred), method="spearman"))
    log.info("SFA cross-check: Spearman rank correlation = %.3f (n=%d)", rho, len(sample))
    record("sfa_crosscheck", spearman=round(rho, 4), n=len(sample))
    return rho


def driver_importance(model, enc, df: pd.DataFrame, tau: float | None = None,
                      n: int = 30_000) -> pd.DataFrame:
    """Permutation importance per feature, scored on pinball loss.

    Permutation rather than SHAP: SHAP's TreeExplainer does not support the
    histogram-based estimator, and permutation importance is model-agnostic and
    measures the thing actually of interest -- how much worse the QUANTILE fit
    gets when a feature is shuffled. Scoring on pinball loss at the same tau the
    model was fit at keeps the question aligned with the objective; scoring on
    R-squared would grade a frontier model on its conditional mean.

    This is the guard against 'the model just predicts panel size'. If
    log_non_class_clms alone dominates, the model has learned practice scale and
    nothing about the market, and gate G2 fails.
    """
    tau = tau if tau is not None else params()["opportunity_model"]["tau"]
    sample = build_features(df.sample(min(n, len(df)), random_state=0))
    cat = enc.transform(sample[CATEGORICAL_FEATURES])
    X = np.hstack([sample[_FEATURES].to_numpy(dtype=float), cat])
    y = np.log1p(sample["class_fills"].to_numpy(dtype=float))
    names = _FEATURES + list(enc.get_feature_names_out(CATEGORICAL_FEATURES))

    scorer = make_scorer(mean_pinball_loss, alpha=tau, greater_is_better=False)
    result = permutation_importance(
        model, X, y, scoring=scorer, n_repeats=3, random_state=0, n_jobs=1,
    )

    imp = (pd.DataFrame({"feature": names,
                         "importance": np.abs(result.importances_mean),
                         "std": result.importances_std})
             .sort_values("importance", ascending=False).reset_index(drop=True))
    total = imp["importance"].sum()
    imp["share_of_total"] = imp["importance"] / total if total > 0 else 0.0

    top = imp.iloc[0]
    log.info("top driver: %s (%.1f%% of total importance, n=%d)",
             top["feature"], 100 * top["share_of_total"], len(sample))
    if top["feature"] == "log_non_class_clms" and top["share_of_total"] > 0.55:
        log.warning("G2 RISK: the model is dominated by practice size. It is predicting "
                    "how many patients a prescriber has, not where the market is. "
                    "Add market covariates or raise tau before proceeding.")
    record("top_driver", feature=str(top["feature"]),
           share=round(float(top["share_of_total"]), 4), method="permutation")
    return imp


def run(fit_year: int | None = None) -> pd.DataFrame:
    """Fit on the training year and score every prescriber-year."""
    p = params()
    fit_year = fit_year or p["years"]["train_end"]
    proc = path("processed")

    metrics = read_parquet(proc / "mart_hcp_metrics.parquet")
    benchmarks = read_parquet(proc / "mart_peer_benchmarks.parquet")

    train = metrics[(metrics["year"] == fit_year) & (metrics["class_fills"] > 0)].copy()
    log.info("fitting potential model on %d prescribers from %d", len(train), fit_year)

    model, enc, names = fit_potential(train)
    crosscheck_against_sfa(train, model, enc)

    scored_frames = []
    for _year, grp in metrics.groupby("year"):
        scored_frames.append(score_opportunity(grp, benchmarks, model, enc))
    scored = pd.concat(scored_frames, ignore_index=True)

    current = scored[scored["year"] == fit_year]
    disagreement_matrix(current).pipe(write_parquet, proc / "disagreement_matrix.parquet")
    driver_importance(model, enc, train).pipe(write_parquet, proc / "shap_drivers.parquet")
    write_parquet(scored, proc / "hcp_scored.parquet")
    return scored


if __name__ == "__main__":
    run()
