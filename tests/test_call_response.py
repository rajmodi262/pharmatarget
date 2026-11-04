"""Tests for the fitted call-response curve.

This module was at 0% coverage, which is the wrong way round for the same
reason `response.py` was: it produces the two numbers that every dollar figure
in the project descends from.

Before this module existed, sizing read them out of config/economics.yaml:

    call_response_ceiling: 0.28
    call_response_half_saturation: 12.0

Those were invented, and sizing's own tornado said break-even swung 229 reps
across the stated range of one of them. Fitting the curve instead of asserting
it is what moved the recommendation from "hire 526 more reps" to "don't hire,
retarget" -- so an untested fitter sits directly underneath the headline.

THREE THINGS THESE TESTS PIN
----------------------------
1. THE BOUNDS. `response.fit_saturation` had to be bounded because unbounded
   `curve_fit` returns a NEGATIVE half-saturation whenever the response is
   negative, which implies response rises without limit as spend falls. The
   same failure mode is available here, and the same guard is in place
   (ceiling in [0, 1], half in [0.5, 60]). `TestBoundsHoldUnderPathology`
   keeps it closed.

2. THE FALLBACK. When there is too little dose-response to fit, this must
   return `{"fitted": False}` so sizing keeps the configured values and labels
   them as configured. Returning a garbage fit instead would be worse than not
   fitting at all, because it would look measured.

3. THE BASELINE SUBTRACTION. `stratified_curve` removes the zero-call stratum
   mean before pooling. That subtraction is the entire difference between a
   dose-response and a raw correlation between calls and growth -- reps visit
   prescribers who were already winning.

`record()` writes to data/manifest.json, so every test touching `fit_hill`
monkeypatches it. Tests must not mutate the run manifest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.models import call_response
from src.models.call_response import MIN_STRATUM, fit_hill, hill, stratified_curve


@pytest.fixture
def recorded(monkeypatch):
    """Capture record() calls instead of writing them to data/manifest.json."""
    calls: dict[str, dict] = {}

    def fake_record(key: str, **fields) -> None:
        calls[key] = fields

    monkeypatch.setattr(call_response, "record", fake_record)
    return calls


# --------------------------------------------------------------------------- #
# hill -- the saturation shape itself
# --------------------------------------------------------------------------- #
class TestHill:
    def test_no_calls_produce_no_response(self):
        assert hill(0.0, ceiling=0.3, half=12.0) == pytest.approx(0.0)

    def test_half_saturation_is_where_half_the_ceiling_is_reached(self):
        """This is the definition of the parameter, and the reason sizing can
        reason about 'calls to half effect' at all. If it drifts, every
        marginal-ROI statement built on it drifts with it."""
        assert hill(12.0, ceiling=0.3, half=12.0) == pytest.approx(0.15)

    def test_response_saturates_towards_the_ceiling(self):
        far = hill(1e6, ceiling=0.3, half=12.0)

        assert far == pytest.approx(0.3, rel=1e-4)
        assert far < 0.3, "Michaelis-Menten approaches the ceiling, never exceeds it"

    def test_response_is_monotonically_increasing(self):
        calls = np.arange(0, 40, dtype=float)
        y = hill(calls, ceiling=0.3, half=12.0)

        assert np.all(np.diff(y) > 0)

    def test_zero_half_saturation_does_not_divide_by_zero(self):
        """`np.maximum(half, 1e-6)` guards this. curve_fit's lower bound is 0.5,
        but hill() is also called directly from sizing."""
        out = hill(np.array([0.0, 1.0, 10.0]), ceiling=0.3, half=0.0)

        assert np.all(np.isfinite(out))

    def test_accepts_a_scalar_or_an_array(self):
        assert np.isscalar(hill(5.0, 0.3, 12.0)) or hill(5.0, 0.3, 12.0).ndim == 0
        assert hill(np.array([1.0, 2.0]), 0.3, 12.0).shape == (2,)


# --------------------------------------------------------------------------- #
# stratified_curve -- confounding control
# --------------------------------------------------------------------------- #
def _panel(decile: int, spec: dict[float, tuple[int, float]]) -> pd.DataFrame:
    """One volume decile. spec maps call level -> (n rows, captured value)."""
    rows = []
    for calls, (n, captured) in spec.items():
        rows.extend({"vol_decile": decile, "calls": calls, "captured": captured}
                    for _ in range(n))
    return pd.DataFrame(rows)


class TestStratifiedCurve:
    def test_zero_call_baseline_is_subtracted(self):
        """Each point must become 'how much MORE headroom did prescribers at
        this call level capture than otherwise-similar prescribers who got no
        visits'. Without the subtraction this is a correlation, not a curve."""
        df = _panel(1, {0.0: (MIN_STRATUM, 0.10), 4.0: (MIN_STRATUM, 0.25)})
        out = stratified_curve(df)

        at_four = out.loc[out["calls"] == 4.0, "captured_excess"].iloc[0]
        assert at_four == pytest.approx(0.15)

    def test_a_stratum_without_enough_baseline_is_dropped(self):
        """With too few zero-call prescribers the stratum mean is noise, and
        subtracting noise manufactures a dose-response that is not there."""
        df = _panel(1, {0.0: (MIN_STRATUM - 1, 0.10), 4.0: (MIN_STRATUM, 0.25)})
        out = stratified_curve(df)

        assert out.empty

    def test_a_thin_cell_is_dropped(self):
        df = _panel(1, {0.0: (MIN_STRATUM, 0.10),
                        4.0: (MIN_STRATUM, 0.25),
                        9.0: (MIN_STRATUM - 1, 0.90)})
        out = stratified_curve(df)

        assert 9.0 not in set(out["calls"])

    def test_pooling_is_weighted_by_cell_size(self):
        """A thin high-decile cell must not drag the pooled curve. Decile 1
        contributes 4x the prescribers, so the pooled excess must sit near its
        value, not midway between the two."""
        df = pd.concat([
            _panel(1, {0.0: (4 * MIN_STRATUM, 0.0), 4.0: (4 * MIN_STRATUM, 0.10)}),
            _panel(2, {0.0: (MIN_STRATUM, 0.0), 4.0: (MIN_STRATUM, 0.50)}),
        ], ignore_index=True)
        out = stratified_curve(df)

        pooled = out.loc[out["calls"] == 4.0, "captured_excess"].iloc[0]
        assert pooled == pytest.approx((4 * 0.10 + 1 * 0.50) / 5)
        assert pooled < 0.30, "unweighted pooling would have returned 0.30"

    def test_returns_empty_frame_when_nothing_qualifies(self):
        df = _panel(1, {0.0: (10, 0.1), 4.0: (10, 0.2)})

        assert stratified_curve(df).empty

    def test_output_is_sorted_by_call_level(self):
        df = _panel(1, {0.0: (MIN_STRATUM, 0.0), 9.0: (MIN_STRATUM, 0.3),
                        2.0: (MIN_STRATUM, 0.1)})
        out = stratified_curve(df)

        assert out["calls"].is_monotonic_increasing


# --------------------------------------------------------------------------- #
# fit_hill -- the fallback, and the bounds
# --------------------------------------------------------------------------- #
def _pooled(calls: list[float], excess: list[float], n: int = 5_000) -> pd.DataFrame:
    return pd.DataFrame({"calls": calls, "captured_excess": excess,
                         "n": [n] * len(calls)})


class TestFitFallback:
    def test_too_few_call_levels_does_not_fit(self, recorded):
        """Sizing must keep the CONFIGURED values and say so. A garbage fit
        here would be worse than no fit, because it would look measured."""
        out = fit_hill(_pooled([0.0, 1.0, 2.0], [0.0, 0.05, 0.08]), n_boot=5)

        assert out == {"fitted": False}

    def test_all_zero_call_levels_do_not_fit(self, recorded):
        out = fit_hill(_pooled([0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0]), n_boot=5)

        assert out == {"fitted": False}

    def test_a_failed_fit_records_nothing(self, recorded):
        """record() is only reached on the success path -- run() records the
        `fitted: False` case itself, so a double-record would overwrite."""
        fit_hill(_pooled([0.0, 1.0, 2.0], [0.0, 0.05, 0.08]), n_boot=5)

        assert "call_response_fit" not in recorded


class TestBoundsHoldUnderPathology:
    def test_a_negative_response_is_clamped_to_a_zero_ceiling(self, recorded):
        """`response.fit_saturation` had to be bounded because an unbounded fit
        on a negative response returns a NEGATIVE half-saturation, implying
        response rises without limit as spend falls -- and that would flow into
        sizing as a Hill parameter. Here the fit succeeds and the bounds pin it
        at the floor instead: no response, rather than an inverted one."""
        calls = [0.0, 2.0, 4.0, 8.0, 16.0, 32.0]
        out = fit_hill(_pooled(calls, [0.0, -0.05, -0.09, -0.14, -0.19, -0.22]),
                       n_boot=10)

        assert out["fitted"] is True
        assert out["ceiling"] == 0.0
        assert out["half_saturation_calls"] >= 0.5

    def test_an_impossible_response_refuses_to_fit(self, recorded):
        """A captured-headroom of 22.0 is 22x more headroom than exists. The
        initial guess is seeded from y.max(), so it lands outside the ceiling
        bound of 1.0 and curve_fit rejects it -- the fit is REFUSED rather than
        clamped silently to 1.0, and sizing falls back to config. Refusing is
        the right answer: this input is not a curve, it is a unit error."""
        calls = [0.0, 2.0, 4.0, 8.0, 16.0, 32.0]
        out = fit_hill(_pooled(calls, [0.0, 5.0, 9.0, 14.0, 19.0, 22.0]), n_boot=10)

        assert out == {"fitted": False}

    def test_a_near_linear_response_pins_half_saturation_at_the_upper_bound(self, recorded):
        """Upper bound 60 calls/year. Beyond it the curve is indistinguishable
        from a straight line over the observed range and the parameter is not
        identified -- so it saturates at the bound rather than running away."""
        calls = [0.0, 2.0, 4.0, 8.0, 16.0, 32.0]
        out = fit_hill(_pooled(calls, [0.0, 0.002, 0.004, 0.008, 0.015, 0.03]),
                       n_boot=10)

        assert out["fitted"] is True
        assert out["half_saturation_calls"] == 60.0
        assert 0.0 <= out["ceiling"] <= 1.0


class TestFitRecoversKnownParameters:
    @pytest.fixture
    def clean_curve(self) -> pd.DataFrame:
        calls = [0.0, 1.0, 2.0, 4.0, 6.0, 9.0, 12.0, 18.0, 24.0, 36.0]
        y = hill(np.array(calls), ceiling=0.30, half=12.0)
        return _pooled(calls, list(y))

    def test_recovers_the_generating_parameters(self, clean_curve, recorded):
        out = fit_hill(clean_curve, n_boot=25)

        assert out["fitted"] is True
        assert out["ceiling"] == pytest.approx(0.30, abs=0.02)
        assert out["half_saturation_calls"] == pytest.approx(12.0, abs=1.0)

    def test_noiseless_data_gives_near_perfect_weighted_r2(self, clean_curve, recorded):
        out = fit_hill(clean_curve, n_boot=25)

        assert out["weighted_r2"] > 0.99

    def test_confidence_intervals_bracket_the_point_estimate(self, clean_curve, recorded):
        out = fit_hill(clean_curve, n_boot=50)

        lo, hi = out["ceiling_ci"]
        assert lo <= out["ceiling"] <= hi
        lo, hi = out["half_saturation_ci"]
        assert lo <= out["half_saturation_calls"] <= hi

    def test_the_result_carries_its_own_caveat(self, clean_curve, recorded):
        """The ceiling is an UPPER BOUND -- volume stratification removes size
        but not rep selection within a stratum. Anything consuming this dict
        must be able to read that from the dict itself, not from the docstring."""
        out = fit_hill(clean_curve, n_boot=25)

        assert "UPPER BOUND" in out["caveat"]
        assert "food-and-beverage" in out["identified_from"]

    def test_a_successful_fit_is_recorded(self, clean_curve, recorded):
        out = fit_hill(clean_curve, n_boot=25)

        assert recorded["call_response_fit"]["ceiling"] == out["ceiling"]

    def test_reports_the_evidence_it_was_fitted_on(self, clean_curve, recorded):
        out = fit_hill(clean_curve, n_boot=25)

        assert out["n_levels"] == 10
        assert out["n_prescribers"] == int(clean_curve["n"].sum())
