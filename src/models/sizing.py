"""Field force sizing and P&L -- the module that makes this consulting.

Every other module describes prescribers. This one answers "how many reps, and
what is the marginal one worth?" -- which is the question a CFO actually asks
and the one ZS built a practice on.

THE MODEL
---------
For a force of n reps:

    annual call capacity  = n * calls/day * selling days/month * 12
    calls are allocated   in descending opportunity order, at the planned
                          frequency from the call plan matrix, until capacity
                          runs out
    fills captured        = opportunity_i * Hill(calls_i)
    contribution          = fills * net revenue per fill * margin
    field cost            = n * fully loaded rep cost
    marginal ROI at n     = d(contribution)/dn  /  rep cost

The Hill response function is the honest weak point and is labelled as such
everywhere it appears:

    Hill(c) = ceiling * c^1 / (k + c)

``ceiling`` is the fraction of a prescriber's remaining opportunity that
unlimited calling could capture in a year; ``k`` is the annual call count
reaching half of it. Both come from config/economics.yaml, fitted by
src/models/response.py where that module has run and taken from the configured
base otherwise. This is why H3 is labelled a SCENARIO and H1/H2 are not.

THE TORNADO
-----------
Six assumptions, each swept low-to-high with everything else held at base, ranked
by their effect on break-even headcount. It exists to answer "what if your margin
assumption is wrong?" before it is asked, and to show which assumptions the
recommendation is genuinely sensitive to. Usually one or two dominate and the
rest are noise -- knowing which is the difference between a defensible
recommendation and a spreadsheet.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import econ, economics, path
from src.utils.io import get_logger, read_parquet, record, write_parquet

log = get_logger(__name__)

SWEEP_KEYS = [
    "rep_cost_annual",
    "calls_per_rep_per_day",
    "selling_days_per_month",
    "net_revenue_per_30day_fill",
    "contribution_margin",
    "call_response_ceiling",
    "call_response_half_saturation",
]


def hill(calls: np.ndarray, ceiling: float, half_sat: float) -> np.ndarray:
    """Diminishing-returns response. Hill with n=1 (Michaelis-Menten form).

    n=1 rather than a fitted exponent: with only two usable years of
    promotional panel there is not enough signal to identify a shape parameter,
    and a fitted n would be a decorative degree of freedom. Stated rather than
    hidden.
    """
    calls = np.asarray(calls, dtype=float)
    return ceiling * calls / (half_sat + calls)


class _Ranked:
    """Opportunity-sorted arrays, computed once and reused.

    evaluate_force() used to sort the full 1.38M-row frame on every call. The
    tornado makes 15 roi_curve() passes over a 68-point rep grid -- roughly a
    thousand sorts of the same data, which took the module from seconds to
    beyond an hour. The ordering never changes, so it is done once.
    """

    __slots__ = ("wanted", "cum", "opportunity", "n")

    def __init__(self, planned: pd.DataFrame):
        order = np.argsort(-planned["opportunity"].to_numpy(dtype=float), kind="stable")

        # UNCONSTRAINED demand, not the served plan.
        #
        # hcp_call_plan.parquet is already truncated at the current force's
        # capacity, so `calls_per_year` sums to exactly what 60 reps can do.
        # Feeding that to the sizing model leaves nothing for rep 61 to call on:
        # the contribution curve flatlines immediately above the current
        # headcount and "break-even" becomes an artefact of the input rather
        # than a finding. Sizing asks what MORE reps would be worth, so it has
        # to see the demand the capacity cut discarded.
        # Accept any of the three shapes a caller might hold, in preference
        # order. `desired_calls` is monthly and unconstrained; `calls_per_year`
        # is already annual; `calls_per_month` is the capacity-capped served
        # plan and is the last resort precisely because of the flatlining above.
        if "desired_calls" in planned.columns:
            wanted = planned["desired_calls"].to_numpy(dtype=float) * 12.0
        elif "calls_per_year" in planned.columns:
            wanted = planned["calls_per_year"].to_numpy(dtype=float)
        elif "calls_per_month" in planned.columns:
            wanted = planned["calls_per_month"].to_numpy(dtype=float) * 12.0
        else:
            raise KeyError(
                "planned frame needs one of desired_calls / calls_per_year / "
                f"calls_per_month; got {list(planned.columns)[:8]}")
        self.wanted = wanted[order]
        self.opportunity = planned["opportunity"].to_numpy(dtype=float)[order]
        self.cum = np.cumsum(self.wanted)
        self.n = len(order)


def evaluate_force(planned: pd.DataFrame | _Ranked, n_reps: int,
                   overrides: dict | None = None) -> dict:
    """Contribution, cost and profit for a force of n_reps."""
    o = overrides or {}

    def p(key: str) -> float:
        return float(o[key]) if key in o else econ(key)

    annual_capacity = (n_reps * p("calls_per_rep_per_day")
                       * p("selling_days_per_month") * 12.0)

    r = planned if isinstance(planned, _Ranked) else _Ranked(planned)

    # Allocate in opportunity order until capacity is exhausted. The prescriber
    # straddling the boundary gets the partial remainder rather than being
    # dropped, so the curve is smooth in n and the derivative is meaningful.
    allocated = np.where(r.cum <= annual_capacity, r.wanted,
                         np.maximum(annual_capacity - (r.cum - r.wanted), 0.0))

    captured = r.opportunity * hill(
        allocated, p("call_response_ceiling"), p("call_response_half_saturation"))

    fills = float(captured.sum())
    contribution = fills * p("net_revenue_per_30day_fill") * p("contribution_margin")
    cost = n_reps * p("rep_cost_annual")

    return {
        "n_reps": n_reps,
        "annual_call_capacity": annual_capacity,
        "calls_allocated": float(allocated.sum()),
        "hcps_reached": int((allocated > 0).sum()),
        "incremental_fills": fills,
        "contribution": contribution,
        "field_cost": cost,
        "profit": contribution - cost,
        "roi": contribution / cost if cost else None,
    }


def roi_curve(planned: pd.DataFrame | _Ranked,
              overrides: dict | None = None) -> pd.DataFrame:
    """Total and marginal economics across the rep range. Exhibit E4."""
    cfg = economics()["sizing"]
    reps = list(range(cfg["rep_range_min"], cfg["rep_range_max"] + 1, cfg["rep_range_step"]))
    ranked = planned if isinstance(planned, _Ranked) else _Ranked(planned)
    rows = [evaluate_force(ranked, n, overrides) for n in reps]
    df = pd.DataFrame(rows)

    step = cfg["rep_range_step"]
    df["marginal_contribution"] = df["contribution"].diff() / step
    df["marginal_cost"] = (
        float(overrides["rep_cost_annual"]) if overrides and "rep_cost_annual" in overrides
        else econ("rep_cost_annual"))
    df["marginal_roi"] = df["marginal_contribution"] / df["marginal_cost"]
    return df


def break_even_reps(curve: pd.DataFrame) -> float:
    """Headcount where the marginal rep stops paying for itself (mROI = 1).

    Linear interpolation between the bracketing grid points rather than the
    nearest one -- with a step of 2 reps, snapping to the grid would quantise
    the headline recommendation into 2-rep jumps and make the sensitivity
    analysis look artificially stable.
    """
    d = curve.dropna(subset=["marginal_roi"])
    below = d[d["marginal_roi"] < 1.0]
    if below.empty:
        return float(d["n_reps"].max())      # still profitable at the top of the range
    first = below.iloc[0]
    prev = d[d["n_reps"] < first["n_reps"]]
    if prev.empty:
        return float(first["n_reps"])
    last = prev.iloc[-1]
    if last["marginal_roi"] == first["marginal_roi"]:
        return float(first["n_reps"])
    frac = (last["marginal_roi"] - 1.0) / (last["marginal_roi"] - first["marginal_roi"])
    return float(last["n_reps"] + frac * (first["n_reps"] - last["n_reps"]))


def tornado(planned: pd.DataFrame | _Ranked) -> pd.DataFrame:
    """Sweep each assumption low/high; rank by effect on break-even headcount."""
    ranked = planned if isinstance(planned, _Ranked) else _Ranked(planned)
    base_curve = roi_curve(ranked)
    base_be = break_even_reps(base_curve)
    econ_cfg = economics()

    rows = []
    for key in SWEEP_KEYS:
        node = econ_cfg[key]
        lo_be = break_even_reps(roi_curve(ranked, {key: node["low"]}))
        hi_be = break_even_reps(roi_curve(ranked, {key: node["high"]}))
        rows.append({
            "assumption": key,
            "base_value": node["base"],
            "low_value": node["low"],
            "high_value": node["high"],
            "break_even_low": lo_be,
            "break_even_base": base_be,
            "break_even_high": hi_be,
            "swing": abs(hi_be - lo_be),
            "basis": node.get("basis", "").strip().replace("\n", " "),
        })

    df = pd.DataFrame(rows).sort_values("swing", ascending=False).reset_index(drop=True)
    top = df.iloc[0]
    log.info("tornado: break-even is most sensitive to %s (swing %.0f reps across its "
             "stated range); least sensitive to %s (swing %.0f)",
             top["assumption"], top["swing"],
             df.iloc[-1]["assumption"], df.iloc[-1]["swing"])
    return df


def headline_h3(planned: pd.DataFrame | _Ranked) -> dict:
    """H3 -- explicitly a scenario, with its sensitivity range attached."""
    current = economics()["sizing"]["current_n_reps"]
    ranked = planned if isinstance(planned, _Ranked) else _Ranked(planned)
    curve = roi_curve(ranked)
    be = break_even_reps(curve)

    at_current = curve.loc[(curve["n_reps"] - current).abs().idxmin()]
    torn = tornado(ranked)
    be_low = float(torn[["break_even_low", "break_even_high"]].min().min())
    be_high = float(torn[["break_even_low", "break_even_high"]].max().max())

    # Value of moving from the current force to the break-even force.
    gap = int(round(be - current))
    at_be = evaluate_force(ranked, max(int(round(be)), 1))
    at_cur = evaluate_force(ranked, current)
    delta_profit = at_be["profit"] - at_cur["profit"]

    res = {
        "current_n_reps": current,
        "break_even_n_reps": round(be, 1),
        "rep_gap": gap,
        "marginal_roi_at_current": round(float(at_current["marginal_roi"]), 3),
        "roi_at_current": round(float(at_cur["roi"] or 0), 3),
        "contribution_at_current": round(at_cur["contribution"], 0),
        "contribution_at_break_even": round(at_be["contribution"], 0),
        "incremental_profit": round(delta_profit, 0),
        "sensitivity_low": round(be_low, 1),
        "sensitivity_high": round(be_high, 1),
        "label": "SCENARIO -- depends on the fitted response curve, not observed calls",
    }
    log.info("H3 (SCENARIO): marginal rep returns $%.2f per $1 at %d reps; break-even at "
             "%.0f reps (%+d). Incremental profit $%.1fM. Sensitivity: %.0f-%.0f reps.",
             res["marginal_roi_at_current"], current, be, gap,
             delta_profit / 1e6, be_low, be_high)
    record("headline_h3", **res)
    return res


def run() -> dict:
    proc = path("processed")
    planned = read_parquet(proc / "hcp_call_plan.parquet")
    ranked = _Ranked(planned)   # sort once, reuse across ~1,000 evaluations

    curve = roi_curve(ranked)
    torn = tornado(ranked)
    h3 = headline_h3(ranked)

    write_parquet(curve, proc / "sizing_roi_curve.parquet")
    write_parquet(torn, proc / "sizing_tornado.parquet")

    # Program P&L at the current force and at break-even.
    current = economics()["sizing"]["current_n_reps"]
    pnl = pd.DataFrame([
        {**evaluate_force(planned, current), "scenario": "Current force"},
        {**evaluate_force(planned, max(int(round(h3["break_even_n_reps"])), 1)),
         "scenario": "Break-even force"},
    ])
    write_parquet(pnl, proc / "sizing_pnl.parquet")
    return h3


if __name__ == "__main__":
    run()
