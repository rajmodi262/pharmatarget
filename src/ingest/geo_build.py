"""Build the ZIP3 geography and market-potential table from public reference data.

    python -m src.ingest.geo_build --local-dir dataset

INPUTS
------
    Census Gazetteer ZCTA   ZCTA5 -> latitude, longitude, land area   (~1 MB)
    CDC PLACES ZCTA         ZCTA5 -> chronic disease prevalence       (~180 MB)

OUTPUT
------
    data/raw/zip3_units.csv, the unit table SQL 04 joins to and the territory
    optimiser clusters over.

WHY THIS IS A SEPARATE MODULE
-----------------------------
CMS publishes no coordinates. Without a geography join there is no map, no
travel metric and no territory alignment -- the entire sixth module is dead. It
is one megabyte of reference data standing behind the most screenshot-able
output in the project.

ZCTA -> ZIP3 AGGREGATION
------------------------
A ZIP3 is the first three digits of a ZIP code, so many ZCTAs roll into one
unit. Coordinates are aggregated POPULATION-WEIGHTED, not as a plain mean: a
plain centroid drags the unit toward empty rural ZCTAs and puts the rep's
notional base in a field rather than near the prescribers. Prevalence is
likewise population-weighted, because averaging a 400-person ZCTA equally with a
60,000-person one misstates the market a rep actually works.

ON PLACES AS A PROXY
--------------------
PLACES carries no atrial fibrillation measure -- the actual indication for a
DOAC. Stroke, coronary heart disease and high blood pressure are used as
correlates of anticoagulant demand. That is a proxy, it is stated as one in the
README, and no reader should be left thinking AF prevalence was measured here.
"""
from __future__ import annotations

import argparse
import io
import re
import zipfile
from pathlib import Path

import pandas as pd

from src.config import ROOT
from src.utils.geo import census_region
from src.utils.io import get_logger, record, write_parquet
from src.utils.schema import ZIP3_UNIT_COLUMNS, require_columns

log = get_logger(__name__)

RAW = ROOT / "data" / "raw"

GAZ_PATTERNS = [r"gaz_zcta_national\.(txt|zip)$", r"gazetteer.*zcta.*\.(txt|zip)$"]
PLACES_PATTERNS = [r"places.*zcta.*\.csv$", r"rows\.csv$"]

# PLACES measure prefixes -> the column names the potential model expects.
PREVALENCE_MEASURES = {
    "STROKE": "prev_stroke",
    "CHD": "prev_chd",
    "BPHIGH": "prev_bp",
}


def _find(local_dir: Path, patterns: list[str]) -> Path | None:
    for p in sorted(local_dir.iterdir()):
        if not p.is_file():
            continue
        for pat in patterns:
            if re.search(pat, p.name.lower()):
                return p
    return None


def load_gazetteer(path: Path) -> pd.DataFrame:
    """ZCTA5 -> lat/lon/land area. Handles the .zip or the extracted .txt."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".txt"))
            raw = z.read(name).decode("utf-8", "replace")
    else:
        raw = path.read_text(encoding="utf-8", errors="replace")

    # Gazetteer files are tab-separated with padded headers.
    df = pd.read_csv(io.StringIO(raw), sep="\t", dtype=str)
    df.columns = [c.strip().upper() for c in df.columns]

    zcol = next(c for c in df.columns if c.startswith("GEOID") or "ZCTA" in c)
    latcol = next(c for c in df.columns if c.startswith("INTPTLAT"))
    loncol = next(c for c in df.columns if c.startswith("INTPTLONG") or c.startswith("INTPTLON"))
    areacol = next((c for c in df.columns if c == "ALAND_SQMI"), None)

    out = pd.DataFrame({
        "zcta": df[zcol].str.strip().str.zfill(5),
        "lat": pd.to_numeric(df[latcol], errors="coerce"),
        "lon": pd.to_numeric(df[loncol], errors="coerce"),
        "land_sqmi": pd.to_numeric(df[areacol], errors="coerce") if areacol else pd.NA,
    }).dropna(subset=["lat", "lon"])
    log.info("gazetteer: %d ZCTAs with coordinates", len(out))
    return out


def load_places(path: Path) -> pd.DataFrame:
    """ZCTA5 -> population and crude prevalence for the proxy measures.

    PLACES ships in TWO shapes and CDC hands out both from the same page:

      LONG  one row per ZCTA per measure, with a MeasureId code column
      WIDE  "GIS friendly format", one row per ZCTA, one column per measure

    Both are handled. The long form is actually preferable -- MeasureId gives
    exact codes (STROKE, CHD, BPHIGH) instead of requiring a prefix match
    against 40 free-text measure names, several of which start with the same
    word.
    """
    head = pd.read_csv(path, nrows=5, dtype=str)
    if "MeasureId" in head.columns:
        return _load_places_long(path)

    cols = {c.upper(): c for c in head.columns}
    zcol = next((cols[c] for c in cols if "ZCTA" in c and "NAME" not in c), None)
    if zcol is None:
        raise SystemExit(f"No ZCTA column in {path.name}: {list(head.columns)[:12]}")
    popcol = next((cols[c] for c in cols if c == "TOTALPOPULATION"), None)

    # Prefer crude prevalence: age-adjusted rates deliberately remove the age
    # structure, and age structure is exactly the signal we want for a drug
    # indicated in an elderly population.
    measure_cols: dict[str, str] = {}
    for prefix, target in PREVALENCE_MEASURES.items():
        hit = next((cols[c] for c in cols
                    if c.startswith(prefix) and "CRUDEPREV" in c and "CI" not in c), None)
        if hit is None:
            hit = next((cols[c] for c in cols
                        if c.startswith(prefix) and "PREV" in c and "CI" not in c), None)
        if hit:
            measure_cols[target] = hit
        else:
            log.warning("PLACES: no column found for %s (%s)", target, prefix)

    usecols = [zcol] + ([popcol] if popcol else []) + list(measure_cols.values())
    df = pd.read_csv(path, usecols=usecols, dtype={zcol: str})

    out = pd.DataFrame({"zcta": df[zcol].str.strip().str.zfill(5)})
    out["population"] = pd.to_numeric(df[popcol], errors="coerce") if popcol else 1.0
    for target, src in measure_cols.items():
        out[target] = pd.to_numeric(df[src], errors="coerce")

    log.info("places: %d ZCTAs, measures %s", len(out), sorted(measure_cols))
    return out


def _load_places_long(path: Path) -> pd.DataFrame:
    """Parse the long PLACES release and pivot it to one row per ZCTA."""
    usecols = ["LocationName", "MeasureId", "DataValueTypeID",
               "Data_Value", "TotalPopulation"]
    df = pd.read_csv(path, usecols=usecols, dtype={"LocationName": str})

    wanted = set(PREVALENCE_MEASURES)          # STROKE, CHD, BPHIGH
    df = df[df["MeasureId"].isin(wanted)].copy()

    # Crude, not age-adjusted. Age adjustment deliberately REMOVES the age
    # structure of a population -- and age structure is precisely the signal we
    # want for a drug indicated in the elderly. Using AgeAdjPrv here would strip
    # out the thing that makes the covariate informative.
    crude = df[df["DataValueTypeID"] == "CrdPrv"]
    if crude.empty:
        log.warning("no crude-prevalence rows found; falling back to whatever "
                    "DataValueTypeID is present")
    else:
        df = crude

    df["zcta"] = df["LocationName"].str.strip().str.zfill(5)
    df["Data_Value"] = pd.to_numeric(df["Data_Value"], errors="coerce")

    wide = (df.pivot_table(index="zcta", columns="MeasureId",
                           values="Data_Value", aggfunc="mean")
              .rename(columns=PREVALENCE_MEASURES)
              .reset_index())

    pop = (df.groupby("zcta")["TotalPopulation"]
             .max().rename("population").reset_index())
    out = wide.merge(pop, on="zcta", how="left")

    found = [c for c in PREVALENCE_MEASURES.values() if c in out.columns]
    log.info("places (long format): %d ZCTAs, measures %s", len(out), found)
    missing = set(PREVALENCE_MEASURES.values()) - set(found)
    if missing:
        log.warning("PLACES is missing expected measures: %s", sorted(missing))
    return out


def build_zip3(gaz: pd.DataFrame, places: pd.DataFrame | None) -> pd.DataFrame:
    df = gaz.copy()
    if places is not None:
        df = df.merge(places, on="zcta", how="left")
        matched = df["population"].notna().sum()
        log.info("gazetteer x places: %d of %d ZCTAs matched (%.1f%%)",
                 matched, len(df), 100 * matched / max(len(df), 1))
    else:
        df["population"] = 1.0

    df["zip3"] = df["zcta"].str[:3]
    # Weight of at least 1 so a ZCTA with no population record still counts
    # toward the centroid rather than vanishing from the map.
    df["w"] = df["population"].fillna(0).clip(lower=1.0)

    def wavg(g: pd.DataFrame, col: str) -> float:
        v = g[col]
        m = v.notna()
        if not m.any():
            return float("nan")
        return float((v[m] * g["w"][m]).sum() / g["w"][m].sum())

    rows = []
    for zip3, g in df.groupby("zip3"):
        rec = {
            "zip3": zip3,
            "lat": wavg(g, "lat"),
            "lon": wavg(g, "lon"),
            "population": float(g["population"].fillna(0).sum()),
            "land_sqmi": float(pd.to_numeric(g.get("land_sqmi"), errors="coerce").fillna(0).sum())
            if "land_sqmi" in g else 0.0,
            "n_zctas": len(g),
        }
        for col in PREVALENCE_MEASURES.values():
            rec[col] = wavg(g, col) if col in g else float("nan")
        rows.append(rec)

    out = pd.DataFrame(rows).dropna(subset=["lat", "lon"]).reset_index(drop=True)
    out["pop_density"] = out["population"] / out["land_sqmi"].replace(0, pd.NA)

    # Median-fill missing prevalence rather than dropping the unit: a ZIP3 with
    # no PLACES match still has prescribers who need a rep assigned to them.
    for col in PREVALENCE_MEASURES.values():
        if col in out:
            missing = out[col].isna().sum()
            if missing:
                out[col] = out[col].fillna(out[col].median())
                log.info("  %s: median-filled %d of %d ZIP3s", col, missing, len(out))

    log.info("zip3 units: %d, population %.1fM", len(out), out["population"].sum() / 1e6)
    return out


def attach_state(units: pd.DataFrame) -> pd.DataFrame:
    """Assign each ZIP3 a state and census region from the Part D extract.

    Derived from where the prescribers actually are rather than a static ZIP3
    crosswalk: ZIP3 boundaries straddle state lines, and the modal state among
    real prescribers is the one a rep would actually be managed under.
    """
    frames = []
    for f in sorted(RAW.glob("partd_provider_*.csv")):
        frames.append(pd.read_csv(f, usecols=["Prscrbr_Zip5", "Prscrbr_State_Abrvtn"],
                                  dtype=str))
    if not frames:
        log.warning("no partd_provider files yet; state/region left blank")
        units["state"] = None
        units["region"] = "Unknown"
        return units

    p = pd.concat(frames, ignore_index=True).dropna()
    p["zip3"] = (p["Prscrbr_Zip5"].str.replace(r"[^0-9]", "", regex=True)
                 .str.zfill(5).str[:3])
    modal = (p.groupby(["zip3", "Prscrbr_State_Abrvtn"]).size()
             .reset_index(name="n").sort_values("n", ascending=False)
             .drop_duplicates("zip3")[["zip3", "Prscrbr_State_Abrvtn"]]
             .rename(columns={"Prscrbr_State_Abrvtn": "state"}))

    out = units.merge(modal, on="zip3", how="left")
    out["region"] = out["state"].map(lambda s: census_region(s) if pd.notna(s) else "Unknown")
    log.info("state attached for %d of %d ZIP3s", out["state"].notna().sum(), len(out))
    return out


def run(local_dir: Path) -> pd.DataFrame:
    gaz_path = _find(local_dir, GAZ_PATTERNS)
    if gaz_path is None:
        raise SystemExit(
            f"No Census Gazetteer ZCTA file in {local_dir}.\n"
            f"Download 2024_Gaz_zcta_national.zip from\n"
            f"  https://www2.census.gov/geo/docs/maps-data/data/gazetteer/"
            f"2024_Gazetteer/2024_Gaz_zcta_national.zip\n"
            f"Without coordinates there is no territory module at all.")
    log.info("gazetteer: %s", gaz_path.name)
    gaz = load_gazetteer(gaz_path)

    places_path = _find(local_dir, PLACES_PATTERNS)
    places = None
    if places_path:
        log.info("places: %s", places_path.name)
        places = load_places(places_path)
    else:
        log.warning("No CDC PLACES file found. The potential model will run WITHOUT "
                    "disease-prevalence covariates and will lean much harder on "
                    "practice size -- check the SHAP output against gate G2.")

    units = attach_state(build_zip3(gaz, places))

    # Both ingest paths must produce identical columns here -- SQL 04 joins this
    # table by name and cannot tell which one wrote it. See src/utils/schema.py.
    require_columns(units, ZIP3_UNIT_COLUMNS,
                    produced_by="geo_build.py (real geography)",
                    consumed_by="SQL 04 and src/models/territory.py")

    RAW.mkdir(parents=True, exist_ok=True)
    out_csv = RAW / "zip3_units.csv"
    units.to_csv(out_csv, index=False)
    write_parquet(units, ROOT / "data" / "processed" / "zip3_units.parquet")

    record("geography", zip3_units=len(units),
           gazetteer=gaz_path.name,
           places=places_path.name if places_path else None,
           has_prevalence=bool(places is not None),
           population_total=float(units["population"].sum()))
    log.info("wrote %s", out_csv.name)
    return units


def main() -> None:
    ap = argparse.ArgumentParser(description="Build ZIP3 geography from reference data.")
    ap.add_argument("--local-dir", type=Path, default=ROOT / "dataset")
    run(ap.parse_args().local_dir)


if __name__ == "__main__":
    main()
