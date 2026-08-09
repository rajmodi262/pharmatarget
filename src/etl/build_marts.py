"""Run the SQL layer against DuckDB and export marts to parquet.

The .sql files are the artifact; this module is just the runner. Templating is
a deliberate ``{{TOKEN}}`` replace rather than f-strings so the SQL files stay
valid, readable SQL that can be pasted into a DuckDB shell unmodified.

    python -m src.etl.build_marts                 # base imputation mode
    python -m src.etl.build_marts --all-modes     # full suppression sensitivity
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

from src.config import ROOT, class_generic_names, focus_generic_names, manufacturers, params, path
from src.utils.io import get_logger, record, write_parquet

log = get_logger(__name__)

SQL_DIR = ROOT / "src" / "sql"
RAW = ROOT / "data" / "raw"


def _sql_list(values) -> str:
    """Render a Python list as a SQL IN-list literal."""
    return ", ".join("'" + str(v).replace("'", "''") + "'" for v in values)


def _alldrug_source() -> str:
    """SQL producing (npi, year, observed_all_clms), whichever ingest ran.

    See the comment block at the top of 03_suppression_recon.sql. The real path
    writes a side-car totals file because it discards out-of-class rows while
    streaming; the synthetic path keeps every drug, so the total is just a sum
    over stg_scripts. Choosing here -- and saying so in the log -- means neither
    path silently produces the wrong suppression figure.
    """
    totals = sorted(RAW.glob("npi_alldrug_totals_*.csv"))
    if totals:
        log.info("all-drug totals: %d side-car file(s) from the streaming ingest", len(totals))
        return (
            "SELECT\n"
            "    CAST(Prscrbr_NPI AS BIGINT)                              AS npi,\n"
            # Anchored to the FILENAME, not the path. An unanchored (\d{4})
            # matches the first four digits anywhere in the absolute path, so a
            # checkout under a directory containing digits silently stamps every
            # row with the wrong year -- and nothing downstream complains.
            "    CAST(regexp_extract(filename, '_(\\d{4})\\.csv$', 1) AS INTEGER)  AS year,\n"
            "    CAST(All_Drug_Tot_Clms_Observed AS DOUBLE)               AS observed_all_clms\n"
            f"FROM read_csv_auto('{RAW.as_posix()}/npi_alldrug_totals_*.csv',\n"
            "                   filename = true, union_by_name = true, header = true)"
        )

    log.info("all-drug totals: no side-car file; summing stg_scripts "
             "(correct for the synthetic ingest, which keeps every drug)")
    return (
        "SELECT npi, year, SUM(tot_clms) AS observed_all_clms\n"
        "FROM stg_scripts\n"
        "GROUP BY npi, year"
    )


def _render(sql: str, impute_mode: str) -> str:
    p = params()
    mfg = manufacturers()
    tokens = {
        "{{RAW}}": RAW.as_posix(),
        "{{ALLDRUG_SOURCE}}": _alldrug_source(),
        "{{FOCUS_GENERICS}}": _sql_list(focus_generic_names()),
        "{{CLASS_GENERICS}}": _sql_list(class_generic_names()),
        "{{IMPUTE_MODE}}": impute_mode,
        "{{ACHIEVABLE_PCT}}": str(p["opportunity_model"]["achievable_share_pct"] / 100.0),
        "{{FOCUS_PARENTS}}": _sql_list(mfg["focus_brand_parents"]),
        "{{COMP_PARENTS}}": _sql_list(mfg["competitor_parents"]),
    }
    for token, value in tokens.items():
        sql = sql.replace(token, value)
    return sql


def _register_manufacturer_map(con: duckdb.DuckDBPyConnection) -> None:
    """Materialise config/manufacturers.yaml as a joinable table."""
    rows = [
        {"raw_name": raw, "parent": parent}
        for parent, names in manufacturers()["parents"].items()
        for raw in names
    ]
    con.register("mfr_map_df", pd.DataFrame(rows))
    con.execute("CREATE OR REPLACE TABLE mfr_map AS SELECT * FROM mfr_map_df")
    log.info("manufacturer map: %d name variants -> %d parents",
             len(rows), len({r["parent"] for r in rows}))


def _measure_payment_match_rate(con: duckdb.DuckDBPyConnection) -> dict:
    """Measure, do not assume, the Open Payments NPI coverage."""
    q = """
        SELECT
            COUNT(*)                                  AS total_rows,
            COUNT(npi)                                AS rows_with_npi,
            COUNT(DISTINCT npi)                       AS distinct_npi
        FROM stg_payments_raw
    """
    total, with_npi, distinct = con.execute(q).fetchone()
    unmapped = con.execute("""
        SELECT COUNT(*) FROM stg_payments_raw r
        LEFT JOIN mfr_map m ON r.manufacturer_raw = m.raw_name
        WHERE m.parent IS NULL
    """).fetchone()[0]

    linked = con.execute("""
        SELECT COUNT(DISTINCT p.npi)
        FROM mart_payments p
        JOIN (SELECT DISTINCT npi FROM stg_prescribers) s USING (npi)
    """).fetchone()[0]

    stats = {
        "payment_rows": int(total),
        "rows_with_npi": int(with_npi),
        "npi_fill_rate": round(with_npi / total, 4) if total else None,
        "distinct_npis_in_payments": int(distinct),
        "npis_linked_to_prescribers": int(linked),
        "link_rate": round(linked / distinct, 4) if distinct else None,
        "unmapped_manufacturer_rows": int(unmapped),
    }
    log.info("Open Payments: NPI fill %.1f%%, linked to prescriber universe %.1f%%, "
             "%d rows with unmapped manufacturer",
             100 * (stats["npi_fill_rate"] or 0),
             100 * (stats["link_rate"] or 0),
             unmapped)
    if unmapped:
        sample = con.execute("""
            SELECT DISTINCT r.manufacturer_raw FROM stg_payments_raw r
            LEFT JOIN mfr_map m ON r.manufacturer_raw = m.raw_name
            WHERE m.parent IS NULL LIMIT 10
        """).fetchall()
        log.warning("  unmapped names (add to config/manufacturers.yaml): %s",
                    [s[0] for s in sample])
    record("open_payments_match", **stats)
    return stats


def build(impute_mode: str | None = None, export: bool = True) -> Path:
    p = params()
    impute_mode = impute_mode or p["suppression"]["base_mode"]
    if impute_mode not in p["suppression"]["imputation_modes"]:
        raise SystemExit(f"unknown imputation mode: {impute_mode}")

    interim = path("interim")
    db_path = interim / f"pharmatarget_{impute_mode}.duckdb"
    if db_path.exists():
        db_path.unlink()

    log.info("building marts (imputation mode = %s)", impute_mode)
    con = duckdb.connect(str(db_path))
    con.execute("SET preserve_insertion_order = false")

    _register_manufacturer_map(con)

    for sql_file in sorted(SQL_DIR.glob("*.sql")):
        log.info("  running %s", sql_file.name)
        con.execute(_render(sql_file.read_text(encoding="utf-8"), impute_mode))

    _measure_payment_match_rate(con)

    # Suppression headline, reported whichever mode is active.
    supp = con.execute("""
        SELECT
            COUNT(*)                                            AS npi_years,
            SUM(CASE WHEN has_suppression THEN 1 ELSE 0 END)    AS with_suppression,
            SUM(suppressed_clms)                                AS hidden_claims,
            SUM(observed_all_clms)                              AS visible_claims
        FROM stg_suppression
    """).fetchdf().iloc[0].to_dict()
    supp["pct_npi_years_affected"] = round(supp["with_suppression"] / max(supp["npi_years"], 1), 4)
    supp["hidden_share_of_total"] = round(
        supp["hidden_claims"] / max(supp["hidden_claims"] + supp["visible_claims"], 1), 4)
    log.info("suppression: %.1f%% of NPI-years affected; %.1f%% of all claim volume hidden",
             100 * supp["pct_npi_years_affected"], 100 * supp["hidden_share_of_total"])
    record(f"suppression_{impute_mode}", **{k: float(v) for k, v in supp.items()})

    if export:
        out = path("processed")
        suffix = "" if impute_mode == p["suppression"]["base_mode"] else f"_{impute_mode}"
        for table in ("mart_hcp_metrics", "mart_peer_benchmarks",
                      "mart_payments", "mart_payment_onset", "stg_suppression"):
            df = con.execute(f"SELECT * FROM {table}").fetchdf()
            write_parquet(df, out / f"{table}{suffix}.parquet", label=f"{table}{suffix}")

    con.close()
    log.info("marts built -> %s", db_path.name)
    return db_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Build DuckDB marts from raw CMS files.")
    ap.add_argument("--mode", default=None, help="suppression imputation mode")
    ap.add_argument("--all-modes", action="store_true",
                    help="build every imputation mode for the sensitivity table")
    a = ap.parse_args()

    if a.all_modes:
        for mode in params()["suppression"]["imputation_modes"]:
            build(mode)
    else:
        build(a.mode)


if __name__ == "__main__":
    main()
