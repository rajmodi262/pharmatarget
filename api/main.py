"""PharmaTarget API.

Nine endpoints. Everything reads from parquet through one DuckDB connection
opened at startup; nothing is recomputed per request.

    uvicorn api.main:app --reload

Interactive docs at /docs. The static dashboard is served at / when
web/dist exists (built React app) or web/static (no-build fallback).
"""
from __future__ import annotations

import csv
import io

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from api import db
from src.config import ROOT, economics, params
from src.utils.io import get_logger, manifest

log = get_logger("api")

app = FastAPI(
    title="PharmaTarget API",
    description=(
        "HCP targeting and territory alignment engine for a branded DOAC. "
        "Every endpoint reads pre-computed parquet -- no model runs at request time."
    ),
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000",
                   "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

SORTABLE = {
    "opportunity", "class_fills", "brand_fills", "brand_share", "calls_per_month",
    "opportunity_decile", "volume_decile", "potential_class", "npi",
}


@app.on_event("startup")
def _startup() -> None:
    db.connect()
    mode = db.data_mode()
    log.info("API ready. data_mode=%s", mode)
    if mode == "SYNTHETIC":
        log.warning("Serving SYNTHETIC data. /api/meta reports this and the UI shows a "
                    "banner. Numbers here validate the pipeline, not the finding.")


def _require(view: str) -> None:
    if not db.has_view(view):
        raise HTTPException(
            status_code=503,
            detail=f"'{view}' is not available. Run `make data` to build the pipeline "
                   f"outputs. This endpoint returns 503 rather than fabricating a shape.",
        )


# --------------------------------------------------------------------------- #
# 1. summary
# --------------------------------------------------------------------------- #
@app.get("/api/summary", tags=["overview"])
def summary() -> dict:
    """KPI block plus the three headline numbers, each labelled by evidence class."""
    m = manifest()
    h2, h3 = m.get("headline_h2", {}), m.get("headline_h3", {})
    terr, g3 = m.get("territory_headline", {}), m.get("gate_g3", {})
    h2h = m.get("backtest_head_to_head", {})
    plan, dis = m.get("call_plan", {}), m.get("disagreement", {})

    return {
        "data_mode": db.data_mode(),
        "kpis": {
            "hcps_analysed": plan.get("n_universe"),
            "hcps_in_market": plan.get("n_in_market"),
            "hcps_targeted": plan.get("n_targets"),
            # Share of the ADDRESSABLE market served, not of the whole Part D
            # file: 1.38M prescribers appear in Part D but only ~267k write
            # anticoagulants, and "3.1% of the market we sell into" is the
            # meaningful figure where "0.6% of all Part D prescribers" is not.
            "pct_targeted": plan.get("pct_of_market_served"),
            "monthly_calls": plan.get("monthly_calls"),
            "implied_reps": plan.get("implied_reps"),
            "current_reps": plan.get("current_reps"),
        },
        "headlines": {
            "h1": {
                "class": "BACK-TESTED",
                "claim": "Opportunity ranking beats volume ranking on volume-neutral "
                         "share growth in a held-out year.",
                "share_growth_ratio": g3.get("share_growth_ratio"),
                "absolute_growth_ratio": g3.get("absolute_growth_ratio"),
                "decile_spearman": g3.get("decile_spearman"),
                "gate_passed": g3.get("passed"),
                "caveat": g3.get("note"),
                "opportunity_pct_of_share_growth": h2h.get("opportunity_pct_of_share_growth"),
                "volume_pct_of_share_growth": h2h.get("volume_pct_of_share_growth"),
            },
            "h2": {
                "class": "ARITHMETIC",
                "claim": "At an identical call budget, opportunity-weighted allocation "
                         "reaches more addressable opportunity than either alternative.",
                "opportunity_reach": h2.get("opportunity_pct_opportunity"),
                "volume_reach": h2.get("volume_pct_opportunity"),
                "geography_reach": h2.get("geography_pct_opportunity"),
                "n_reps": h2.get("n_reps"),
                "hcps_reachable": h2.get("hcps_reachable"),
            },
            "h3": {
                "class": "SCENARIO",
                "claim": "Marginal-rep economics imply the force is under-sized.",
                "current_n_reps": h3.get("current_n_reps"),
                "break_even_n_reps": h3.get("break_even_n_reps"),
                "rep_gap": h3.get("rep_gap"),
                "marginal_roi_at_current": h3.get("marginal_roi_at_current"),
                "incremental_profit": h3.get("incremental_profit"),
                "sensitivity_range": [h3.get("sensitivity_low"), h3.get("sensitivity_high")],
                "caveat": h3.get("label"),
            },
        },
        "disagreement": dis,
        "territory": terr,
    }


# --------------------------------------------------------------------------- #
# 2. hcps (list)
# --------------------------------------------------------------------------- #
@app.get("/api/hcps", tags=["targets"])
def list_hcps(
    state: str | None = None,
    specialty: str | None = None,
    segment: str | None = None,
    decile_min: int = Query(1, ge=1, le=10),
    decile_max: int = Query(10, ge=1, le=10),
    targets_only: bool = False,
    q: str | None = Query(None, description="name or NPI prefix"),
    sort: str = Query("opportunity"),
    desc: bool = True,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    """Filtered, sorted, paginated prescriber list. All work happens in SQL."""
    _require("hcps")
    if sort not in SORTABLE:
        raise HTTPException(400, f"sort must be one of {sorted(SORTABLE)}")

    where, args = ["opportunity_decile BETWEEN ? AND ?"], [decile_min, decile_max]
    if state:
        where.append("state = ?")
        args.append(state.upper())
    if specialty:
        where.append("specialty_group = ?")
        args.append(specialty)
    if targets_only:
        where.append("is_target")
    if q:
        where.append("(CAST(npi AS VARCHAR) LIKE ? OR last_name LIKE ?)")
        args += [f"{q}%", f"{q.upper()}%"]

    clause = " AND ".join(where)
    total = db.query_one(f"SELECT count(*) AS n FROM hcps WHERE {clause}", args)["n"]

    direction = "DESC" if desc else "ASC"
    rows = db.query(
        f"""SELECT npi, last_name, first_name, city, state, specialty, specialty_group,
                   zip3, class_fills, brand_fills, brand_share, potential_class,
                   potential_brand, opportunity, opportunity_decile, volume_decile,
                   decile_shift, calls_per_month, is_target, achievable_share
            FROM hcps WHERE {clause}
            ORDER BY {sort} {direction} NULLS LAST, npi
            LIMIT ? OFFSET ?""",
        args + [page_size, (page - 1) * page_size],
    )
    return {"total": total, "page": page, "page_size": page_size,
            "pages": max((total + page_size - 1) // page_size, 1), "rows": rows}


# --------------------------------------------------------------------------- #
# 3. hcp detail
# --------------------------------------------------------------------------- #
@app.get("/api/hcps/{npi}", tags=["targets"])
def hcp_detail(npi: int) -> dict:
    _require("hcps")
    row = db.query_one("SELECT * FROM hcps WHERE npi = ?", [npi])
    if not row:
        raise HTTPException(404, f"NPI {npi} not found")

    trend = db.query(
        """SELECT year, class_fills, brand_fills, brand_share, class_growth_yoy
           FROM hcp_metrics WHERE npi = ? ORDER BY year""", [npi]
    ) if db.has_view("hcp_metrics") else []

    pay = db.query(
        """SELECT year, pay_total, pay_count, n_manufacturers, pay_focus, pay_competitor
           FROM payments WHERE npi = ? ORDER BY year""", [npi]
    ) if db.has_view("payments") else []

    seg = db.query_one("SELECT segment FROM hcp_segments WHERE npi = ?", [npi]) \
        if db.has_view("hcp_segments") else None

    return {"hcp": row, "trend": trend, "payments": pay,
            "segment": (seg or {}).get("segment")}


# --------------------------------------------------------------------------- #
# 4. export
# --------------------------------------------------------------------------- #
@app.get("/api/hcps/export/csv", tags=["targets"])
def export_hcps(state: str | None = None, decile_min: int = 1, decile_max: int = 10,
                targets_only: bool = False, limit: int = Query(50_000, le=200_000)):
    """Streaming CSV of the current filter set."""
    _require("hcps")
    where, args = ["opportunity_decile BETWEEN ? AND ?"], [decile_min, decile_max]
    if state:
        where.append("state = ?")
        args.append(state.upper())
    if targets_only:
        where.append("is_target")

    rows = db.query(
        f"""SELECT npi, last_name, first_name, city, state, specialty_group,
                   class_fills, brand_fills, brand_share, opportunity,
                   opportunity_decile, volume_decile, calls_per_month
            FROM hcps WHERE {" AND ".join(where)}
            ORDER BY opportunity DESC LIMIT ?""", args + [limit])

    def gen():
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()) if rows else ["npi"])
        w.writeheader()
        yield buf.getvalue()
        for r in rows:
            buf.seek(0), buf.truncate(0)
            w.writerow(r)
            yield buf.getvalue()

    return StreamingResponse(
        gen(), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=pharmatarget_targets.csv"})


# --------------------------------------------------------------------------- #
# 5-9. analytics endpoints
# --------------------------------------------------------------------------- #
@app.get("/api/callplan", tags=["analytics"])
def callplan() -> dict:
    _require("call_plan_matrix")
    return {
        "matrix": db.query("SELECT * FROM call_plan_matrix"),
        "reach_curve": db.query("SELECT * FROM reach_curve ORDER BY rule, hcps_called")
        if db.has_view("reach_curve") else [],
        "disagreement_matrix": db.query("SELECT * FROM disagreement_matrix")
        if db.has_view("disagreement_matrix") else [],
        "summary": manifest().get("call_plan", {}),
    }


@app.get("/api/backtest", tags=["analytics"])
def backtest() -> dict:
    _require("backtest_lift")
    m = manifest()
    return {
        "decile_lift": db.query("SELECT * FROM backtest_lift ORDER BY rule, decile"),
        "head_to_head": m.get("backtest_head_to_head", {}),
        "matched": m.get("backtest_matched", {}),
        "gate": m.get("gate_g3", {}),
        "misses": db.query("SELECT * FROM backtest_misses LIMIT 50")
        if db.has_view("backtest_misses") else [],
        "miss_diagnosis": m.get("backtest_misses", {}),
    }


@app.get("/api/sizing", tags=["analytics"])
def sizing() -> dict:
    _require("roi_curve")
    return {
        "roi_curve": db.query("SELECT * FROM roi_curve ORDER BY n_reps"),
        "tornado": db.query("SELECT * FROM tornado ORDER BY swing DESC"),
        "pnl": db.query("SELECT * FROM pnl") if db.has_view("pnl") else [],
        "headline": manifest().get("headline_h3", {}),
        "assumptions": {k: v for k, v in economics().items() if k != "sizing"},
    }


@app.get("/api/segments", tags=["analytics"])
def segments() -> dict:
    _require("segment_profiles")
    return {
        "profiles": db.query("SELECT * FROM segment_profiles ORDER BY n_hcps DESC"),
        "diagnostics": db.query("SELECT * FROM segmentation_diagnostics ORDER BY k")
        if db.has_view("segmentation_diagnostics") else [],
        "summary": manifest().get("segmentation", {}),
    }


@app.get("/api/response", tags=["analytics"])
def response() -> dict:
    m = manifest()
    sat = m.get("response_saturation", {})
    return {
        "naive_ols": m.get("response_naive_ols", {}),
        "pretrend": m.get("response_pretrend", {}),
        "matching": m.get("response_matching", {}),
        "did": m.get("response_did", {}),
        "saturation": sat,
        "saturation_curve": db.query("SELECT * FROM response_saturation ORDER BY payment_usd")
        if db.has_view("response_saturation") else [],
        "balance": db.query("SELECT * FROM response_balance")
        if db.has_view("response_balance") else [],
        "caveat": (
            "Manufacturer payments flow toward prescribers who are already high-volume "
            "and already favourable -- that is what a targeting operation does. Matching "
            "and DiD reduce that selection bias but cannot remove it, because unobserved "
            "enthusiasm for the drug drives both payment receipt and prescribing. Treat "
            "every estimate here as an UPPER BOUND on any causal effect."
        ),
    }


@app.get("/api/territories", tags=["territories"])
def territories(n_reps: int = Query(60), alignment: str = Query("optimised")) -> dict:
    _require("territory_summary")
    presolved = params()["territory"]["n_reps_presolve"]
    if alignment == "optimised" and n_reps not in presolved:
        raise HTTPException(
            400, f"n_reps must be one of {presolved}. Alignments are pre-solved so the "
                 f"map responds instantly; solving on request would time out the demo.")

    return {
        "alignment": alignment,
        "n_reps": n_reps,
        "territories": db.query(
            """SELECT * FROM territory_summary
               WHERE alignment = ? AND n_reps = ? ORDER BY territory""",
            [alignment, n_reps]),
        "units": db.query(
            """SELECT unit, state, lat, lon, territory, workload, n_hcps, n_targets,
                      high_decile_hcps
               FROM territory_assignments WHERE alignment = ? AND n_reps = ?""",
            [alignment, n_reps]) if db.has_view("territory_assignments") else [],
        "stats": db.query(
            "SELECT * FROM territory_stats WHERE alignment = ? AND n_reps = ?",
            [alignment, n_reps]),
        "all_stats": db.query("SELECT * FROM territory_stats ORDER BY alignment, n_reps"),
        "headline": manifest().get("territory_headline", {}),
        "presolved_rep_counts": presolved,
    }


# NOT /api/hcps/sample: `/api/hcps/{npi}` is declared above and FastAPI matches
# in declaration order, so "sample" would be parsed as an NPI and 422.
@app.get("/api/hcp-sample", tags=["targets"])
def hcp_sample(n: int = Query(24_000, ge=1_000, le=80_000)) -> dict:
    """A compact random sample of real prescribers, for the story-mode field.

    Returned as PARALLEL ARRAYS rather than an array of objects: 24,000 rows of
    `{"opportunity_decile": 7, ...}` is ~4 MB of JSON keys repeated 24,000
    times, while six typed arrays is ~600 KB. The particle system wants column
    vectors anyway -- it uploads them straight into GPU buffers with no
    per-point object churn.

    Every particle is a REAL prescriber. The sample size and the universe it was
    drawn from are both returned so the caption can state them honestly rather
    than implying a million points are on screen.
    """
    _require("hcps")
    # ORDER BY random(), not USING SAMPLE. DuckDB's default sample is applied
    # per row-group, so `USING SAMPLE 24000 ROWS` returned 4,736 -- a silently
    # short sample that would have thinned the particle field with no error.
    #
    # Bounded to the contiguous US. This is a VISUALISATION endpoint: Alaska,
    # Hawaii, Guam and Puerto Rico span 300 degrees of longitude and would
    # squash the mainland into a third of the canvas. They remain in the
    # analysis -- territories are solved over every unit -- and only the map
    # background drops them, which the caption states.
    rows = db.query(
        """SELECT opportunity_decile, volume_decile, brand_share,
                  class_fills, opportunity, lat, lon, calls_per_month
           FROM hcps
           WHERE class_fills > 0
             AND lat BETWEEN 24 AND 50 AND lon BETWEEN -125 AND -66
           ORDER BY random()
           LIMIT ?""",
        [int(n)],
    )
    universe = db.query_one(
        "SELECT count(*) AS n FROM hcps WHERE class_fills > 0")["n"]

    def col(key: str, cast=float):
        return [cast(r[key]) if r[key] is not None else 0 for r in rows]

    return {
        "n": len(rows),
        "universe": universe,
        "opportunity_decile": col("opportunity_decile", int),
        "volume_decile": col("volume_decile", int),
        "brand_share": [round(v, 4) for v in col("brand_share")],
        "class_fills": col("class_fills"),
        "opportunity": col("opportunity"),
        "lat": [round(v, 3) for v in col("lat")],
        "lon": [round(v, 3) for v in col("lon")],
    }


@app.get("/api/meta", tags=["overview"])
def meta() -> dict:
    """Data vintage, row counts, assumptions and limitations. Feeds /method."""
    m = manifest()
    p = params()

    # ------------------------------------------------------------------
    # data_scope: honest disclosure when the deployment serves a subset.
    # The manifest always contains full-universe headline numbers; the
    # browsable prescriber list may be truncated to the deploy bundle.
    # /api/hcps can only page through whatever rows are in the parquet
    # file that was loaded -- if that is 50 000 rows the pager will show
    # 50 000, not 1.38 M.  This object makes that visible in the API
    # response so the frontend can surface it without hiding it.
    # ------------------------------------------------------------------
    prescribers_analysed: int = m.get("call_plan", {}).get("n_universe", 0)
    prescribers_served: int = 0
    if db.has_view("hcps"):
        row = db.query_one("SELECT count(*) AS n FROM hcps")
        prescribers_served = row["n"] if row else 0
    scope_mode = (
        "full" if prescribers_served >= prescribers_analysed else "deploy_bundle"
    )
    data_scope = {
        "mode": scope_mode,
        "prescribers_served": prescribers_served,
        "prescribers_analysed": prescribers_analysed,
        "note": (
            "This deployment serves the top 50,000 prescribers by opportunity "
            "plus every aggregate table. All headline figures are computed on "
            "the full 1.38M-prescriber universe; only the browsable list is "
            "truncated."
            if scope_mode == "deploy_bundle"
            else "This deployment serves the full analysed universe."
        ),
    }

    return {
        "data_mode": db.data_mode(),
        "data_mode_warning": (
            "SYNTHETIC data. The generative process encodes the hypothesis the "
            "opportunity model tests, so confirming it here is circular by construction. "
            "This mode validates the PIPELINE, not the FINDING."
            if db.data_mode() == "SYNTHETIC" else None),
        "data_scope": data_scope,
        "years": p["years"],
        "therapeutic_class": p["class_definition"],
        "volume_metric": p["volume_metric"],
        "row_counts": {k: v for k, v in m.items()
                       if isinstance(v, dict) and "rows" in v},
        "suppression": {k: v for k, v in m.items() if k.startswith("suppression")},
        "open_payments_match": m.get("open_payments_match", {}),
        "potential_model": m.get("potential_model", {}),
        "sfa_crosscheck": m.get("sfa_crosscheck", {}),
        "shap_top_driver": m.get("top_driver", m.get("shap_top_driver", {})),
        "gates": {g: m.get(g) for g in ("gate_g2", "gate_g3", "gate_g4")},
        "economic_assumptions": economics(),
        "territory_config": p["territory"],
        "limitations": [
            "Medicare-only. Part D excludes commercial and Medicaid patients and skews "
            "65+. Less distorting for a DOAC than for most classes, since the indicated "
            "population is largely elderly, but it still under-counts younger AF patients.",
            "Roughly two-year data lag. The latest full CMS release is not current "
            "market conditions.",
            "Suppression. NPI x drug rows under 11 claims are removed from the file "
            "entirely, not blanked. Handled by reconciling against provider-level totals; "
            "sensitivity across three imputation modes is reported. Residual bias "
            "understates low-volume prescribers.",
            "Payments are not causal. Matched DiD reduces but does not remove selection "
            "on unobservables. Every elasticity is an upper bound.",
            "No call-activity data. The current-state allocation is inferred from "
            "geography, not observed. H2 compares two allocation RULES, not this model "
            "against the client's actual field behaviour.",
            "The back-test measures where growth happened, not where a call would have "
            "caused growth. No CMS-only design can separate the two.",
            "Straight-line distance, not drive time. Coastal and mountain territories "
            "are where this hurts most.",
            "Territory granularity. ZIP3 units are indivisible and each is roughly 10% "
            "of a territory's workload, which bounds achievable workload CV near 0.15. "
            "Real alignments split to ZIP5 to go finer.",
            "The territory model ignores rep tenure, existing relationships and "
            "organisational boundaries, which dominate real alignment decisions.",
            "Economic parameters are public benchmarks, not the client's actuals. All "
            "six are in config/economics.yaml with ranges; the tornado chart shows which "
            "ones the recommendation is actually sensitive to.",
        ],
        "sources": [
            {"name": "Medicare Part D Prescribers - by Provider and Drug",
             "url": "https://data.cms.gov/provider-summary-by-type-of-service"},
            {"name": "Medicare Part D Prescribers - by Provider",
             "url": "https://data.cms.gov/provider-summary-by-type-of-service"},
            {"name": "Open Payments - General Payments",
             "url": "https://openpaymentsdata.cms.gov/"},
            {"name": "Census Gazetteer - ZCTA", "url": "https://www.census.gov/geographies/reference-files.html"},
            {"name": "CDC PLACES", "url": "https://www.cdc.gov/places/"},
        ],
    }


@app.get("/api/health", tags=["overview"])
def health() -> dict:
    return {"status": "ok", "data_mode": db.data_mode()}


# --------------------------------------------------------------------------- #
# Static frontend
# --------------------------------------------------------------------------- #
_WEB_DIR = next(
    (p for p in (ROOT / "web" / "dist", ROOT / "web" / "static") if p.exists()),
    None,
)

if _WEB_DIR is not None:
    log.info("serving frontend from %s", _WEB_DIR.relative_to(ROOT))

    # Real files (JS, CSS, fonts) are served from /assets by the built app.
    _assets = _WEB_DIR / "assets"
    if _assets.exists():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        """SPA fallback.

        React Router owns /app/targets and friends. A plain StaticFiles mount
        404s those on a hard refresh or a shared deep link -- the app works
        until someone reloads, which is exactly when a demo breaks. Serve the
        real file when it exists, otherwise hand back index.html and let the
        router resolve the path client-side.

        /api/* never reaches here: those routes are registered above and FastAPI
        matches in declaration order.
        """
        candidate = (_WEB_DIR / full_path).resolve()
        # Guard against path traversal before touching the filesystem.
        if (
            full_path
            and _WEB_DIR.resolve() in candidate.parents
            and candidate.is_file()
        ):
            return FileResponse(candidate)

        index = _WEB_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        raise HTTPException(404, "Frontend not built. Run `make web-build`.")
