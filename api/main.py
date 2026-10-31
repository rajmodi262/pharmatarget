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
import math
import time
import uuid

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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

@app.middleware("http")
async def _request_log(request: Request, call_next):
    """One structured log line per API request, tagged with a request id.

    The id goes back in X-Request-ID so a user's "it broke" can be matched to
    the server log line, and into the body of any 500 (handler below).
    """
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    request.state.request_id = rid
    t0 = time.perf_counter()
    response = await call_next(request)
    ms = (time.perf_counter() - t0) * 1000
    response.headers["X-Request-ID"] = rid
    if request.url.path.startswith("/api/"):
        log.info("request id=%s method=%s path=%s status=%d ms=%.1f",
                 rid, request.method, request.url.path, response.status_code, ms)
    return response


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    """A JSON 500 with the request id, never a bare stack trace or HTML page."""
    rid = getattr(request.state, "request_id", "-")
    log.exception("unhandled id=%s path=%s", rid, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal error. Quote the request id when reporting it.",
                 "request_id": rid},
        headers={"X-Request-ID": rid})


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
    psm, boot = m.get("propensity_matched", {}), m.get("bootstrap_headlines", {})
    rules = {r.get("rule"): r for r in (m.get("challenger") or {}).get("results", [])}

    def _ci(key: str) -> list | None:
        v = boot.get(key)
        return v if isinstance(v, list) and len(v) == 3 else None

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
                # [low, estimate, high] from the prescriber bootstrap.
                "share_growth_ratio_ci": _ci("share_ratio"),
                "absolute_growth_ratio_ci": _ci("abs_ratio"),
                "spearman_ci": _ci("spearman"),
                # Propensity-matched comparison: the headline, five covariates.
                "matched_growth_ratio": psm.get("growth_ratio"),
                "matched_paired_difference": psm.get("paired_difference"),
                "matched_ci": [psm.get("ci_low"), psm.get("ci_high")],
                "matched_pairs": psm.get("n_pairs"),
            },
            # Realised 2023->2024 outcomes of each rule's 60-rep list. Not
            # causal, but observed -- and the place the trade-off is visible.
            "business_case": {
                "class": "BACK-TESTED",
                "n_budget": (m.get("challenger") or {}).get("n_budget"),
                "rules": {k: {f: v.get(f) for f in
                              ("abs_capture", "share_capture", "net_brand_fill_growth",
                               "median_base_class_fills")}
                          for k, v in rules.items()},
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
                "claim": "Marginal-rep economics, priced through the fitted response "
                         "curve: where the next rep stops paying for itself.",
                "current_n_reps": h3.get("current_n_reps"),
                "break_even_n_reps": h3.get("break_even_n_reps"),
                "recommended_n_reps": h3.get("recommended_n_reps"),
                "marginal_roi_at_current": h3.get("marginal_roi_at_current"),
                "incremental_profit": h3.get("incremental_profit"),
                "sensitivity_range": [h3.get("sensitivity_low"), h3.get("sensitivity_high")],
                "caveat": h3.get("label"),
                # False when the call response is not identifiable from public
                # data: break-even/ROI above are then ILLUSTRATIVE, and the
                # decision-relevant number is the required response.
                "response_identified": h3.get("response_identified", True),
                "required_ceiling_at_current": h3.get("required_ceiling_at_current"),
            },
            "recommendation": m.get("recommendation", {}),
            "retargeting": {k: m.get("retargeting_value", {}).get(k) for k in
                            ("hybrid_vs_volume_contribution", "delta_contribution",
                             "priced_at", "label")},
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

    clause, args = _hcp_filters(state, specialty, segment, decile_min, decile_max,
                                targets_only, q)
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


def _hcp_filters(state: str | None, specialty: str | None, segment: str | None,
                 decile_min: int, decile_max: int, targets_only: bool,
                 q: str | None) -> tuple[str, list]:
    """WHERE clause shared by the list and the export.

    One builder, because two drifted: the export ignored specialty and search,
    so "Export current view" downloaded a different list from the one on screen.
    """
    where, args = ["opportunity_decile BETWEEN ? AND ?"], [decile_min, decile_max]
    if state:
        where.append("state = ?")
        args.append(state.upper())
    if specialty:
        where.append("specialty_group = ?")
        args.append(specialty)
    if targets_only:
        where.append("is_target")
    if segment and db.has_view("hcp_segments"):
        # Accepted and documented since v1 but never applied -- a filter that
        # silently returns the unfiltered list is worse than no filter.
        where.append("npi IN (SELECT npi FROM hcp_segments WHERE segment = ?)")
        args.append(segment)
    if q:
        where.append("(CAST(npi AS VARCHAR) LIKE ? OR last_name LIKE ?)")
        args += [f"{q}%", f"{q.upper()}%"]
    return " AND ".join(where), args


def _csv_response(rows: list[dict], filename: str) -> StreamingResponse:
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
        headers={"Content-Disposition": f"attachment; filename={filename}"})


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

    explanation = db.query(
        """SELECT rank, feature, label, contribution, multiplier, value
           FROM ds_explanations WHERE npi = ? ORDER BY rank""", [npi]
    ) if db.has_view("ds_explanations") else []
    for e in explanation:
        e["display"] = readable_value(e["feature"], e["value"])
    forecast = db.query_one(
        "SELECT forecast_year, p_active, brand_fills_pred, brand_fills_lo, brand_fills_hi "
        "FROM ds_forecast WHERE npi = ?", [npi]) if db.has_view("ds_forecast") else None
    uplift = db.query_one("SELECT cate, propensity FROM ds_uplift_scores WHERE npi = ?", [npi]) \
        if db.has_view("ds_uplift_scores") else None

    return {"hcp": row, "trend": trend, "payments": pay,
            "segment": (seg or {}).get("segment"),
            "explanation": explanation, "forecast": forecast, "uplift": uplift}


# --------------------------------------------------------------------------- #
# 4. export
# --------------------------------------------------------------------------- #
@app.get("/api/hcps/export/csv", tags=["targets"])
def export_hcps(state: str | None = None, specialty: str | None = None,
                segment: str | None = None, decile_min: int = Query(1, ge=1, le=10),
                decile_max: int = Query(10, ge=1, le=10), targets_only: bool = False,
                q: str | None = None, limit: int = Query(50_000, ge=1, le=200_000)):
    """Streaming CSV of exactly the filter set on screen."""
    _require("hcps")
    clause, args = _hcp_filters(state, specialty, segment, decile_min, decile_max,
                                targets_only, q)
    rows = db.query(
        f"""SELECT npi, last_name, first_name, city, state, specialty_group,
                   class_fills, brand_fills, brand_share, opportunity,
                   opportunity_decile, volume_decile, calls_per_month
            FROM hcps WHERE {clause}
            ORDER BY opportunity DESC LIMIT ?""", args + [limit])
    return _csv_response(rows, "pharmatarget_targets.csv")


# --------------------------------------------------------------------------- #
# 4b. call list -- one rep's territory, in visit order
# --------------------------------------------------------------------------- #
def _calllist_rows(territory: int, n_reps: int, targets_only: bool) -> list[dict]:
    """Prescribers whose ZIP3 is assigned to this territory, highest priority first.

    `why` is the single largest driver of modelled potential from the TreeSHAP
    explanations, phrased so a rep can read it aloud: "Specialty: Cardiology
    (x2.36)". Prescribers outside the explained set get NULL, not a guess.
    """
    has_expl = db.has_view("ds_explanations")
    has_fc = db.has_view("ds_forecast")
    why = ("e.feature AS why_feature, e.label AS why_label, e.value AS why_value, "
           "e.multiplier AS why_multiplier"
           if has_expl else "NULL AS why_feature, NULL AS why_label, "
                            "NULL AS why_value, NULL AS why_multiplier")
    join_e = ("LEFT JOIN ds_explanations e ON e.npi = h.npi AND e.rank = 1"
              if has_expl else "")
    fc = ("f.brand_fills_lo AS forecast_lo, f.brand_fills_pred AS forecast_mid, "
          "f.brand_fills_hi AS forecast_hi, f.p_active"
          if has_fc else "NULL AS forecast_lo, NULL AS forecast_mid, "
                         "NULL AS forecast_hi, NULL AS p_active")
    join_f = "LEFT JOIN ds_forecast f ON f.npi = h.npi" if has_fc else ""
    target = "AND h.is_target" if targets_only else ""
    rows = db.query(
        f"""SELECT row_number() OVER (ORDER BY h.is_target DESC, h.opportunity DESC,
                                      h.npi) AS priority,
                   h.npi, h.last_name, h.first_name, h.city, h.state, h.zip3,
                   h.specialty_group, h.class_fills, h.brand_share, h.opportunity,
                   h.opportunity_decile, h.calls_per_month, h.is_target,
                   {why}, {fc}
            FROM hcps h
            JOIN territory_assignments t
              ON t.unit = h.zip3 AND t.alignment = 'optimised' AND t.n_reps = ?
            {join_e} {join_f}
            WHERE t.territory = ? {target}
            ORDER BY priority""",
        [n_reps, territory])
    out = []
    for r in rows:
        feat, label = r.pop("why_feature"), r.pop("why_label")
        val, mult = r.pop("why_value"), r.pop("why_multiplier")
        r["why"] = reason(feat, label, val, mult)
        for k in ("class_fills", "opportunity", "forecast_lo", "forecast_mid", "forecast_hi"):
            if r.get(k) is not None:
                r[k] = round(r[k])
        for k in ("brand_share", "p_active"):
            if r.get(k) is not None:
                r[k] = round(r[k], 3)
        out.append(r)
    return out


def reason(feature: str | None, label: str | None, value: str | None,
           multiplier: float | None) -> str | None:
    """The top driver as one sentence a rep can say out loud."""
    if feature is None or multiplier is None:
        return None
    # The volume driver is U-shaped: prescribers with almost no claims outside
    # the class (<500) score HIGH, because they are anticoagulation clinics.
    # "Total prescribing volume: 55 (x3.6)" reads as a bug; say what it means.
    if feature == "log_non_class_clms" and value is not None and multiplier > 1:
        n = math.expm1(float(value))
        if n < 500:
            return (f"Anticoagulant-focused practice: only {n:,.0f} claims for other "
                    f"drugs (x{multiplier:.2f} potential)")
    return f"{label}: {readable_value(feature, value)} (x{multiplier:.2f} potential)"


def readable_value(feature: str | None, value: str | None) -> str:
    """A model input as a person would say it.

    Explanations store the model's own inputs, and several are log1p counts:
    "Total prescribing volume: 9.94" means 20,700 claims, and a rep reading the
    first would rightly ignore it.
    """
    if feature is None or value is None:
        return "--"
    try:
        v = float(value)
    except ValueError:
        return value                        # categorical: "Cardiology"
    if feature.startswith("log_"):
        return f"{math.expm1(v):,.0f}"
    if feature.startswith("pct_"):
        return f"{v:.0%}"
    return f"{v:.2f}"


def _check_calllist(n_reps: int) -> None:
    _require("territory_assignments")
    presolved = params()["territory"]["n_reps_presolve"]
    if n_reps not in presolved:
        raise HTTPException(400, f"n_reps must be one of {presolved}")


@app.get("/api/calllist", tags=["territories"])
def calllist(territory: int | None = Query(None, ge=0), n_reps: int = Query(60),
             targets_only: bool = True) -> dict:
    """A rep's call list: every territory to choose from, and the chosen one's
    prescribers in priority order with calls/month, a one-line reason and the
    2025 forecast range. Without `territory`, returns only the options."""
    _check_calllist(n_reps)
    options = db.query(
        """SELECT territory, sum(n_hcps) AS n_hcps, sum(n_targets) AS n_targets,
                  sum(workload) AS workload, sum(opportunity) AS opportunity,
                  string_agg(DISTINCT state, ', ' ORDER BY state) AS states
           FROM territory_assignments
           WHERE alignment = 'optimised' AND n_reps = ?
           GROUP BY territory ORDER BY territory""", [n_reps])
    if territory is None:
        return {"n_reps": n_reps, "options": options, "territory": None, "rows": []}
    head = next((o for o in options if o["territory"] == territory), None)
    if head is None:
        raise HTTPException(404, f"territory {territory} not found at {n_reps} reps")
    rows = _calllist_rows(territory, n_reps, targets_only)
    return {"n_reps": n_reps, "options": options, "territory": head,
            "targets_only": targets_only, "rows": rows,
            # The deploy bundle serves the top 50k prescribers; say so where it
            # changes what a rep sees, rather than only on the Method page.
            "served_hcps": len(rows)}


@app.get("/api/calllist/csv", tags=["territories"])
def calllist_csv(territory: int = Query(..., ge=0), n_reps: int = Query(60),
                 targets_only: bool = True):
    """The same call list as a CSV a rep can open in Excel or load into a CRM."""
    _check_calllist(n_reps)
    rows = _calllist_rows(territory, n_reps, targets_only)
    if not rows:
        raise HTTPException(404, f"territory {territory} has no prescribers at {n_reps} reps")
    return _csv_response(rows, f"pharmatarget_territory_{territory}_calllist.csv")


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
        "retargeting": manifest().get("retargeting_value", {}),
        "assumptions": {k: v for k, v in _assumptions_in_use(manifest()).items()
                        if k != "sizing"},
    }


# Publicly reported 2026 Medicare negotiated price (Inflation Reduction Act,
# CMS, August 2024) for the focus brand's 30-day supply. Used ONLY as a named
# scenario on the decision lab's revenue slider, never in a base-case figure.
IRA_2026_PRICE_PER_FILL = 231.0


@app.get("/api/decision", tags=["analytics"])
def decision() -> dict:
    """Inputs for the decision lab: blend frontier, headcount explorer, pilot sizing.

    Everything the page computes interactively is linear in its sliders --
    marginal ROI and retargeting value both scale with the response ceiling and
    with revenue per fill -- so the browser can recompute exactly from these
    pre-computed anchors instead of re-running a model per drag.
    """
    _require("decision_frontier")
    m = manifest()
    econ_ = economics()
    return {
        "frontier": db.query("SELECT * FROM decision_frontier ORDER BY period, weight"),
        "frontier_summary": m.get("decision_frontier", {}),
        "recommendation": m.get("recommendation", {}),
        "pilot": m.get("pilot_design", {}),
        "required_response": db.query(
            "SELECT * FROM required_response ORDER BY n_reps")
        if db.has_view("required_response") else [],
        "retargeting": m.get("retargeting_value", {}),
        "headline": m.get("headline_h3", {}),
        "business_case": m.get("business_case_value", {}),
        "value_grid": db.query("SELECT * FROM value_grid ORDER BY n_reps")
        if db.has_view("value_grid") else [],
        "economics": {
            "net_revenue_per_30day_fill": econ_["net_revenue_per_30day_fill"],
            "contribution_margin": econ_["contribution_margin"],
            "rep_cost_annual": econ_["rep_cost_annual"],
            "ira_2026_price_per_fill": IRA_2026_PRICE_PER_FILL,
        },
    }


# The steering-committee pack, downloadable from the app. A fixed allow-list:
# the route never takes a path from the request.
DOWNLOADS = {
    "executive": ("PharmaTarget_Executive.pdf", "10-slide executive deck"),
    "onepager": ("PharmaTarget_OnePager.pdf", "One-page decision memo"),
    "full": ("PharmaTarget_Recommendations.pdf", "Full analysis deck (appendix)"),
}


@app.get("/api/download/{name}", tags=["overview"])
def download(name: str):
    if name not in DOWNLOADS:
        raise HTTPException(404, f"unknown document '{name}'")
    fname, _ = DOWNLOADS[name]
    f = ROOT / "outputs" / fname
    if not f.exists():
        raise HTTPException(503, f"{fname} not built -- run python -m src.report.make_assets")
    return FileResponse(f, media_type="application/pdf", filename=fname)


DS_TABLES = {
    "ladder": "SELECT * FROM ds_ladder ORDER BY value_capture DESC",
    "gain_curves": "SELECT * FROM ds_gain_curves ORDER BY rule, fraction_targeted",
    "coverage": "SELECT * FROM ds_conformal_coverage",
    "calibration": "SELECT * FROM ds_calibration ORDER BY bin",
    "hurdle_calibration": "SELECT * FROM ds_hurdle_calibration ORDER BY bin",
    "errors": "SELECT * FROM ds_error_segments",
    "representation": "SELECT * FROM ds_representation",
    "causal": "SELECT * FROM ds_causal",
    "qini": "SELECT * FROM ds_uplift_qini ORDER BY fraction_targeted",
    "uplift_deciles": "SELECT * FROM ds_uplift_value_deciles ORDER BY decile",
    "shap_global": "SELECT * FROM ds_shap_global ORDER BY mean_abs_shap DESC",
    "ablation": "SELECT * FROM ds_ablation",
    "drift": "SELECT * FROM ds_drift",
    "network": "SELECT * FROM ds_network",
    "shrinkage_h2h": "SELECT * FROM ds_shrinkage_h2h",
    "shrinkage_funnel": "SELECT * FROM ds_shrinkage_funnel",
    "contracts": "SELECT * FROM ds_contract_results",
}
DS_KEYS = ("ds_shrinkage", "ds_evaluation", "ds_conformal", "ds_errors", "ds_causal",
           "ds_uplift", "ds_explain", "ds_ablation", "ds_drift", "ds_contracts", "ds_network")


@app.get("/api/datascience", tags=["analytics"])
def datascience() -> dict:
    """Everything the Model Lab shows: evaluation, uncertainty, causal ML,
    uplift, explanations, ablations, drift, contracts and the practice network."""
    _require("ds_ladder")
    m = manifest()
    tables = {}
    for key, sql in DS_TABLES.items():
        view = sql.split(" FROM ")[1].split()[0]
        tables[key] = db.query(sql) if db.has_view(view) else []
    return {"summary": {k.removeprefix("ds_"): m.get(k, {}) for k in DS_KEYS}, **tables}


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
    if alignment in ("baseline", "kmeans"):
        # The comparison alignments are solved at the default force only. Serve
        # that rather than an empty map when the slider sits elsewhere.
        n_reps = params()["territory"]["n_reps_default"]

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
        "row_counts": {k.removeprefix("artifact:"): v for k, v in m.items()
                       if k.startswith("artifact:") and isinstance(v, dict)},
        "suppression": {k: v for k, v in m.items() if k.startswith("suppression")},
        "open_payments_match": m.get("open_payments_match", {}),
        "potential_model": m.get("potential_model", {}),
        "sfa_crosscheck": m.get("sfa_crosscheck", {}),
        "shap_top_driver": m.get("top_driver", m.get("shap_top_driver", {})),
        "gates": {g: m.get(g) for g in ("gate_g2", "gate_g3", "gate_g4")},
        "economic_assumptions": _assumptions_in_use(m),
        "call_response_fit": m.get("call_response_fit", {}),
        "territory_config": p["territory"],
        "limitations": [
            "Medicare-only. Part D excludes commercial and Medicaid patients and skews "
            "65+. Less distorting for a DOAC than for most classes, since the indicated "
            "population is largely elderly, but it still under-counts younger AF patients.",
            "~17-month data lag. Data year 2024 was published in May 2026; it is not "
            "current market conditions.",
            "The promotional proxy is Open Payments food-and-beverage events that name "
            "the brand. Not every detail involves a meal, so it under-counts calls, and "
            "reps choose whom to visit, so any response fitted on it is an upper bound.",
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


def _assumptions_in_use(m: dict) -> dict:
    """economics.yaml, with the two response parameters replaced by their FITTED
    values when the fit has run -- the Method page must show what the model
    actually used, not the fallback constants it no longer reads."""
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in economics().items()}
    fit = m.get("call_response_fit") or {}
    if fit.get("fitted") and not fit.get("identifiable", True):
        note = ("NOT IDENTIFIED: brand-named visit events show no measurable "
                "dose-response, so this config value is an ILLUSTRATIVE assumption, not a "
                "measurement. Sizing reports the break-even response instead.")
        for key in ("call_response_ceiling", "call_response_half_saturation"):
            out[key]["basis"] = note
        return out
    if fit.get("fitted"):
        basis = ("FITTED from Open Payments brand-named food-and-beverage events "
                 "(src/models/call_response.py); range is the prescriber bootstrap 95% CI.")
        out["call_response_ceiling"].update(
            base=fit["ceiling"], low=fit["ceiling_ci"][0], high=fit["ceiling_ci"][1], basis=basis)
        out["call_response_half_saturation"].update(
            base=fit["half_saturation_calls"], low=fit["half_saturation_ci"][0],
            high=fit["half_saturation_ci"][1], basis=basis)
    return out


@app.get("/api/health", tags=["overview"])
def health() -> dict:
    """Liveness plus enough state to tell a healthy deploy from a hollow one.

    `degraded` means the process is up but a core view is missing, so the
    routes that need it return 503. The platform health check still passes
    (status 200) -- restarting would not bring the missing file back.
    """
    core = ("hcps", "territory_summary", "territory_assignments", "pnl")
    missing = [v for v in core if not db.has_view(v)]
    m = manifest()
    return {
        "status": "degraded" if missing else "ok",
        "data_mode": db.data_mode(),
        "version": app.version,
        "missing_core_views": missing,
        "pipeline_run": m.get("pipeline_run", {}),
    }


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
