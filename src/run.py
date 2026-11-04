"""Resumable, dependency-aware runner for the whole project. Cross-platform.

    python -m src.run                         every stale stage, then a summary
    python -m src.run --only sizing territory just those stages
    python -m src.run --force                 everything, regardless of artifacts
    python -m src.run --list                  the stages and whether each is stale
    python -m src.run --skip-web --serve      no frontend build; start the API after

A stage runs when its artifact is missing or older than any of its sources, so
"fix a bug, re-run" re-runs exactly the stages that bug could have affected, and
an interrupted run loses only the stage in flight. Every stage's output is
appended to data/run.log, so a failure nobody watched is still diagnosable.

This replaces the logic that lived in run_all.ps1. Stage paths are pathlib
objects here: in PowerShell strings, "\\t", "\\v" and "\\f" sequences in Windows
paths were silently turned into control characters three times, and each one
quietly broke a staleness check.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = Path("data/processed")
R = Path("data/raw")
LOG = ROOT / "data" / "run.log"
PY = sys.executable

# Lines worth echoing to the console: the findings, not the firehose.
HIGHLIGHT = re.compile(
    r"GATE|H2 |H3 |suppression:|disagreement|top driver|BASELINE|OPTIMISED @60|capacity cut|"
    r"call plan @|selected k|PRE-TREND|DiD:|SELECTION GAP|CHALLENGER|CHAMPION|tornado:|"
    r"frontier fit|SFA cross|CONTRACTS|LADDER|COVERAGE|DML|UPLIFT|DRIFT|BLEND|PILOT|VALUE")


@dataclass
class Stage:
    name: str
    cmd: list[str]
    artifact: Path | None = None          # None: always runs
    sources: list[Path] = field(default_factory=list)
    critical: bool = False                # a failure stops the run
    group: str = "pipeline"


def _py(module: str, *args: str) -> list[str]:
    return [PY, "-m", module, *args]


def _ds(name: str, artifact: str, extra: list[Path] | None = None) -> Stage:
    return Stage(f"ds-{name}", _py(f"src.ds.{name}"), P / f"{artifact}.parquet",
                 [Path(f"src/ds/{name}.py"), Path("src/ds/data.py"),
                  Path("src/ds/features.py"), P / "hcp_scored.parquet", *(extra or [])],
                 group="ds")


STAGES: list[Stage] = [
    # ---- ingest (each runs only if data/raw is incomplete) ----------------
    Stage("geography", _py("src.ingest.geo_build", "--local-dir", "dataset"),
          R / "zip3_units.csv", [Path("src/ingest/geo_build.py")], group="ingest"),
    Stage("ingest", _py("src.ingest.download", "--local-dir", "dataset"),
          R / "open_payments_2024.csv", [Path("src/ingest/download.py")], group="ingest"),
    # ---- marts -----------------------------------------------------------
    Stage("marts", _py("src.etl.build_marts"), P / "mart_hcp_metrics.parquet",
          [Path("src/etl/build_marts.py"), *sorted(Path("src/sql").glob("*.sql")),
           Path("config/params.yaml")], critical=True),
    # ---- models ----------------------------------------------------------
    Stage("opportunity", _py("src.models.opportunity"), P / "hcp_scored.parquet",
          [Path("src/models/opportunity.py"), P / "mart_hcp_metrics.parquet"], critical=True),
    Stage("callplan", _py("src.models.callplan"), P / "hcp_call_plan.parquet",
          [Path("src/models/callplan.py"), P / "hcp_scored.parquet",
           Path("config/economics.yaml")], critical=True),
    Stage("backtest", _py("src.models.backtest"), P / "backtest_decile_lift.parquet",
          [Path("src/models/backtest.py"), P / "hcp_scored.parquet"]),
    Stage("challenger", _py("src.models.challenger"), P / "challenger_results.parquet",
          [Path("src/models/challenger.py"), P / "hcp_scored.parquet"]),
    # MUST precede sizing: it fits the response curve sizing prices calls with.
    Stage("call-response", _py("src.models.call_response"), P / "call_response_curve.parquet",
          [Path("src/models/call_response.py"), P / "mart_payments.parquet"]),
    Stage("sizing", _py("src.models.sizing"), P / "sizing_tornado.parquet",
          [Path("src/models/sizing.py"), P / "hcp_call_plan.parquet",
           Path("config/economics.yaml"), P / "call_response_curve.parquet"]),
    Stage("territory", _py("src.models.territory"), P / "territory_stats.parquet",
          [Path("src/models/territory.py"), P / "hcp_call_plan.parquet", Path("src/utils/geo.py")]),
    Stage("segmentation", _py("src.models.segmentation"), P / "segment_profiles.parquet",
          [Path("src/models/segmentation.py"), P / "hcp_scored.parquet"]),
    # Writes no saturation parquet when the curve is unidentifiable (a legitimate
    # outcome), so it is keyed off the balance table. It is cheap.
    Stage("response", _py("src.models.response"), P / "response_balance.parquet",
          [Path("src/models/response.py"), P / "mart_hcp_metrics.parquet"]),
    Stage("robustness", _py("src.models.robustness"), P / "robustness_bootstrap.parquet",
          [Path("src/models/robustness.py"), P / "backtest_frame.parquet",
           P / "hcp_call_plan.parquet"]),
    Stage("decision", _py("src.models.decision"), P / "decision_frontier.parquet",
          [Path("src/models/decision.py"), P / "hcp_scored.parquet",
           P / "challenger_results.parquet", P / "territory_assignments.parquet",
           P / "sizing_required_response.parquet"]),
    Stage("value", _py("src.models.value"), P / "decision_value_grid.parquet",
          [Path("src/models/value.py"), Path("config/economics.yaml"),
           P / "hcp_call_plan.parquet", P / "decision_frontier.parquet"]),
    # ---- data-science layer: contracts first, nothing below trusts a mart
    #      that fails them ----------------------------------------------------
    Stage("ds-contracts", _py("src.ds.contracts"), P / "ds_contract_results.parquet",
          [Path("src/ds/contracts.py"), Path("config/contracts.yaml"),
           P / "hcp_scored.parquet", P / "hcp_call_plan.parquet"], critical=True, group="ds"),
    _ds("shrinkage", "ds_shrinkage_h2h"), _ds("evaluation", "ds_ladder"),
    _ds("ceiling", "ds_ceiling", [P / "ds_ladder.parquet"]),
    _ds("conformal", "ds_conformal_coverage"), _ds("errors", "ds_error_segments"),
    _ds("causal", "ds_causal"), _ds("placebo", "ds_placebo", [Path("src/ds/causal.py")]),
    _ds("uplift", "ds_uplift_qini"),
    _ds("explain", "ds_explanations"), _ds("ablation", "ds_ablation"),
    _ds("drift", "ds_drift"), _ds("network", "ds_network"),
    Stage("ds-tracking", _py("src.ds.tracking"), group="ds"),
    # ---- gates, reports, bundle --------------------------------------------
    # G2 and G4 are evaluated in src/pipeline.py, which this runner does not
    # call (it runs modules directly so stages stay independently resumable).
    Stage("gates", _py("src.utils.gates"), group="report"),
    Stage("assets", _py("src.report.make_assets"), Path("outputs/PharmaTarget_Recommendations.pdf"),
          [Path("src/report/make_assets.py"), Path("src/report/ds_report.py"),
           Path("src/report/executive.py"), P / "territory_stats.parquet",
           P / "challenger_results.parquet", Path("data/manifest.json")], group="report"),
    # The slim bundle the Docker image serves. Rebuilt whenever the manifest
    # moves, so a deployment can never show numbers the pipeline has replaced.
    Stage("deploy-bundle", _py("src.report.make_deploy_bundle"), Path("data/deploy/manifest.json"),
          [Path("src/report/make_deploy_bundle.py"), Path("data/manifest.json")], group="report"),
    # ---- checks ------------------------------------------------------------
    Stage("lint", _py("ruff", "check", "src", "api", "tests"), group="check"),
    Stage("tests", _py("pytest", "tests", "-q"), group="check"),
]


# --------------------------------------------------------------------------- #
def _log(msg: str, level: str = "INFO") -> None:
    line = f"{time.strftime('%H:%M:%S')}  {level:<7} {msg}"
    colour = {"OK": "32", "SKIP": "90", "WARN": "33", "FAIL": "31", "STAGE": "36"}.get(level)
    print(f"\033[{colour}m{line}\033[0m" if colour and sys.stdout.isatty() else line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def _mtime(p: Path) -> float:
    """Newest mtime under p (a directory counts as its newest file)."""
    p = ROOT / p
    if p.is_dir():
        return max((f.stat().st_mtime for f in p.rglob("*") if f.is_file()), default=0.0)
    return p.stat().st_mtime if p.exists() else 0.0


def stale(stage: Stage) -> bool:
    if stage.artifact is None:
        return True
    target = ROOT / stage.artifact
    if not target.exists():
        return True
    built = target.stat().st_mtime
    return any(_mtime(s) > built for s in stage.sources)


def _npm() -> str | None:
    local = ROOT / ".tools" / "node-v22.20.0-win-x64"
    if (local / "npm.cmd").exists():
        os.environ["PATH"] = f"{local}{os.pathsep}{os.environ['PATH']}"
        return str(local / "npm.cmd")
    return shutil.which("npm")


def web_stages() -> list[Stage]:
    npm = _npm()
    if npm is None:
        _log("npm not found -- skipping the frontend build; the API serves web/static", "WARN")
        return []
    out = []
    if not (ROOT / "web" / "node_modules").exists():
        out.append(Stage("web-install", [npm, "--prefix", "web", "ci", "--no-fund", "--no-audit"],
                         Path("web/node_modules/.package-lock.json"), group="web"))
    out.append(Stage("web-build", [npm, "--prefix", "web", "run", "build"], Path("web/dist/index.html"),
                     [Path("web/src"), Path("web/package.json"), Path("web/vite.config.ts")],
                     group="web"))
    return out


def run_stage(stage: Stage) -> bool:
    _log(f"=== {stage.name} ===", "STAGE")
    t0 = time.time()
    proc = subprocess.run(stage.cmd, cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    out = (proc.stdout + proc.stderr).splitlines()
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.writelines(f"    {line}\n" for line in out)
    secs = time.time() - t0
    if proc.returncode != 0:
        _log(f"{stage.name} FAILED (exit {proc.returncode}) after {secs:.0f}s", "FAIL")
        for line in out[-12:]:
            print(f"    {line}")
        return False
    for line in [x for x in out if HIGHLIGHT.search(x)][-8:]:
        print(f"    {line.strip()}")
    _log(f"{stage.name} OK in {secs:.0f}s", "OK")
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", nargs="+", metavar="STAGE", help="run just these stages")
    ap.add_argument("--force", action="store_true", help="re-run every stage")
    ap.add_argument("--skip-web", action="store_true", help="skip the frontend build")
    ap.add_argument("--serve", action="store_true", help="start the API afterwards")
    ap.add_argument("--list", action="store_true", help="list stages and staleness, run nothing")
    a = ap.parse_args(argv)

    LOG.parent.mkdir(parents=True, exist_ok=True)
    stages = STAGES + ([] if a.skip_web else web_stages())
    names = {s.name for s in stages}
    if a.only and (unknown := set(a.only) - names):
        ap.error(f"unknown stage(s): {', '.join(sorted(unknown))}. Known: {', '.join(s.name for s in stages)}")

    if a.list:
        for s in stages:
            state = "always" if s.artifact is None else ("STALE" if stale(s) else "current")
            print(f"  {s.group:<9} {s.name:<16} {state}")
        return 0

    _log(f"PharmaTarget run started -- log: {LOG.relative_to(ROOT)}", "STAGE")
    ran, skipped, failed = [], [], []
    for s in stages:
        if a.only and s.name not in a.only:
            continue
        if not a.force and not a.only and not stale(s):
            _log(f"{s.name} -- artifact current, skipping", "SKIP")
            skipped.append(s.name)
            continue
        if run_stage(s):
            ran.append(s.name)
        else:
            failed.append(s.name)
            if s.critical:
                _log(f"{s.name} is critical -- stopping. See {LOG.relative_to(ROOT)}", "FAIL")
                return 1

    _log("=== SUMMARY ===", "STAGE")
    _log(f"ran: {', '.join(ran) or 'nothing'}")
    if skipped:
        _log(f"skipped (current): {', '.join(skipped)}", "SKIP")
    if failed:
        _log(f"FAILED: {', '.join(failed)}", "FAIL")
    if (ROOT / "data" / "manifest.json").exists():
        subprocess.run(_py("src.utils.summary"), cwd=ROOT)
    _log("finished WITH FAILURES" if failed else "finished cleanly", "FAIL" if failed else "OK")

    if a.serve and not failed:
        _log("starting the API on http://127.0.0.1:8000  (Ctrl+C to stop)", "STAGE")
        subprocess.run(_py("uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000"), cwd=ROOT)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
