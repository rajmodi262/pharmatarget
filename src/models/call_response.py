"""Fit the call-response curve from data instead of asserting it.

    python -m src.models.call_response

THE PROBLEM THIS SOLVES
-----------------------
Every dollar figure in this project -- the contribution, the marginal ROI, the
break-even headcount -- flowed from two numbers typed into config/economics.yaml:

    call_response_ceiling: 0.28
    call_response_half_saturation: 12.0

They were invented. The sizing module was therefore a spreadsheet with a curve
drawn on it, and its own tornado said so: break-even swung 229 reps across the
stated range of a single input.

THE PROXY, AND WHY IT IS DEFENSIBLE
-----------------------------------
CMS publishes no rep call data. But Open Payments logs a food-and-beverage
transfer whenever a representative buys a prescriber a meal during a detailing
visit -- so the COUNT of those events is the closest public approximation of the
number of promotional touchpoints a prescriber received in a year.

Counting EVENTS, restricted to the food nature, is what makes this a call proxy
rather than a spend proxy: a $12 sandwich and a $12 coffee are two visits, while
a single $2,400 consulting fee is not a visit at all.

Real distribution: 457,496 prescriber-years with at least one food event,
median 3 per year, mean 6.1, max 137. That is a plausible detailing frequency
and it is measured, not assumed.

CONFOUNDING, HANDLED AND THEN STATED ANYWAY
-------------------------------------------
Reps visit prescribers who are already high-volume and already favourable. Left
uncontrolled, the fitted response would mostly be measuring targeting.

Controlled here by fitting WITHIN volume-decile strata: a prescriber is compared
only against others of similar baseline volume, and the stratum mean is removed
before fitting. That kills the dominant confounder -- size -- but not the
residual one: within a volume band, reps still choose whom to visit, and they
choose on information the model cannot see.

So the fitted ceiling remains an UPPER BOUND on the true causal response, and
sizing.py labels every figure derived from it a SCENARIO. What changes is that
the scenario is now anchored to observed behaviour with a published confidence
interval, rather than to a number someone typed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

from src.config import params, path
from src.utils.io import get_logger, read_parquet, record, write_parquet

log = get_logger(__name__)

N_BOOT = 300
MAX_CALLS = 36          # 3/month; beyond this the data is too thin to fit
MIN_STRATUM = 200       # prescribers needed in a (decile, calls) cell


def hill(calls: np.ndarray, ceiling: float, half: float) -> np.ndarray:
    """Michaelis-Menten saturation. n=1 -- see sizing.hill for why not fitted."""
    calls = np.asarray(calls, dtype=float)
    return ceiling * calls / (np.maximum(half, 1e-6) + calls)


def build_panel() -> pd.DataFrame:
    """Per-prescriber annual calls (year t) against share growth (t -> t+1)."""
    p = params()["years"]
    t, t1 = p["train_end"], p["holdout"]
    proc = path("processed")

    metrics = read_parquet(proc / "mart_hcp_metrics.parquet")
    payments = read_parquet(proc / "mart_payments.parquet")

    base = metrics[(metrics["year"] == t) & (metrics["class_fills"] > 0)][
        ["npi", "class_fills", "brand_share", "brand_fills"]]
    nxt = metrics[metrics["year"] == t1][["npi", "brand_share", "brand_fills"]].rename(
        columns={"brand_share": "brand_share_next", "brand_fills": "brand_fills_next"})

    calls = payments[payments["year"] == t][["npi", "pay_food_count"]].rename(
        columns={"pay_food_count": "calls"})

    df = base.merge(nxt, on="npi", how="inner").merge(calls, on="npi", how="left")
    df["calls"] = df["calls"].fillna(0).clip(upper=MAX_CALLS)
    df["brand_share"] = df["brand_share"].fillna(0.0)
    df["brand_share_next"] = df["brand_share_next"].fillna(0.0)
    df["share_growth"] = df["brand_share_next"] - df["brand_share"]

    # Headroom: a prescriber at 95% share cannot gain 20 points however many
    # visits they get, so the response has to be measured against what is
    # actually winnable rather than against zero.
    df["headroom"] = (1.0 - df["brand_share"]).clip(lower=0.01)
    df["captured"] = (df["share_growth"] / df["headroom"]).clip(-1, 1)

    df["vol_decile"] = pd.qcut(df["class_fills"].rank(method="first"),
                               10, labels=False) + 1

    log.info("panel: %s prescribers, %s with >=1 call, median calls %.0f",
             f"{len(df):,}", f"{int((df['calls'] > 0).sum()):,}",
             df.loc[df["calls"] > 0, "calls"].median())
    return df


def stratified_curve(df: pd.DataFrame) -> pd.DataFrame:
    """Mean captured-headroom by call count, within volume strata, then pooled.

    Removing the stratum mean at zero calls is what turns a raw correlation into
    a dose-response: each point becomes "how much more headroom did prescribers
    at this call level capture than otherwise-similar prescribers who got no
    visits at all".
    """
    rows = []
    for decile, grp in df.groupby("vol_decile"):
        baseline = grp.loc[grp["calls"] == 0, "captured"]
        if len(baseline) < MIN_STRATUM:
            continue
        base_mean = float(baseline.mean())
        for calls, cell in grp.groupby("calls"):
            if len(cell) < MIN_STRATUM:
                continue
            rows.append({
                "vol_decile": int(decile),
                "calls": float(calls),
                "n": len(cell),
                "captured_excess": float(cell["captured"].mean()) - base_mean,
            })

    cell = pd.DataFrame(rows)
    if cell.empty:
        return cell

    # Pool strata weighted by cell size, so a thin high-decile cell cannot
    # dominate the fit. Done with a weighted sum rather than groupby.apply:
    # `include_groups` is a pandas 2.2 API and this project runs on 1.5.3.
    cell["weighted"] = cell["captured_excess"] * cell["n"]
    agg = cell.groupby("calls", as_index=False).agg(
        weighted=("weighted", "sum"), n=("n", "sum"))
    agg["captured_excess"] = agg["weighted"] / agg["n"]
    pooled = agg[["calls", "captured_excess", "n"]].sort_values("calls").reset_index(drop=True)
    log.info("dose-response: %d call levels, %s prescribers pooled across %d strata",
             len(pooled), f"{int(pooled['n'].sum()):,}", cell["vol_decile"].nunique())
    return pooled


def fit_hill(pooled: pd.DataFrame, n_boot: int = N_BOOT) -> dict:
    """Fit ceiling and half-saturation with a weighted bootstrap CI."""
    x = pooled["calls"].to_numpy(dtype=float)
    y = pooled["captured_excess"].to_numpy(dtype=float)
    w = pooled["n"].to_numpy(dtype=float)

    if len(x) < 4 or x.max() <= 0:
        log.warning("too few call levels to fit; sizing will fall back to config")
        return {"fitted": False}

    p0 = [max(float(y.max()), 0.05), 6.0]
    try:
        popt, _ = curve_fit(hill, x, y, p0=p0, sigma=1.0 / np.sqrt(w),
                            bounds=([0.0, 0.5], [1.0, 60.0]), maxfev=20000)
    except (RuntimeError, ValueError) as exc:
        log.warning("Hill fit did not converge (%s); falling back to config", exc)
        return {"fitted": False}

    rng = np.random.default_rng(0)
    boots = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(x), len(x))
        try:
            b, _ = curve_fit(hill, x[idx], y[idx], p0=popt,
                             sigma=1.0 / np.sqrt(w[idx]),
                             bounds=([0.0, 0.5], [1.0, 60.0]), maxfev=8000)
            boots.append(b)
        except (RuntimeError, ValueError):
            continue

    boots = np.array(boots) if len(boots) > 20 else popt[None, :]
    ceiling, half = float(popt[0]), float(popt[1])
    c_lo, c_hi = np.percentile(boots[:, 0], [2.5, 97.5])
    h_lo, h_hi = np.percentile(boots[:, 1], [2.5, 97.5])

    pred = hill(x, *popt)
    ss_res = float(np.sum(w * (y - pred) ** 2))
    ss_tot = float(np.sum(w * (y - np.average(y, weights=w)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

    res = {
        "fitted": True,
        "ceiling": round(ceiling, 5),
        "ceiling_ci": [round(float(c_lo), 5), round(float(c_hi), 5)],
        "half_saturation_calls": round(half, 3),
        "half_saturation_ci": [round(float(h_lo), 3), round(float(h_hi), 3)],
        "weighted_r2": round(float(r2), 4),
        "n_levels": int(len(x)),
        "n_prescribers": int(pooled["n"].sum()),
        "identified_from": "Open Payments food-and-beverage event count (rep-visit proxy)",
        "caveat": ("Observational. Volume-decile stratification removes the dominant "
                   "confounder but reps still select within a stratum on information "
                   "the model cannot see. Treat the ceiling as an UPPER BOUND."),
    }

    log.info("FITTED call-response curve:")
    log.info("  ceiling            %.4f of headroom  [%.4f, %.4f]",
             ceiling, c_lo, c_hi)
    log.info("  half-saturation    %.1f calls/year   [%.1f, %.1f]", half, h_lo, h_hi)
    log.info("  weighted R^2       %.3f over %d call levels, %s prescribers",
             r2, len(x), f"{int(pooled['n'].sum()):,}")
    log.info("  vs the previously ASSUMED ceiling 0.28 and half-saturation 12.0 -- "
             "those were typed into a config file; these are measured.")
    record("call_response_fit", **res)
    return res


def run() -> dict:
    proc = path("processed")
    df = build_panel()
    pooled = stratified_curve(df)
    if pooled.empty:
        log.warning("no usable dose-response cells; sizing keeps the configured values")
        record("call_response_fit", fitted=False)
        return {"fitted": False}

    write_parquet(pooled, proc / "call_response_curve.parquet")
    res = fit_hill(pooled)
    return res


if __name__ == "__main__":
    run()
