"""Ablations: what is each modelling choice actually worth?

    python -m src.ds.ablation

Every variant refits the potential frontier on the 2023 in-market prescribers
exactly as production does, scores them, and is judged on the same held-out
2023 -> 2024 outcomes at the same 60-rep k. Three readings per variant:

    rank agreement     Spearman of its opportunity score with production's
    value capture      of its opportunity list and of the 50/50 hybrid built on it
                       (the primary metric, evaluation.py)
    abs vs volume      the brand team's guardrail for the hybrid

Variants (one change each, everything else production):
    no practice/patient features   no market features   no specialty   no region
    median, not frontier (tau 0.5) no peer benchmark (national achievable share)

WHAT IT FOUND: the practice and patient-mix features carry the model (drop them
and value capture falls by a third). Two SIMPLER variants -- a median rather
than a 0.80 frontier, and a national rather than peer achievable share -- score
slightly higher on the holdout. They are not adopted: choosing on the test year
is fitting to the exam. They are pre-declared for the next refresh.

Not ablated, and why: the suppression imputation changes the marts themselves
and needs a full re-ingest (~1 hour of DuckDB on 39 GB); its effect is
reported separately in the manifest (imputation_ev) instead.
"""
from __future__ import annotations

from contextlib import contextmanager

import duckdb
import numpy as np
import pandas as pd

from src.config import params, path
from src.ds.data import n_budget
from src.ds.shrinkage import prepared
from src.ds.tracking import log_run
from src.models import opportunity as opp
from src.utils.io import get_logger, record, write_parquet

log = get_logger(__name__)

PRACTICE = ["log_panel_benes", "log_non_class_clms", "risk_score", "log_age65_cnt", "pct_panel_65"]
MARKET = ["log_zip3_population", "log_pop_density", "prev_stroke", "prev_chd", "prev_bp"]


@contextmanager
def numeric_features(keep: list[str]):
    saved = list(opp.NUMERIC_FEATURES)
    opp.NUMERIC_FEATURES[:] = [f for f in saved if f in keep]
    try:
        yield
    finally:
        opp.NUMERIC_FEATURES[:] = saved


def load_mart(year: int) -> pd.DataFrame:
    f = (path("processed") / "mart_hcp_metrics.parquet").as_posix()
    con = duckdb.connect()
    try:
        return con.execute(f"SELECT * FROM read_parquet('{f}') WHERE year = {year} "
                           f"AND class_fills > 0").df()
    finally:
        con.close()


def variant(train: pd.DataFrame, bench: pd.DataFrame, keep: list[str], tau: float,
            flatten: tuple[str, ...] = (), national: bool = False) -> pd.Series:
    t = train.copy()
    for col in flatten:
        t[col] = "All"
    b = bench.copy()
    if national:
        b["achievable_share"] = float(b["achievable_share"].median())
    if flatten:
        # Benchmarks are joined on specialty and region; flattened columns need a
        # single row per remaining key.
        keys = [c for c in ("specialty_group", "region") if c not in flatten] + ["year"]
        b = b.groupby(keys, as_index=False)["achievable_share"].median()
        for col in flatten:
            b[col] = "All"
    with numeric_features(keep):
        model, enc, _ = opp.fit_potential(t, tau=tau)
        scored = opp.score_opportunity(t, b, model, enc)
    return scored.set_index("npi")["opportunity"]


def capture(score: pd.Series, frame: pd.DataFrame, k: int) -> dict[str, float]:
    s = score.reindex(frame["npi"]).fillna(0).to_numpy()
    vol = frame["class_fills"].to_numpy(dtype=float)
    gv = frame["eb_share_fills"].clip(lower=0).to_numpy()
    ga = frame["growth_abs"].clip(lower=0).to_numpy()
    hyb = (pd.Series(s).rank(pct=True) + pd.Series(vol).rank(pct=True)).to_numpy() / 2
    top, toph = np.argsort(-s)[:k], np.argsort(-hyb)[:k]
    vol_abs = ga[np.argsort(-vol)[:k]].sum()
    return {"value_capture": float(gv[top].sum() / gv.sum()),
            "hybrid_value_capture": float(gv[toph].sum() / gv.sum()),
            "hybrid_abs_vs_volume": float(ga[toph].sum() / vol_abs)}


def run() -> dict:
    year = params()["years"]["train_end"]
    tau = params()["opportunity_model"]["tau"]
    train = load_mart(year)
    bench = pd.read_parquet(path("processed") / "mart_peer_benchmarks.parquet")
    _, apply_, _ = prepared()
    apply_["eb_share_fills"] = apply_["eb_growth_share"] * apply_["class_fills"].clip(lower=0)
    frame = apply_[["npi", "class_fills", "eb_share_fills", "growth_abs"]].copy()
    del apply_
    k = n_budget()
    every = PRACTICE + MARKET

    specs = [
        ("production", every, tau, (), False),
        ("no practice / patient-mix features", MARKET, tau, (), False),
        ("no local-market features", PRACTICE, tau, (), False),
        ("no specialty", every, tau, ("specialty_group",), False),
        ("no region", every, tau, ("region",), False),
        ("median, not frontier (tau 0.50)", every, 0.50, (), False),
        ("no peer benchmark (national share)", every, tau, (), True),
    ]
    scores: dict[str, pd.Series] = {}
    for name, keep, t, flat, nat in specs:
        scores[name] = variant(train, bench, keep, t, flat, nat)
        log.info("  ablation fitted: %s", name)
    base = scores["production"]
    rows = []
    for name, s in scores.items():
        common = base.index.intersection(s.index)
        rows.append({"variant": name,
                     "spearman_vs_production": float(base[common].corr(s[common], method="spearman")),
                     **capture(s, frame, k)})
    df = pd.DataFrame(rows)
    p = df.iloc[0]
    df["value_capture_change"] = df["value_capture"] - p["value_capture"]
    df["hybrid_value_capture_change"] = df["hybrid_value_capture"] - p["hybrid_value_capture"]

    proc = path("processed")
    write_parquet(df, proc / "ds_ablation.parquet")
    biggest = df.iloc[1:].loc[df.iloc[1:]["value_capture_change"].idxmin()]
    t = df.set_index("variant")
    res = {"k": k, "table": df.round(4).to_dict(orient="records"),
           # Two simpler variants score HIGHER on the holdout. Adopting either now
           # would be choosing on the test set; they are pre-declared for the next
           # refresh instead.
           "beats_production_on_holdout": df.loc[df["value_capture_change"] > 0.002, "variant"].tolist(),
           "median_regression_value_gain_points": round(
               100 * float(t.loc["median, not frontier (tau 0.50)", "value_capture_change"]), 2),
           "prospective_test": "tau 0.50 and national achievable share, scored on the 2025 refresh",
           "most_valuable_component": str(biggest["variant"]),
           "most_valuable_component_loss_points": round(100 * float(biggest["value_capture_change"]), 2),
           "not_ablated": "suppression imputation (requires full re-ingest)"}
    for r in df.itertuples(index=False):
        log.info("  %-38s rho %.3f  value %5.1f%% (%+.1f)  hybrid value %5.1f%%  hybrid abs/vol %.3f",
                 r.variant, r.spearman_vs_production, 100 * r.value_capture,
                 100 * r.value_capture_change, 100 * r.hybrid_value_capture, r.hybrid_abs_vs_volume)
    record("ds_ablation", **res)
    log_run("ds_ablation", params={"k": k, "variants": len(df)},
            metrics={f"{r['variant']}.value_capture": r["value_capture"] for r in res["table"]},
            artifacts=[proc / "ds_ablation.parquet"])
    return res


if __name__ == "__main__":
    run()
