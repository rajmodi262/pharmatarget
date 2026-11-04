"""How much of next year's value is predictable at all? The noise ceiling.

    python -m src.ds.ceiling

THE CRITICISM THIS ANSWERS. The best rule captures ~17% of next year's
value at the budget, so "85% is unexplained". That number has no meaning
until it is set against what ANY model could achieve. Two ceilings:

    HINDSIGHT   rank by the realised outcome itself. The most any list of k
                prescribers could have captured. Unattainable: it knows the
                future, noise included.

    NOISE       a parametric bootstrap of next year's counts. Suppose a model
                knew every prescriber's EXPECTED next-year prescribing exactly.
                Next year's fills are still a draw -- class fills Poisson around
                that expectation, brand fills binomial within them -- so the
                realised value moves even when the expectation is known. Rank
                by the expectation (the observed value, as plug-in), score
                against B fresh draws, average. That is the capture a perfect
                model of expected behaviour would get: the noise ceiling.

The noise ceiling is still optimistic (the plug-in expectation contains this
year's noise, which only flatters it), so "share of the ceiling" is, if
anything, understated.

READING. Rule capture / noise ceiling = the share of the PREDICTABLE value a
rule finds. Below that, the remaining gap is behaviour no administrative
dataset records (a new partner in the practice, a formulary change).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import path
from src.ds.data import n_budget
from src.ds.evaluation import metrics_at_k
from src.ds.shrinkage import prepared, shrink
from src.ds.tracking import log_run
from src.utils.io import get_logger, read_parquet, record, write_parquet

log = get_logger(__name__)

B = 30


def value(frame: pd.DataFrame, priors: pd.DataFrame, brand_next: np.ndarray,
          class_next: np.ndarray) -> np.ndarray:
    """The value-aligned target, recomputed for a given draw of next-year counts."""
    nxt = pd.DataFrame({"specialty_group": frame["specialty_group"].to_numpy(),
                        "b": brand_next, "n": class_next})
    eb_next = shrink(nxt, priors, "b", "n")
    return (eb_next - frame["eb_share"].to_numpy(dtype=float)) * \
        frame["class_fills"].clip(lower=0).to_numpy(dtype=float)


def capture(score: np.ndarray, realised: np.ndarray, k: int) -> float:
    top = np.argsort(-score, kind="stable")[:k]
    pos = np.clip(realised, 0, None)
    return float(pos[top].sum() / pos.sum())


def noise_ceiling(frame: pd.DataFrame, priors: pd.DataFrame, k: int, b: int = B,
                  seed: int = 0) -> tuple[float, list[float]]:
    rng = np.random.default_rng(seed)
    n_obs = frame["class_obs_next"].to_numpy(dtype=float).clip(min=0)
    b_obs = frame["brand_fills_next"].to_numpy(dtype=float).clip(min=0)
    p_next = np.divide(b_obs, n_obs, out=np.zeros_like(n_obs), where=n_obs > 0).clip(0, 1)
    expected = value(frame, priors, b_obs, n_obs)
    draws = []
    for _ in range(b):
        n_star = rng.poisson(n_obs).astype(float)
        b_star = rng.binomial(n_star.astype(np.int64), p_next).astype(float)
        draws.append(capture(expected, value(frame, priors, b_star, n_star), k))
    return float(np.mean(draws)), draws


def run() -> dict:
    _, apply_, priors = prepared()
    apply_["eb_share_fills"] = apply_["eb_growth_share"] * apply_["class_fills"].clip(lower=0)
    k = n_budget()
    gv = apply_["eb_share_fills"].to_numpy(dtype=float)

    hindsight = metrics_at_k(gv, apply_, k)["value_capture"]
    ceiling, draws = noise_ceiling(apply_, priors, k)

    ladder = read_parquet(path("processed") / "ds_ladder.parquet")
    rows = [{"rule": "hindsight (knows the future)", "value_capture": hindsight, "kind": "ceiling"},
            {"rule": "noise ceiling (knows expected behaviour)", "value_capture": ceiling,
             "kind": "ceiling"}]
    for r in ladder.itertuples():
        rows.append({"rule": r.rule, "value_capture": float(r.value_capture), "kind": "rule"})
    table = pd.DataFrame(rows)
    table["share_of_noise_ceiling"] = table["value_capture"] / ceiling
    table["share_of_hindsight"] = table["value_capture"] / hindsight

    winner = ladder.loc[ladder["passes_guardrail"]].iloc[0]
    best = ladder.iloc[0]
    proc = path("processed")
    write_parquet(table, proc / "ds_ceiling.parquet")
    res = {
        "k": k,
        "n_prescribers": int(len(apply_)),
        "bootstrap_draws": B,
        "hindsight_capture": round(hindsight, 4),
        "noise_ceiling": round(ceiling, 4),
        "noise_ceiling_range": [round(float(np.min(draws)), 4), round(float(np.max(draws)), 4)],
        "best_rule": str(best["rule"]),
        # Shares are of HINDSIGHT, the most any list could capture. The noise
        # ceiling sits at ~98% of it, so the two readings barely differ; one
        # basis everywhere keeps the page, the report and the README agreeing.
        "best_rule_share_of_max": round(float(best["value_capture"]) / hindsight, 4),
        "winner_under_guardrail": str(winner["rule"]),
        "winner_share_of_max": round(float(winner["value_capture"]) / hindsight, 4),
        "random_share_of_max": round(float(
            ladder.loc[ladder["rule"] == "random", "value_capture"].iloc[0]) / hindsight, 4),
        "noise_share_of_hindsight": round(ceiling / hindsight, 4),
        # If knowing expected behaviour gets almost all of hindsight, count noise
        # is not what limits capture -- unrecorded behaviour change is.
        "reading": ("count noise is negligible at this budget: the gap between the rules and "
                    "hindsight is behaviour change no administrative dataset records"
                    if ceiling / hindsight > 0.95 else
                    "a material share of the gap to hindsight is count noise no model can remove"),
    }
    log.info("CEILING: hindsight %.1f%%, noise ceiling %.1f%% (B=%d). Best rule %s finds "
             "%.0f%% of the achievable maximum; the guardrail winner %s finds %.0f%%; random %.0f%%.",
             100 * hindsight, 100 * ceiling, B, res["best_rule"],
             100 * res["best_rule_share_of_max"], res["winner_under_guardrail"],
             100 * res["winner_share_of_max"], 100 * res["random_share_of_max"])
    record("ds_ceiling", **res)
    log_run("ds_ceiling", params={"method": "parametric bootstrap, Poisson x binomial", "B": B},
            metrics={k_: v for k_, v in res.items() if isinstance(v, (int, float))},
            artifacts=[proc / "ds_ceiling.parquet"])
    return res


if __name__ == "__main__":
    run()
