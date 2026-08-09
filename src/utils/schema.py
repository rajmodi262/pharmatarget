"""Canonical column contracts shared by the two ingest paths.

WHY THIS EXISTS
---------------
The same logical tables are produced by two completely different code paths:

    REAL       src/ingest/download.py  + src/ingest/geo_build.py
    SYNTHETIC  src/ingest/synth.py

Everything downstream -- five SQL files, eight models, twelve API routes -- is
deliberately source-agnostic: `build_marts.py` cannot tell which ingest ran, and
that is the property that makes the synthetic mode a real test of the pipeline
rather than a toy.

That property is also the trap. When the two paths drift, nothing complains at
the boundary; the failure surfaces hundreds of lines later as a DuckDB binder
error, or worse, as a silently wrong number. This has now happened three times:

  1. synth invented `Bene_Age_GE_65_Cnt`, a column CMS does not publish. The
     whole pipeline ran green on synthetic data and died on the first real
     extract.
  2. synth emitted `pop_65_plus` / `pct_65_plus` while geo_build produced
     `population` / `pop_density`, so SQL 04 failed in the binder the moment it
     was updated for real data.
  3. The suppression reconciliation was rewired to read a side-car totals file
     that only the streaming ingest writes, breaking the synthetic path.

So the contract lives here, in one place neither module owns, and BOTH producers
validate against it before writing. A drift now fails at the point it is
introduced, with a message naming the missing columns -- not five stages later.
"""
from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

# --------------------------------------------------------------------------- #
# zip3_units.csv -- written by geo_build.py (real) and synth.py (synthetic),
# consumed by SQL 04 and by the territory optimiser.
# --------------------------------------------------------------------------- #

ZIP3_UNIT_COLUMNS: tuple[str, ...] = (
    "zip3",          # VARCHAR, zero-padded to 3 -- '021' must not become 21
    "state",
    "region",
    "lat",
    "lon",
    "population",
    "land_sqmi",
    "pop_density",
    "prev_stroke",   # CDC PLACES proxies -- PLACES carries no atrial
    "prev_chd",      # fibrillation measure, which is the actual DOAC
    "prev_bp",       # indication. Labelled a proxy everywhere it appears.
)

# --------------------------------------------------------------------------- #
# Part D "by Provider" columns that SQL 01 reads. These are the REAL CMS names.
#
# There is no Bene_Age_GE_65_Cnt. CMS publishes age BANDS and SQL 01 assembles
# the 65+ count from them. If you are tempted to add a convenience column here,
# check it exists in the actual file first.
# --------------------------------------------------------------------------- #

PARTD_PROVIDER_COLUMNS: tuple[str, ...] = (
    "Prscrbr_NPI",
    "Prscrbr_Last_Org_Name",
    "Prscrbr_First_Name",
    "Prscrbr_City",
    "Prscrbr_State_Abrvtn",
    "Prscrbr_Type",
    "Tot_Clms",
    "Tot_Benes",
    "Bene_Avg_Risk_Scre",
    "Bene_Age_65_74_Cnt",
    "Bene_Age_75_84_Cnt",
    "Bene_Age_GT_84_Cnt",
)

# --------------------------------------------------------------------------- #
# Part D "by Provider and Drug" columns that SQL 02 reads.
# --------------------------------------------------------------------------- #

PARTD_DRUG_COLUMNS: tuple[str, ...] = (
    "Prscrbr_NPI",
    "Brnd_Name",
    "Gnrc_Name",
    "Tot_Clms",
    "Tot_30day_Fills",
)


def require_columns(df: pd.DataFrame, required: Iterable[str], *, produced_by: str,
                    consumed_by: str) -> None:
    """Raise unless `df` carries every required column.

    The error names the producer AND the consumer, because the person reading it
    is usually looking at neither -- they are looking at a stack trace from five
    stages downstream and wondering which ingest wrote the file.
    """
    required = tuple(required)
    missing = [c for c in required if c not in df.columns]
    if not missing:
        return

    raise ValueError(
        f"{produced_by} is missing {len(missing)} column(s) required by "
        f"{consumed_by}: {missing}\n"
        f"  present: {sorted(df.columns)[:14]}{' ...' if len(df.columns) > 14 else ''}\n"
        f"  The real and synthetic ingest paths must produce identical column "
        f"names -- everything downstream is deliberately source-agnostic and "
        f"cannot tell them apart. See src/utils/schema.py."
    )
