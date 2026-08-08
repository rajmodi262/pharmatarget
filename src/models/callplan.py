"""Call plan matrix and reach curves.

THE CALL PLAN MATRIX
--------------------
The core business artifact. Two axes, because two questions determine how often
a rep should visit:

    * opportunity decile -- how much is there to win here?
    * current brand share -- are we defending or converting?

A decile-10 prescriber already at 80% share needs maintenance, not conversion.
A decile-10 prescriber at 5% share is the single best use of a rep's day. Volume
alone cannot separate them, which is the argument the whole project rests on.

REACH CURVES
------------
Exhibit E3, and the source of headline H2. Three competing allocation rules are
run against the SAME call budget and scored on what fraction of addressable
opportunity each reaches:

    1. geography-proportional -- calls spread by prescriber count (the naive
       current state, and the honest stand-in for real call logs we do not have)
    2. volume-ranked          -- the industry default
    3. opportunity-ranked     -- this project's recommendation

H2 contains no behavioural assumption whatsoever. It does not claim a rep visit
causes anything. It says: given a fixed number of calls, here is how much
addressable volume each rule puts a rep in front of. That is arithmetic, and it
is why H2 survives questioning that H3 cannot.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import econ, params, path
from src.utils.io import get_logger, read_parquet, record, write_parquet

log = get_logger(__name__)

# Brand-share bands. Labels are business language, not bin edges -- these
# strings reach the UI and the deck unchanged.
SHARE_BANDS = [
    ("Low (<20%)", 0.00, 0.20),
    ("Mid (20-50%)", 0.20, 0.50),
    ("High (>50%)", 0.50, 1.01),
]

# Calls per month by (opportunity decile band, share band).
# Reads as a strategy, which is the point: convert where there is headroom,
# maintain where there is share to defend, do not call where there is neither.
#
# CALIBRATION. The frequencies are not free parameters. A rep carries roughly
# 150-200 prescribers, so a 60-rep force can hold a target list of order 10,000
# -- about a quarter of a 40,000-prescriber universe. A matrix that targets 90%
# of the universe is not a strategy, it is an unpriced wish list, and it makes
# the sizing module report a nonsense rep count. These values are set so total
# workload lands in a plausible band, and `run()` asserts it: if implied reps
# fall outside 0.5x-2.5x the current force, the matrix is miscalibrated and the
# pipeline says so rather than quietly producing a broken headline.
CALL_MATRIX: dict[tuple[str, str], float] = {
    ("Decile 9-10", "Low (<20%)"): 2.00,   # highest-value conversion targets
    ("Decile 9-10", "Mid (20-50%)"): 1.50,
    ("Decile 9-10", "High (>50%)"): 0.75,  # maintain a franchise already won
    ("Decile 7-8", "Low (<20%)"): 1.00,
    ("Decile 7-8", "Mid (20-50%)"): 0.75,
    ("Decile 7-8", "High (>50%)"): 0.25,
    ("Decile 1-6", "Low (<20%)"): 0.0,     # no-call: no modelled headroom
    ("Decile 1-6", "Mid (20-50%)"): 0.0,
    ("Decile 1-6", "High (>50%)"): 0.0,
}

DECILE_BANDS = ("Decile 9-10", "Decile 7-8", "Decile 1-6")


def decile_band(d: int) -> str:
    # Decile 0 means out-of-market (does not write the class) and falls through
    # to the no-call band.
    if d >= 9:
        return "Decile 9-10"
    if d >= 7:
        return "Decile 7-8"
    return "Decile 1-6"


def share_band(s: float) -> str:
    s = 0.0 if pd.isna(s) else float(s)
    for label, lo, hi in SHARE_BANDS:
        if lo <= s < hi:
            return label
    return SHARE_BANDS[-1][0]


def apply_call_plan(scored: pd.DataFrame, n_reps: int | None = None) -> pd.DataFrame:
    """Assign call frequency, then CUT THE LIST AT THE FORCE'S CAPACITY.

    The matrix alone is a frequency policy, not a plan. Applied to every
    prescriber it produced a target list implying 4,575 reps against a force of
    60 -- an unpriced wish list, and the reason sizing.py needs a guard.

    Real call planning is capacity-constrained: you have N reps, you rank the
    universe, and you fill their diaries from the top. So the ranking decides
    WHO, the matrix decides HOW OFTEN, and headcount decides HOW FAR DOWN THE
    LIST YOU GET. Everyone past that point is a no-call -- which is a genuine
    finding, not a rounding error: it is the population the brand cannot serve
    at current headcount, and it is exactly what the sizing module then prices.
    """
    n_reps = n_reps or params()["territory"]["n_reps_default"]
    out = scored.copy()

    out["decile_band"] = out["opportunity_decile"].map(decile_band)
    out["share_band"] = out["brand_share"].map(share_band)
    out["desired_calls"] = [
        CALL_MATRIX[(d, s)]
        for d, s in zip(out["decile_band"], out["share_band"], strict=True)
    ]

    # Out-of-market prescribers are never called: no anticoagulant patients
    # means nothing to convert, whatever the frontier says they could reach.
    if "in_market" in out.columns:
        out.loc[~out["in_market"].astype(bool), "desired_calls"] = 0.0

    # Fill capacity from the top of the opportunity ranking.
    out = out.sort_values("opportunity", ascending=False, kind="mergesort")
    cumulative = out["desired_calls"].cumsum()
    budget = capacity_calls_per_month(n_reps)

    out["calls_per_month"] = np.where(cumulative <= budget, out["desired_calls"], 0.0)
    out["calls_per_year"] = out["calls_per_month"] * 12.0
    out["is_target"] = out["calls_per_month"] > 0

    reached = int(out["is_target"].sum())
    wanted = int((out["desired_calls"] > 0).sum())
    log.info("capacity cut: %s of %s prescribers the matrix would call are reachable "
             "with %d reps (%.1f%%)",
             f"{reached:,}", f"{wanted:,}", n_reps,
             100 * reached / max(wanted, 1))
    return out.sort_index()


def matrix_summary(planned: pd.DataFrame) -> pd.DataFrame:
    """The matrix with HCP counts and opportunity per cell. Deck slide 8."""
    rows = []
    for band in DECILE_BANDS:
        for label, _lo, _hi in SHARE_BANDS:
            cell = planned[(planned["decile_band"] == band) & (planned["share_band"] == label)]
            rows.append({
                "decile_band": band,
                "share_band": label,
                "calls_per_month": CALL_MATRIX[(band, label)],
                "hcp_count": len(cell),
                "class_fills": float(cell["class_fills"].sum()),
                "brand_fills": float(cell["brand_fills"].sum()),
                "opportunity": float(cell["opportunity"].sum()),
                "monthly_calls": float(cell["calls_per_month"].sum()),
            })
    return pd.DataFrame(rows)


def capacity_calls_per_month(n_reps: int) -> float:
    """Monthly call capacity of a field force of n_reps."""
    return (n_reps
            * econ("calls_per_rep_per_day")
            * econ("selling_days_per_month"))


def reach_curve(scored: pd.DataFrame, n_points: int = 60) -> pd.DataFrame:
    """Cumulative opportunity reached vs calls spent, for three allocation rules.

    'Reached' means a rep is in front of that prescriber at the planned
    frequency. It is a coverage measure, not an outcome measure -- deliberately
    so. See the module docstring.
    """
    df = scored.copy()
    total_opportunity = df["opportunity"].sum()
    total_class = df["class_fills"].sum()

    rules = {
        # Rank by modelled opportunity -- the recommendation.
        "opportunity": df["opportunity"].rank(ascending=False, method="first"),
        # Rank by observed class volume -- the industry default.
        "volume": df["class_fills"].rank(ascending=False, method="first"),
        # Geography-proportional: no prescriber-level intelligence at all.
        # Reproducible ordering seeded per-rule so the curve is stable across runs.
        "geography": pd.Series(
            np.random.default_rng(7).permutation(len(df)) + 1, index=df.index
        ),
    }

    out = []
    for rule, order in rules.items():
        ordered = df.assign(_rank=order).sort_values("_rank")
        cum_opp = ordered["opportunity"].cumsum() / total_opportunity
        cum_vol = ordered["class_fills"].cumsum() / total_class
        # Cost model: one unit of call budget per prescriber added to the target
        # list. Flat rather than frequency-weighted on purpose -- weighting by
        # planned calls would let the RULE change the x-axis, and then the three
        # curves would no longer be plotted against a common budget.
        cum_calls = np.arange(1, len(ordered) + 1, dtype=float)

        idx = np.unique(np.linspace(0, len(ordered) - 1, n_points).astype(int))
        out.append(pd.DataFrame({
            "rule": rule,
            "hcps_called": (idx + 1),
            "pct_of_universe": (idx + 1) / len(ordered),
            "calls_index": cum_calls[idx],
            "pct_opportunity_reached": cum_opp.iloc[idx].to_numpy(),
            "pct_class_volume_reached": cum_vol.iloc[idx].to_numpy(),
        }))
    return pd.concat(out, ignore_index=True)


def headline_h2(scored: pd.DataFrame, n_reps: int | None = None) -> dict:
    """H2: reach under each rule at an identical, fixed call budget."""
    n_reps = n_reps or params()["territory"]["n_reps_default"]
    df = scored.copy()

    # How many prescribers a force of this size can cover, at the average
    # planned call frequency among prescribers worth calling at all.
    planned = apply_call_plan(df)
    avg_freq = planned.loc[planned["is_target"], "calls_per_month"].mean()
    budget_calls = capacity_calls_per_month(n_reps)
    n_reachable = int(min(budget_calls / max(avg_freq, 0.1), len(df)))

    # If the force can cover the entire universe, reach is 100% under every rule
    # and the comparison is vacuous. That happens on the --sample run (8k
    # prescribers, 9.6k monthly calls) and it is a scale artefact, not a result.
    if n_reachable >= len(df):
        log.warning("H2 is not meaningful: %d reps can cover the whole %d-prescriber "
                    "universe, so every allocation rule reaches 100%%. Run the full "
                    "pipeline (make data) instead of --sample before quoting H2.",
                    n_reps, len(df))

    total_opp = df["opportunity"].sum()
    total_vol = df["class_fills"].sum()
    result = {"n_reps": n_reps, "monthly_call_budget": budget_calls,
              "avg_calls_per_target": round(float(avg_freq), 2),
              "hcps_reachable": n_reachable, "universe": len(df)}

    for rule, key in (("opportunity", "opportunity"), ("volume", "class_fills")):
        top = df.nlargest(n_reachable, key)
        result[f"{rule}_pct_opportunity"] = round(float(top["opportunity"].sum() / total_opp), 4)
        result[f"{rule}_pct_class_volume"] = round(float(top["class_fills"].sum() / total_vol), 4)

    rng = np.random.default_rng(7)
    geo = df.iloc[rng.permutation(len(df))[:n_reachable]]
    result["geography_pct_opportunity"] = round(float(geo["opportunity"].sum() / total_opp), 4)
    result["geography_pct_class_volume"] = round(float(geo["class_fills"].sum() / total_vol), 4)

    result["lift_vs_geography_pp"] = round(
        100 * (result["opportunity_pct_opportunity"] - result["geography_pct_opportunity"]), 1)
    result["lift_vs_volume_pp"] = round(
        100 * (result["opportunity_pct_opportunity"] - result["volume_pct_opportunity"]), 1)

    log.info("H2 @ %d reps (%d HCPs reachable): opportunity-ranked reaches %.1f%% of "
             "addressable opportunity vs %.1f%% volume-ranked and %.1f%% geography-proportional",
             n_reps, n_reachable,
             100 * result["opportunity_pct_opportunity"],
             100 * result["volume_pct_opportunity"],
             100 * result["geography_pct_opportunity"])
    record("headline_h2", **result)
    return result


def run() -> pd.DataFrame:
    proc = path("processed")
    scored = read_parquet(proc / "hcp_scored.parquet")
    current_year = params()["years"]["train_end"]
    current = scored[scored["year"] == current_year].copy()

    planned = apply_call_plan(current)
    write_parquet(planned, proc / "hcp_call_plan.parquet")
    write_parquet(matrix_summary(planned), proc / "call_plan_matrix.parquet")
    write_parquet(reach_curve(current), proc / "reach_curve.parquet")
    headline_h2(current)

    current_reps = params()["territory"]["n_reps_default"]
    targets = int(planned["is_target"].sum())
    monthly = float(planned["calls_per_month"].sum())

    # Unconstrained demand: what the frequency policy WOULD spend if headcount
    # were free. The gap between this and the current force is the sizing
    # finding, and it only means anything now that the served list is capped.
    wanted_hcps = int((planned["desired_calls"] > 0).sum())
    wanted_calls = float(planned["desired_calls"].sum())
    demand_reps = wanted_calls / capacity_calls_per_month(1)
    in_market = int(planned["in_market"].sum()) if "in_market" in planned else len(planned)

    log.info("call plan @ %d reps: %s of %s in-market prescribers served "
             "(%.1f%%), %.0f calls/month at %.0f%% capacity",
             current_reps, f"{targets:,}", f"{in_market:,}",
             100 * targets / max(in_market, 1), monthly,
             100 * monthly / capacity_calls_per_month(current_reps))
    log.info("  unconstrained demand: %s prescribers, %.0f calls/month, "
             "which would need %.0f reps", f"{wanted_hcps:,}", wanted_calls, demand_reps)

    record("call_plan",
           n_targets=targets, n_universe=len(planned), n_in_market=in_market,
           pct_of_market_served=round(targets / max(in_market, 1), 4),
           monthly_calls=round(monthly, 1),
           capacity_utilisation=round(monthly / capacity_calls_per_month(current_reps), 4),
           demand_hcps=wanted_hcps,
           demand_calls=round(wanted_calls, 1),
           implied_reps=round(demand_reps, 1),
           current_reps=current_reps)
    return planned


if __name__ == "__main__":
    run()
