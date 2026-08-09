"""Print the run findings from data/manifest.json.

    python -m src.utils.summary

Lives in a module rather than embedded in run_all.ps1: Python inside a
PowerShell here-string needs quote escaping that silently produces invalid
Python, and a summary that crashes after a two-hour pipeline is worse than no
summary at all.

Reads only the manifest, so it is instant and safe to run at any time -- during
a pipeline, after a partial failure, or to re-read yesterday's numbers.
"""
from __future__ import annotations

import json

from src.config import ROOT

MANIFEST = ROOT / "data" / "manifest.json"


def _get(m: dict, key: str, field: str, default=None):
    return (m.get(key) or {}).get(field, default)


def _pct(v, digits: int = 1) -> str:
    try:
        return f"{100 * float(v):.{digits}f}%"
    except (TypeError, ValueError):
        return "--"


def _num(v, digits: int = 0) -> str:
    try:
        return f"{float(v):,.{digits}f}"
    except (TypeError, ValueError):
        return "--"


def render() -> str:
    if not MANIFEST.exists():
        return "  no manifest yet -- nothing has run"

    m = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out: list[str] = []

    # ---- data ------------------------------------------------------------
    out.append("  DATA")
    mode = _get(m, "data_mode", "mode", "UNKNOWN")
    out.append(f"    mode                 {mode}")
    out.append(f"    years                {_get(m, 'data_mode', 'years')}")
    supp = next((v for k, v in m.items()
                 if k.startswith("suppression_") and isinstance(v, dict)), {})
    out.append(f"    volume suppressed    {_pct(supp.get('hidden_share_of_total'))}")
    out.append(f"    NPI-years affected   {_pct(supp.get('pct_npi_years_affected'))}")
    out.append(f"    Open Payments link   {_pct(_get(m, 'open_payments_match', 'link_rate'))}")
    if mode == "SYNTHETIC":
        out.append("    !! SYNTHETIC -- validates the pipeline, not the finding")

    # ---- model -----------------------------------------------------------
    out.append("")
    out.append("  MODEL")
    out.append(f"    frontier coverage    {_get(m, 'potential_model', 'in_sample_coverage')} "
               f"(target tau {_get(m, 'potential_model', 'tau')})")
    out.append(f"    SFA cross-check      {_get(m, 'sfa_crosscheck', 'spearman')}")
    out.append(f"    top driver           {_get(m, 'top_driver', 'feature', '--')} "
               f"({_pct(_get(m, 'top_driver', 'share'))})")
    dis = m.get("disagreement") or {}
    out.append(f"    decile disagreement  {_pct(dis.get('disagree_by_2plus_pct'))}")
    if dis:
        out.append(f"      low-vol/high-opp   {_num(dis.get('volume_low_opportunity_high'))} "
                   f"(skipped by the volume rule)")
        out.append(f"      high-vol/low-opp   {_num(dis.get('volume_high_opportunity_low'))} "
                   f"(over-served by it)")

    # ---- gates -----------------------------------------------------------
    out.append("")
    out.append("  GATES")
    for gate in ("gate_g2", "gate_g3", "gate_g4"):
        node = m.get(gate)
        if node:
            verdict = "PASSED" if node.get("passed") else "FAILED -> pre-committed pivot"
            out.append(f"    {gate.upper():<9} {verdict}")

    # ---- headlines -------------------------------------------------------
    out.append("")
    out.append("  FINDINGS")
    h2 = m.get("headline_h2") or {}
    if h2:
        out.append(f"    reach @ {h2.get('n_reps')} reps      "
                   f"opportunity {_pct(h2.get('opportunity_pct_opportunity'))} | "
                   f"volume {_pct(h2.get('volume_pct_opportunity'))} | "
                   f"geography {_pct(h2.get('geography_pct_opportunity'))}")

    cp = m.get("call_plan") or {}
    if cp:
        out.append(f"    plan                 {_num(cp.get('n_targets'))} of "
                   f"{_num(cp.get('n_in_market'))} in-market prescribers served "
                   f"({_pct(cp.get('pct_of_market_served'))})")
        out.append(f"    unconstrained demand {_num(cp.get('demand_hcps'))} prescribers, "
                   f"needing {_num(cp.get('implied_reps'))} reps vs "
                   f"{_num(cp.get('current_reps'))} today")

    bt = m.get("backtest_head_to_head") or {}
    g3 = m.get("gate_g3") or {}
    if bt or g3:
        out.append(f"    back-test            Spearman {g3.get('decile_spearman', '--')} | "
                   f"share capture {g3.get('share_growth_ratio', '--')}x | "
                   f"absolute {g3.get('absolute_growth_ratio', '--')}x")
    matched = m.get("backtest_matched") or {}
    if matched.get("growth_ratio"):
        out.append(f"    vs matched controls  {matched['growth_ratio']}x faster growth")

    h3 = m.get("headline_h3") or {}
    if h3:
        # Recommendation first, diagnostic second and clearly labelled. The
        # uncapped break-even is a real output but is not a hiring plan, and
        # leading with it implies the response curve is carrying the result.
        out.append(f"    sizing RECOMMEND     +{_num(h3.get('recommended_add'))} reps "
                   f"({_num(h3.get('current_n_reps'))} -> {_num(h3.get('recommended_n_reps'))}), "
                   f"worth {_num(h3.get('incremental_profit'))} contribution; "
                   f"marginal rep still {h3.get('marginal_roi_at_recommended','--')}x")
        if h3.get("recommendation_capped"):
            out.append(f"      diagnostic (not an ask): economics bind at "
                       f"{_num(h3.get('break_even_n_reps'))} reps "
                       f"(sensitivity {_num(h3.get('sensitivity_low'))}-"
                       f"{_num(h3.get('sensitivity_high'))}); "
                       f"{_num(h3.get('unmet_demand_reps'))} reps of unmet demand")

    t = m.get("territory_headline") or {}
    if t:
        out.append(f"    territory            imbalance {t.get('imbalance_before')}x -> "
                   f"{t.get('imbalance_after')}x | contiguity "
                   f"{_pct(t.get('contiguity_before'), 0)} -> {_pct(t.get('contiguity_after'), 0)} | "
                   f"travel -{_pct(t.get('travel_reduction_pct'), 0)}")

    seg = m.get("segmentation") or {}
    if seg:
        out.append(f"    segments             k={seg.get('k')} "
                   f"(silhouette {seg.get('silhouette')}, stability {seg.get('stability_ari')})")

    pre = m.get("response_pretrend") or {}
    did = m.get("response_did") or {}
    if pre or did:
        holds = pre.get("parallel_trends_holds")
        out.append(f"    response             parallel trends "
                   f"{'HOLD' if holds else 'FAIL -> association only'} | "
                   f"naive {_get(m, 'response_naive_ols', 'elasticity', '--')} vs "
                   f"matched DiD {did.get('did_estimate', '--')}")

    # ---- champion vs challenger -----------------------------------------
    ch = m.get("challenger") or {}
    if ch:
        out.append("")
        out.append("  CHAMPION vs CHALLENGER")
        for r in ch.get("results", []):
            out.append(f"    {r.get('rule',''):<12} share {_pct(r.get('share_capture'))} | "
                       f"absolute {_pct(r.get('abs_capture'))} | "
                       f"median base {_num(r.get('median_base_class_fills'))} fills")
        verdict = m.get("challenger_verdict") or {}
        if verdict.get("metric_gamed"):
            out.append("    ^ the share-capture win is driven by small denominators, not")
            out.append("      persuadability. Do not report share capture alone.")

    return "\n".join(out)


if __name__ == "__main__":
    print(render())
