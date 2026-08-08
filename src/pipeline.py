"""End-to-end pipeline runner.

    python -m src.pipeline --synthetic --sample     # ~2 minutes
    python -m src.pipeline --synthetic              # full synthetic run
    python -m src.pipeline                          # real CMS data (must be downloaded)

Stages run in dependency order and each one logs its gate criterion from the
execution playbook. A failed gate does not stop the pipeline -- it prints the
pre-committed response and continues, because the downstream artifacts are still
needed and because a gate failure is a finding to be reported, not an error to
be swallowed.
"""
from __future__ import annotations

import argparse
import time

from src.utils.io import get_logger, manifest, record

log = get_logger("pipeline")


def run(synthetic: bool = False, sample: bool = False, skip_optional: bool = False) -> dict:
    t0 = time.time()
    results: dict = {}

    if synthetic:
        log.info("=" * 72)
        log.info("STAGE 0/8  generate synthetic CMS-shaped data")
        log.info("=" * 72)
        from src.ingest import synth
        synth.generate(*(8_000, 220) if sample else (40_000, 620))

    log.info("=" * 72)
    log.info("STAGE 1/8  SQL marts (DuckDB)")
    log.info("=" * 72)
    from src.etl import build_marts
    build_marts.build()

    log.info("=" * 72)
    log.info("STAGE 2/8  opportunity model      [GATE G2: opportunity must differ from volume]")
    log.info("=" * 72)
    from src.models import opportunity
    opportunity.run()
    dis = manifest().get("disagreement", {})
    g2 = dis.get("disagree_by_2plus_pct", 0) >= 0.30
    log.info("GATE G2 %s -- %.1f%% of prescribers move 2+ deciles (criterion: >=30%%)",
             "PASSED" if g2 else "FAILED", 100 * dis.get("disagree_by_2plus_pct", 0))
    if not g2:
        log.warning("  The opportunity score is tracking volume. Check the SHAP drivers: "
                    "if practice size dominates, the model has learned panel size and "
                    "not market headroom.")
    record("gate_g2", passed=bool(g2), disagree_pct=dis.get("disagree_by_2plus_pct"))
    results["g2"] = g2

    log.info("=" * 72)
    log.info("STAGE 3/8  call plan + reach curves")
    log.info("=" * 72)
    from src.models import callplan
    callplan.run()

    log.info("=" * 72)
    log.info("STAGE 4/8  back-test              [GATE G3: does the model beat volume?]")
    log.info("=" * 72)
    from src.models import backtest
    results["backtest"] = backtest.run()

    log.info("=" * 72)
    log.info("STAGE 5/8  field force sizing + P&L")
    log.info("=" * 72)
    from src.models import sizing
    results["sizing"] = sizing.run()

    log.info("=" * 72)
    log.info("STAGE 6/8  territory alignment    [GATE G4: contiguity >=95%%, CV within max]")
    log.info("=" * 72)
    from src.models import territory
    territory.run()
    th = manifest().get("territory_headline", {})
    g4 = th.get("contiguity_after", 0) >= 0.95
    log.info("GATE G4 %s -- contiguity %.1f%% (was %.1f%%), CV %.3f (was %.3f)",
             "PASSED" if g4 else "FAILED",
             100 * th.get("contiguity_after", 0), 100 * th.get("contiguity_before", 0),
             th.get("cv_after", 0), th.get("cv_before", 0))
    record("gate_g4", passed=bool(g4))
    results["g4"] = g4

    if not skip_optional:
        log.info("=" * 72)
        log.info("STAGE 7/8  segmentation")
        log.info("=" * 72)
        from src.models import segmentation
        segmentation.run()

        log.info("=" * 72)
        log.info("STAGE 8/8  promotional response")
        log.info("=" * 72)
        from src.models import response
        results["response"] = response.run()

    elapsed = time.time() - t0
    record("pipeline_run", elapsed_seconds=round(elapsed, 1),
           synthetic=synthetic, sample=sample)
    _summary(elapsed)
    return results


def _summary(elapsed: float) -> None:
    m = manifest()
    log.info("=" * 72)
    log.info("PIPELINE COMPLETE in %.0fs", elapsed)
    log.info("=" * 72)

    mode = m.get("data_mode", {}).get("mode", "UNKNOWN")
    if mode == "SYNTHETIC":
        log.warning("DATA MODE: SYNTHETIC. These numbers validate the PIPELINE, not the "
                    "FINDING. Do not put them in a README, a deck, or an interview.")

    for gate in ("gate_g2", "gate_g3", "gate_g4"):
        g = m.get(gate)
        if g:
            log.info("  %s: %s", gate.upper().replace("_", " "),
                     "PASSED" if g.get("passed") else "FAILED (see pre-committed response)")

    h2 = m.get("headline_h2", {})
    if h2:
        log.info("  H2  opportunity-ranked reaches %.1f%% of addressable opportunity vs "
                 "%.1f%% volume-ranked, %.1f%% geography-proportional",
                 100 * h2.get("opportunity_pct_opportunity", 0),
                 100 * h2.get("volume_pct_opportunity", 0),
                 100 * h2.get("geography_pct_opportunity", 0))
    h3 = m.get("headline_h3", {})
    if h3:
        log.info("  H3  (SCENARIO) break-even at %.0f reps vs %d current; sensitivity %.0f-%.0f",
                 h3.get("break_even_n_reps", 0), h3.get("current_n_reps", 0),
                 h3.get("sensitivity_low", 0), h3.get("sensitivity_high", 0))
    th = m.get("territory_headline", {})
    if th:
        log.info("  TERRITORY  imbalance %.1fx -> %.1fx, contiguity %.0f%% -> %.0f%%, "
                 "travel -%.0f%%",
                 th.get("imbalance_before", 0), th.get("imbalance_after", 0),
                 100 * th.get("contiguity_before", 0), 100 * th.get("contiguity_after", 0),
                 100 * th.get("travel_reduction_pct", 0))
    log.info("  full manifest: data/manifest.json")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the PharmaTarget pipeline end to end.")
    ap.add_argument("--synthetic", action="store_true", help="generate synthetic data first")
    ap.add_argument("--sample", action="store_true", help="small synthetic run (~2 min)")
    ap.add_argument("--skip-optional", action="store_true",
                    help="skip segmentation and response modules")
    a = ap.parse_args()
    run(a.synthetic, a.sample, a.skip_optional)


if __name__ == "__main__":
    main()
