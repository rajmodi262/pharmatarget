"""One lean loader for the out-of-time panels every data-science module uses.

    train   state at 2022 with realised change 2022 -> 2023   (learning period)
    apply   state at 2023 with realised change 2023 -> 2024   (the holdout)

Reads hcp_scored through DuckDB, keeping only prescribers who write the class
in at least one year, so the 4.1M-row file never lands in pandas whole -- the
machine this runs on has about a gigabyte free. Churners (a writer who stops)
are kept because the next-year row is read for every ever-writer.
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from src.config import params, path

STATE = ["npi", "year", "zip3", "state", "specialty_group", "region", "class_fills",
         "class_fills_observed", "brand_fills", "brand_share", "potential_brand",
         "opportunity", "panel_benes", "non_class_clms", "age65_cnt", "risk_score",
         "pct_panel_65", "zip3_population", "zip3_pop_density", "prev_stroke",
         "prev_chd", "prev_bp", "lat", "lon"]

RURAL_DENSITY = 100.0          # people per square mile (ZIP3); the usual US cut-off
SIZE_BANDS = [0, 50, 200, 800, np.inf]
SIZE_LABELS = ["<50 fills", "50-200", "200-800", "800+"]


def load_scored(columns: list[str] = STATE) -> pd.DataFrame:
    f = (path("processed") / "hcp_scored.parquet").as_posix()
    cols = ", ".join(columns)
    con = duckdb.connect()
    try:
        con.execute("SET memory_limit='700MB'; SET threads=2")
        df = con.execute(f"""
            SELECT {cols} FROM read_parquet('{f}')
            WHERE npi IN (SELECT DISTINCT npi FROM read_parquet('{f}') WHERE class_fills > 0)
        """).df()
    finally:
        con.close()
    for c in df.select_dtypes("float64").columns:
        df[c] = df[c].astype("float32")
    return df


def eb_columns(df: pd.DataFrame, nxt: pd.DataFrame) -> pd.DataFrame:
    """Attach next-year observed class volume, needed for shrunk share change."""
    return df.merge(nxt.rename(columns={"class_fills_observed": "class_obs_next"}),
                    on="npi", how="left").assign(
        class_obs_next=lambda d: d["class_obs_next"].fillna(0.0))


def panels(scored: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(train, apply) with outcomes, segments and the prior-year change."""
    from src.models.challenger import build_panels

    scored = scored if scored is not None else load_scored()
    train, apply_ = build_panels(scored)
    p = params()["years"]
    y1, y2 = p["train_end"], p["holdout"]

    def obs(year: int) -> pd.DataFrame:
        return scored.loc[scored["year"] == year, ["npi", "class_fills_observed"]]

    train = eb_columns(train, obs(y1))
    apply_ = eb_columns(apply_, obs(y2))
    # Prior-year change for the holdout panel: the momentum baseline and the
    # pre-trend control the causal models need.
    prior = train[["npi", "growth_abs", "growth_share"]].rename(
        columns={"growth_abs": "prior_growth_abs", "growth_share": "prior_growth_share"})
    apply_ = apply_.merge(prior, on="npi", how="left")
    for frame in (train, apply_):
        frame["rural"] = frame["zip3_pop_density"].fillna(0) < RURAL_DENSITY
        frame["size_band"] = pd.cut(frame["class_fills"], SIZE_BANDS, labels=SIZE_LABELS,
                                    right=False).astype(str)
    return train, apply_


def n_budget() -> int:
    """Prescribers 60 reps can cover -- the k every ranking metric is read at."""
    from src.utils.io import manifest
    return int((manifest().get("challenger") or {}).get("n_budget") or 8878)
