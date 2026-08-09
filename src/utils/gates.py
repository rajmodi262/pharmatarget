"""Evaluate gates G2 and G4 from the artifacts on disk.

    python -m src.utils.gates

WHY THIS EXISTS
---------------
G3 is recorded inside backtest.py, so it always reaches the manifest. G2 and G4
were only evaluated inside src/pipeline.py -- and run_all.ps1 deliberately does
not call that, because it runs each module directly so stages stay
independently resumable.

The result was that a full run_all.ps1 pass produced a manifest containing one
gate instead of three, and the summary printed one line where three were
expected. Nothing failed; the checks simply never happened, which is the worst
kind of missing check.

This module re-derives both from artifacts already on disk, so it is cheap,
order-independent, and safe to run at any point after the models have produced
their parquet.
"""
from __future__ import annotations

from src.config import params, path
from src.utils.io import get_logger, manifest, read_parquet, record

log = get_logger(__name__)


def gate_g2() -> dict:
    """Opportunity must actually differ from volume, or there is no project."""
    dis = manifest().get("disagreement", {})
    pct = dis.get("disagree_by_2plus_pct")
    passed = pct is not None and pct >= 0.30

    verdict = {
        "gate": "G2",
        "passed": bool(passed),
        "disagree_pct": pct,
        "criterion": "at least 30% of in-market prescribers move 2+ deciles "
                     "between the volume and opportunity rankings",
    }
    if passed:
        log.info("GATE G2 PASSED -- %.1f%% of prescribers move 2+ deciles",
                 100 * (pct or 0))
    else:
        log.warning("GATE G2 FAILED -- only %.1f%% move 2+ deciles. The opportunity "
                    "score is tracking volume; check the driver attribution before "
                    "trusting anything downstream.", 100 * (pct or 0))
    record("gate_g2", **verdict)
    return verdict


def gate_g4() -> dict:
    """Territories must be contiguous and balanced enough to be implementable."""
    cfg = params()["territory"]
    stats = read_parquet(path("processed") / "territory_stats.parquet")
    opt = stats[(stats["alignment"] == "optimised")
                & (stats["n_reps"] == cfg["n_reps_default"])]
    if opt.empty:
        opt = stats[stats["alignment"] == "optimised"]
    if opt.empty:
        log.warning("GATE G4 not evaluable -- no optimised alignment in territory_stats")
        return {"gate": "G4", "passed": False, "computable": False}

    row = opt.iloc[0]
    contiguity = float(row["contiguity_rate"])
    cv = float(row["workload_cv"]) if row["workload_cv"] is not None else 1.0

    cond_contig = contiguity >= cfg["min_contiguity_rate"]
    cond_cv = cv <= cfg["max_cv"]
    passed = cond_contig and cond_cv

    verdict = {
        "gate": "G4",
        "passed": bool(passed),
        "contiguity_rate": round(contiguity, 4),
        "workload_cv": round(cv, 4),
        "conditions": {"contiguous": bool(cond_contig), "balanced": bool(cond_cv)},
        "criterion": (f"contiguity >= {cfg['min_contiguity_rate']} "
                      f"AND workload CV <= {cfg['max_cv']}"),
    }
    if passed:
        log.info("GATE G4 PASSED -- contiguity %.1f%%, CV %.3f",
                 100 * contiguity, cv)
    else:
        failed = [k for k, v in verdict["conditions"].items() if not v]
        log.warning("GATE G4 FAILED on %s -- contiguity %.1f%%, CV %.3f. "
                    "A territory map with detached islands is not implementable; "
                    "report the shortfall rather than relaxing the threshold.",
                    ", ".join(failed), 100 * contiguity, cv)
    record("gate_g4", **verdict)
    return verdict


def run() -> dict:
    return {"g2": gate_g2(), "g4": gate_g4()}


if __name__ == "__main__":
    run()
