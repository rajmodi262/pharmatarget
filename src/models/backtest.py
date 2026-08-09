"""Back-test -- the module that earns headline H1.

This is the only place in the project where a claim is *validated* rather than
computed or assumed. Everything else describes the data or projects a scenario;
this predicts something and then checks.

PROTOCOL
--------
    fit      on 2021-2022 only
    freeze   the model and the resulting opportunity scores
    score    against actual 2023 branded volume growth -- a year the model has
             never seen in any form

Three comparisons, in increasing order of how hard they are to argue with:

    1. DECILE LIFT. Mean 2023 branded growth by 2022 opportunity decile. A
       monotone ramp is the basic evidence that the score orders prescribers
       correctly.

    2. HEAD-TO-HEAD AT A FIXED BUDGET. Take the top N prescribers under each
       rule -- opportunity vs volume -- where N is what the field force can
       actually cover. Which set captured more of the growth that really
       happened? This is the comparison a brand team cares about, because N is
       fixed by headcount whatever the analyst prefers.

    3. VOLUME-MATCHED CONTROL. Match each flagged prescriber to an unflagged
       one at similar 2022 class volume, then compare growth. This is what
       licenses the phrase "faster than comparable prescribers" -- without it,
       the model could simply be rediscovering that big prescribers grow more.

PRE-COMMITTED PIVOT
-------------------
If the lift is flat, that is reported as the finding and the headline moves to
H2, which is pure arithmetic and cannot fail. This decision was written into
CHARTER.md before the model was fit. ``run()`` prints the verdict either way and
``gate_g3_verdict()`` returns it programmatically, so a null result is
structurally impossible to quietly bury.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import params, path
from src.models import opportunity as opp
from src.utils.io import get_logger, read_parquet, record, write_parquet

log = get_logger(__name__)

FLAG_DECILE_MIN = 8      # "flagged" = opportunity decile 8-10
MIN_BASE_FILLS = 5.0     # exclude microscopic prescribers from growth ratios


def build_holdout_frame() -> pd.DataFrame:
    """Score prescribers as of the training year, join actual holdout outcomes."""
    p = params()
    fit_year, holdout_year = p["years"]["train_end"], p["years"]["holdout"]
    proc = path("processed")

    metrics = read_parquet(proc / "mart_hcp_metrics.parquet")
    benchmarks = read_parquet(proc / "mart_peer_benchmarks.parquet")

    train = metrics[(metrics["year"] == fit_year) & (metrics["class_fills"] > 0)].copy()
    log.info("back-test: fitting on %d prescribers from %d, scoring against %d",
             len(train), fit_year, holdout_year)

    # Refit explicitly here rather than reusing opportunity.run()'s model. The
    # extra 12 seconds buys certainty that no holdout-year information reached
    # the fit through a shared object.
    model, enc, _ = opp.fit_potential(train)
    scored = opp.score_opportunity(train, benchmarks, model, enc)

    future = (metrics[metrics["year"] == holdout_year]
              [["npi", "brand_fills", "class_fills", "brand_share"]]
              .rename(columns={"brand_fills": "brand_fills_next",
                               "class_fills": "class_fills_next",
                               "brand_share": "brand_share_next"}))

    df = scored.merge(future, on="npi", how="inner")
    df["brand_growth_abs"] = df["brand_fills_next"] - df["brand_fills"]
    df["brand_growth_pct"] = (df["brand_growth_abs"]
                              / df["brand_fills"].clip(lower=MIN_BASE_FILLS))
    df["share_growth"] = df["brand_share_next"] - df["brand_share"]
    df["flagged"] = df["opportunity_decile"] >= FLAG_DECILE_MIN
    log.info("  %d prescribers present in both %d and %d", len(df), fit_year, holdout_year)
    return df


def decile_lift(df: pd.DataFrame) -> pd.DataFrame:
    """Actual holdout growth by predicted decile, for both competing rules."""
    frames = []
    for rule, col in (("opportunity", "opportunity_decile"), ("volume", "volume_decile")):
        g = (df.groupby(col)
               .agg(n=("npi", "count"),
                    mean_growth_abs=("brand_growth_abs", "mean"),
                    median_growth_abs=("brand_growth_abs", "median"),
                    total_growth_abs=("brand_growth_abs", "sum"),
                    mean_share_growth=("share_growth", "mean"))
               .reset_index().rename(columns={col: "decile"}))
        g.insert(0, "rule", rule)
        frames.append(g)
    out = pd.concat(frames, ignore_index=True)

    # Spearman correlation between decile and realised growth: one number for
    # "does the ranking rank?"
    for rule in ("opportunity", "volume"):
        sub = out[out["rule"] == rule]
        rho = sub["decile"].corr(sub["mean_growth_abs"], method="spearman")
        log.info("decile lift [%s]: Spearman(decile, mean growth) = %.3f", rule, rho)
        record(f"backtest_lift_{rule}", spearman=round(float(rho), 4),
               top_decile_growth=float(sub.loc[sub["decile"] == 10, "mean_growth_abs"].iloc[0]),
               bottom_decile_growth=float(sub.loc[sub["decile"] == 1, "mean_growth_abs"].iloc[0]))
    return out


def head_to_head(df: pd.DataFrame, n_budget: int | None = None) -> dict:
    """Growth captured by the top-N under each rule, at an identical N.

    TWO OUTCOME METRICS, AND WHY BOTH ARE REPORTED
    ----------------------------------------------
    Absolute fill growth scales mechanically with baseline volume: a prescriber
    writing 400 fills can gain 40 by moving four share points, while one writing
    40 cannot gain 40 no matter what happens. So ranking by volume is close to
    tautologically strong on absolute growth, and beating it on that metric is
    not the test it appears to be.

    Share-point growth is volume-neutral. It measures whether the prescriber's
    behaviour actually moved toward the brand, which is the outcome a rep visit
    is supposed to influence. A targeting rule that finds prescribers whose
    SHARE moves is finding persuadable prescribers; a rule that finds
    prescribers whose absolute volume moves may only be finding large ones.

    Both are reported. Neither is suppressed because it is inconvenient.

    WHAT THIS BACK-TEST CANNOT DO
    -----------------------------
    It measures where growth HAPPENED, with no rep call data in the holdout. It
    therefore cannot identify where a call would have CAUSED growth. Targeting
    prescribers who were going to grow anyway is the reverse-causality trap this
    project warns about in the response module -- and a CMS-only back-test
    cannot escape it. Stated in the README limitations, not buried here.
    """
    if n_budget is None:
        n_budget = max(int(0.20 * len(df)), 1)

    total_growth = df.loc[df["brand_growth_abs"] > 0, "brand_growth_abs"].sum()
    total_share_growth = df.loc[df["share_growth"] > 0, "share_growth"].sum()
    res = {"n_budget": n_budget, "universe": len(df),
           "total_positive_growth": float(total_growth),
           "total_positive_share_growth": float(total_share_growth)}

    for rule, col in (("opportunity", "opportunity"), ("volume", "class_fills")):
        top = df.nlargest(n_budget, col)

        captured = float(top["brand_growth_abs"].clip(lower=0).sum())
        res[f"{rule}_growth_captured"] = captured
        res[f"{rule}_pct_of_growth"] = round(captured / total_growth, 4) if total_growth else None
        res[f"{rule}_growth_per_hcp"] = round(captured / n_budget, 3)

        share_captured = float(top["share_growth"].clip(lower=0).sum())
        res[f"{rule}_share_growth_captured"] = share_captured
        res[f"{rule}_pct_of_share_growth"] = (
            round(share_captured / total_share_growth, 4) if total_share_growth else None)
        res[f"{rule}_mean_share_growth"] = round(float(top["share_growth"].mean()), 5)

        # Base volume of the SELECTED list. This is the anti-gaming guard, and
        # it exists because src/models/challenger.py demonstrated the failure:
        # a model trained to maximise share growth won that metric by 5x while
        # selecting prescribers with a median base of 35 class fills against 840
        # for this one -- and delivered 1.9% of actual volume. Share growth on a
        # tiny denominator is arithmetic, not persuadability. A rule that wins
        # share capture while collapsing the base is not better, it is gaming.
        res[f"{rule}_median_base_fills"] = round(float(top["class_fills"].median()), 1)

    if res.get("volume_growth_captured"):
        res["opportunity_vs_volume_ratio"] = round(
            res["opportunity_growth_captured"] / res["volume_growth_captured"], 3)
    if res.get("volume_share_growth_captured"):
        res["opportunity_vs_volume_share_ratio"] = round(
            res["opportunity_share_growth_captured"] / res["volume_share_growth_captured"], 3)

    log.info("head-to-head at N=%d", n_budget)
    log.info("  ABSOLUTE fill growth : opportunity %.1f%%, volume %.1f%% (ratio %.2fx) "
             "-- volume is mechanically advantaged on this metric",
             100 * (res.get("opportunity_pct_of_growth") or 0),
             100 * (res.get("volume_pct_of_growth") or 0),
             res.get("opportunity_vs_volume_ratio") or 0)
    log.info("  SHARE-POINT growth   : opportunity %.1f%%, volume %.1f%% (ratio %.2fx) "
             "-- volume-neutral, measures persuadability",
             100 * (res.get("opportunity_pct_of_share_growth") or 0),
             100 * (res.get("volume_pct_of_share_growth") or 0),
             res.get("opportunity_vs_volume_share_ratio") or 0)
    record("backtest_head_to_head", **res)
    return res


def volume_matched_comparison(df: pd.DataFrame, n_bins: int = 20) -> dict:
    """Flagged vs unflagged growth, matched on 2022 class volume.

    Stratified matching on volume decile-of-deciles: within each thin volume
    stratum, compare flagged and unflagged prescribers. Removes the obvious
    confound that bigger prescribers grow more in absolute terms.
    """
    d = df[df["class_fills"] >= MIN_BASE_FILLS].copy()
    d["vol_stratum"] = pd.qcut(d["class_fills"].rank(method="first"), n_bins, labels=False)

    rows = []
    for stratum, grp in d.groupby("vol_stratum"):
        flagged = grp[grp["flagged"]]
        control = grp[~grp["flagged"]]
        if len(flagged) < 5 or len(control) < 5:
            continue
        rows.append({
            "stratum": int(stratum),
            "n_flagged": len(flagged),
            "n_control": len(control),
            "mean_class_fills": float(grp["class_fills"].mean()),
            "flagged_growth": float(flagged["brand_growth_abs"].mean()),
            "control_growth": float(control["brand_growth_abs"].mean()),
        })

    strata = pd.DataFrame(rows)
    if strata.empty:
        log.warning("no volume stratum had both flagged and control prescribers; "
                    "matched comparison not computable")
        return {"computable": False}

    # Weight strata by flagged count so the aggregate reflects the treated
    # population rather than giving a sparse stratum equal say.
    w = strata["n_flagged"]
    flagged_mean = float((strata["flagged_growth"] * w).sum() / w.sum())
    control_mean = float((strata["control_growth"] * w).sum() / w.sum())
    ratio = flagged_mean / control_mean if control_mean > 0 else np.nan

    res = {
        "computable": True,
        "n_strata": len(strata),
        "flagged_mean_growth": round(flagged_mean, 3),
        "control_mean_growth": round(control_mean, 3),
        "growth_ratio": round(float(ratio), 3) if np.isfinite(ratio) else None,
        "absolute_difference": round(flagged_mean - control_mean, 3),
    }
    log.info("volume-matched: flagged prescribers grew %.2f fills vs %.2f for matched "
             "controls (%.2fx)", flagged_mean, control_mean, ratio)
    record("backtest_matched", **res)
    return res


def where_the_model_was_wrong(df: pd.DataFrame, top_n: int = 50) -> pd.DataFrame:
    """Profile the biggest misses. A section titled this is worth three charts.

    Highest actual growth among prescribers the model ranked in the bottom half.
    If they share a specialty or a geography, that is a named, fixable weakness
    -- and naming it is the difference between owning your model and hoping
    nobody looks.
    """
    misses = (df[df["opportunity_decile"] <= 5]
              .nlargest(top_n, "brand_growth_abs")
              [["npi", "specialty_group", "region", "state", "class_fills",
                "brand_fills", "brand_share", "opportunity", "opportunity_decile",
                "volume_decile", "brand_growth_abs"]])

    if len(misses):
        by_spec = (misses["specialty_group"].value_counts(normalize=True)
                   - df["specialty_group"].value_counts(normalize=True)).dropna()
        over = by_spec.sort_values(ascending=False)
        if len(over):
            log.info("biggest misses over-represent: %s (+%.1f pp vs universe)",
                     over.index[0], 100 * over.iloc[0])
            record("backtest_misses", top_over_represented=str(over.index[0]),
                   excess_pp=round(float(100 * over.iloc[0]), 2), n_examined=len(misses))
    return misses


def gate_g3_verdict(lift: pd.DataFrame, h2h: dict, matched: dict) -> dict:
    """Pass/fail against the execution playbook's G3 criterion.

    Fails loudly. A back-test that quietly returns a flat ramp and gets written
    up as a success is the single worst outcome available to this project.
    """
    opp_lift = lift[lift["rule"] == "opportunity"]
    rho = float(opp_lift["decile"].corr(opp_lift["mean_growth_abs"], method="spearman"))
    ratio = h2h.get("opportunity_vs_volume_ratio") or 0.0
    share_ratio = h2h.get("opportunity_vs_volume_share_ratio") or 0.0
    matched_ratio = matched.get("growth_ratio") or 0.0

    # THREE CONDITIONS, NOT ONE.
    #
    # An earlier version of this gate rested on share-growth capture alone.
    # src/models/challenger.py then showed that criterion is gameable: a model
    # trained directly on share growth beat it 11.7% to 2.4% while selecting
    # prescribers with a median base of 35 class fills, capturing 1.9% of
    # actual volume. It won the metric and would have been commercially
    # worthless.
    #
    # So the gate now requires the ranking to ORDER correctly, to beat volume on
    # the volume-neutral outcome, AND not to have bought that win by collapsing
    # into micro-prescribers. Absolute capture is reported but deliberately not
    # a pass condition -- volume ranking wins it mechanically, and the back-test
    # cannot separate that from growth which would have happened anyway.
    base = h2h.get("opportunity_median_base_fills")
    vol_base = h2h.get("volume_median_base_fills")
    base_ratio = (base / vol_base) if (base and vol_base) else None

    cond_orders = rho >= 0.60
    cond_beats = share_ratio >= 1.05
    cond_not_gamed = base_ratio is None or base_ratio >= 0.25

    passed = cond_orders and cond_beats and cond_not_gamed
    verdict = {
        "gate": "G3",
        "passed": bool(passed),
        "decile_spearman": round(rho, 3),
        "share_growth_ratio": share_ratio,
        "absolute_growth_ratio": ratio,
        "matched_growth_ratio": matched_ratio,
        "median_base_fills": base,
        "base_ratio_vs_volume": round(base_ratio, 3) if base_ratio else None,
        "conditions": {
            "orders_correctly": bool(cond_orders),
            "beats_volume_on_share": bool(cond_beats),
            "not_gamed_by_small_base": bool(cond_not_gamed),
        },
        "criterion": ("Spearman >= 0.60 AND share-growth capture >= 1.05x volume "
                      "AND median base volume of the selected list >= 25% of the "
                      "volume rule's (anti-gaming guard)"),
        "note": ("Absolute-growth capture is reported but is NOT a pass condition. "
                 "Volume ranking wins it mechanically, and with no call data in the "
                 "holdout the back-test cannot separate captured growth from growth "
                 "that would have occurred regardless."),
    }

    if passed:
        log.info("GATE G3 PASSED -- Spearman %.3f, share capture %.2fx, matched %.2fx, "
                 "selected-list median base %.0f fills (%.0f%% of the volume rule's) "
                 "-- the win is not bought with micro-prescribers.",
                 rho, share_ratio, matched_ratio, base or 0, 100 * (base_ratio or 0))
    else:
        failed = [k for k, v in verdict["conditions"].items() if not v]
        log.warning("GATE G3 FAILED on %s. Per CHARTER.md the pre-committed response is "
                    "to report this as the finding and move the headline to H2 (reach), "
                    "which is arithmetic and cannot fail. DO NOT rewrite the criterion "
                    "to make it pass.", ", ".join(failed))
    record("gate_g3", **verdict)
    return verdict


def run() -> dict:
    proc = path("processed")
    df = build_holdout_frame()

    lift = decile_lift(df)
    h2h = head_to_head(df)
    matched = volume_matched_comparison(df)
    misses = where_the_model_was_wrong(df)
    verdict = gate_g3_verdict(lift, h2h, matched)

    write_parquet(lift, proc / "backtest_decile_lift.parquet")
    write_parquet(misses, proc / "backtest_misses.parquet")
    # share_growth and brand_share are persisted because robustness.py bootstraps
    # the SHARE-growth ratio, which is the gate's actual criterion. Omitting them
    # meant the headline metric silently got no confidence interval while the
    # secondary one did.
    write_parquet(df[["npi", "opportunity", "opportunity_decile", "volume_decile",
                      "class_fills", "brand_fills", "brand_share",
                      "brand_growth_abs", "share_growth", "flagged"]],
                  proc / "backtest_frame.parquet")

    return {"lift": lift, "head_to_head": h2h, "matched": matched, "verdict": verdict}


if __name__ == "__main__":
    run()
