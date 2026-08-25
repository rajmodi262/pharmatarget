"""Tests for the acceptance gates.

The gates decide whether the project's conclusions are trustworthy, and they
were at 0% coverage -- so nothing checked that the checks work. That is the
failure mode gates.py itself was written to fix: its module docstring records
that G2 and G4 silently never ran during a full `run_all.ps1` pass, producing a
manifest with one gate where three were expected. "Nothing failed; the checks
simply never happened" is the worst kind of missing check, and an untested gate
is the same bug one level up.

Every test monkeypatches `manifest`, `read_parquet`, `params` and `record` on
the gates module. These functions read and write real pipeline artifacts, and a
test run must not consult -- or overwrite -- the state of an actual run.
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.utils import gates


TERRITORY_CFG = {
    "n_reps_default": 60,
    "min_contiguity_rate": 0.95,
    "max_cv": 0.20,
}


@pytest.fixture
def recorded(monkeypatch):
    calls: dict[str, dict] = {}
    monkeypatch.setattr(gates, "record", lambda key, **f: calls.__setitem__(key, f))
    return calls


@pytest.fixture
def fake_params(monkeypatch):
    monkeypatch.setattr(gates, "params", lambda: {"territory": dict(TERRITORY_CFG)})


def _stats(contiguity: float, cv: float, n_reps: int = 60,
           alignment: str = "optimised") -> pd.DataFrame:
    return pd.DataFrame([{
        "alignment": alignment,
        "n_reps": n_reps,
        "contiguity_rate": contiguity,
        "workload_cv": cv,
    }])


def _use_stats(monkeypatch, df: pd.DataFrame) -> None:
    monkeypatch.setattr(gates, "read_parquet", lambda _p: df)
    monkeypatch.setattr(gates, "path", lambda _k: __import__("pathlib").Path("."))


# --------------------------------------------------------------------------- #
# G2 -- opportunity must differ from volume
# --------------------------------------------------------------------------- #
class TestGateG2:
    def test_passes_when_enough_prescribers_move(self, monkeypatch, recorded):
        monkeypatch.setattr(gates, "manifest",
                            lambda: {"disagreement": {"disagree_by_2plus_pct": 0.594}})
        v = gates.gate_g2()
        assert v["passed"] is True
        assert v["disagree_pct"] == 0.594
        assert recorded["gate_g2"]["passed"] is True

    def test_fails_when_opportunity_merely_tracks_volume(self, monkeypatch, recorded):
        """If the two rankings agree, there is no project to have."""
        monkeypatch.setattr(gates, "manifest",
                            lambda: {"disagreement": {"disagree_by_2plus_pct": 0.05}})
        v = gates.gate_g2()
        assert v["passed"] is False
        assert recorded["gate_g2"]["passed"] is False

    def test_threshold_is_inclusive_at_thirty_percent(self, monkeypatch, recorded):
        monkeypatch.setattr(gates, "manifest",
                            lambda: {"disagreement": {"disagree_by_2plus_pct": 0.30}})
        assert gates.gate_g2()["passed"] is True

    def test_just_below_threshold_fails(self, monkeypatch, recorded):
        monkeypatch.setattr(gates, "manifest",
                            lambda: {"disagreement": {"disagree_by_2plus_pct": 0.2999}})
        assert gates.gate_g2()["passed"] is False

    def test_missing_measurement_fails_rather_than_passing(self, monkeypatch, recorded):
        """A gate with no input must not report success.

        This is the exact shape of the bug gates.py exists to prevent: an absent
        check reading as a passed one.
        """
        monkeypatch.setattr(gates, "manifest", lambda: {})
        v = gates.gate_g2()
        assert v["passed"] is False
        assert v["disagree_pct"] is None

    def test_verdict_carries_its_criterion(self, monkeypatch, recorded):
        monkeypatch.setattr(gates, "manifest",
                            lambda: {"disagreement": {"disagree_by_2plus_pct": 0.5}})
        assert "2+ deciles" in gates.gate_g2()["criterion"]


# --------------------------------------------------------------------------- #
# G4 -- territories must be implementable
# --------------------------------------------------------------------------- #
@pytest.mark.usefixtures("fake_params")
class TestGateG4:
    def test_passes_when_contiguous_and_balanced(self, monkeypatch, recorded):
        _use_stats(monkeypatch, _stats(contiguity=1.00, cv=0.16))
        v = gates.gate_g4()
        assert v["passed"] is True
        assert v["conditions"] == {"contiguous": True, "balanced": True}

    def test_fails_on_detached_islands(self, monkeypatch, recorded):
        """A territory map with detached pieces is not a map a rep can drive."""
        _use_stats(monkeypatch, _stats(contiguity=0.80, cv=0.16))
        v = gates.gate_g4()
        assert v["passed"] is False
        assert v["conditions"]["contiguous"] is False
        assert v["conditions"]["balanced"] is True

    def test_fails_on_workload_imbalance(self, monkeypatch, recorded):
        _use_stats(monkeypatch, _stats(contiguity=1.00, cv=0.35))
        v = gates.gate_g4()
        assert v["passed"] is False
        assert v["conditions"]["balanced"] is False

    def test_both_conditions_required(self, monkeypatch, recorded):
        _use_stats(monkeypatch, _stats(contiguity=0.50, cv=0.90))
        v = gates.gate_g4()
        assert v["passed"] is False
        assert v["conditions"] == {"contiguous": False, "balanced": False}

    def test_thresholds_are_inclusive_at_the_boundary(self, monkeypatch, recorded):
        _use_stats(monkeypatch, _stats(contiguity=0.95, cv=0.20))
        assert gates.gate_g4()["passed"] is True

    def test_falls_back_to_any_optimised_alignment(self, monkeypatch, recorded):
        """The default rep count may not have been solved; a 40-rep row still counts."""
        _use_stats(monkeypatch, _stats(contiguity=0.98, cv=0.18, n_reps=40))
        v = gates.gate_g4()
        assert v["passed"] is True

    def test_baseline_only_stats_are_not_evaluable(self, monkeypatch, recorded):
        """Grading the un-optimised baseline would be grading the wrong thing."""
        _use_stats(monkeypatch, _stats(contiguity=1.0, cv=0.1, alignment="baseline"))
        v = gates.gate_g4()
        assert v["passed"] is False
        assert v["computable"] is False
        assert "gate_g4" not in recorded, "an unevaluable gate must not record a verdict"

    def test_missing_cv_is_treated_as_worst_case(self, monkeypatch, recorded):
        """None must fail closed, not be silently skipped."""
        _use_stats(monkeypatch, _stats(contiguity=1.00, cv=None))
        v = gates.gate_g4()
        assert v["passed"] is False
        assert v["workload_cv"] == 1.0


# --------------------------------------------------------------------------- #
# run()
# --------------------------------------------------------------------------- #
@pytest.mark.usefixtures("fake_params")
def test_run_reports_both_gates(monkeypatch, recorded):
    """The bug this module fixed was a manifest carrying one gate, not three."""
    monkeypatch.setattr(gates, "manifest",
                        lambda: {"disagreement": {"disagree_by_2plus_pct": 0.594}})
    _use_stats(monkeypatch, _stats(contiguity=1.00, cv=0.16))

    out = gates.run()
    assert set(out) == {"g2", "g4"}
    assert out["g2"]["gate"] == "G2"
    assert out["g4"]["gate"] == "G4"
    assert {"gate_g2", "gate_g4"} <= set(recorded)
