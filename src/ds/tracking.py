"""MLflow experiment tracking, local file store at ./mlruns.

Every data-science module logs one run: its parameters, its headline metrics
and the artifacts it wrote. ``python -m src.ds.tracking`` also back-fills runs
for the consulting models (opportunity, back-test, challenger, decision, value)
from the manifest, so the whole project's model history sits in one place:

    mlflow ui --backend-store-uri ./mlruns

Tracking must never break the pipeline: if MLflow is missing or the store is
unwritable, the call logs a warning and returns.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from src.config import ROOT
from src.utils.io import get_logger, manifest

log = get_logger(__name__)

EXPERIMENT = "pharmatarget"
STORE = ROOT / "mlruns"


def _flat(d: dict, prefix: str = "") -> dict[str, float]:
    """Numeric leaves of a nested dict, dotted keys (MLflow metrics are scalars)."""
    out: dict[str, float] = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, bool) or isinstance(v, (int, float)) and v == v:
            out[key] = float(v)
        elif isinstance(v, dict):
            out.update(_flat(v, f"{key}."))
    return out


def log_run(name: str, params: dict[str, Any] | None = None,
            metrics: dict[str, Any] | None = None, artifacts: list[Path] | None = None,
            tags: dict[str, str] | None = None) -> str | None:
    # MLflow probes for git to tag the source commit; without a git binary on
    # the Python PATH that prints a spurious WinError. Quiet the probe.
    os.environ.setdefault("GIT_PYTHON_REFRESH", "quiet")
    try:
        import mlflow
    except ImportError:
        log.warning("mlflow not installed -- run %s not tracked", name)
        return None
    try:
        mlflow.set_tracking_uri(STORE.resolve().as_uri())
        mlflow.set_experiment(EXPERIMENT)
        with mlflow.start_run(run_name=name) as run:
            mlflow.set_tags({"module": name, "data_mode":
                             str((manifest().get("data_mode") or {}).get("mode", "?")),
                             **(tags or {})})
            if params:
                mlflow.log_params({k: (json.dumps(v) if isinstance(v, (list, dict)) else v)
                                   for k, v in params.items()})
            if metrics:
                flat = _flat(metrics)
                # MLflow metric keys allow a restricted character set.
                mlflow.log_metrics({re.sub(r"[^A-Za-z0-9_\-.]", "_", k)[:250]: v
                                    for k, v in flat.items()})
            for a in artifacts or []:
                if Path(a).exists() and Path(a).stat().st_size < 50_000_000:
                    mlflow.log_artifact(str(a))
            log.info("tracked: mlflow run %s (%s)", name, run.info.run_id[:8])
            return run.info.run_id
    except Exception as exc:  # noqa: BLE001 -- tracking must never fail a stage
        log.warning("mlflow tracking failed for %s: %s", name, exc)
        return None


BACKFILL = {
    "opportunity_model": ["potential_model", "sfa_crosscheck", "top_driver", "gate_g2"],
    "backtest": ["gate_g3", "propensity_matched", "bootstrap_headlines"],
    "challenger": ["challenger", "recommendation", "bootstrap_60rep"],
    "decision_lab": ["decision_frontier", "pilot_design"],
    "business_case": ["business_case_value", "retargeting_value"],
    "territory": ["territory_headline", "gate_g4"],
}


def backfill() -> None:
    m = manifest()
    for run, keys in BACKFILL.items():
        metrics = {k: m[k] for k in keys if isinstance(m.get(k), dict)}
        log_run(run, params={"source": "manifest back-fill"}, metrics=metrics,
                tags={"kind": "consulting-model"})


if __name__ == "__main__":
    backfill()
