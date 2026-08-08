"""Create a slimmed deploy bundle from data/processed/.

Why this module exists
----------------------
data/processed/ is ~800 MB across 27 parquet files.  No free hosting tier
accepts that, and GitHub's file limit (100 MB) blocks several individual
files.  But the API only ever serves aggregates plus a paginated slice of
prescribers, so a bundle containing the top ~50 000 prescribers by
opportunity plus every aggregate table behaves identically to the full
dataset for a demo.

Contract
--------
The set of tables included is derived directly from api.db.VIEWS — that
dict is the authoritative list of what the API reads.  Tables that are not
in VIEWS (stg_suppression, backtest_frame, etc.) are simply omitted; they
cost disk space and serve no endpoint.

NPI keep-set
------------
Picked once from hcp_call_plan ordered by opportunity DESC, then applied
to every prescriber-level table so referential integrity is preserved: a
row in hcp_metrics must exist for every NPI that /api/hcps/{npi} can
return, or the detail drawer 404s on a row the list just displayed.

Run
---
    python -m src.report.make_deploy_bundle              # defaults
    python -m src.report.make_deploy_bundle --top-n 30000 --out data/small
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from src.config import ROOT
from src.utils.io import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Which parquet stems map to which view names.
# Derived from api.db.VIEWS -- import it directly so this never drifts from
# the API''s own contract.
# ---------------------------------------------------------------------------
from api.db import VIEWS  # noqa: E402  (after stdlib/third-party imports)

# Prescriber-level tables: rows are one-per-NPI (or one-per-NPI-per-year).
# We filter these to the NPI keep-set.
PRESCRIBER_TABLES: frozenset[str] = frozenset(
    {
        "hcp_call_plan",    # primary HCP list -- source of the NPI keep-set
        "hcp_scored",       # model scores, one row per NPI-year
        "hcp_segments",     # behavioural segment label per NPI
        "mart_payments",    # open-payments rows, one per NPI-year
        "mart_hcp_metrics", # volume/share metrics, one per NPI-year
    }
)

# Derive aggregate tables from VIEWS, excluding any prescriber-level stem.
AGGREGATE_TABLES: frozenset[str] = frozenset(VIEWS.keys()) - PRESCRIBER_TABLES

# Column that carries NPI in every prescriber-level table.
NPI_COL = "npi"

COMPRESSION = "zstd"


def _pick_npi_keep_set(proc: Path, top_n: int) -> frozenset[int]:
    """Return the top `top_n` NPIs ordered by opportunity descending.

    hcp_call_plan is the canonical HCP table (the ''hcps'' view).  Ordering
    by opportunity there, not by class_fills, matches the API''s default sort
    and ensures the most commercially relevant prescribers are in the bundle.
    """
    src = proc / "hcp_call_plan.parquet"
    # Read only the two columns we need -- the full file is 124 MB.
    df = pd.read_parquet(src, columns=[NPI_COL, "opportunity"])
    top = df.nlargest(top_n, "opportunity")[NPI_COL]
    keep: frozenset[int] = frozenset(top.tolist())
    log.info(
        "NPI keep-set: top %d of %d by opportunity  (%.1f%%)",
        len(keep),
        len(df),
        100 * len(keep) / len(df),
    )
    return keep


def _write_filtered(
    src: Path,
    dst: Path,
    keep: frozenset[int],
) -> tuple[int, int]:
    """Filter a prescriber-level parquet to the NPI keep-set and write it.

    Returns (before_bytes, after_bytes).
    """
    before = src.stat().st_size
    df = pd.read_parquet(src)
    n_before = len(df)
    df = df[df[NPI_COL].isin(keep)]
    n_after = len(df)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, dst, compression=COMPRESSION)
    after = dst.stat().st_size
    log.info(
        "  filtered  %-34s %8d -> %6d rows  %6.1f MB -> %5.1f MB",
        src.name,
        n_before,
        n_after,
        before / 1e6,
        after / 1e6,
    )
    return before, after


def _write_whole(src: Path, dst: Path) -> tuple[int, int]:
    """Re-compress an aggregate parquet verbatim and write it.

    Returns (before_bytes, after_bytes).
    """
    before = src.stat().st_size
    table = pq.read_table(src)
    pq.write_table(table, dst, compression=COMPRESSION)
    after = dst.stat().st_size
    log.info(
        "  aggregate %-34s %6.1f MB -> %5.1f MB",
        src.name,
        before / 1e6,
        after / 1e6,
    )
    return before, after


def _log_size_table(rows: list[tuple[str, int, int]]) -> None:
    """Print a final size summary table to the log."""
    total_before = sum(b for _, b, _ in rows)
    total_after = sum(a for _, _, a in rows)
    log.info("")
    log.info("%-38s  %9s  %9s  %8s", "file", "before", "after", "ratio")
    log.info("-" * 72)
    for name, before, after in sorted(rows):
        ratio = after / before if before else 0
        log.info(
            "%-38s  %7.1f MB  %7.1f MB  %6.2f*",
            name,
            before / 1e6,
            after / 1e6,
            ratio,
        )
    log.info("-" * 72)
    log.info(
        "%-38s  %7.1f MB  %7.1f MB  %6.2f*",
        "TOTAL",
        total_before / 1e6,
        total_after / 1e6,
        total_after / total_before if total_before else 0,
    )
    log.info("")


def build_bundle(top_n: int, out_dir: Path) -> None:
    """Main entry point: build the deploy bundle."""
    proc = ROOT / "data" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    log.info("Building deploy bundle -> %s", out_dir)
    log.info("Source:  %s", proc)
    log.info("top-n:   %d prescribers by opportunity", top_n)
    log.info("")

    # ------------------------------------------------------------------
    # Step 1: pick the NPI keep-set
    # ------------------------------------------------------------------
    keep = _pick_npi_keep_set(proc, top_n)

    # ------------------------------------------------------------------
    # Step 2: process every table the API actually reads (VIEWS contract)
    # ------------------------------------------------------------------
    size_rows: list[tuple[str, int, int]] = []

    for stem in VIEWS:
        src = proc / f"{stem}.parquet"
        dst = out_dir / f"{stem}.parquet"

        if not src.exists():
            log.warning(
                "MISSING: %s -- skipping (the API will return 503 for that view)", stem
            )
            continue

        if stem in PRESCRIBER_TABLES:
            b, a = _write_filtered(src, dst, keep)
        else:
            b, a = _write_whole(src, dst)

        size_rows.append((stem, b, a))

    # ------------------------------------------------------------------
    # Step 3: copy manifest verbatim
    # /api/summary and /api/meta read it; the headline numbers must stay
    # as the full-universe values so we never overstate what we computed.
    # ------------------------------------------------------------------
    manifest_src = ROOT / "data" / "manifest.json"
    manifest_dst = out_dir / "manifest.json"
    if manifest_src.exists():
        shutil.copy2(manifest_src, manifest_dst)
        log.info("Copied manifest.json verbatim (%d bytes)", manifest_src.stat().st_size)
    else:
        log.warning("manifest.json not found -- /api/summary will return empty KPIs")

    # ------------------------------------------------------------------
    # Step 4: log the size table
    # ------------------------------------------------------------------
    _log_size_table(size_rows)
    log.info("Deploy bundle complete: %s", out_dir)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Build a slimmed deploy bundle from data/processed/. "
            "See module docstring for the full rationale."
        )
    )
    ap.add_argument(
        "--top-n",
        type=int,
        default=50_000,
        metavar="N",
        help="Number of top prescribers by opportunity to keep (default: 50000)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "data" / "deploy",
        metavar="DIR",
        help="Output directory (default: data/deploy)",
    )
    args = ap.parse_args()
    build_bundle(top_n=args.top_n, out_dir=args.out)


if __name__ == "__main__":
    main()
