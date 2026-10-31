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
from src.models.opportunity import hybrid_score
from src.utils.io import get_logger, manifest, read_parquet, record, write_parquet

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


def _fitted_response() -> dict[str, float]:
    """The call-response parameters MEASURED by src/models/call_response.py.

    These were previously two constants typed into config/economics.yaml
    (ceiling 0.28, half-saturation 12.0), which made every dollar figure in this
    module an assertion. They are now fitted to Open Payments food-and-beverage
    event counts -- the closest public proxy for a rep visit -- within
    volume-decile strata, with a bootstrap interval.

    The fitted values are dramatically smaller than the assumed ones (ceiling
    0.0156 against 0.28, an 18-fold difference), which is precisely why the
    assumption could not be left standing.

    UNITS. The fit expresses the ceiling as a fraction of a prescriber's SHARE
    headroom captured per year; it is applied here to their opportunity in
    fills. Both are "the gap that could be closed", so the quantity carries
    over, but they are not identical constructions and that is stated rather
    than smoothed over.

    Falls back to the configured values when the fit has not run, and says so.
    """
    fit = manifest().get("call_response_fit") or {}
    if _response_identified(fit):
        return {
            "call_response_ceiling": float(fit["ceiling"]),
            "call_response_half_saturation": float(fit["half_saturation_calls"]),
        }
    return {}


def _response_identified(fit: dict | None = None) -> bool:
    """True only for a fitted curve that is off its bounds (call_response.py)."""
    fit = fit if fit is not None else (manifest().get("call_response_fit") or {})
    return bool(fit.get("fitted")) and fit.get("identifiable", True)


def _fitted_ranges() -> dict[str, dict]:
    """Tornado nodes (base/low/high/basis) for the fitted response parameters."""
    fit = manifest().get("call_response_fit") or {}
    if not _response_identified(fit):
        return {}
    basis = ("Fitted in src/models/call_response.py; range is the prescriber-level "
             "bootstrap 95% interval.")
    return {
        "call_response_ceiling": {
            "base": fit["ceiling"], "low": fit["ceiling_ci"][0],
            "high": fit["ceiling_ci"][1], "basis": basis},
        "call_response_half_saturation": {
            "base": fit["half_saturation_calls"], "low": fit["half_saturation_ci"][0],
            "high": fit["half_saturation_ci"][1], "basis": basis},
    }


def evaluate_force(planned: pd.DataFrame | _Ranked, n_reps: int,
                   overrides: dict | None = None) -> dict:
    """Contribution, cost and profit for a force of n_reps."""
    o = {**_fitted_response(), **(overrides or {})}

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
    fitted = _fitted_ranges()

    rows = []
    for key in SWEEP_KEYS:
        # A FITTED parameter is swept across its bootstrap interval, not the
        # config range. The config range for the ceiling (0.15-0.40) was drawn
        # around the old ASSUMED 0.28; sweeping it against a fitted 0.016 put
        # break-even anywhere from 40 to 589 reps -- a sensitivity to a number
        # the model no longer uses.
        node = fitted.get(key) or econ_cfg[key]
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

    # --- separate the DIAGNOSTIC from the RECOMMENDATION --------------------
    #
    # `be` is where economics alone stop binding. It is a real output and is
    # published. It is NOT a hiring plan: nothing in the model knows a field
    # force cannot be grown ten-fold, and presenting a 526-rep ask would tell a
    # reader that the fitted response curve is doing all the work.
    #
    # The recommendation is capped at one recruiting cycle. Everything past the
    # cap is reported as unmet demand -- which is the honest description of it,
    # and is arithmetic rather than scenario.
    ceiling = economics()["sizing"].get("max_plausible_expansion", 1.5)
    max_recommendable = int(round(current * ceiling))
    recommended = int(min(round(be), max_recommendable))
    capped = round(be) > max_recommendable

    at_cur = evaluate_force(ranked, current)
    at_rec = evaluate_force(ranked, max(recommended, 1))
    at_be = evaluate_force(ranked, max(int(round(be)), 1))
    delta_profit = at_rec["profit"] - at_cur["profit"]

    res = {
        "current_n_reps": current,
        # what we actually recommend
        "recommended_n_reps": recommended,
        "recommended_add": recommended - current,
        "recommendation_capped": bool(capped),
        "cap_basis": (f"one recruiting cycle ({ceiling}x current force); "
                      f"the model's unconstrained answer is not executable"),
        "incremental_profit": round(delta_profit, 0),
        # the diagnostic, published but never presented as an ask
        "break_even_n_reps": round(be, 1),
        "unmet_demand_reps": max(int(round(be)) - recommended, 0),
        "marginal_roi_at_current": round(float(at_current["marginal_roi"]), 3),
        "marginal_roi_at_recommended": round(
            float(curve.loc[(curve["n_reps"] - recommended).abs().idxmin(), "marginal_roi"] or 0), 3),
        "roi_at_current": round(float(at_cur["roi"] or 0), 3),
        "contribution_at_current": round(at_cur["contribution"], 0),
        "contribution_at_recommended": round(at_rec["contribution"], 0),
        "contribution_at_break_even": round(at_be["contribution"], 0),
        "sensitivity_low": round(be_low, 1),
        "sensitivity_high": round(be_high, 1),
        "label": "SCENARIO -- depends on the fitted response curve, not observed calls",
    }

    if not _response_identified():
        # THE HONEST BRANCH. The fitted response is not identifiable from the
        # public proxy, so there is no measured curve to price headcount on.
        # Pricing the flat fit would "recommend" cutting the force to the bottom
        # of the grid (zero response => every rep is pure cost), and pricing the
        # config constants would resurrect the invented 0.28. Neither is a
        # finding. The decision-useful output is the BREAK-EVEN RESPONSE: how
        # large the call response must be for today's 60th rep to pay for itself.
        # The recommendation is to hold headcount and measure that number in a
        # pilot, which public data cannot do.
        need = required_ceiling(ranked, current)
        res.update({
            "response_identified": False,
            "recommended_n_reps": current,
            "recommended_add": 0,
            "recommendation_capped": False,
            "incremental_profit": 0.0,
            "required_ceiling_at_current": round(need, 5) if need is not None else None,
            "required_ceiling_half_saturation": econ("call_response_half_saturation"),
            "illustrative_break_even_n_reps": round(be, 1),
            "label": ("NOT IDENTIFIED -- public data show no measurable call response; "
                      "headcount held, break-even response reported, pilot recommended. "
                      "Break-even and sensitivity shown use the config ASSUMPTIONS and "
                      "are illustrative only."),
        })
        log.warning("H3: call response not identified. HOLD at %d reps. The 60th rep "
                    "pays for itself only if a year of calling captures >= %.2f%% of a "
                    "prescriber's remaining opportunity (half-saturation %.0f calls).",
                    current, 100 * (need or float("nan")),
                    econ("call_response_half_saturation"))
        record("headline_h3", **res)
        return res

    res["response_identified"] = True
    log.info("H3 RECOMMENDATION: add %d reps (%d -> %d), worth $%.1fM in contribution. "
             "Marginal rep still returns $%.2f per $1 at the recommended size.",
             res["recommended_add"], current, recommended,
             delta_profit / 1e6, res["marginal_roi_at_recommended"])
    if capped:
        log.info("  DIAGNOSTIC (not a recommendation): economics alone do not bind until "
                 "%.0f reps, leaving %d reps of unmet demand beyond what one recruiting "
                 "cycle can absorb. Reported as coverage shortfall, not as a hiring ask -- "
                 "a %.0fx expansion is not executable and quoting it would say only that "
                 "the response curve is carrying the result.",
                 be, res["unmet_demand_reps"], be / current)
    log.info("  Sensitivity on the break-even diagnostic: %.0f-%.0f reps.", be_low, be_high)

    record("headline_h3", **res)
    return res


def required_ceiling(ranked: _Ranked, n_reps: int, half_sat: float | None = None,
                     lo: float = 1e-5, hi: float = 1.0, iters: int = 40) -> float | None:
    """Response ceiling at which the n-th rep exactly pays for itself (mROI = 1).

    Marginal ROI rises monotonically in the ceiling (contribution is linear in
    it), so bisection is exact. Uses the same one-step marginal as roi_curve:
    contribution(n) - contribution(n - step), per rep, over rep cost.
    """
    step = economics()["sizing"]["rep_range_step"]
    half = half_sat if half_sat is not None else econ("call_response_half_saturation")
    cost = econ("rep_cost_annual")

    def mroi(c: float) -> float:
        o = {"call_response_ceiling": c, "call_response_half_saturation": half}
        hi_ = evaluate_force(ranked, n_reps, o)["contribution"]
        lo_ = evaluate_force(ranked, max(n_reps - step, 1), o)["contribution"]
        return (hi_ - lo_) / step / cost

    if mroi(hi) < 1.0:
        return None          # not even a 100%-of-headroom response pays
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        if mroi(mid) >= 1.0:
            hi = mid
        else:
            lo = mid
    return hi


def retargeting_value(planned: pd.DataFrame, n_reps: int | None = None) -> dict:
    """What is the recommendation WORTH, at identical headcount and cost?

    THE GAP THIS CLOSES
    -------------------
    Once the fitted response curve showed the field force was already the right
    size, the sizing module stopped producing a dollar figure -- and the project
    was left arguing brilliantly for a recommendation whose value it never
    stated. "2.2x more addressable opportunity reached" is a ratio. A brand team
    approves money, not ratios.

    THE COMPARISON
    --------------
    Hold EVERYTHING constant except the ranking used to allocate a fixed call
    budget:

        same 60 reps, same cost, same calls/day, same response curve
        rule A: fill the diaries from the top of the OPPORTUNITY ranking
        rule B: fill them from the top of the VOLUME ranking (the status quo)

    The difference in captured fills, priced at net revenue and margin, is the
    value of retargeting. Because cost is identical on both sides it cancels
    entirely -- this is pure incremental contribution, which is the cleanest
    form a consulting number can take.

    It is still a SCENARIO: it inherits the fitted response curve and therefore
    that curve's upper-bound caveat. But the curve is now measured, and the
    comparison holds every other input fixed, so the ratio between the two arms
    is far more robust than either arm's absolute level.
    """
    n_reps = n_reps or economics()["sizing"]["current_n_reps"]
    resp = _fitted_response()
    identified = _response_identified()
    if identified:
        ceiling = resp["call_response_ceiling"]
        half = resp["call_response_half_saturation"]
        pricing = "fitted response curve"
    else:
        # No measured response to price on. Price at the BREAK-EVEN response --
        # the weakest response under which today's force pays for itself. If
        # calling works at all well enough to justify 60 reps, re-targeting is
        # worth at least this; it is a floor conditional on the force being
        # worth having, not a measurement.
        half = econ("call_response_half_saturation")
        ceiling = required_ceiling(_Ranked(planned), n_reps, half) or 0.0
        pricing = "break-even response (the response at which today's force exactly pays)"

    annual_capacity = (n_reps * econ("calls_per_rep_per_day")
                       * econ("selling_days_per_month") * 12.0)
    per_fill = econ("net_revenue_per_30day_fill") * econ("contribution_margin")

    # Flat frequency so the two arms differ ONLY in who is chosen, not in how
    # often they are seen. Using the opportunity-derived matrix frequency on
    # both sides would smuggle the opportunity model into the volume arm.
    served = planned.loc[planned["is_target"], "calls_per_month"]
    freq = float(served.mean() * 12.0) if len(served) else 12.0
    n_reachable = int(min(annual_capacity / max(freq, 1e-6), len(planned)))

    out: dict[str, float | int | str] = {
        "n_reps": n_reps,
        "annual_capacity_calls": round(annual_capacity, 0),
        "calls_per_target_per_year": round(freq, 2),
        "prescribers_reachable": n_reachable,
    }

    # Rank inside the addressable market. Ranking the whole Part D file on
    # opportunity used to put non-writers on the list (see score_opportunity).
    pool = planned[planned["class_fills"] > 0].copy()
    pool["hybrid"] = hybrid_score(pool)
    n_reachable = min(n_reachable, len(pool))
    out["prescribers_reachable"] = n_reachable

    captured: dict[str, float] = {}
    for rule, col in (("opportunity", "opportunity"), ("volume", "class_fills"),
                      ("hybrid", "hybrid")):
        top = pool.nlargest(n_reachable, col)
        fills = float((top["opportunity"].to_numpy(dtype=float)
                       * hill(np.full(len(top), freq), ceiling, half)).sum())
        captured[rule] = fills
        out[f"{rule}_incremental_fills"] = round(fills, 0)
        out[f"{rule}_contribution"] = round(fills * per_fill, 0)

    delta_fills = captured["opportunity"] - captured["volume"]
    delta_value = delta_fills * per_fill
    out["delta_fills"] = round(delta_fills, 0)
    out["delta_contribution"] = round(delta_value, 0)
    out["uplift_vs_volume"] = (round(captured["opportunity"] / captured["volume"], 3)
                               if captured["volume"] else None)
    out["hybrid_vs_volume_contribution"] = round(
        (captured["hybrid"] - captured["volume"]) * per_fill, 0)
    out["field_cost"] = round(n_reps * econ("rep_cost_annual"), 0)
    out["incremental_cost"] = 0
    # READ THIS BEFORE QUOTING THE DOLLAR FIGURE. Each arm is priced as
    # (modelled opportunity on its list) x (fitted response). Ranking by
    # opportunity maximises the first term BY CONSTRUCTION, so the opportunity
    # arm cannot lose this comparison -- it is a valuation of the opportunity
    # model's own view, not evidence for it. The evidence is the back-test
    # (realised 2024 growth on each list); see challenger.py / backtest.py.
    out["priced_at"] = pricing
    out["priced_ceiling"] = round(float(ceiling), 5)
    out["priced_half_saturation"] = float(half)
    out["label"] = (f"MODELLED -- prices each list's modelled opportunity at the {pricing}. "
                    "Ranking on opportunity maximises modelled opportunity by construction; "
                    "validate against the realised-growth back-test before quoting.")

    log.info("RETARGETING VALUE at %d reps (cost identical on both sides):", n_reps)
    log.info("  opportunity-ranked  %s incremental fills  -> %s contribution",
             f"{captured['opportunity']:,.0f}", f"${out['opportunity_contribution']:,.0f}")
    log.info("  volume-ranked       %s incremental fills  -> %s contribution",
             f"{captured['volume']:,.0f}", f"${out['volume_contribution']:,.0f}")
    log.info("  DELTA               %s fills = %s a year, for ZERO additional cost "
             "(%.2fx uplift on the same %d reps)",
             f"{delta_fills:,.0f}", f"${delta_value:,.0f}",
             out["uplift_vs_volume"] or 0, n_reps)

    record("retargeting_value", **out)
    return out


def run() -> dict:
    proc = path("processed")
    planned = read_parquet(proc / "hcp_call_plan.parquet")
    ranked = _Ranked(planned)   # sort once, reuse across ~1,000 evaluations

    curve = roi_curve(ranked)
    torn = tornado(ranked)
    h3 = headline_h3(ranked)
    retarget = retargeting_value(planned)
    h3["retargeting_contribution"] = retarget.get("delta_contribution")

    write_parquet(curve, proc / "sizing_roi_curve.parquet")
    write_parquet(torn, proc / "sizing_tornado.parquet")

    # The exhibit that replaces the ROI curve when the response is not
    # identified: for each force size, the call response the LAST rep would
    # need to pay for itself. It turns "we cannot measure it" into a number a
    # pilot can be designed against.
    cfg = economics()["sizing"]
    grid = range(cfg["rep_range_min"] + cfg["rep_range_step"], cfg["rep_range_max"] + 1,
                 cfg["rep_range_step"])
    need = pd.DataFrame([{"n_reps": n, "required_ceiling": required_ceiling(ranked, n)}
                         for n in grid])
    write_parquet(need, proc / "sizing_required_response.parquet")

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
