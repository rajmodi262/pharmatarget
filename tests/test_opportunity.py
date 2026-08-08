"""Tests for the opportunity model.

The leakage tests are the important ones. A leaked target would silently
invalidate the back-test and every number downstream of it, and it would do so
while producing beautiful metrics. These tests raise rather than warn.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.models import opportunity as opp


def _frame(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    panel = rng.lognormal(4.8, 0.7, n)
    return pd.DataFrame({
        "npi": np.arange(n) + 1_400_000_000,
        "year": 2022,
        "panel_benes": panel,
        "non_class_clms": panel * rng.uniform(6, 26, n),
        "age65_cnt": panel * rng.uniform(0.5, 0.9, n),
        "pop_65_plus": rng.lognormal(9.5, 0.8, n),
        "risk_score": rng.normal(1.4, 0.3, n).clip(0.5, 4),
        "pct_panel_65": rng.uniform(0.4, 0.95, n),
        "zip3_pct_65": rng.uniform(0.08, 0.4, n),
        "prev_stroke": rng.uniform(1.5, 8, n),
        "prev_chd": rng.uniform(3, 14, n),
        "prev_bp": rng.uniform(25, 60, n),
        "specialty_group": rng.choice(["Cardiology", "Primary Care", "Hem/Onc"], n),
        "region": rng.choice(["Northeast", "South", "West", "Midwest"], n),
        "class_fills": rng.lognormal(3.5, 1.0, n),
        "brand_fills": rng.lognormal(2.8, 1.0, n),
        "brand_share": rng.uniform(0, 0.95, n),
    })


class TestLeakage:
    def test_named_leak_is_rejected(self):
        """A feature named after the target must raise, not warn."""
        X = pd.DataFrame({"log_panel_benes": [1.0, 2.0, 3.0],
                          "brand_share": [0.1, 0.2, 0.3]})
        with pytest.raises(ValueError, match="Leakage"):
            opp.assert_no_leakage(X, pd.Series([1.0, 2.0, 3.0]), list(X.columns))

    def test_correlated_leak_is_rejected(self):
        """A target transform under an innocent name must also raise."""
        y = pd.Series(np.linspace(1, 100, 200))
        X = pd.DataFrame({"innocuous_name": y * 2.0 + 0.001})
        with pytest.raises(ValueError, match="correlates with the target"):
            opp.assert_no_leakage(X, y, list(X.columns))

    def test_non_class_clms_is_exempt(self):
        """The panel-size proxy contains 'class_clms' but is the opposite of a leak."""
        assert "log_non_class_clms" in opp.EXEMPT_FEATURES
        rng = np.random.default_rng(0)
        X = pd.DataFrame({"log_non_class_clms": rng.normal(size=200)})
        opp.assert_no_leakage(X, pd.Series(rng.normal(size=200)),
                              ["log_non_class_clms"])

    def test_real_feature_list_is_clean(self):
        """Every configured feature survives the guard on realistic data."""
        train = _frame()
        model, enc, names = opp.fit_potential(train)
        assert model is not None
        assert not any(n.startswith("brand") for n in names)


class TestFrontier:
    def test_coverage_matches_tau(self):
        """A tau-quantile fit should leave ~tau of observations below it."""
        train = _frame(600)
        model, enc, _ = opp.fit_potential(train, tau=0.80)
        pred = np.log1p(opp.predict_potential(model, enc, train))
        coverage = (np.log1p(train["class_fills"]) <= pred).mean()
        assert 0.70 <= coverage <= 0.90, f"coverage {coverage:.3f} far from tau=0.80"

    def test_higher_tau_gives_higher_frontier(self):
        """The frontier must be monotone in tau, or it is not a quantile."""
        train = _frame(600)
        m_low, e_low, _ = opp.fit_potential(train, tau=0.50)
        m_high, e_high, _ = opp.fit_potential(train, tau=0.90)
        assert (opp.predict_potential(m_high, e_high, train).mean()
                > opp.predict_potential(m_low, e_low, train).mean())


class TestDecile:
    def test_buckets_are_equal_count(self):
        s = pd.Series(np.random.default_rng(0).lognormal(size=1000))
        d = opp._decile(s)
        counts = d.value_counts()
        assert set(d.unique()) <= set(range(1, 11))
        assert counts.max() - counts.min() <= 1

    def test_handles_mass_at_zero(self):
        """Opportunity has heavy mass at exactly zero -- qcut would fail here."""
        s = pd.Series([0.0] * 500 + list(np.linspace(1, 100, 500)))
        d = opp._decile(s)
        counts = d.value_counts()
        assert counts.max() - counts.min() <= 1, "zero-mass broke the bucketing"

    def test_ordering_is_ascending(self):
        s = pd.Series([5.0, 1.0, 9.0, 3.0])
        d = opp._decile(s)
        assert d.iloc[2] > d.iloc[0] > d.iloc[3] > d.iloc[1]


class TestOpportunityScore:
    def test_never_negative(self):
        train = _frame(400)
        model, enc, _ = opp.fit_potential(train)
        bench = pd.DataFrame([
            {"specialty_group": s, "region": r, "year": 2022, "achievable_share": 0.6}
            for s in train["specialty_group"].unique()
            for r in train["region"].unique()
        ])
        scored = opp.score_opportunity(train, bench, model, enc)
        assert (scored["opportunity"] >= 0).all()

    def test_potential_at_least_actual(self):
        """A prescriber above the fitted frontier keeps their own volume."""
        train = _frame(400)
        model, enc, _ = opp.fit_potential(train)
        bench = pd.DataFrame([
            {"specialty_group": s, "region": r, "year": 2022, "achievable_share": 0.6}
            for s in train["specialty_group"].unique()
            for r in train["region"].unique()
        ])
        scored = opp.score_opportunity(train, bench, model, enc)
        assert (scored["potential_class"] >= scored["class_fills"] - 1e-6).all()
