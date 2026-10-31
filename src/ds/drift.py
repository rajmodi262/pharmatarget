"""Drift monitoring: is next year's market still the one the model learned?

    python -m src.ds.drift

Population Stability Index for every model input and for the model's own
score, between each pair of consecutive years, on in-market prescribers:

    PSI = sum over bins (actual% - expected%) * ln(actual% / expected%)

with deciles fixed on the earlier year. Industry thresholds:
    < 0.10   stable           0.10 - 0.25   moderate shift, watch
    >= 0.25  major shift -- retrain before trusting the ranking

Kolmogorov-Smirnov is reported beside PSI for the numeric inputs (PSI is
binned and robust; KS is exact and, on 260,000 prescribers, flags differences
far too small to matter -- which is why the decision uses PSI).

CONCEPT DRIFT is measured separately, because stable inputs do not mean a
stable relationship: the score's rank correlation with next-year growth and its
top-decile lift, in each out-of-time panel.

The verdict feeds the retraining rule in the model card: any input at >= 0.25,
the score itself at >= 0.10, or the score-outcome rank correlation moving by
more than 0.05 triggers a refit at the next data release.
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

from src.config import params, path
from src.ds.tracking import log_run
from src.models import opportunity as opp
from src.utils.io import get_logger, record, write_parquet

log = get_logger(__name__)

STABLE, MAJOR = 0.10, 0.25
SCORE_RETRAIN = 0.10
NUMERIC = list(opp.NUMERIC_FEATURES) + ["class_fills", "brand_share", "opportunity"]


def psi(expected: np.ndarray, actual: np.ndarray, bins: int = 10) -> float:
    e = expected[np.isfinite(expected)]
    a = actual[np.isfinite(actual)]
    edges = np.unique(np.quantile(e, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    pe = np.histogram(e, edges)[0] / len(e)
    pa = np.histogram(a, edges)[0] / len(a)
    pe, pa = np.clip(pe, 1e-4, None), np.clip(pa, 1e-4, None)
    return float(((pa - pe) * np.log(pa / pe)).sum())


def psi_categorical(expected: pd.Series, actual: pd.Series) -> float:
    pe = expected.value_counts(normalize=True)
    pa = actual.value_counts(normalize=True)
    idx = pe.index.union(pa.index)
    pe, pa = pe.reindex(idx).fillna(1e-4).clip(lower=1e-4), pa.reindex(idx).fillna(1e-4).clip(lower=1e-4)
    return float(((pa - pe) * np.log(pa / pe)).sum())


def load(year: int) -> pd.DataFrame:
    f = (path("processed") / "hcp_scored.parquet").as_posix()
    cols = ["specialty_group", "region", "class_fills", "brand_share", "opportunity", "panel_benes",
            "non_class_clms", "age65_cnt", "risk_score", "pct_panel_65", "zip3_population",
            "zip3_pop_density", "prev_stroke", "prev_chd", "prev_bp"]
    con = duckdb.connect()
    try:
        df = con.execute(f"SELECT {', '.join(cols)} FROM read_parquet('{f}') "
                         f"WHERE year = {year} AND class_fills > 0").df()
    finally:
        con.close()
    return opp.build_features(df)


def concept_drift() -> dict:
    """Does the score still rank OUTCOMES the same way? PSI cannot see this.

    Covariate drift (inputs moving) and concept drift (the input -> outcome
    relationship moving) are different failures. The second is the one that
    broke the tuned blend weight (decision.py), so it is measured directly:
    rank correlation of the opportunity score with next-year growth, and the
    lift of its top decile, in each out-of-time panel.
    """
    from src.ds.data import panels
    train, apply_ = panels()
    out = {}
    for name, d in (("2022->2023", train), ("2023->2024", apply_)):
        top = d["opportunity"] >= d["opportunity"].quantile(0.9)
        out[name] = {
            "spearman_score_growth": round(float(d["opportunity"].corr(d["growth_abs"], method="spearman")), 4),
            "top_decile_lift": round(float(d.loc[top, "growth_abs"].mean() / max(d["growth_abs"].mean(), 1e-9)), 3),
        }
    a, b = out["2022->2023"], out["2023->2024"]
    out["spearman_change"] = round(b["spearman_score_growth"] - a["spearman_score_growth"], 4)
    out["lift_change"] = round(b["top_decile_lift"] - a["top_decile_lift"], 3)
    return out


def status(v: float) -> str:
    return "stable" if v < STABLE else "moderate" if v < MAJOR else "major"


def run() -> dict:
    years = sorted(params()["years"]["all"])
    frames = {y: load(y) for y in years}
    rows = []
    for a, b in zip(years[:-1], years[1:], strict=True):
        fa, fb = frames[a], frames[b]
        for col in NUMERIC:
            if col not in fa or col not in fb:
                continue
            x, y = fa[col].to_numpy(dtype=float), fb[col].to_numpy(dtype=float)
            p = psi(x, y)
            ks = ks_2samp(x[np.isfinite(x)], y[np.isfinite(y)]).statistic
            rows.append({"from_year": a, "to_year": b, "feature": col, "kind": "numeric",
                         "psi": p, "ks": float(ks), "status": status(p),
                         "is_score": col == "opportunity"})
        for col in opp.CATEGORICAL_FEATURES:
            p = psi_categorical(fa[col], fb[col])
            rows.append({"from_year": a, "to_year": b, "feature": col, "kind": "categorical",
                         "psi": p, "ks": np.nan, "status": status(p), "is_score": False})
    df = pd.DataFrame(rows)
    proc = path("processed")
    write_parquet(df, proc / "ds_drift.parquet")

    last = df[df["to_year"] == years[-1]]
    score_psi = float(last.loc[last["is_score"], "psi"].iloc[0])
    inputs = last[~last["is_score"]]
    worst = inputs.loc[inputs["psi"].idxmax()]
    concept = concept_drift()
    # Concept drift trigger: the score's rank correlation with outcomes moves by
    # more than 0.05 between panels.
    concept_flag = abs(concept["spearman_change"]) > 0.05
    retrain = bool((inputs["psi"] >= MAJOR).any() or score_psi >= SCORE_RETRAIN or concept_flag)
    res = {
        "thresholds": {"stable": STABLE, "major": MAJOR, "score_retrain": SCORE_RETRAIN},
        "latest_pair": [int(years[-2]), int(years[-1])],
        "score_psi": round(score_psi, 4),
        "worst_input": str(worst["feature"]), "worst_input_psi": round(float(worst["psi"]), 4),
        "n_moderate": int((inputs["status"] == "moderate").sum()),
        "n_major": int((inputs["status"] == "major").sum()),
        "concept_drift": concept,
        "concept_drift_flag": concept_flag,
        "retrain_triggered": retrain,
    }
    log.info("DRIFT %d->%d: score PSI %.3f (%s); worst input %s PSI %.3f; %d moderate, %d "
             "major. Retrain triggered: %s.", years[-2], years[-1], score_psi, status(score_psi),
             res["worst_input"], res["worst_input_psi"], res["n_moderate"], res["n_major"], retrain)
    log.info("CONCEPT DRIFT: score-growth rank corr %s -> %s (change %+.3f); top-decile lift "
             "%s -> %s.", concept["2022->2023"]["spearman_score_growth"],
             concept["2023->2024"]["spearman_score_growth"], concept["spearman_change"],
             concept["2022->2023"]["top_decile_lift"], concept["2023->2024"]["top_decile_lift"])
    record("ds_drift", **res)
    log_run("ds_drift", params={"bins": 10, "thresholds": res["thresholds"]},
            metrics={f"{r.feature}.psi_{r.from_year}_{r.to_year}": r.psi for r in df.itertuples()},
            artifacts=[proc / "ds_drift.parquet"])
    return res


if __name__ == "__main__":
    run()
