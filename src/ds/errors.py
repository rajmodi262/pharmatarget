"""Error analysis and fairness: where is the model wrong, and who does the list skip?

    python -m src.ds.errors

Two questions a model review always asks and an aggregate metric never answers.

1. ERRORS BY SEGMENT. A Poisson gradient-boosted forecast of next-year branded
   fills (fitted 2022 -> 2023, scored 2023 -> 2024), broken down by specialty,
   size, region and rural/urban: mean absolute error, bias (over- or under-
   forecast), and relative bias. A model that is right on average and 30% low
   on cardiologists is a model that will misallocate cardiologists.

2. REPRESENTATION. For the recommended 60-rep list (the hybrid rule): each
   segment's share of the LIST against its share of the realised VALUE (share-
   driven fills, evaluation.py). A ratio of 1.0 means the segment is called in
   proportion to where growth actually happened. Rural prescribers are the
   segment to watch: every density-weighted plan tends to under-serve them,
   and patients there have the fewest alternatives.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import path
from src.ds import features as F
from src.ds.data import n_budget
from src.ds.shrinkage import prepared
from src.ds.tracking import log_run
from src.models.opportunity import hybrid_score
from src.utils.io import get_logger, record, write_parquet

log = get_logger(__name__)

SEGMENTS = ("specialty_group", "size_band", "region", "rural")


def segment_errors(frame: pd.DataFrame, pred: np.ndarray) -> pd.DataFrame:
    d = frame[list(SEGMENTS)].copy()
    d["rural"] = np.where(d["rural"], "rural", "urban")
    d["pred"] = pred
    d["actual"] = frame["brand_fills_next"].to_numpy(dtype=float)
    rows = []
    for seg in ("all",) + SEGMENTS:
        groups = [("all", d)] if seg == "all" else list(d.groupby(seg))
        for lvl, g in groups:
            if len(g) < 200:
                continue
            err = g["pred"] - g["actual"]
            rows.append({"segment": seg, "level": str(lvl), "n": len(g),
                         "mae": float(err.abs().mean()),
                         "bias": float(err.mean()),
                         "relative_bias": float(err.sum() / max(g["actual"].sum(), 1e-9)),
                         "mean_actual": float(g["actual"].mean())})
    return pd.DataFrame(rows)


def representation(frame: pd.DataFrame, on_list: np.ndarray) -> pd.DataFrame:
    d = frame[list(SEGMENTS)].copy()
    d["rural"] = np.where(d["rural"], "rural", "urban")
    v = frame["eb_share_fills"].clip(lower=0).to_numpy(dtype=float)
    rows = []
    for seg in SEGMENTS:
        for lvl, idx in d.groupby(seg).groups.items():
            m = d.index.isin(idx)
            share_list = float(on_list[m].sum() / on_list.sum())
            share_value = float(v[m].sum() / v.sum())
            share_prescribers = float(m.mean())
            captured = float(v[m & on_list].sum() / max(v[m].sum(), 1e-9))
            rows.append({"segment": seg, "level": str(lvl),
                         "share_of_prescribers": share_prescribers,
                         "share_of_list": share_list, "share_of_value": share_value,
                         "representation_ratio": share_list / share_value if share_value > 0 else np.nan,
                         "value_captured_in_segment": captured})
    return pd.DataFrame(rows)


def run() -> dict:
    train, apply_, _ = prepared()
    for frame in (train, apply_):
        frame["eb_share_fills"] = frame["eb_growth_share"] * frame["class_fills"].clip(lower=0)
    Xtr, enc, _ = F.design(train)
    Xap, _, _ = F.design(apply_, enc)
    model = F.gbm("poisson").fit(Xtr, train["brand_fills_next"].to_numpy(dtype=float).clip(0))
    pred = model.predict(Xap)
    errs = segment_errors(apply_, pred)

    k = n_budget()
    score = hybrid_score(apply_).to_numpy(dtype=float)
    on_list = np.zeros(len(apply_), dtype=bool)
    on_list[np.argsort(-score)[:k]] = True
    rep = representation(apply_.reset_index(drop=True), on_list)

    proc = path("processed")
    write_parquet(errs, proc / "ds_error_segments.parquet")
    write_parquet(rep, proc / "ds_representation.parquet")

    seg = errs[errs["segment"] != "all"]
    worst = seg.loc[seg["relative_bias"].abs().idxmax()]
    rural = rep[(rep["segment"] == "rural") & (rep["level"] == "rural")].iloc[0]
    res = {
        "overall_mae": round(float(errs.iloc[0]["mae"]), 2),
        "overall_relative_bias": round(float(errs.iloc[0]["relative_bias"]), 4),
        "worst_bias_segment": f"{worst['segment']}={worst['level']}",
        "worst_relative_bias": round(float(worst["relative_bias"]), 4),
        "rural_share_of_list": round(float(rural["share_of_list"]), 4),
        "rural_share_of_value": round(float(rural["share_of_value"]), 4),
        "rural_representation_ratio": round(float(rural["representation_ratio"]), 3),
        "rural_value_captured": round(float(rural["value_captured_in_segment"]), 4),
        "under_represented": rep[rep["representation_ratio"] < 0.8][["segment", "level"]]
        .astype(str).agg("=".join, axis=1).tolist(),
    }
    log.info("ERRORS: MAE %.1f fills, relative bias %+.1f%%; worst segment %s at %+.1f%%.",
             res["overall_mae"], 100 * res["overall_relative_bias"],
             res["worst_bias_segment"], 100 * res["worst_relative_bias"])
    log.info("REPRESENTATION: rural prescribers are %.1f%% of the list vs %.1f%% of realised "
             "value (ratio %.2f). Under-represented (<0.8): %s",
             100 * res["rural_share_of_list"], 100 * res["rural_share_of_value"],
             res["rural_representation_ratio"], res["under_represented"])
    record("ds_errors", **res)
    log_run("ds_errors", params={"model": "poisson GBM", "list": "hybrid", "k": k},
            metrics={k_: v for k_, v in res.items() if not isinstance(v, (str, list))},
            artifacts=[proc / "ds_error_segments.parquet", proc / "ds_representation.parquet"])
    return res


if __name__ == "__main__":
    run()
