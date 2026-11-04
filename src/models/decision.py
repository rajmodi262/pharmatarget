"""Decision lab: the three questions a partner asks after reading the deck.

    python -m src.models.decision

The recommendation survived the back-test, but three soft spots remain, and a
reviewer will find each of them in the first ten minutes:

  1. WHY AN EQUAL-WEIGHT BLEND? The hybrid is 50% opportunity rank + 50% volume
     rank. Nothing chose 50%. If 30% or 70% does better, the recommendation is
     leaving value on the table; if the answer moves a lot with the weight, it
     is fragile. So the weight is swept 0 -> 1, CHOSEN on the earlier period
     (2022 state -> 2023 growth) and only then READ on the holdout (2023 ->
     2024). Choosing it on the holdout would be fitting to the exam.

  2. HOW CLOSE IS THE CALL? The hybrid keeps 90.8% of volume's absolute growth
     against a 90% floor. A point estimate that close to its threshold is a
     coin the reader has to be shown. The bootstrap gives the probability that
     each weight clears the floor.

  3. WHAT WOULD THE PILOT NEED? Headcount is held because public data cannot
     measure a call response. "Run a pilot" is only a recommendation if it says
     how big, how long and what it can detect. This sizes it: the effect the
     pilot must detect is the break-even response, and the noise is the real
     year-on-year growth variance of the prescribers it would run on.

Everything here reuses the challenger's out-of-time panels and capture metric,
so the numbers reconcile with challenger.py and robustness.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import econ, economics, path
from src.models.challenger import ABS_FLOOR_VS_VOLUME, build_panels
from src.models.sizing import hill
from src.utils.io import get_logger, manifest, read_parquet, record, write_parquet

log = get_logger(__name__)

WEIGHTS = np.round(np.linspace(0.0, 1.0, 21), 2)   # opportunity weight; 0 = volume
N_BOOT = 200


# --------------------------------------------------------------------------- #
# 1-2. Blend frontier
# --------------------------------------------------------------------------- #

def _ranks(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    return (df["opportunity"].rank(pct=True).to_numpy(dtype=float),
            df["class_fills"].rank(pct=True).to_numpy(dtype=float))


def _capture(score: np.ndarray, g_abs: np.ndarray, g_share: np.ndarray,
             n_budget: int) -> tuple[float, float, float]:
    """(abs capture, share capture, net branded fills) of the top-n list."""
    top = np.argpartition(-score, n_budget - 1)[:n_budget]
    tot_abs = g_abs[g_abs > 0].sum()
    tot_share = g_share[g_share > 0].sum()
    return (float(np.clip(g_abs[top], 0, None).sum() / tot_abs),
            float(np.clip(g_share[top], 0, None).sum() / tot_share),
            float(g_abs[top].sum()))


def blend_frontier(panel: pd.DataFrame, n_budget: int,
                   weights: np.ndarray = WEIGHTS) -> pd.DataFrame:
    """Share and absolute capture of the w-weighted list, relative to volume (w=0)."""
    r_opp, r_vol = _ranks(panel)
    g_abs = panel["growth_abs"].to_numpy(dtype=float)
    g_share = panel["growth_share"].to_numpy(dtype=float)
    rows = []
    for w in weights:
        a, s, net = _capture(w * r_opp + (1 - w) * r_vol, g_abs, g_share, n_budget)
        rows.append({"weight": float(w), "abs_capture": a, "share_capture": s,
                     "net_brand_fill_growth": net})
    out = pd.DataFrame(rows)
    base = out.iloc[0]
    out["abs_vs_volume"] = out["abs_capture"] / base["abs_capture"]
    out["share_vs_volume"] = out["share_capture"] / base["share_capture"]
    out["clears_floor"] = out["abs_vs_volume"] >= ABS_FLOOR_VS_VOLUME
    return out


def bootstrap_frontier(panel: pd.DataFrame, n_budget: int, n_boot: int = N_BOOT,
                       weights: np.ndarray = WEIGHTS) -> pd.DataFrame:
    """Per weight: CI on both ratios and P(abs ratio >= floor), resampling prescribers.

    Ranks are recomputed inside each draw so a resampled prescriber's percentile
    reflects the resampled market, exactly as a fresh year would.
    """
    rng = np.random.default_rng(7)
    n = len(panel)
    opp_ = panel["opportunity"].to_numpy(dtype=float)
    vol_ = panel["class_fills"].to_numpy(dtype=float)
    ga = panel["growth_abs"].to_numpy(dtype=float)
    gs = panel["growth_share"].to_numpy(dtype=float)

    abs_r = np.empty((n_boot, len(weights)))
    share_r = np.empty((n_boot, len(weights)))
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        ro = pd.Series(opp_[idx]).rank(pct=True).to_numpy()
        rv = pd.Series(vol_[idx]).rank(pct=True).to_numpy()
        res = [_capture(w * ro + (1 - w) * rv, ga[idx], gs[idx], n_budget) for w in weights]
        a = np.array([x[0] for x in res])
        s = np.array([x[1] for x in res])
        abs_r[b] = a / a[0]
        share_r[b] = s / s[0]
        if (b + 1) % 50 == 0:
            log.info("  frontier bootstrap %d/%d", b + 1, n_boot)

    return pd.DataFrame({
        "weight": weights,
        "abs_vs_volume_lo": np.percentile(abs_r, 2.5, axis=0),
        "abs_vs_volume_hi": np.percentile(abs_r, 97.5, axis=0),
        "share_vs_volume_lo": np.percentile(share_r, 2.5, axis=0),
        "share_vs_volume_hi": np.percentile(share_r, 97.5, axis=0),
        # Two decimals, so every surface (deck, API, browser) rounds it alike.
        "p_clears_floor": np.round((abs_r >= ABS_FLOOR_VS_VOLUME).mean(axis=0), 2),
    })


def choose_weight(frontier: pd.DataFrame) -> float:
    """The pre-declared rule, applied to a continuum instead of three candidates."""
    ok = frontier[frontier["abs_vs_volume"] >= ABS_FLOOR_VS_VOLUME]
    return float(ok.loc[ok["share_capture"].idxmax(), "weight"])


# --------------------------------------------------------------------------- #
# 3. Pilot power
# --------------------------------------------------------------------------- #

def _icc(values: np.ndarray, groups: np.ndarray) -> float:
    """One-way ANOVA intraclass correlation (ICC(1)), floored at zero."""
    df = pd.DataFrame({"y": values, "g": groups}).dropna()
    k = df.groupby("g")["y"].agg(["mean", "count", "var"])
    k = k[k["count"] >= 2]
    if len(k) < 3:
        return 0.0
    n_i = k["count"].to_numpy(dtype=float)
    N, a = n_i.sum(), len(n_i)
    grand = df.loc[df["g"].isin(k.index), "y"].mean()
    msb = (n_i * (k["mean"] - grand) ** 2).sum() / (a - 1)
    msw = ((n_i - 1) * k["var"]).sum() / (N - a)
    n0 = (N - (n_i ** 2).sum() / N) / (a - 1)
    icc = (msb - msw) / (msb + (n0 - 1) * msw) if (msb + (n0 - 1) * msw) > 0 else 0.0
    return float(max(icc, 0.0))


def _norm_cdf(x: np.ndarray | float) -> np.ndarray:
    from math import erf, sqrt
    return np.vectorize(lambda v: 0.5 * (1 + erf(v / sqrt(2))))(x)


def power(delta: float, sd: float, n_treat: float, n_ctrl: float, deff: float = 1.0,
          alpha_z: float = 1.959964) -> float:
    """Two-arm, two-sided z-test power for a mean difference (arms may be unequal)."""
    se = sd * np.sqrt(deff * (1.0 / max(n_treat, 1.0) + 1.0 / max(n_ctrl, 1.0)))
    return float(_norm_cdf(delta / se - alpha_z))


def _endpoint(lst: pd.DataFrame, train: pd.DataFrame, effect: pd.Series,
              col: str, terr: np.ndarray) -> dict:
    """Effect, winsorised noise, CUPED correlation and territory ICC for one outcome."""
    g = lst[col].astype(float).reset_index(drop=True)
    lo, hi = g.quantile([0.01, 0.99])
    g_w = g.clip(lo, hi)
    prior = lst[["npi"]].merge(train[["npi", col]].rename(columns={col: "prior"}),
                               on="npi", how="left")["prior"].to_numpy()
    both = ~np.isnan(prior)
    rho = (float(np.corrcoef(g_w.to_numpy()[both], np.clip(prior[both], lo, hi))[0, 1])
           if both.sum() > 30 else 0.0)
    return {
        "effect_per_year": float(effect.mean()),
        "sd_per_year": float(g_w.std()),
        "prior_rho": max(rho, 0.0),
        "icc_territory": _icc(g_w.to_numpy(), terr),
    }


def _designs(ep: dict, n_list: int, m_size: float, n_terr: int) -> dict:
    """Worked designs: prescriber hold-out and territory randomisation, 6 and 12 months."""
    out = {}
    adj = np.sqrt(max(1 - ep["prior_rho"] ** 2, 0.0))
    deff = 1 + (m_size - 1) * ep["icc_territory"]
    for months in (6, 12):
        t = months / 12
        d, s = ep["effect_per_year"] * t, ep["sd_per_year"] * np.sqrt(t) * adj
        hold = 0.2 * n_list
        out[f"power_holdout20_{months}m"] = round(power(d, s, n_list - hold, hold), 3)
        half = (n_terr // 2) * m_size
        out[f"power_territory_split_{months}m"] = round(power(d, s, half, half, deff), 3)
        out[f"holdout_share_needed_80pct_{months}m"] = next(
            (round(f, 2) for f in np.arange(0.05, 0.51, 0.01)
             if power(d, s, n_list * (1 - f), n_list * f) >= 0.8), None)
    return out


def pilot_design(apply_: pd.DataFrame, train: pd.DataFrame, weight: float,
                 n_budget: int) -> dict:
    """Effect, noise and clustering inputs for the pilot, plus worked designs.

    THE EFFECT. If calling works exactly well enough for today's force to pay
    (the break-even response), a called prescriber gains
        required_ceiling * opportunity * f / (k + f)
    branded fills a year at f calls -- or that divided by their class volume in
    share points. That is the smallest effect worth finding: anything weaker
    means the force is over-sized whatever the targeting.

    THE NOISE. The real 2023->2024 change across the prescribers the pilot would
    run on, winsorised at 1%/99% because a handful of practice mergers would
    otherwise set the sample size. Prior-year change is the covariate for a
    CUPED/ANCOVA adjustment, which removes rho^2 of the variance at no cost.

    THE ENDPOINT DECIDES THE PILOT. Branded fills are dominated by the size of
    the practice: a 2,000-fill prescriber swings by hundreds a year for reasons
    no rep controls. Share points are volume-neutral, so the same break-even
    effect stands several times further out of the noise. Both are reported so
    the choice is visible rather than assumed.

    TIME. Effect scales linearly with duration; noise is assumed to scale with
    the square root of it (a random walk). That assumption is stated because it
    is the one the pilot's own first quarter should check.
    """
    m = manifest()
    req = float((m.get("headline_h3") or {}).get("required_ceiling_at_current") or 0.0)
    rv = m.get("retargeting_value") or {}
    f = float(rv.get("calls_per_target_per_year") or 12.0)
    k = econ("call_response_half_saturation")

    r_opp = apply_["opportunity"].rank(pct=True)
    r_vol = apply_["class_fills"].rank(pct=True)
    lst = (apply_.assign(_s=weight * r_opp + (1 - weight) * r_vol)
           .nlargest(n_budget, "_s").reset_index(drop=True))

    fills_effect = req * lst["opportunity"].clip(lower=0) * float(hill(np.array([f]), 1.0, k)[0])
    share_effect = fills_effect / lst["class_fills"].clip(lower=1)

    # Territory of each listed prescriber, from the optimised alignment.
    assign = read_parquet(path("processed") / "territory_assignments.parquet",
                          columns=["unit", "alignment", "n_reps", "territory"], lean=False)
    n_reps = economics()["sizing"]["current_n_reps"]
    assign = assign[(assign["alignment"] == "optimised") & (assign["n_reps"] == n_reps)]
    terr = lst[["zip3"]].astype(str).merge(
        assign[["unit", "territory"]].astype({"unit": str}),
        left_on="zip3", right_on="unit", how="left")["territory"].to_numpy()
    m_size = float(len(lst) / max(len(pd.unique(terr[~pd.isna(terr)])), 1))

    endpoints = {
        "share": _endpoint(lst, train, share_effect, "growth_share", terr),
        "fills": _endpoint(lst, train, fills_effect, "growth_abs", terr),
    }
    out: dict = {
        "weight": weight,
        "n_list": int(len(lst)),
        "required_ceiling": req,
        "calls_per_year": f,
        "half_saturation": k,
        "prescribers_per_territory": round(m_size, 1),
        "n_territories": int(n_reps),
        "time_scaling": "effect ~ T, noise ~ sqrt(T)",
        "winsorised": "1%/99%",
        "recommended_endpoint": "share",
    }
    for name, ep in endpoints.items():
        ep.update(_designs(ep, len(lst), m_size, n_reps))
        out[name] = {k_: (round(v, 5) if isinstance(v, float) else v) for k_, v in ep.items()}
        log.info("PILOT [%s]: break-even effect %.4g/prescriber/yr, sd %.4g, rho %.2f, "
                 "ICC %.3f | 20%% hold-out power %.0f%% at 6m, %.0f%% at 12m",
                 name, ep["effect_per_year"], ep["sd_per_year"], ep["prior_rho"],
                 ep["icc_territory"], 100 * ep["power_holdout20_6m"],
                 100 * ep["power_holdout20_12m"])
    return out


# --------------------------------------------------------------------------- #

def run() -> dict:
    proc = path("processed")
    scored = read_parquet(proc / "hcp_scored.parquet", columns=[
        "npi", "year", "zip3", "class_fills", "brand_fills", "brand_share",
        "potential_brand", "opportunity"])
    train, apply_ = build_panels(scored)
    del scored
    n_budget = int((manifest().get("challenger") or {}).get("n_budget") or 0.03 * len(apply_))

    fit = blend_frontier(train, n_budget)
    hold = blend_frontier(apply_, n_budget)
    w_star = choose_weight(fit)
    boot = bootstrap_frontier(apply_, n_budget)

    frontier = pd.concat([fit.assign(period="selection"),
                          hold.merge(boot, on="weight").assign(period="holdout")],
                         ignore_index=True)
    write_parquet(frontier, proc / "decision_frontier.parquet")

    h = hold.set_index("weight")
    b = boot.set_index("weight")
    star, eq = h.loc[w_star], h.loc[0.5]
    res = {
        "n_budget": n_budget,
        "abs_floor_vs_volume": ABS_FLOOR_VS_VOLUME,
        "selected_weight": w_star,
        "selected_on": "2022 state -> 2023 growth (selection period)",
        "holdout_share_vs_volume": round(float(star["share_vs_volume"]), 3),
        "holdout_abs_vs_volume": round(float(star["abs_vs_volume"]), 3),
        "holdout_p_clears_floor": round(float(b.loc[w_star, "p_clears_floor"]), 3),
        "equal_weight_share_vs_volume": round(float(eq["share_vs_volume"]), 3),
        "equal_weight_abs_vs_volume": round(float(eq["abs_vs_volume"]), 3),
        "equal_weight_p_clears_floor": round(float(b.loc[0.5, "p_clears_floor"]), 3),
        "holdout_best_weight": choose_weight(hold),
        # The heaviest opportunity weight that still clears the floor in >= 95%
        # of bootstrap draws: the setting to use if the brand team wants the
        # floor kept with confidence rather than on the point estimate.
        "robust_weight_p95": float(b[b["p_clears_floor"] >= 0.95].index.max()),
    }
    log.info("BLEND: weight %.2f chosen on the selection period; on the holdout it "
             "keeps %.1f%% of volume's absolute growth (P(clears floor) %.0f%%) and "
             "wins %.2fx its share growth. Equal weight: %.1f%%, P %.0f%%.",
             w_star, 100 * res["holdout_abs_vs_volume"],
             100 * res["holdout_p_clears_floor"], res["holdout_share_vs_volume"],
             100 * res["equal_weight_abs_vs_volume"],
             100 * res["equal_weight_p_clears_floor"])
    record("decision_frontier", **res)

    # The pilot runs on the list actually recommended (equal weight), not on the
    # selection-period optimum, which fails the floor out of time.
    pilot = pilot_design(apply_, train, 0.5, n_budget)
    record("pilot_design", **pilot)
    return {"frontier": res, "pilot": pilot}


if __name__ == "__main__":
    run()
