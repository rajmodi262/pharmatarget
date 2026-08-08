"""Synthetic CMS-shaped data generator.

WHY THIS EXISTS
---------------
The real inputs are ~6 GB across three years. Nobody cloning this repo will wait
for that before seeing whether the pipeline works. This module emits files with
the *exact* CMS column names and the same structural quirks -- suppression of
sub-11-claim rows, ZIP+4 contamination, partial Open Payments NPI coverage --
so every downstream stage is source-agnostic. `build_marts.py` cannot tell
whether it was handed synthetic or real data.

WHAT IT DOES AND DOES NOT VALIDATE
----------------------------------
Read this before quoting any number produced in synthetic mode.

The generative process below encodes a hypothesis about how the world works:
that prescribers drift toward an achievable frontier at a rate proportional to
their gap from it, and that promotional payments flow *toward* already-high
prescribers while having only a modest true effect. Because that hypothesis is
baked in, running the opportunity model on synthetic data will confirm it. That
is circular by construction.

    Synthetic mode validates THE PIPELINE.
    Only real CMS data validates THE FINDING.

Every figure and every table generated in synthetic mode is stamped
SYNTHETIC in the manifest, and the API reports `data_mode` on /api/meta so the
distinction survives all the way to the UI. Do not put a synthetic number in
your README, your deck, or your mouth.

The reverse-causality structure (payments target high prescribers) is
deliberate: it means the naive OLS in response.py will overstate the effect and
the matched DiD will partially correct it, which is exactly the behaviour the
caveat in the README describes.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from src.config import ROOT, params
from src.utils.geo import STATE_CENTROIDS, census_region
from src.utils.io import claim_raw_dir, get_logger, record

log = get_logger(__name__)

RAW = ROOT / "data" / "raw"

# Prescriber mix for an anticoagulant class. Weights approximate the Part D
# specialty distribution for DOAC writers.
SPECIALTIES: list[tuple[str, float, float, float]] = [
    # (Prscrbr_Type, share of universe, panel-size multiplier, class-propensity)
    ("Cardiology", 0.13, 1.35, 2.60),
    ("Internal Medicine", 0.26, 1.10, 1.00),
    ("Family Practice", 0.22, 1.00, 0.70),
    ("Nurse Practitioner", 0.14, 0.80, 0.62),
    ("Physician Assistant", 0.08, 0.72, 0.55),
    ("Cardiac Electrophysiology", 0.03, 1.05, 4.10),
    ("Hematology/Oncology", 0.04, 0.85, 1.55),
    ("Nephrology", 0.03, 0.95, 1.30),
    ("Neurology", 0.04, 0.90, 1.15),
    ("Geriatric Medicine", 0.03, 0.88, 1.70),
]

DRUGS: list[tuple[str, str, float]] = [
    # (Brnd_Name, Gnrc_Name, baseline within-class preference weight)
    ("ELIQUIS", "APIXABAN", 0.42),
    ("XARELTO", "RIVAROXABAN", 0.24),
    ("PRADAXA", "DABIGATRAN ETEXILATE MESYLATE", 0.05),
    ("SAVAYSA", "EDOXABAN TOSYLATE", 0.02),
    ("COUMADIN", "WARFARIN SODIUM", 0.05),
    ("JANTOVEN", "WARFARIN SODIUM", 0.22),
]

# Out-of-class drugs. These MUST be emitted: the real Part D drug file contains
# every drug a prescriber wrote, and the suppression reconciliation in SQL 03
# works by differencing provider-level totals against the sum of drug rows. If
# the drug file held only the therapeutic class, that difference would measure
# "drugs I chose not to generate" rather than "rows CMS suppressed", and the
# reconciliation would report ~95% hidden volume -- which is a bug, not a finding.
OTHER_DRUGS: list[tuple[str, str, float, float]] = [
    # (Brnd_Name, Gnrc_Name, share of out-of-class volume, cost per 30-day fill)
    ("ATORVASTATIN CALCIUM", "ATORVASTATIN CALCIUM", 0.16, 11.0),
    ("LISINOPRIL", "LISINOPRIL", 0.13, 6.5),
    ("METFORMIN HCL", "METFORMIN HCL", 0.12, 8.0),
    ("LEVOTHYROXINE SODIUM", "LEVOTHYROXINE SODIUM", 0.11, 12.0),
    ("AMLODIPINE BESYLATE", "AMLODIPINE BESYLATE", 0.10, 7.0),
    ("OMEPRAZOLE", "OMEPRAZOLE", 0.09, 9.5),
    ("METOPROLOL SUCCINATE", "METOPROLOL SUCCINATE", 0.09, 14.0),
    ("GABAPENTIN", "GABAPENTIN", 0.08, 13.0),
    ("LOSARTAN POTASSIUM", "LOSARTAN POTASSIUM", 0.07, 8.5),
    ("FUROSEMIDE", "FUROSEMIDE", 0.05, 5.5),
]

# Cost per 30-day fill, used only to populate Tot_Drug_Cst realistically.
DRUG_COST = {
    "ELIQUIS": 560.0, "XARELTO": 545.0, "PRADAXA": 520.0,
    "SAVAYSA": 430.0, "COUMADIN": 45.0, "JANTOVEN": 12.0,
}

MANUFACTURERS = [
    ("Bristol-Myers Squibb Company", "ELIQUIS"),
    ("Pfizer Inc.", "ELIQUIS"),
    ("Janssen Pharmaceuticals, Inc.", "XARELTO"),
    ("Bayer HealthCare Pharmaceuticals Inc.", "XARELTO"),
    ("Boehringer Ingelheim Pharmaceuticals, Inc.", "PRADAXA"),
    ("Daiichi Sankyo, Inc.", "SAVAYSA"),
]

NATURES = [
    ("Food and Beverage", 0.74, 22.0),
    ("Travel and Lodging", 0.09, 640.0),
    ("Consulting Fee", 0.06, 2400.0),
    ("Compensation for services other than consulting", 0.07, 1750.0),
    ("Education", 0.04, 130.0),
]

_SURNAMES = ["SMITH", "JOHNSON", "WILLIAMS", "BROWN", "JONES", "GARCIA", "MILLER", "DAVIS", "RODRIGUEZ", "MARTINEZ", "HERNANDEZ", "LOPEZ", "GONZALEZ", "WILSON", "ANDERSON", "THOMAS", "TAYLOR", "MOORE", "JACKSON", "MARTIN", "LEE", "PEREZ", "THOMPSON", "WHITE", "HARRIS", "SANCHEZ", "CLARK", "RAMIREZ", "LEWIS", "ROBINSON", "WALKER", "YOUNG", "ALLEN", "KING", "WRIGHT", "SCOTT", "TORRES", "NGUYEN", "HILL", "FLORES", "GREEN", "ADAMS", "NELSON", "BAKER", "HALL", "RIVERA", "CAMPBELL", "MITCHELL", "CARTER", "ROBERTS", "PATEL", "SHAH", "KIM", "CHEN"]
_FIRSTNAMES = ["JAMES", "MARY", "ROBERT", "PATRICIA", "JOHN", "JENNIFER", "MICHAEL", "LINDA", "DAVID", "ELIZABETH", "WILLIAM", "BARBARA", "RICHARD", "SUSAN", "JOSEPH", "JESSICA", "THOMAS", "SARAH", "CHARLES", "KAREN", "PRIYA", "ARJUN", "WEI", "MEI", "RAJESH", "ANITA", "DANIEL", "NANCY", "MATTHEW", "LISA", "ANTHONY", "BETTY"]


def _make_zip3_units(rng: np.random.Generator, n_units: int) -> pd.DataFrame:
    """ZIP3 geographic units with market-potential covariates.

    Disease prevalence is spatially correlated with the 65+ share, which is what
    makes the potential model's prevalence features carry real information
    rather than noise.
    """
    states = [s for s in STATE_CENTROIDS if s not in ("AK", "HI")]
    weights = np.array([1.0 + 2.0 * rng.random() for _ in states])
    weights /= weights.sum()
    picks = rng.choice(len(states), size=n_units, p=weights)

    rows = []
    for i, si in enumerate(picks):
        st = states[si]
        lat0, lon0 = STATE_CENTROIDS[st]
        lat = lat0 + rng.normal(0, 1.15)
        lon = lon0 + rng.normal(0, 1.45)
        pct_65 = float(np.clip(rng.beta(4.2, 20.0) + 0.06, 0.06, 0.44))
        # Prevalence rises with age structure plus a local idiosyncratic term.
        base = 0.55 * pct_65 + 0.45 * rng.beta(3.0, 9.0)
        rows.append({
            "zip3": f"{(i * 7 + 100) % 900 + 100:03d}",
            "state": st,
            "region": census_region(st),
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "pop_65_plus": int(rng.lognormal(9.6, 0.85)),
            "pct_65_plus": round(pct_65, 4),
            "prev_stroke": round(float(np.clip(base * 12.0 + rng.normal(0, 0.35), 1.0, 9.5)), 3),
            "prev_chd": round(float(np.clip(base * 18.0 + rng.normal(0, 0.55), 2.0, 15.0)), 3),
            "prev_bp": round(float(np.clip(base * 95.0 + rng.normal(0, 3.0), 22.0, 62.0)), 3),
        })
    df = pd.DataFrame(rows).drop_duplicates(subset="zip3").reset_index(drop=True)
    return df


def _make_prescribers(rng: np.random.Generator, n: int, units: pd.DataFrame) -> pd.DataFrame:
    spec_names = [s[0] for s in SPECIALTIES]
    spec_p = np.array([s[1] for s in SPECIALTIES])
    spec_p = spec_p / spec_p.sum()
    spec_idx = rng.choice(len(SPECIALTIES), size=n, p=spec_p)

    unit_pick = rng.choice(len(units), size=n, p=_unit_weights(units))
    u = units.iloc[unit_pick].reset_index(drop=True)

    panel_mult = np.array([SPECIALTIES[i][2] for i in spec_idx])
    panel = np.clip(rng.lognormal(4.85, 0.78, size=n) * panel_mult, 11, None)

    df = pd.DataFrame({
        "npi": (1_400_000_000 + rng.choice(90_000_000, size=n, replace=False)).astype("int64"),
        "last_name": rng.choice(_SURNAMES, size=n),
        "first_name": rng.choice(_FIRSTNAMES, size=n),
        "specialty": [spec_names[i] for i in spec_idx],
        "class_propensity": np.array([SPECIALTIES[i][3] for i in spec_idx]),
        "state": u["state"],
        "zip3": u["zip3"],
        "lat": u["lat"],
        "lon": u["lon"],
        "pct_65_plus": u["pct_65_plus"],
        "prev_stroke": u["prev_stroke"],
        "prev_chd": u["prev_chd"],
        "prev_bp": u["prev_bp"],
        "panel_benes": panel.round().astype(int),
        "risk_score": np.clip(rng.normal(1.42, 0.34, size=n) + u["pct_65_plus"] * 0.8, 0.5, 4.2).round(3),
    })
    df["city"] = ["CITY-" + z for z in df["zip3"]]
    # ZIP+4 contamination on a slice of rows, mirroring the real files.
    plus4 = rng.random(n) < 0.18
    df["zip"] = np.where(plus4, df["zip3"] + "01-" + rng.integers(1000, 9999, n).astype(str), df["zip3"] + "01")
    return df


def _unit_weights(units: pd.DataFrame) -> np.ndarray:
    w = units["pop_65_plus"].to_numpy(dtype=float)
    return w / w.sum()


def _simulate_panel(rng: np.random.Generator, pres: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    """The generative core. See the module docstring on circularity.

    Latent frontier -> observed volume via a heterogeneous efficiency term.
    Brand share mean-reverts toward an achievable ceiling at a rate proportional
    to the gap. That mean reversion is the signal the opportunity model is
    designed to detect, and it is a HYPOTHESIS, not a fact established here.
    """
    n = len(pres)

    # --- latent market potential (never observed by the model) ---------------
    log_potential = (
        1.05
        + 0.62 * np.log(pres["panel_benes"].to_numpy())
        + 0.55 * np.log(pres["class_propensity"].to_numpy())
        + 0.30 * pres["risk_score"].to_numpy()
        + 0.075 * pres["prev_stroke"].to_numpy()
        + 0.020 * pres["prev_chd"].to_numpy()
        + rng.normal(0, 0.42, size=n)          # irreducible market noise
    )
    potential = np.exp(log_potential)

    # Efficiency: how much of their own potential a prescriber currently works.
    efficiency = np.clip(rng.beta(5.2, 3.1, size=n), 0.05, 0.99)

    # Achievable brand share ceiling, and where each prescriber starts.
    ceiling = np.clip(rng.beta(6.0, 3.4, size=n), 0.10, 0.94)
    share = np.clip(ceiling * rng.beta(2.0, 2.6, size=n), 0.0, 0.98)

    # Payment propensity rises with volume -> reverse causality, on purpose.
    vol0 = potential * efficiency
    pay_logit = -3.05 + 1.02 * (np.log1p(vol0) - np.log1p(vol0).mean()) / np.log1p(vol0).std()
    pay_prob = 1.0 / (1.0 + np.exp(-pay_logit))

    # How much out-of-class Part D volume each prescriber writes, as a multiple
    # of their class volume. Stable across years (a prescriber's practice mix
    # does not lurch year to year) so the reconciliation is well behaved.
    other_mult = rng.uniform(6.0, 26.0, size=n)

    frames = []
    payment_rows = []
    ever_paid = np.zeros(n, dtype=bool)

    for yi, year in enumerate(years):
        # Class volume drifts up modestly; efficiency creeps toward the frontier.
        efficiency = np.clip(efficiency + 0.045 * (1.0 - efficiency) + rng.normal(0, 0.035, n), 0.03, 1.0)
        class_vol = potential * efficiency * (1.0 + 0.035 * yi) * np.exp(rng.normal(0, 0.10, n))

        # Payments for this year.
        paid_now = rng.random(n) < pay_prob
        ever_paid |= paid_now
        for idx in np.flatnonzero(paid_now):
            n_pay = 1 + rng.poisson(2.6)
            for _ in range(n_pay):
                mfr, _brand = MANUFACTURERS[rng.integers(len(MANUFACTURERS))]
                nat_i = rng.choice(len(NATURES), p=[x[1] for x in NATURES])
                nature, _p, scale = NATURES[nat_i]
                payment_rows.append((
                    int(pres["npi"].iat[idx]), mfr, nature,
                    round(float(rng.exponential(scale) + 8.0), 2), year,
                ))

        # --- brand share dynamics -------------------------------------------
        # Mean reversion toward the ceiling (the hypothesis under test) plus a
        # small genuine promotional effect. The promotional effect is small
        # relative to the selection effect, which is the whole point.
        gap = ceiling - share
        promo_lift = 0.028 * paid_now.astype(float)
        share = np.clip(share + 0.30 * gap + promo_lift + rng.normal(0, 0.030, n), 0.0, 0.985)

        frames.append(pd.DataFrame({
            "npi": pres["npi"].to_numpy(),
            "year": year,
            "class_fills": class_vol,
            "brand_share": share.copy(),
            "other_fills": class_vol * other_mult * np.exp(rng.normal(0, 0.08, n)),
        }))

    panel = pd.concat(frames, ignore_index=True)
    payments = pd.DataFrame(payment_rows, columns=["npi", "manufacturer", "nature", "amount", "year"])
    return panel, payments


def _explode_to_drug_rows(
    rng: np.random.Generator, panel: pd.DataFrame, pres: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Turn NPI-year volume into CMS drug-level rows, then suppress.

    Returns (published_rows, true_totals). ``true_totals`` holds each
    prescriber-year's real all-drug claim count BEFORE suppression -- that is
    what the provider-level file reports, and differencing it against the
    published rows is precisely the reconciliation SQL 03 performs.
    """
    meta = pres.set_index("npi")[["last_name", "first_name", "city", "state", "specialty"]]
    non_focus = [d for d in DRUGS if d[0] != "ELIQUIS"]
    nf_w = np.array([d[2] for d in non_focus])
    nf_w = nf_w / nf_w.sum()
    other_w = np.array([d[2] for d in OTHER_DRUGS])
    other_w = other_w / other_w.sum()
    cost = dict(DRUG_COST)
    cost.update({d[0]: d[3] for d in OTHER_DRUGS})

    out = []
    for row in panel.itertuples(index=False):
        alloc: list[tuple[str, str, float]] = []

        # --- in-class allocation --------------------------------------------
        total = float(row.class_fills)
        if total >= 1:
            focus = total * float(row.brand_share)
            rest = total - focus
            alloc.append(("ELIQUIS", "APIXABAN", focus))
            # Dirichlet split so the competitive mix varies by prescriber
            # rather than sitting at a constant ratio for everyone.
            if rest > 0:
                shares = rng.dirichlet(nf_w * 8.0)
                for (brnd, gnrc, _w), s in zip(non_focus, shares, strict=True):
                    alloc.append((brnd, gnrc, rest * s))

        # --- out-of-class allocation ----------------------------------------
        other_total = float(row.other_fills)
        if other_total >= 1:
            shares = rng.dirichlet(other_w * 12.0)
            for (brnd, gnrc, _w, _c), s in zip(OTHER_DRUGS, shares, strict=True):
                alloc.append((brnd, gnrc, other_total * s))

        for brnd, gnrc, fills in alloc:
            f30 = int(round(fills))
            if f30 < 1:
                continue
            clms = max(1, int(round(f30 * rng.uniform(0.80, 1.05))))
            out.append((
                int(row.npi), brnd, gnrc, clms, f30,
                round(f30 * 30 * rng.uniform(0.92, 1.08)),
                round(f30 * cost[brnd] * rng.uniform(0.88, 1.12), 2),
                max(1, int(f30 * rng.uniform(0.28, 0.55))),
                int(row.year),
            ))

    df = pd.DataFrame(out, columns=[
        "npi", "Brnd_Name", "Gnrc_Name", "Tot_Clms", "Tot_30day_Fills",
        "Tot_Day_Suply", "Tot_Drug_Cst", "Tot_Benes", "year",
    ])

    # True provider-level totals, computed before anything is removed.
    true_totals = (df.groupby(["npi", "year"], as_index=False)["Tot_Clms"]
                     .sum().rename(columns={"Tot_Clms": "true_all_clms"}))

    df = df.join(meta, on="npi")

    # --- SUPPRESSION ---------------------------------------------------------
    # CMS removes NPI x drug rows with fewer than 11 claims from the file.
    # They are ABSENT, not blank. This single line is why src/sql/03 exists.
    threshold = int(params()["suppression"]["threshold"])
    before = len(df)
    df = df[df["Tot_Clms"] >= threshold].copy()
    hidden = out and (before - len(df))
    log.info("suppression: dropped %d of %d drug rows (<%d claims) -- %.1f%% of rows, "
             "%.1f%% of claim volume",
             hidden, before, threshold, 100 * hidden / max(before, 1),
             100 * (true_totals["true_all_clms"].sum() - df["Tot_Clms"].sum())
             / max(true_totals["true_all_clms"].sum(), 1))

    df = df.rename(columns={
        "npi": "Prscrbr_NPI",
        "last_name": "Prscrbr_Last_Org_Name",
        "first_name": "Prscrbr_First_Name",
        "city": "Prscrbr_City",
        "state": "Prscrbr_State_Abrvtn",
        "specialty": "Prscrbr_Type",
    })
    return df, true_totals


def generate(n_prescribers: int = 40_000, n_units: int = 620, seed: int = 42,
             force: bool = False) -> None:
    rng = np.random.default_rng(seed)
    yrs = list(params()["years"]["all"])
    RAW.mkdir(parents=True, exist_ok=True)
    # Refuse to scribble synthetic files over a real CMS extract.
    claim_raw_dir("SYNTHETIC", force)

    log.info("generating %d prescribers across %d ZIP3 units, years %s", n_prescribers, n_units, yrs)

    units = _make_zip3_units(rng, n_units)
    pres = _make_prescribers(rng, n_prescribers, units)
    panel, payments = _simulate_panel(rng, pres, yrs)
    drug_rows, true_totals = _explode_to_drug_rows(rng, panel, pres)

    # --- D1: Part D by Provider and Drug ------------------------------------
    for year in yrs:
        sub = drug_rows[drug_rows["year"] == year].drop(columns="year")
        sub.to_csv(RAW / f"partd_drug_{year}.csv", index=False)
        log.info("  partd_drug_%d.csv         %8d rows", year, len(sub))

    # --- D2: Part D by Provider ---------------------------------------------
    # Provider totals are the TRUE all-drug claim counts, unaffected by the row
    # suppression applied to D1. That asymmetry is real -- it is what makes the
    # reconciliation in SQL 03 possible on the actual CMS files.
    # Age-band shares per prescriber: [under 65, 65-74, 75-84, 85+]. Dirichlet
    # so each prescriber's panel has its own age structure rather than every
    # panel looking identical.
    ge65_split = rng.dirichlet([2.0, 5.0, 3.5, 1.5], size=len(pres))

    for year in yrs:
        tt = true_totals[true_totals["year"] == year].set_index("npi")["true_all_clms"]
        prov = pd.DataFrame({
            "Prscrbr_NPI": pres["npi"],
            "Prscrbr_Last_Org_Name": pres["last_name"],
            "Prscrbr_First_Name": pres["first_name"],
            "Prscrbr_City": pres["city"],
            "Prscrbr_State_Abrvtn": pres["state"],
            "Prscrbr_zip5": pres["zip"],
            "Prscrbr_Type": pres["specialty"],
            "Tot_Clms": pres["npi"].map(tt).fillna(0).round().astype(int),
            "Tot_Benes": pres["panel_benes"],
            "Bene_Avg_Risk_Scre": pres["risk_score"],
            # CMS publishes age BANDS, not a 65+ total.
            #
            # An earlier version of this generator emitted an invented
            # `Bene_Age_GE_65_Cnt` column. The entire pipeline ran green on
            # synthetic data and then failed on the first real CMS extract,
            # because that column does not exist. A generator that invents a
            # schema validates the pipeline against a world that is not there.
            # These are the real column names -- keep them that way.
            "Bene_Age_LT_65_Cnt": (pres["panel_benes"] * ge65_split[:, 0]).round().astype(int),
            "Bene_Age_65_74_Cnt": (pres["panel_benes"] * ge65_split[:, 1]).round().astype(int),
            "Bene_Age_75_84_Cnt": (pres["panel_benes"] * ge65_split[:, 2]).round().astype(int),
            "Bene_Age_GT_84_Cnt": (pres["panel_benes"] * ge65_split[:, 3]).round().astype(int),
            "GE65_Tot_Benes": (pres["panel_benes"] * ge65_split[:, 1:].sum(axis=1)).round().astype(int),
            "Bene_Avg_Age": (68 + 12 * ge65_split[:, 1:].sum(axis=1)).round(1),
            "Prscrbr_RUCA": rng.choice([1.0, 2.0, 4.0, 7.0, 10.0], size=len(pres)),
            "Tot_Drug_Cst": (pres["npi"].map(tt).fillna(0) * rng.uniform(40, 90, len(pres))).round(2),
        })
        prov.to_csv(RAW / f"partd_provider_{year}.csv", index=False)
        log.info("  partd_provider_%d.csv     %8d rows", year, len(prov))

    # --- D3: Open Payments --------------------------------------------------
    # NPI is blanked on a slice of rows so the measured match rate downstream is
    # a real measurement rather than 100% by construction.
    pay = payments.copy()
    blank = rng.random(len(pay)) < 0.14
    pay["Covered_Recipient_NPI"] = np.where(blank, "", pay["npi"].astype(str))
    op = pd.DataFrame({
        "Covered_Recipient_NPI": pay["Covered_Recipient_NPI"],
        "Covered_Recipient_Type": "Covered Recipient Physician",
        "Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name": pay["manufacturer"],
        "Nature_of_Payment_or_Transfer_of_Value": pay["nature"],
        "Total_Amount_of_Payment_USDollars": pay["amount"],
        "Program_Year": pay["year"],
    })
    for year in yrs:
        sub = op[op["Program_Year"] == year]
        sub.to_csv(RAW / f"open_payments_{year}.csv", index=False)
        log.info("  open_payments_%d.csv      %8d rows", year, len(sub))

    # --- D4/D5/D6: geography + market covariates ----------------------------
    units.to_csv(RAW / "zip3_units.csv", index=False)
    log.info("  zip3_units.csv           %8d rows", len(units))

    record("data_mode", mode="SYNTHETIC", seed=seed,
           n_prescribers=n_prescribers, n_units=n_units, years=yrs,
           warning="Synthetic data validates the pipeline, not the finding. "
                   "Do not quote numbers produced in this mode.")
    log.info("done. data_mode=SYNTHETIC recorded in manifest.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate CMS-shaped synthetic data.")
    ap.add_argument("--n", type=int, default=40_000, help="number of prescribers")
    ap.add_argument("--units", type=int, default=620, help="number of ZIP3 units")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--sample", action="store_true", help="small run: 8k prescribers, 220 units")
    a = ap.parse_args()
    if a.sample:
        generate(8_000, 220, a.seed)
    else:
        generate(a.n, a.units, a.seed)


if __name__ == "__main__":
    main()
