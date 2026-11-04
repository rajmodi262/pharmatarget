"""The business case under uncertainty: what is each headcount decision worth,
and what is the pilot worth?

    python -m src.models.value

THE PROBLEM THIS SOLVES
-----------------------
Every dollar figure for headcount rests on one number public data cannot
supply: how much a year of calls moves a prescriber (the response ceiling). The
honest answer so far was "hold, and measure it". A CFO's next question is
"what is measuring it worth, and what does it cost me to wait?" -- a decision
analysis question with a closed answer once the uncertainty is written down.

THE MODEL
---------
Contribution is exactly linear in the response ceiling c (sizing.hill is
c * f / (k + f)), so for a force of n reps

    annual profit(n, c) = c * K(n) - n * rep_cost

where K(n) is the contribution a ceiling of 1.0 would produce -- computed once
per n from the real call plan. Over the horizon H a size change also pays

    hiring     rep_hire_cost per rep, plus new reps at half productivity for
               rep_ramp_months
    releasing  rep_separation_cost per rep

which is what makes a headcount decision costly to reverse, and therefore what
gives a measurement its value.

    Belief about c   log-normal, median = m x the break-even response, log-sd s.
                     Stated, swept across m, and settable in the browser.
    Strategies       cut, hold, grow (one recruiting cycle at most), or hold and
                     pilot for six months, then choose the size the posterior
                     mean supports.
    Pilot            20% hold-out scored on share points. Its error comes from the
                     power analysis (decision.py): se(c) = c_req x se(effect)/effect.
                     Its cost: held-out prescribers' calls go to the next names on
                     the list, so the pilot loses the opportunity GAP between them,
                     not the calls.
    Horizon          two years -- the window before generic entry.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import econ, economics, path
from src.models.sizing import _Ranked, evaluate_force
from src.utils.io import get_logger, manifest, read_parquet, record, write_parquet

log = get_logger(__name__)

HORIZON_YEARS = 2.0
PILOT_MONTHS = 6
HOLDOUT = 0.2
PRIOR_LOG_SD = 1.0
SCENARIOS = (0.25, 0.5, 1.0, 2.0, 4.0)       # response, x break-even
BELIEFS = (0.25, 0.4, 0.6, 0.8, 1.0, 1.25, 1.6, 2.0, 2.5, 3.0, 4.0)
N_DRAWS = 20_000


def contribution_grid(planned: pd.DataFrame, reps: list[int]) -> pd.DataFrame:
    """K(n): annual contribution per unit of response ceiling, for each force size."""
    ranked = _Ranked(planned)
    k = econ("call_response_half_saturation")
    rows = []
    for n in reps:
        r = evaluate_force(ranked, n, {"call_response_ceiling": 1.0,
                                       "call_response_half_saturation": k})
        rows.append({"n_reps": n, "contribution_per_ceiling": r["contribution"],
                     "field_cost": r["field_cost"]})
    return pd.DataFrame(rows)


def holdout_cost_fraction(planned: pd.DataFrame, n_list: int, holdout: float = HOLDOUT) -> float:
    """Share of the list's annual contribution a hold-out forgoes.

    Held-out prescribers' calls are re-spent on the next names below the cut,
    so the loss is the opportunity gap between a random held-out prescriber and
    a replacement, not the calls themselves.
    """
    opp = np.sort(planned["opportunity"].to_numpy(dtype=float))[::-1]
    n_hold = int(round(holdout * n_list))
    on_list = opp[:n_list].mean()
    replacement = opp[n_list:n_list + n_hold].mean()
    return float(holdout * max(1 - replacement / on_list, 0.0)) if on_list > 0 else holdout


class Economics:
    """Horizon value of each force size, relative to holding, for any response."""

    def __init__(self, grid: pd.DataFrame, current: int, hire: float, ramp_months: float,
                 separation: float):
        self.reps = grid["n_reps"].to_numpy()
        self.K = grid["contribution_per_ceiling"].to_numpy(dtype=float)
        self.cost = grid["field_cost"].to_numpy(dtype=float)
        self.i0 = int(np.argmin(np.abs(self.reps - current)))
        d = self.reps - self.reps[self.i0]
        self.switch = np.where(d > 0, d * hire, -d * separation).astype(float)
        # New reps at half productivity during ramp: a share of the extra K.
        self.ramp_K = np.where(d > 0, 0.5 * ramp_months / 12 * (self.K - self.K[self.i0]), 0.0)

    def value(self, c: np.ndarray, horizon: float) -> np.ndarray:
        """Rows = force sizes, columns = response draws: horizon value vs holding."""
        c = np.atleast_1d(c)[None, :]
        annual = (self.K - self.K[self.i0])[:, None] * c - (self.cost - self.cost[self.i0])[:, None]
        return horizon * annual - self.switch[:, None] - self.ramp_K[:, None] * c

    def best_for(self, c_mean: np.ndarray, horizon: float) -> np.ndarray:
        """Index of the size a decision-maker picks, given an expected response."""
        return np.argmax(self.value(c_mean, horizon), axis=0)


def posterior_mean_fn(median: float, log_sd: float, se: float):
    """E[c | c_hat] for a log-normal prior and a normal measurement, on a grid."""
    c = np.exp(np.linspace(np.log(median) - 5 * log_sd, np.log(median) + 5 * log_sd, 600))
    prior = np.exp(-0.5 * ((np.log(c) - np.log(median)) / log_sd) ** 2) / c
    obs = np.linspace(-4 * se, c.max() + 4 * se, 900)
    like = np.exp(-0.5 * ((obs[:, None] - c[None, :]) / se) ** 2)
    w = like * prior[None, :]
    pm = (w * c[None, :]).sum(axis=1) / np.maximum(w.sum(axis=1), 1e-300)
    return lambda x: np.interp(x, obs, pm)


def strategies(eco: Economics, c_req: float, se_c: float, list_K: float, cost_frac: float,
               median_x: float, log_sd: float = PRIOR_LOG_SD,
               horizon: float = HORIZON_YEARS, seed: int = 0) -> dict:
    """Expected horizon value (vs holding) of each strategy under one belief."""
    rng = np.random.default_rng(seed)
    median = median_x * c_req
    c = median * np.exp(rng.normal(0, log_sd, N_DRAWS))
    V = eco.value(c, horizon)                                # sizes x draws
    j = np.arange(N_DRAWS)

    # Act now: risk-neutral, so the expected response picks the size.
    i_now = int(eco.best_for(np.array([c.mean()]), horizon)[0])

    # Pilot: six months at today's size, then the size the posterior supports.
    t_p = PILOT_MONTHS / 12
    pilot_cost = cost_frac * t_p * c * list_K
    c_hat = c + rng.normal(0, se_c, N_DRAWS)
    post = posterior_mean_fn(median, log_sd, se_c)(c_hat)
    after = eco.value(c, horizon - t_p)
    choice = eco.best_for(post, horizon - t_p)
    pilot = after[choice, j] - pilot_cost

    out = {
        "median_x": median_x,
        "hold": 0.0,
        "cut": float(V[0].mean()),
        "grow": float(V[-1].mean()),
        "act_now": float(V[i_now].mean()),
        "act_now_n": int(eco.reps[i_now]),
        "pilot_then_decide": float(pilot.mean()),
        "pilot_cost": float(pilot_cost.mean()),
        "evpi": float((V.max(axis=0) - V[i_now]).mean()),
        "p_pilot_says_grow": float((eco.reps[choice] > eco.reps[eco.i0]).mean()),
        "p_pilot_says_cut": float((eco.reps[choice] < eco.reps[eco.i0]).mean()),
    }
    out["evsi"] = out["pilot_then_decide"] + out["pilot_cost"] - out["act_now"]
    out["best"] = max(("hold", "cut", "grow", "pilot_then_decide"), key=lambda k_: out[k_])
    return out


def payoff_matrix(eco: Economics, c_req: float, decisions: dict[str, int],
                  horizon: float = HORIZON_YEARS, pilot: list[dict] | None = None) -> pd.DataFrame:
    """Horizon value vs holding for each decision under each response scenario."""
    rows = []
    for x in SCENARIOS:
        V = eco.value(np.array([x * c_req]), horizon)[:, 0]
        for name, n in decisions.items():
            i = int(np.argmin(np.abs(eco.reps - n)))
            rows.append({"decision": name, "n_reps": int(eco.reps[i]), "response_x": x,
                         "value_vs_hold": float(V[i])})
    df = pd.DataFrame(rows)
    if pilot is not None:
        df = pd.concat([df, pd.DataFrame(pilot)], ignore_index=True)
    df["regret"] = df.groupby("response_x")["value_vs_hold"].transform("max") - df["value_vs_hold"]
    return df


def pilot_under_scenarios(eco: Economics, c_req: float, se_c: float, list_K: float,
                          cost_frac: float, horizon: float = HORIZON_YEARS,
                          log_sd: float = PRIOR_LOG_SD, seed: int = 1) -> list[dict]:
    """Expected value of pilot-then-decide if the TRUE response is each scenario.

    The decision after the pilot uses a neutral belief (median at break-even);
    the measurement noise is the pilot's real standard error.
    """
    rng = np.random.default_rng(seed)
    post_fn = posterior_mean_fn(c_req, log_sd, se_c)
    t_p = PILOT_MONTHS / 12
    rows = []
    for x in SCENARIOS:
        c = x * c_req
        c_hat = c + rng.normal(0, se_c, N_DRAWS)
        choice = eco.best_for(post_fn(c_hat), horizon - t_p)
        after = eco.value(np.array([c]), horizon - t_p)[:, 0]
        v = after[choice] - cost_frac * t_p * c * list_K
        rows.append({"decision": "pilot", "n_reps": int(eco.reps[eco.i0]), "response_x": x,
                     "value_vs_hold": float(v.mean())})
    return rows


def grow_threshold(eco: Economics, c_req: float, horizon: float = HORIZON_YEARS) -> float | None:
    """Response (x break-even) above which adding a full recruiting cycle pays."""
    for x in np.arange(1.0, 8.0, 0.01):
        if eco.value(np.array([x * c_req]), horizon)[-1, 0] > 0:
            return round(float(x), 2)
    return None


def run() -> dict:
    m = manifest()
    current = economics()["sizing"]["current_n_reps"]
    cap = economics()["sizing"].get("max_plausible_expansion", 1.5)
    c_req = float((m.get("headline_h3") or {}).get("required_ceiling_at_current") or 0)
    pilot = m.get("pilot_design") or {}
    sh = pilot.get("share") or {}
    if not c_req or not sh:
        log.warning("value: needs headline_h3 and pilot_design -- run sizing and decision first")
        return {}

    planned = read_parquet(path("processed") / "hcp_call_plan.parquet",
                           columns=["desired_calls", "opportunity"])
    reps = list(range(int(round(current * 2 / 3)), int(round(current * cap)) + 1, 2))
    grid = contribution_grid(planned, reps)
    n_list = int(pilot.get("n_list") or 0)
    cost_frac = holdout_cost_fraction(planned, n_list)
    del planned
    write_parquet(grid, path("processed") / "decision_value_grid.parquet")

    eco = Economics(grid, current, econ("rep_hire_cost"), econ("rep_ramp_months"),
                    econ("rep_separation_cost"))
    list_K = float(eco.K[eco.i0])

    # Pilot measurement error in units of the response ceiling.
    t = PILOT_MONTHS / 12
    se_eff = (sh["sd_per_year"] * np.sqrt(t) * np.sqrt(max(1 - sh["prior_rho"] ** 2, 0))
              * np.sqrt(1 / (n_list * (1 - HOLDOUT)) + 1 / (n_list * HOLDOUT)))
    se_c = c_req * se_eff / (sh["effect_per_year"] * t)

    pay = payoff_matrix(eco, c_req, {"cut": reps[0], "hold": current, "grow": reps[-1]},
                        pilot=pilot_under_scenarios(eco, c_req, se_c, list_K, cost_frac))
    worst = pay.groupby("decision")["regret"].max()
    beliefs = [strategies(eco, c_req, se_c, list_K, cost_frac, x) for x in BELIEFS]
    base = next(b for b in beliefs if b["median_x"] == 1.0)
    band = [b["median_x"] for b in beliefs if b["best"] == "pilot_then_decide"]
    grow_x = grow_threshold(eco, c_req)

    rv = m.get("retargeting_value") or {}
    per_c = float(rv.get("hybrid_vs_volume_contribution") or 0) / max(
        float(rv.get("priced_ceiling") or c_req), 1e-9)

    res = {
        "horizon_years": HORIZON_YEARS,
        "pilot_months": PILOT_MONTHS,
        "holdout": HOLDOUT,
        "holdout_cost_fraction": round(cost_frac, 4),
        "prior_log_sd": PRIOR_LOG_SD,
        "break_even_ceiling": c_req,
        "pilot_se_ceiling": round(float(se_c), 6),
        "pilot_se_x_break_even": round(float(se_c / c_req), 3),
        "rep_range": [reps[0], reps[-1]],
        "current_n_reps": current,
        "rep_cost_annual": econ("rep_cost_annual"),
        "rep_hire_cost": econ("rep_hire_cost"),
        "rep_ramp_months": econ("rep_ramp_months"),
        "rep_separation_cost": econ("rep_separation_cost"),
        "payoff": pay.round({"value_vs_hold": 0, "regret": 0}).to_dict(orient="records"),
        "max_regret": {k: round(float(v), 0) for k, v in worst.items()},
        "minimax_regret_decision": str(worst.idxmin()),
        "by_belief": [{k: (round(v, 3) if isinstance(v, float) else v) for k, v in b.items()}
                      for b in beliefs],
        "pilot_best_band_x": [min(band), max(band)] if band else None,
        "grow_pays_above_x": grow_x,
        "base_evpi": round(base["evpi"], 0),
        "base_evsi": round(base["evsi"], 0),
        "base_pilot_cost": round(base["pilot_cost"], 0),
        "base_pilot_value": round(base["pilot_then_decide"], 0),
        "base_net_value_of_pilot": round(base["evsi"] - base["pilot_cost"], 0),
        "retargeting_per_year_by_response": {
            str(x): round(per_c * x * c_req, 0) for x in SCENARIOS},
        "retargeting_incremental_cost": 0,
    }
    log.info("BUSINESS CASE (%.0f-yr horizon; belief median = break-even, log-sd %.1f):",
             HORIZON_YEARS, PRIOR_LOG_SD)
    log.info("  hold-out forgoes %.1f%% of the list's contribution while it runs", 100 * cost_frac)
    log.info("  value of perfect information $%.1fM; pilot EVSI $%.1fM; pilot cost $%.2fM",
             base["evpi"] / 1e6, base["evsi"] / 1e6, base["pilot_cost"] / 1e6)
    log.info("  strategy values vs hold: cut $%.1fM, grow $%.1fM, pilot-then-decide $%.1fM",
             base["cut"] / 1e6, base["grow"] / 1e6, base["pilot_then_decide"] / 1e6)
    log.info("  pilot is the best strategy for beliefs %s x break-even; a full recruiting "
             "cycle pays only above %sx", band, grow_x)
    record("business_case_value", **res)
    return res


if __name__ == "__main__":
    run()
