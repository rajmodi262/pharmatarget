"""The ingest column contract.

Everything downstream of ingest is deliberately source-agnostic -- build_marts
cannot tell whether the real or the synthetic path wrote data/raw. That is the
property which makes synthetic mode a genuine test of the pipeline, and it is
also the property that lets the two paths drift apart silently.

These tests are the guard rail. Each one corresponds to a drift that ACTUALLY
HAPPENED and cost real debugging time.
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import pytest

from src.config import ROOT
from src.utils.schema import (
    PARTD_DRUG_COLUMNS,
    PARTD_PROVIDER_COLUMNS,
    ZIP3_UNIT_COLUMNS,
    require_columns,
)

SQL_DIR = ROOT / "src" / "sql"


class TestRequireColumns:
    def test_passes_when_complete(self):
        df = pd.DataFrame({c: [1] for c in ZIP3_UNIT_COLUMNS})
        require_columns(df, ZIP3_UNIT_COLUMNS, produced_by="test", consumed_by="test")

    def test_raises_naming_the_missing_columns(self):
        df = pd.DataFrame({c: [1] for c in ZIP3_UNIT_COLUMNS if c != "pop_density"})
        with pytest.raises(ValueError, match="pop_density"):
            require_columns(df, ZIP3_UNIT_COLUMNS, produced_by="p", consumed_by="c")

    def test_error_names_producer_and_consumer(self):
        """The reader is usually looking at a stack trace from five stages away."""
        df = pd.DataFrame({"zip3": ["001"]})
        with pytest.raises(ValueError) as exc:
            require_columns(df, ZIP3_UNIT_COLUMNS,
                            produced_by="synth.py", consumed_by="SQL 04")
        assert "synth.py" in str(exc.value)
        assert "SQL 04" in str(exc.value)


class TestHistoricalDrifts:
    """One test per drift that actually shipped and broke something."""

    def test_no_invented_age_column(self):
        """CMS publishes age BANDS, not a 65+ total.

        `Bene_Age_GE_65_Cnt` was invented by the synthetic generator. The whole
        pipeline ran green on synthetic data and died on the first real extract.
        """
        assert "Bene_Age_GE_65_Cnt" not in PARTD_PROVIDER_COLUMNS
        for band in ("Bene_Age_65_74_Cnt", "Bene_Age_75_84_Cnt", "Bene_Age_GT_84_Cnt"):
            assert band in PARTD_PROVIDER_COLUMNS

    def test_geography_uses_population_not_pop_65_plus(self):
        """synth emitted pop_65_plus while geo_build produced population.

        SQL 04 failed in the binder the moment it was updated for real data.
        """
        assert "population" in ZIP3_UNIT_COLUMNS
        assert "pop_density" in ZIP3_UNIT_COLUMNS
        assert "pop_65_plus" not in ZIP3_UNIT_COLUMNS

    def test_year_regex_is_anchored_to_the_filename(self):
        """An unanchored (\\d{4}) matched the absolute PATH, not the filename.

        A checkout under a directory containing four digits stamped every row
        with that number -- observed as year 6310 from a temp path -- producing
        an empty training set and no error. Nothing downstream validates the
        year, so this failed completely silently.
        """
        offenders = []
        for sql in SQL_DIR.glob("*.sql"):
            text = sql.read_text(encoding="utf-8")
            for m in re.finditer(r"regexp_extract\(\s*filename\s*,\s*'([^']+)'", text):
                pattern = m.group(1)
                if "csv" not in pattern:
                    offenders.append(f"{sql.name}: {pattern}")

        assert not offenders, (
            "Year regex must be anchored to the filename, e.g. '_(\\d{4})\\.csv$'. "
            f"Unanchored in: {offenders}"
        )

    def test_build_marts_year_regex_also_anchored(self):
        """The same regex is embedded in Python for the side-car totals file."""
        src = (ROOT / "src" / "etl" / "build_marts.py").read_text(encoding="utf-8")
        for m in re.finditer(r"regexp_extract\(filename, '([^']+)'", src):
            assert "csv" in m.group(1), f"unanchored year regex: {m.group(1)}"


class TestSqlConsumesWhatIngestProduces:
    """Columns the SQL layer reads must exist in the declared contracts."""

    def test_sql01_reads_only_declared_provider_columns(self):
        sql = (SQL_DIR / "01_stg_prescribers.sql").read_text(encoding="utf-8")
        for col in ("Tot_Benes", "Bene_Avg_Risk_Scre", "Bene_Age_65_74_Cnt"):
            if col in sql:
                assert col in PARTD_PROVIDER_COLUMNS, (
                    f"SQL 01 reads {col} but it is not in PARTD_PROVIDER_COLUMNS, "
                    f"so synth.py is not required to emit it")

    def test_sql02_reads_only_declared_drug_columns(self):
        sql = (SQL_DIR / "02_stg_scripts.sql").read_text(encoding="utf-8")
        for col in ("Gnrc_Name", "Tot_30day_Fills", "Tot_Clms"):
            if col in sql:
                assert col in PARTD_DRUG_COLUMNS

    def test_sql04_geography_columns_are_declared(self):
        sql = (SQL_DIR / "04_mart_hcp_metrics.sql").read_text(encoding="utf-8")
        for col in ("population", "pop_density", "prev_stroke", "prev_chd", "prev_bp"):
            if f"u.{col}" in sql:
                assert col in ZIP3_UNIT_COLUMNS, (
                    f"SQL 04 joins u.{col} but it is not in ZIP3_UNIT_COLUMNS")


class TestLiveArtifacts:
    """If an ingest has actually run, validate what it wrote."""

    def test_zip3_units_on_disk_satisfies_the_contract(self):
        f = Path(ROOT) / "data" / "raw" / "zip3_units.csv"
        if not f.exists():
            pytest.skip("no ingest has run in this checkout")
        require_columns(pd.read_csv(f, nrows=5, dtype={"zip3": str}),
                        ZIP3_UNIT_COLUMNS,
                        produced_by="data/raw/zip3_units.csv",
                        consumed_by="SQL 04")

    def test_provider_file_on_disk_satisfies_the_contract(self):
        files = sorted((Path(ROOT) / "data" / "raw").glob("partd_provider_*.csv"))
        if not files:
            pytest.skip("no ingest has run in this checkout")
        require_columns(pd.read_csv(files[0], nrows=5),
                        PARTD_PROVIDER_COLUMNS,
                        produced_by=files[0].name,
                        consumed_by="src/sql/01_stg_prescribers.sql")
