"""Read-only DuckDB connection over the processed parquet files.

One connection, opened at startup, held for the process lifetime. DuckDB reads
parquet directly, so there is no load step and no copy in memory -- the API
queries the same files the pipeline wrote.

Filtering, sorting and pagination all happen IN SQL. Not in pandas, not in
Python lists, and never in the browser. That is the difference between a
/api/hcps that answers in 40ms on 400k rows and one that hangs during a demo.

Data directory
--------------
The parquet directory defaults to data/processed/ but can be overridden via
the PHARMATARGET_DATA_DIR environment variable (absolute path).  The deploy
bundle sets this to point at data/deploy/ without moving any files.  Which
directory is chosen is logged at startup -- a silent fallback to the wrong
directory is exactly the kind of failure that only surfaces in production.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import duckdb

from src.config import path
from src.utils.io import get_logger, manifest

log = get_logger("api.db")


def _resolve_data_dir() -> Path:
    """Return the parquet directory, honouring PHARMATARGET_DATA_DIR.

    The env var must be an absolute path.  If it is set and the directory does
    not exist the process fails fast rather than silently reading zero files.
    """
    env = os.environ.get("PHARMATARGET_DATA_DIR", "").strip()
    if env:
        p = Path(env)
        if not p.is_dir():
            raise FileNotFoundError(
                f"PHARMATARGET_DATA_DIR is set to '{env}' but that directory "
                f"does not exist.  Check the path or unset the variable to "
                f"fall back to data/processed/."
            )
        log.info("Data directory (PHARMATARGET_DATA_DIR): %s", p)
        return p
    fallback = path("processed")
    log.info("Data directory (default data/processed): %s", fallback)
    return fallback

_con: duckdb.DuckDBPyConnection | None = None
_lock = threading.Lock()

# Parquet name -> view name exposed to SQL.
VIEWS = {
    "hcp_call_plan": "hcps",
    "hcp_scored": "hcp_scored",
    "call_plan_matrix": "call_plan_matrix",
    "reach_curve": "reach_curve",
    "disagreement_matrix": "disagreement_matrix",
    "shap_drivers": "shap_drivers",
    "backtest_decile_lift": "backtest_lift",
    "backtest_misses": "backtest_misses",
    "sizing_roi_curve": "roi_curve",
    "sizing_tornado": "tornado",
    "sizing_pnl": "pnl",
    "territory_stats": "territory_stats",
    "territory_summary": "territory_summary",
    "territory_assignments": "territory_assignments",
    "segment_profiles": "segment_profiles",
    "hcp_segments": "hcp_segments",
    "segmentation_diagnostics": "segmentation_diagnostics",
    "response_saturation": "response_saturation",
    "response_balance": "response_balance",
    "mart_payments": "payments",
    "mart_hcp_metrics": "hcp_metrics",
}


def connect() -> duckdb.DuckDBPyConnection:
    """Open the shared read-only connection and register every available view."""
    global _con
    with _lock:
        if _con is not None:
            return _con

        proc = _resolve_data_dir()
        con = duckdb.connect(database=":memory:")
        con.execute("SET enable_progress_bar = false")

        available, missing = [], []
        for stem, view in VIEWS.items():
            f = proc / f"{stem}.parquet"
            if f.exists():
                con.execute(
                    f"CREATE OR REPLACE VIEW {view} AS "
                    f"SELECT * FROM read_parquet('{f.as_posix()}')"
                )
                available.append(view)
            else:
                missing.append(view)

        log.info("DuckDB ready: %d views available", len(available))
        if missing:
            log.warning("missing parquet for: %s -- run `make data` (those endpoints "
                        "will return 503 rather than pretending)", ", ".join(missing))
        _con = con
        return _con


def has_view(view: str) -> bool:
    con = connect()
    rows = con.execute(
        "SELECT count(*) FROM duckdb_views() WHERE view_name = ?", [view]
    ).fetchone()
    return bool(rows and rows[0])


def query(sql: str, params: list | None = None) -> list[dict]:
    con = connect()
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def query_one(sql: str, params: list | None = None) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def data_mode() -> str:
    return manifest().get("data_mode", {}).get("mode", "UNKNOWN")
