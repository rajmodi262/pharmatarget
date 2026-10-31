"""Data contracts: every table a model reads is checked before the model runs.

    python -m src.ds.contracts          check, record, exit 1 on any failure

The contracts live in config/contracts.yaml. Each check is one DuckDB query
over the parquet file, so the 4.1M-row marts are validated without ever being
loaded into memory. Results go to the manifest (``ds_contracts``) and to
ds_contract_results.parquet, so the Method page can show the last run.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import pandas as pd
import yaml

from src.config import ROOT, path
from src.ds.tracking import log_run
from src.utils.io import get_logger, record, write_parquet

log = get_logger(__name__)

CONTRACTS = ROOT / "config" / "contracts.yaml"


class ContractError(RuntimeError):
    pass


def check_table(con: duckdb.DuckDBPyConnection, name: str, file: Path, spec: dict) -> list[dict]:
    src = f"read_parquet('{file.as_posix()}')"
    out: list[dict] = []

    def add(check: str, passed: bool, detail: str) -> None:
        out.append({"table": name, "check": check, "passed": bool(passed), "detail": detail})

    if not file.exists():
        add("exists", False, f"{file.name} missing")
        return out
    cols = {r[0]: r[1] for r in con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()}
    n = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
    add("min_rows", n >= spec.get("min_rows", 0), f"{n:,} rows (min {spec.get('min_rows', 0):,})")

    key = spec.get("key") or []
    if key and all(k in cols for k in key):
        k = ", ".join(key)
        dup = con.execute(f"SELECT count(*) FROM (SELECT {k} FROM {src} GROUP BY {k} "
                          f"HAVING count(*) > 1)").fetchone()[0]
        add(f"unique({k})", dup == 0, f"{dup:,} duplicated keys")

    for col, rule in (spec.get("columns") or {}).items():
        if col not in cols:
            add(f"{col}: present", False, "column missing")
            continue
        numeric = any(t in cols[col].upper() for t in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "BIGINT"))
        if rule.get("type") == "numeric" and not numeric:
            add(f"{col}: type", False, f"expected numeric, found {cols[col]}")
        nulls = con.execute(f"SELECT avg(({col} IS NULL)::double) FROM {src}").fetchone()[0] or 0.0
        cap = rule.get("nullable", 0.0)
        add(f"{col}: nulls", nulls <= cap + 1e-9, f"{nulls:.2%} null (max {cap:.0%})")
        if numeric and ("min" in rule or "max" in rule):
            lo, hi = con.execute(f"SELECT min({col}), max({col}) FROM {src}").fetchone()
            ok = True
            if lo is not None and "min" in rule:
                ok &= lo >= rule["min"] - 1e-9
            if hi is not None and "max" in rule:
                ok &= hi <= rule["max"] + 1e-9
            add(f"{col}: range", ok, f"[{lo}, {hi}] vs [{rule.get('min', '-inf')}, {rule.get('max', 'inf')}]")

    for rule in spec.get("rules") or []:
        bad = con.execute(f"SELECT count(*) FROM {src} WHERE NOT ({rule})").fetchone()[0]
        add(f"rule: {rule}", bad == 0, f"{bad:,} violating rows")
    return out


def validate(contracts: dict | None = None, directory: Path | None = None) -> pd.DataFrame:
    contracts = contracts or yaml.safe_load(CONTRACTS.read_text(encoding="utf-8"))
    directory = directory or path("processed")
    con = duckdb.connect()
    try:
        con.execute("SET memory_limit='600MB'; SET threads=2")
        rows = []
        for name, spec in contracts.items():
            rows += check_table(con, name, directory / f"{name}.parquet", spec)
    finally:
        con.close()
    return pd.DataFrame(rows)


def run(strict: bool = True) -> dict:
    df = validate()
    write_parquet(df, path("processed") / "ds_contract_results.parquet")
    failed = df[~df["passed"]]
    res = {"checks": int(len(df)), "passed": int(df["passed"].sum()), "failed": int(len(failed)),
           "tables": sorted(df["table"].unique().tolist()),
           "failures": failed[["table", "check", "detail"]].to_dict(orient="records")}
    log.info("CONTRACTS: %d/%d checks passed across %d tables.", res["passed"], res["checks"],
             len(res["tables"]))
    for f in res["failures"]:
        log.error("  CONTRACT FAILED  %s  %s  (%s)", f["table"], f["check"], f["detail"])
    record("ds_contracts", **res)
    log_run("ds_contracts", metrics={"checks": res["checks"], "failed": res["failed"]})
    if strict and res["failed"]:
        raise ContractError(f"{res['failed']} data-contract check(s) failed -- see the log")
    return res


if __name__ == "__main__":
    try:
        run()
    except ContractError as exc:
        log.error("%s", exc)
        sys.exit(1)
