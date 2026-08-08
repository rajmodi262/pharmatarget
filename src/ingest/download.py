"""CMS data ingest — resolve, stream, filter.

    python -m src.ingest.download                  # all three years, all sources
    python -m src.ingest.download --years 2024     # one year
    python -m src.ingest.download --resolve-only   # print URLs, download nothing

WHY THIS STREAMS INSTEAD OF DOWNLOADING
---------------------------------------
Naively pulling every source for three years is ~40 GB:

    Part D by Provider and Drug   ~4.1 GB/yr   (25M rows, every drug)
    Part D by Provider            ~0.8 GB/yr
    Open Payments general         ~8.2 GB/yr   (15M rows, every manufacturer)

On a typical connection that is most of a day and it leaves 40 GB on disk to
support a therapeutic class that occupies well under 1% of it.

So each file is consumed as a stream and reduced on the fly. Nothing large is
ever written:

    drug file      keep rows whose Gnrc_Name is in the class, AND accumulate a
                   per-NPI running total of Tot_Clms across ALL rows
    provider file  keep the dozen columns the marts use
    open payments  fetched through the filtered datastore API, not the bulk CSV

THE PER-NPI RUNNING TOTAL IS THE WHOLE TRICK. The suppression reconciliation in
SQL 03 needs Σ(all drug rows) per prescriber to difference against the
provider-level total. Filtering to the class alone would destroy that sum and
the reconciliation would silently measure "drugs I chose not to keep" instead of
"rows CMS suppressed" — the exact bug the synthetic generator was fixed for.
Accumulating the sum while streaming preserves it at no storage cost.

Result: ~14 GB transferred, ~200 MB retained.

Downloads are resumable at file granularity. A completed year is never refetched,
because losing three hours of streaming to a dropped connection is how schedules
slip.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from src.config import ROOT, class_generic_names, params
from src.utils.io import claim_raw_dir, get_logger, record

log = get_logger(__name__)

RAW = ROOT / "data" / "raw"

CMS_CATALOG = "https://data.cms.gov/data.json"
OP_METASTORE = ("https://openpaymentsdata.cms.gov/api/1/metastore/schemas/"
                "dataset/items?show-reference-ids")
OP_DATASTORE = "https://openpaymentsdata.cms.gov/api/1/datastore/query/{dataset}/0"
OP_MFR_FIELD = "applicable_manufacturer_or_applicable_gpo_making_payment_name"

DRUG_TITLE = "Medicare Part D Prescribers - by Provider and Drug"
PROVIDER_TITLE = "Medicare Part D Prescribers - by Provider"

# Columns the marts actually read. Both CMS files carry 20-70 columns; keeping
# only these is what turns a 0.8 GB provider file into a 40 MB one.
DRUG_COLS = ["Prscrbr_NPI", "Prscrbr_Last_Org_Name", "Prscrbr_First_Name",
             "Prscrbr_City", "Prscrbr_State_Abrvtn", "Prscrbr_Type",
             "Brnd_Name", "Gnrc_Name", "Tot_Clms", "Tot_30day_Fills",
             "Tot_Day_Suply", "Tot_Drug_Cst", "Tot_Benes"]

# NOTE ON THE AGE COLUMNS. There is no `Bene_Age_GE_65_Cnt` in the CMS file --
# that column was invented by the synthetic generator, which is why the whole
# pipeline ran green on synthetic data and failed on the first real extract.
# CMS publishes age BANDS (LT_65 / 65_74 / 75_84 / GT_84) plus GE65_Tot_Benes;
# the 65+ count is assembled from the bands in SQL 01.
#
# The lesson is baked into src/ingest/synth.py, which now emits these exact
# names: a generator that invents a schema will validate a pipeline against a
# world that does not exist.
PROVIDER_COLS = ["Prscrbr_NPI", "Prscrbr_Last_Org_Name", "Prscrbr_First_Name",
                 "Prscrbr_City", "Prscrbr_State_Abrvtn", "Prscrbr_Zip5",
                 "Prscrbr_Type", "Prscrbr_RUCA", "Tot_Clms", "Tot_Benes",
                 "Tot_Drug_Cst", "Bene_Avg_Age",
                 "Bene_Age_LT_65_Cnt", "Bene_Age_65_74_Cnt",
                 "Bene_Age_75_84_Cnt", "Bene_Age_GT_84_Cnt",
                 "GE65_Tot_Benes",
                 "Bene_Avg_Risk_Scre"]

UA = {"User-Agent": "PharmaTarget/2.0 (portfolio analytics; CMS public data)"}


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #

def _get_json(url: str, timeout: int = 180):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))


def resolve_partd() -> dict[str, dict[int, str]]:
    """Map dataset -> {data_year: csv_url} from the live DCAT catalog.

    The data year is parsed from the filename (``..._DY24_...``), not from the
    release year in the title. RY26 ships DY24; conflating the two silently
    shifts every year in the analysis by two.
    """
    cat = _get_json(CMS_CATALOG)
    items = cat.get("dataset", [])
    out: dict[str, dict[int, str]] = {"partd_drug": {}, "partd_provider": {}}

    for key, title in (("partd_drug", DRUG_TITLE), ("partd_provider", PROVIDER_TITLE)):
        for d in items:
            if d.get("title", "").strip() != title:
                continue
            for dist in d.get("distribution", []):
                url = dist.get("downloadURL") or ""
                if not url.lower().endswith(".csv"):
                    continue
                m = re.search(r"_dy(\d{2})_", url.lower())
                if m:
                    out[key][2000 + int(m.group(1))] = url
    for key, mapping in out.items():
        log.info("resolved %s: data years %s", key, sorted(mapping))
    return out


def resolve_open_payments() -> dict[int, str]:
    """Map program year -> DATASET id (not distribution id) for General Payments.

    The datastore query endpoint is /datastore/query/{dataset_id}/{index}. Passing
    the distribution identifier instead returns 404, and passing the wrong query
    syntax returns 200 with the FULL UNFILTERED dataset -- see _op_query().
    """
    try:
        items = _get_json(OP_METASTORE)
    except Exception as exc:  # noqa: BLE001
        log.warning("Open Payments metastore unreachable (%s)", exc)
        return {}
    out: dict[int, dict] = {}
    for d in items:
        title = d.get("title", "")
        if "general payment" not in title.lower():
            continue
        m = re.search(r"(20\d\d)", title)
        if not m:
            continue
        dists = d.get("distribution") or []
        csv_url = ""
        for dist in dists:
            csv_url = (dist.get("data") or {}).get("downloadURL", "") or dist.get("downloadURL", "")
            if csv_url:
                break
        out[int(m.group(1))] = {"dataset": d.get("identifier"), "csv": csv_url}
    log.info("resolved open_payments: program years %s", sorted(out))
    return out


def _op_query(dataset_id: str, conditions: list[dict], properties: list[str] | None,
              limit: int, offset: int) -> dict:
    """Query the Open Payments datastore with filters that actually apply.

    THE TRAP: this API accepts several query encodings and only some of them
    filter. Passing ``?query=<json blob>`` returns HTTP 200 with count=14.7M --
    the entire dataset, silently unfiltered. So does ``?filter[field]=value``.
    Either would have produced a file labelled "payments from our manufacturers"
    that actually contained random manufacturers, and nothing downstream would
    have complained.

    The encoding that works is bracketed query parameters:
        conditions[0][property]=... &conditions[0][value]=... &conditions[0][operator]==

    fetch_open_payments_year() asserts the returned rows match the requested
    manufacturer, so a future API change breaks the build instead of quietly
    poisoning the analysis.
    """
    params_: dict[str, str] = {"limit": str(limit), "offset": str(offset)}
    for i, c in enumerate(conditions):
        params_[f"conditions[{i}][property]"] = c["property"]
        params_[f"conditions[{i}][value]"] = c["value"]
        params_[f"conditions[{i}][operator]"] = c.get("operator", "=")
    for i, p in enumerate(properties or []):
        params_[f"properties[{i}]"] = p
    url = (OP_DATASTORE.format(dataset=dataset_id) + "?"
           + urllib.parse.urlencode(params_))
    return _get_json(url, timeout=240)


def discover_manufacturers(dataset_id: str, year: int,
                           needles: list[str] | None = None) -> dict[str, list[str]]:
    """Find the exact manufacturer name strings present in a given program year.

    Legal names drift between years and bear no resemblance to how anyone writes
    them: 'Bristol Myers Squibb Company' (no hyphen), 'PFIZER INC.' (upper case),
    'Janssen Pharmaceuticals, Inc' (no trailing period). Hand-maintaining these
    guarantees silent under-capture -- an exact-match filter on a name that does
    not exist returns zero rows and no error.

    So they are discovered, per year, and written to config/manufacturers.yaml
    rather than guessed.
    """
    needles = needles or ["Bristol", "Squibb", "Pfizer", "Janssen", "Johnson",
                          "Bayer", "Boehringer", "Daiichi"]
    found: dict[str, list[str]] = {}
    for needle in needles:
        try:
            r = _op_query(dataset_id,
                          [{"property": OP_MFR_FIELD, "value": f"%{needle}%",
                            "operator": "LIKE"}],
                          [OP_MFR_FIELD], 400, 0)
        except Exception as exc:  # noqa: BLE001
            log.warning("  discovery failed for '%s': %s", needle, exc)
            continue
        names = sorted({row.get(OP_MFR_FIELD) for row in r.get("results", [])
                        if isinstance(row, dict) and row.get(OP_MFR_FIELD)})
        if names:
            found[needle] = names
            for n in names:
                log.info("  %d  %-12s -> %s", year, needle, n)
    return found


# --------------------------------------------------------------------------- #
# Streaming
# --------------------------------------------------------------------------- #

def _stream_rows(source: str, label: str):
    """Yield csv.DictReader rows from a URL *or* a local path, unbuffered.

    Accepting a local path matters: the bulk files can be fetched far faster by
    a download manager (parallel connections, resume) than by a single Python
    socket. Point --local-dir at whatever you downloaded and the same filtering
    runs against the file on disk -- identical output, no re-download.
    """
    t0 = time.time()
    is_url = source.startswith(("http://", "https://"))

    if is_url:
        handle = urllib.request.urlopen(urllib.request.Request(source, headers=UA),
                                        timeout=300)
        total = handle.headers.get("Content-Length")
        stream = io.TextIOWrapper(handle, encoding="utf-8", errors="replace", newline="")
    else:
        p = Path(source)
        total = str(p.stat().st_size)
        handle = None
        # noqa: SIM115 -- a `with` block cannot span a generator's yields. The
        # handle is closed in the finally below, which also covers the caller
        # abandoning the generator early.
        stream = open(p, encoding="utf-8", errors="replace", newline="")  # noqa: SIM115

    total_gb = int(total) / 1e9 if total else None
    try:
        reader = csv.DictReader(stream)
        seen = 0
        for row in reader:
            seen += 1
            if seen % 1_000_000 == 0:
                log.info("  %s: %.1fM rows, %.0fs elapsed%s",
                         label, seen / 1e6, time.time() - t0,
                         f", ~{total_gb:.1f} GB source" if total_gb else "")
            yield row
        log.info("  %s: %d rows read in %.0fs", label, seen, time.time() - t0)
    finally:
        stream.close()
        if handle is not None:
            handle.close()


# Filename fragments that identify a manually downloaded bulk file.
LOCAL_PATTERNS = {
    "partd_drug": r"mup_dpr_.*_dy(\d{2})_npibn\.csv$",
    "partd_provider": r"mup_dpr_.*_dy(\d{2})_npi\.csv$",
    "open_payments": r"op_dtl_gnrl_pgyr(\d{4})_.*\.csv$",
}


def scan_local(local_dir: Path) -> dict[str, dict[int, str]]:
    """Map manually downloaded bulk files to (dataset, year) by filename.

    Year comes from the filename -- ``_DY24_`` for Part D, ``PGYR2024`` for Open
    Payments. Part D encodes the DATA year, which is two behind the release year
    in the same name (RY26 ships DY24); reading the wrong one silently shifts
    every year in the analysis.
    """
    found: dict[str, dict[int, str]] = {k: {} for k in LOCAL_PATTERNS}
    if not local_dir.exists():
        raise SystemExit(f"--local-dir not found: {local_dir}")

    for p in sorted(local_dir.iterdir()):
        if not p.is_file():
            continue
        name = p.name.lower()
        for key, pattern in LOCAL_PATTERNS.items():
            m = re.search(pattern, name)
            if not m:
                continue
            raw = m.group(1)
            year = int(raw) if len(raw) == 4 else 2000 + int(raw)
            found[key][year] = str(p)
            log.info("local %-16s %d  %s (%.1f GB)", key, year, p.name,
                     p.stat().st_size / 1e9)
            break

    if not any(found.values()):
        log.warning("no recognised bulk files in %s. Expected names like "
                    "MUP_DPR_RY26_P04_V10_DY24_NPIBN.csv or "
                    "OP_DTL_GNRL_PGYR2024_....csv", local_dir)
    return found


def fetch_drug_year(url: str, year: int, force: bool = False) -> dict:
    """Stream one drug-file year: keep class rows, accumulate all-drug totals."""
    class_out = RAW / f"partd_drug_{year}.csv"
    totals_out = RAW / f"npi_alldrug_totals_{year}.csv"
    if class_out.exists() and totals_out.exists() and not force:
        log.info("cached, skipping partd_drug %d", year)
        return {"cached": True}

    class_names = set(class_generic_names())
    totals: dict[str, float] = {}
    kept = 0
    unparseable = 0

    RAW.mkdir(parents=True, exist_ok=True)
    tmp_class = class_out.with_suffix(".part")
    with open(tmp_class, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=DRUG_COLS, extrasaction="ignore")
        writer.writeheader()
        for row in _stream_rows(url, f"partd_drug {year}"):
            npi = row.get("Prscrbr_NPI")
            if not npi:
                continue
            # (1) accumulate across EVERY drug -- this is what makes the
            #     suppression reconciliation possible. Never filter first.
            #
            # Parse failures are COUNTED, not suppressed. Every dropped row
            # understates that prescriber's observed total, which inflates the
            # apparent suppression gap. Silently swallowing these would corrupt
            # the reconciliation in a direction that looks like a finding.
            try:
                totals[npi] = totals.get(npi, 0.0) + float(row.get("Tot_Clms") or 0)
            except (ValueError, TypeError):
                unparseable += 1
            # (2) retain only the therapeutic class
            if (row.get("Gnrc_Name") or "").strip().upper() in class_names:
                writer.writerow(row)
                kept += 1
    tmp_class.replace(class_out)

    with open(totals_out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Prscrbr_NPI", "All_Drug_Tot_Clms_Observed"])
        for npi, tot in totals.items():
            w.writerow([npi, f"{tot:.0f}"])

    log.info("  partd_drug %d: kept %s class rows, %s NPIs with all-drug totals",
             year, f"{kept:,}", f"{len(totals):,}")
    if unparseable:
        log.warning("  partd_drug %d: %s rows had an unparseable Tot_Clms and were "
                    "excluded from the all-drug totals. This inflates the apparent "
                    "suppression gap -- investigate before trusting SQL 03.",
                    year, f"{unparseable:,}")
    stats = {"class_rows": kept, "npis": len(totals),
             "unparseable_tot_clms": unparseable, "source": url}
    record(f"raw_partd_drug_{year}", **stats)
    return stats


def fetch_provider_year(url: str, year: int, force: bool = False) -> dict:
    """Stream one provider-file year, keeping only the columns the marts use."""
    out = RAW / f"partd_provider_{year}.csv"
    if out.exists() and not force:
        log.info("cached, skipping partd_provider %d", year)
        return {"cached": True}

    RAW.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    n = 0
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PROVIDER_COLS, extrasaction="ignore")
        writer.writeheader()
        for row in _stream_rows(url, f"partd_provider {year}"):
            if not row.get("Prscrbr_NPI"):
                continue
            writer.writerow(row)
            n += 1
    tmp.replace(out)
    log.info("  partd_provider %d: %s rows", year, f"{n:,}")
    record(f"raw_partd_provider_{year}", rows=n, source=url)
    return {"rows": n, "source": url}


def fetch_open_payments_year(source: dict, year: int, force: bool = False) -> dict:
    """Stream the General Payments bulk CSV, keeping only our manufacturers.

    WHY STREAM RATHER THAN USE THE FILTERED API
    -------------------------------------------
    The datastore filter works, but it caps ``limit`` at 500 rows per request.
    Pfizer alone has ~515,000 payment records in a single program year, so one
    manufacturer costs 1,030 round trips; the full competitive set across three
    years is roughly 3,000 requests and several hours, with a retry story for
    every one of them.

    The bulk CSV is 8.2 GB but streams at the same rate as the Part D files
    (~7 MB/s measured), so a whole year is ~20 minutes with no pagination state
    to get wrong. Filtering happens here, in one pass, and nothing large is kept.

    The API is still used -- for discover_manufacturers(), where its filtering is
    exactly the right tool and the result sets are tiny.
    """
    from src.config import manufacturers

    out = RAW / f"open_payments_{year}.csv"
    if out.exists() and not force:
        log.info("cached, skipping open_payments %d", year)
        return {"cached": True}

    url = source.get("csv")
    if not url:
        log.warning("no bulk CSV URL resolved for open_payments %d", year)
        return {"rows": 0}

    wanted = {name for names in manufacturers()["parents"].values() for name in names}
    keep_cols = ["Covered_Recipient_NPI", "Covered_Recipient_Type",
                 "Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name",
                 "Nature_of_Payment_or_Transfer_of_Value",
                 "Total_Amount_of_Payment_USDollars", "Program_Year"]

    RAW.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".part")
    kept = 0
    per_name: dict[str, int] = {}

    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=keep_cols, extrasaction="ignore")
        writer.writeheader()
        for row in _stream_rows(url, f"open_payments {year}"):
            mfr = (row.get("Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name")
                   or "").strip()
            if mfr not in wanted:
                continue
            writer.writerow(row)
            kept += 1
            per_name[mfr] = per_name.get(mfr, 0) + 1
    tmp.replace(out)

    for name in sorted(per_name, key=lambda k: -per_name[k]):
        log.info("    %-46s %9s rows", name[:46], f"{per_name[name]:,}")

    missing = sorted(wanted - set(per_name))
    if missing:
        log.warning("  %d configured manufacturer names matched ZERO rows in %d: %s. "
                    "Legal names drift between program years -- rerun with "
                    "--discover-manufacturers and update config/manufacturers.yaml.",
                    len(missing), year, missing[:4])

    log.info("  open_payments %d: kept %s rows from %d of %d configured names",
             year, f"{kept:,}", len(per_name), len(wanted))
    record(f"raw_open_payments_{year}", rows=kept,
           names_matched=len(per_name), names_configured=len(wanted),
           names_with_zero_rows=missing, source=url)
    return {"rows": kept, "matched": len(per_name)}


# --------------------------------------------------------------------------- #

def download(years: list[int] | None = None, force: bool = False,
             skip: tuple[str, ...] = (), local_dir: Path | None = None) -> None:
    years = years or params()["years"]["all"]
    # Refuse to write real files into a directory holding synthetic ones.
    claim_raw_dir("REAL", force)

    local = scan_local(local_dir) if local_dir else {k: {} for k in LOCAL_PATTERNS}

    # Only hit the network for what is not already on disk.
    need_remote = any(
        year not in local[key]
        for key in ("partd_drug", "partd_provider", "open_payments")
        if key not in skip
        for year in years
    )
    partd: dict[str, dict[int, str]] = {"partd_drug": {}, "partd_provider": {}}
    op: dict[int, dict] = {}
    if need_remote:
        log.info("resolving CMS distributions from the live catalog")
        partd = resolve_partd()
        op = resolve_open_payments() if "open_payments" not in skip else {}

    def source_for(key: str, year: int):
        """Local file wins; fall back to the resolved remote URL."""
        if year in local.get(key, {}):
            return local[key][year]
        if key == "open_payments":
            return op.get(year)
        return partd.get(key, {}).get(year)

    for year in years:
        log.info("=" * 70)
        log.info("YEAR %d", year)
        log.info("=" * 70)

        if "partd_provider" not in skip:
            src = source_for("partd_provider", year)
            if src:
                fetch_provider_year(src, year, force)
            else:
                log.warning("no source for partd_provider %d", year)

        if "partd_drug" not in skip:
            src = source_for("partd_drug", year)
            if src:
                fetch_drug_year(src, year, force)
            else:
                log.warning("no source for partd_drug %d", year)

        if "open_payments" not in skip:
            src = source_for("open_payments", year)
            if isinstance(src, str):
                fetch_open_payments_year({"csv": src}, year, force)
            elif isinstance(src, dict):
                fetch_open_payments_year(src, year, force)
            else:
                log.warning("no source for open_payments %d", year)

    record("data_mode", mode="REAL", years=years, source="data.cms.gov",
           note="Streamed and filtered at ingest; see src/ingest/download.py")
    log.info("done. data_mode=REAL")


def main() -> None:
    ap = argparse.ArgumentParser(description="Stream CMS source data into data/raw/.")
    ap.add_argument("--years", type=int, nargs="+", default=None)
    ap.add_argument("--force", action="store_true", help="refetch cached years")
    ap.add_argument("--skip", nargs="*", default=[],
                    choices=["partd_drug", "partd_provider", "open_payments"])
    ap.add_argument("--resolve-only", action="store_true",
                    help="print resolved URLs and exit")
    ap.add_argument("--discover-manufacturers", action="store_true",
                    help="print the exact Open Payments manufacturer strings per year")
    ap.add_argument("--local-dir", type=Path, default=None,
                    help="directory of manually downloaded bulk CSVs; these are "
                         "used instead of re-fetching, matched by filename")
    a = ap.parse_args()

    if a.discover_manufacturers:
        op = resolve_open_payments()
        for year in (a.years or params()["years"]["all"]):
            if year in op:
                log.info("=" * 66)
                log.info("program year %d", year)
                log.info("=" * 66)
                discover_manufacturers(op[year]["dataset"], year)
        return

    if a.resolve_only:
        partd = resolve_partd()
        op = resolve_open_payments()
        for key, mapping in partd.items():
            for y, u in sorted(mapping.items()):
                print(f"{key:16} {y}  {u}")
        for y, d in sorted(op.items()):
            print(f"{'open_payments':16} {y}  {d['csv']}")
        return

    download(a.years, a.force, tuple(a.skip), a.local_dir)


if __name__ == "__main__":
    main()
