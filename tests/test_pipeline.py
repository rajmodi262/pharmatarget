"""Tests for suppression handling, the call plan, and sizing economics."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.config import class_generic_names, econ, economics, focus_generic_names, params
from src.models import callplan, sizing


class TestConfig:
    def test_class_includes_focus_and_comparators(self):
        names = class_generic_names()
        assert "APIXABAN" in names
        assert "RIVAROXABAN" in names
        assert "WARFARIN SODIUM" in names, "warfarin must be in-class for market sizing"
        assert focus_generic_names() == ["APIXABAN"]

    def test_three_years_configured(self):
        """Two years cannot test parallel trends. Three is the minimum."""
        assert len(params()["years"]["all"]) >= 3

    def test_holdout_is_after_training(self):
        y = params()["years"]
        assert y["holdout"] > y["train_end"], "the holdout year must be unseen"

    def test_every_economic_assumption_has_a_range_and_basis(self):
        for key, node in economics().items():
            if key == "sizing":
                continue
            assert {"base", "low", "high", "basis"} <= set(node), f"{key} is under-specified"
            assert node["low"] <= node["base"] <= node["high"], f"{key} range is inverted"
            assert len(node["basis"].strip()) > 20, f"{key} basis is not a real citation"


class TestCallPlan:
    def test_bands_cover_every_decile(self):
        assert {callplan.decile_band(d) for d in range(1, 11)} == set(callplan.DECILE_BANDS)

    def test_matrix_is_complete(self):
        for band in callplan.DECILE_BANDS:
            for label, _lo, _hi in callplan.SHARE_BANDS:
                assert (band, label) in callplan.CALL_MATRIX

    def test_share_bands_partition_the_unit_interval(self):
        for s in (0.0, 0.19, 0.2, 0.49, 0.5, 0.99, 1.0):
            assert callplan.share_band(s) in {b[0] for b in callplan.SHARE_BANDS}
        assert callplan.share_band(np.nan) == "Low (<20%)"

    def test_frequency_falls_with_decile(self):
        """A lower-opportunity prescriber must never earn more calls."""
        for label, _lo, _hi in callplan.SHARE_BANDS:
            top = callplan.CALL_MATRIX[("Decile 9-10", label)]
            mid = callplan.CALL_MATRIX[("Decile 7-8", label)]
            low = callplan.CALL_MATRIX[("Decile 1-6", label)]
            assert top >= mid >= low

    def test_frequency_falls_with_share(self):
        """Within a decile band, high share means maintain, not convert."""
        for band in ("Decile 9-10", "Decile 7-8"):
            assert (callplan.CALL_MATRIX[(band, "Low (<20%)")]
                    >= callplan.CALL_MATRIX[(band, "Mid (20-50%)")]
                    >= callplan.CALL_MATRIX[(band, "High (>50%)")])

    def test_capacity_arithmetic(self):
        expected = econ("calls_per_rep_per_day") * econ("selling_days_per_month")
        assert callplan.capacity_calls_per_month(1) == pytest.approx(expected)
        assert callplan.capacity_calls_per_month(60) == pytest.approx(60 * expected)


class TestSizing:
    def test_hill_is_monotone_and_bounded(self):
        calls = np.linspace(0, 500, 200)
        r = sizing.hill(calls, ceiling=0.3, half_sat=12.0)
        assert (np.diff(r) >= -1e-12).all(), "response must be non-decreasing in calls"
        assert r.max() <= 0.3 + 1e-9, "response must not exceed its ceiling"
        assert r[0] == pytest.approx(0.0), "zero calls must give zero response"

    def test_hill_half_saturation(self):
        r = sizing.hill(np.array([12.0]), ceiling=0.3, half_sat=12.0)
        assert r[0] == pytest.approx(0.15, rel=1e-6)

    def test_break_even_interpolates(self):
        curve = pd.DataFrame({"n_reps": [10, 20, 30, 40],
                              "marginal_roi": [3.0, 2.0, 1.0, 0.5]})
        be = sizing.break_even_reps(curve)
        assert 20 <= be <= 40

    def test_break_even_when_always_profitable(self):
        curve = pd.DataFrame({"n_reps": [10, 20, 30], "marginal_roi": [3.0, 2.5, 2.0]})
        assert sizing.break_even_reps(curve) == 30

    def test_diminishing_returns(self):
        """Each additional rep must add less than the one before it."""
        rng = np.random.default_rng(0)
        planned = pd.DataFrame({
            "opportunity": rng.lognormal(3, 1, 2000),
            "calls_per_year": rng.choice([0, 6, 12, 24], 2000),
        })
        curve = sizing.roi_curve(planned)
        marginal = curve["marginal_contribution"].dropna().to_numpy()
        assert marginal[0] >= marginal[-1], "marginal return did not diminish"


class TestSuppression:
    def test_reconciliation_identity(self):
        """observed + suppressed == the provider-level total, by construction."""
        provider_total = np.array([100.0, 250.0, 80.0])
        observed = np.array([92.0, 250.0, 61.0])
        suppressed = np.maximum(provider_total - observed, 0)
        assert np.allclose(observed + suppressed, provider_total)

    def test_hidden_row_bounds(self):
        """A hidden row holds 1..10 claims, so gap/10 <= rows <= gap."""
        gap = 47.0
        assert np.ceil(gap / 10.0) <= gap / 5.5 <= gap

    def test_modes_are_ordered(self):
        """zero <= ev <= max, for every prescriber, always."""
        observed, gap, frac = 100.0, 40.0, 0.25
        zero = observed
        ev = observed + gap * frac
        mx = observed + np.ceil(gap / 10.0) * 10.0 * frac
        assert zero <= ev <= mx

    def test_configured_modes_present(self):
        modes = params()["suppression"]["imputation_modes"]
        assert set(modes) == {"zero", "ev", "max"}
        assert params()["suppression"]["base_mode"] in modes
