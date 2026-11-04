"""Double machine learning for promotion, with an omitted-variable sensitivity analysis.

    python -m src.ds.causal

THE QUESTION. Is a brand-named rep meal (the public proxy for a visit)
associated with a prescriber's share moving the next year, once everything we
can observe is held fixed -- and how strong would an UNOBSERVED confounder have
to be to explain the association away?

METHOD -- partially linear DML (Chernozhukov et al. 2018)
    Y = theta * D + g(X) + e,      D = m(X) + v
    Y  shrunk brand-share change 2023 -> 2024 (shrinkage.py)
    D  any brand-named food event in 2023 (binary), or log1p(focus-brand $)
    X  practice, market, specialty, region, current brand state, and -- the
       control the earlier DiD lacked -- each prescriber's OWN prior-year share
       change and prior-year promotion
    Nuisances g and m are gradient-boosted and CROSS-FITTED (5 folds), so the
    flexible fit never sees the rows it residualises. theta is the slope of
    residual on residual, with a heteroskedasticity-robust standard error.

SENSITIVITY -- Cinelli & Hazlett (2020)
    Robustness value RV: the share of residual variance an unobserved
    confounder would need to explain in BOTH treatment and outcome to drive the
    estimate to zero (RV_q) or to make it insignificant (RV_q,alpha). Benchmarked
    against the strongest thing we DID observe -- the prior-year trend.

READING. This upgrades "association only" to a quantified statement; it does
not turn it into causation. A meal is a visit proxy, reps choose whom to see on
information no dataset has, and the pilot remains the causal test.
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from src.config import params, path
from src.ds import features as F
from src.ds.shrinkage import prepared
from src.ds.tracking import log_run
from src.utils.io import get_logger, record, write_parquet

log = get_logger(__name__)

K_FOLDS = 5
T_CRIT = 1.959964


def payments(years: list[int]) -> pd.DataFrame:
    f = (path("processed") / "mart_payments.parquet").as_posix()
    con = duckdb.connect()
    try:
        df = con.execute(f"""
            SELECT npi, year, coalesce(pay_focus, 0) AS pay_focus,
                   coalesce(pay_food_count_focus, 0) AS food_focus,
                   coalesce(pay_total, 0) AS pay_total
            FROM read_parquet('{f}') WHERE year IN ({",".join(map(str, years))})""").df()
    finally:
        con.close()
    return df


def with_treatment(apply_: pd.DataFrame) -> pd.DataFrame:
    y1 = params()["years"]["train_end"]
    pay = payments([y1 - 1, y1])
    cur = pay[pay["year"] == y1].drop(columns="year")
    pri = pay[pay["year"] == y1 - 1].drop(columns="year").add_suffix("_prior").rename(
        columns={"npi_prior": "npi"})
    out = apply_.merge(cur, on="npi", how="left").merge(pri, on="npi", how="left")
    for c in ("pay_focus", "food_focus", "pay_total", "pay_focus_prior", "food_focus_prior",
              "pay_total_prior"):
        out[c] = out[c].fillna(0.0)
    out["treated"] = (out["food_focus"] > 0).astype(float)
    out["log_pay_focus"] = np.log1p(out["pay_focus"])
    out["log_pay_prior"] = np.log1p(out["pay_total_prior"])
    out["food_prior"] = (out["food_focus_prior"] > 0).astype(float)
    out["prior_growth_share"] = out["prior_growth_share"].fillna(0.0)
    return out


def crossfit_residuals(X: np.ndarray, y: np.ndarray, d: np.ndarray, binary: bool,
                       seed: int = 0) -> tuple[np.ndarray, np.ndarray]:
    fold = F.folds(len(y), K_FOLDS, seed)
    ry, rd = np.empty_like(y), np.empty_like(d)
    for k in range(K_FOLDS):
        tr, te = fold != k, fold == k
        ry[te] = y[te] - F.gbm(seed=seed).fit(X[tr], y[tr]).predict(X[te])
        if binary:
            p = F.gbm_classifier(seed).fit(X[tr], d[tr]).predict_proba(X[te])[:, 1]
            rd[te] = d[te] - np.clip(p, 0.01, 0.99)
        else:
            rd[te] = d[te] - F.gbm(seed=seed).fit(X[tr], d[tr]).predict(X[te])
    return ry, rd


def plr(ry: np.ndarray, rd: np.ndarray) -> dict[str, float]:
    theta = float((rd * ry).sum() / (rd ** 2).sum())
    psi = (ry - theta * rd) * rd
    se = float(np.sqrt(np.mean(psi ** 2) / np.mean(rd ** 2) ** 2 / len(ry)))
    return {"theta": theta, "se": se, "ci_low": theta - T_CRIT * se, "ci_high": theta + T_CRIT * se,
            "t": theta / se if se > 0 else np.nan}


def robustness_value(t: float, dof: int, q: float = 1.0, alpha_t: float = 0.0) -> float:
    """Cinelli-Hazlett RV_q (alpha_t = 0) or RV_q,alpha (alpha_t = critical t)."""
    f = q * abs(t) / np.sqrt(dof)
    if alpha_t:
        f = f - alpha_t / np.sqrt(dof - 1)
    if f <= 0:
        return 0.0
    return float(0.5 * (np.sqrt(f ** 4 + 4 * f ** 2) - f ** 2))


def partial_r2(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.corrcoef(a, b)[0, 1] ** 2)


def run() -> dict:
    _, apply_, _ = prepared()
    df = with_treatment(apply_)
    y = df["eb_growth_share"].to_numpy(dtype=float)

    base_extra = ["log_pay_prior", "food_prior"]
    full_extra = base_extra + ["prior_growth_share"]
    X_full, _, _ = F.design(df, extra=full_extra)
    X_nopt, _, _ = F.design(df, extra=base_extra)

    results = []
    naive = float(y[df["treated"] == 1].mean() - y[df["treated"] == 0].mean())
    results.append({"spec": "naive difference in means", "treatment": "any brand meal",
                    "theta": naive, "se": np.nan, "ci_low": np.nan, "ci_high": np.nan, "t": np.nan})

    ry_np, rd_np = crossfit_residuals(X_nopt, y, df["treated"].to_numpy(dtype=float), True)
    results.append({"spec": "DML, no pre-trend control", "treatment": "any brand meal",
                    **plr(ry_np, rd_np)})
    ry, rd = crossfit_residuals(X_full, y, df["treated"].to_numpy(dtype=float), True)
    main = plr(ry, rd)
    results.append({"spec": "DML, full controls", "treatment": "any brand meal", **main})
    ry_c, rd_c = crossfit_residuals(X_full, y, df["log_pay_focus"].to_numpy(dtype=float), False)
    results.append({"spec": "DML, full controls", "treatment": "log1p brand $ (dose)",
                    **plr(ry_c, rd_c)})
    table = pd.DataFrame(results)

    dof = len(y) - X_full.shape[1] - 1
    rv = robustness_value(main["t"], dof)
    rv_a = robustness_value(main["t"], dof, alpha_t=T_CRIT)
    # Benchmark: how much of treatment and outcome the prior-year trend explains
    # beyond everything else -- the strongest confounder we can actually see.
    pt = df["prior_growth_share"].to_numpy(dtype=float)
    _, rpt = crossfit_residuals(X_nopt, y, pt, False, seed=2)
    r2_y = partial_r2(ry_np, rpt)
    r2_d = partial_r2(rd_np, rpt)
    bench = max(r2_y, r2_d, 1e-9)

    proc = path("processed")
    write_parquet(table, proc / "ds_causal.parquet")
    res = {
        "outcome": "shrunk brand-share change 2023->2024",
        "treatment": "any brand-named food event in 2023",
        "n": int(len(y)),
        "treated_share": round(float(df["treated"].mean()), 4),
        "estimates": table.round(6).to_dict(orient="records"),
        "theta_points": round(100 * main["theta"], 3),
        "ci_points": [round(100 * main["ci_low"], 3), round(100 * main["ci_high"], 3)],
        "pretrend_control_shift_points": round(100 * (main["theta"] - results[1]["theta"]), 3),
        "robustness_value": round(rv, 4),
        "robustness_value_alpha": round(rv_a, 4),
        "benchmark_r2_outcome_pretrend": round(r2_y, 4),
        "benchmark_r2_treatment_pretrend": round(r2_d, 4),
        "confounder_multiple_of_pretrend": round(rv_a / bench, 2) if rv_a > 0 else 0.0,
        "reading": "association, quantified -- the pilot remains the causal test",
    }
    log.info("DML: brand meal -> shrunk share change %+.2f pts [%+.2f, %+.2f] (naive %+.2f, "
             "without pre-trend control %+.2f).", 100 * main["theta"], 100 * main["ci_low"],
             100 * main["ci_high"], 100 * naive, 100 * results[1]["theta"])
    log.info("SENSITIVITY: RV %.1f%% (to zero), RV_alpha %.1f%% (to insignificance). The "
             "prior-year trend explains %.2f%% of outcome / %.2f%% of treatment residual "
             "variance, so a hidden confounder %.1fx as strong as it would be needed.",
             100 * rv, 100 * rv_a, 100 * r2_y, 100 * r2_d, res["confounder_multiple_of_pretrend"])
    record("ds_causal", **res)
    log_run("ds_causal", params={"method": "PLR DML, 5-fold cross-fit, GBM nuisances",
                                 "treatment": res["treatment"]},
            metrics={k: v for k, v in res.items() if isinstance(v, (int, float))},
            artifacts=[proc / "ds_causal.parquet"])
    return res


if __name__ == "__main__":
    run()
