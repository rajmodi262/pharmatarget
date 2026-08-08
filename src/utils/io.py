"""Parquet IO and run logging.

Every stage writes a parquet and appends a row-count line to the run manifest.
When someone asks "how many prescribers?" the answer is in a file, not in your
memory of a notebook cell you ran three weeks ago.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

from src.config import ROOT

_LOG_FORMAT = "%(asctime)s  %(levelname)-7s  %(name)-22s  %(message)s"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, datefmt="%H:%M:%S"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


log = get_logger(__name__)

MANIFEST = ROOT / "data" / "manifest.json"


def write_parquet(df: pd.DataFrame, target: Path, label: str | None = None) -> Path:
    """Write a dataframe and record its shape in the manifest."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(target, index=False)
    record(label or target.stem, rows=len(df), cols=df.shape[1], path=str(target.relative_to(ROOT)))
    log.info("wrote %-34s %8d rows x %2d cols", target.name, len(df), df.shape[1])
    return target


def read_parquet(target: Path) -> pd.DataFrame:
    return pd.read_parquet(target)


def record(key: str, **fields) -> None:
    """Append a fact to data/manifest.json."""
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    payload: dict = {}
    if MANIFEST.exists():
        try:
            payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    payload[key] = fields
    MANIFEST.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def manifest() -> dict:
    if not MANIFEST.exists():
        return {}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Data-mode guard
# --------------------------------------------------------------------------- #
# Synthetic and real ingest write the SAME filenames into data/raw/
# (partd_drug_2022.csv and so on). Nothing structurally prevents a real drug
# file from sitting beside a synthetic provider file, and because the ETL is
# deliberately source-agnostic it would join them without complaint and produce
# a confident, meaningless answer.
#
# This happened during development: a real 2022 drug stream was about to be
# reconciled against synthetic 2022 provider totals. It surfaced only because a
# "cached, skipping" line looked wrong.
#
# So data/raw/ carries a mode marker, and either ingest refuses to write into a
# directory claimed by the other mode.

_MODE_MARKER = ROOT / "data" / "raw" / ".data_mode"


def claim_raw_dir(mode: str, force: bool = False) -> None:
    """Assert data/raw/ belongs to `mode` ('REAL' or 'SYNTHETIC'), or fail."""
    _MODE_MARKER.parent.mkdir(parents=True, exist_ok=True)
    existing = _MODE_MARKER.read_text(encoding="utf-8").strip() if _MODE_MARKER.exists() else None

    has_data = any(p.suffix == ".csv" for p in _MODE_MARKER.parent.iterdir()) \
        if _MODE_MARKER.parent.exists() else False

    if existing and existing != mode and has_data and not force:
        raise SystemExit(
            f"data/raw/ already holds {existing} data and you are running {mode} ingest.\n"
            f"Mixing them produces a silently wrong analysis -- real drug rows "
            f"reconciled against synthetic provider totals, for example.\n"
            f"Clear the directory first:  python -m src.utils.io --clear-raw\n"
            f"or pass --force to overwrite deliberately."
        )
    if existing != mode:
        _MODE_MARKER.write_text(mode, encoding="utf-8")
        log.info("data/raw/ claimed for %s ingest", mode)


def raw_mode() -> str | None:
    return _MODE_MARKER.read_text(encoding="utf-8").strip() if _MODE_MARKER.exists() else None


def _clear_raw() -> None:
    d = _MODE_MARKER.parent
    n = 0
    for p in d.glob("*"):
        if p.is_file():
            p.unlink()
            n += 1
    log.info("cleared %d files from data/raw/", n)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="data/raw maintenance")
    ap.add_argument("--clear-raw", action="store_true")
    if ap.parse_args().clear_raw:
        _clear_raw()
