"""Tests for the uncertainty and sensitivity layer.

robustness.py exists to answer "how much of the analysis survives being pushed
on", and it was itself unpushed-on at 0% coverage. Two of its outputs are quoted
directly in the README and the deck -- the bootstrap intervals on the capture
ratios, and the tau band showing rho >= 0.980 within +/-0.05 -- so a silent
error here misstates the project's own robustness claim.

The tau tests stub `opp.fit_potential` / `opp.score_opportunity`. Refitting the
frontier six times is the expensive part and it is not what needs testing: the
logic under test is the near/far band split and the verdict thresholds, which
decide whether the project is allowed to call tau "a tuning choice, not the
finding".
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.models import robustness as rb


@pytest.fixture
def recorded(monkeypatch):
    calls: dict[str, dict] = {}
    monkeypatch.setattr(rb, "record", lambda key, **f: calls.__setitem__(key, f))
    return calls


def _holdout(n: int = 600, seed: int = 0) -> pd.DataFrame:
    """A holdout frame where absolute growth scales with volume, as it really does."""
    rng = np.random.default_rng(seed)
    class_fills = rng.lognormal(4.2, 1.1, n)
    brand_share = rng.beta(2.0, 3.0, n)
    share_growth = rng.normal(0.01, 0.05, n)
    return pd.DataFrame({
        "npi": np.arange(n) + 1_600_000_000,
        "class_fills": class_fills,
        "brand_share": brand_share,
        "opportunity": class_fills * (0.75 - brand_share).clip(0),
        "opportunity_decile": rng.integers(1, 11, n),
        "brand_growth_abs": class_fills * share_growth,
        "share_growth": share_growth,
    })


# --------------------------------------------------------------------------- #
# _metrics
# --------------------------------------------------------------------------- #
class TestMetrics:
    def test_capture_fractions_are_proportions(self):
        out = rb._metrics(_holdout(), n_budget=120)
        for key in ("opportunity_abs", "opportunity_share", "volume_abs", "volume_share"):
            assert 0.0 <= out[key] <= 1.0, f"{key} is a share of a total, not a count"

    def test_ratios_are_the_two_captures_divided(self):
        out = rb._metrics(_holdout(), n_budget=120)
        assert out["share_ratio"] == pytest.approx(
            out["opportunity_share"] / out["volume_share"])
        assert out["abs_ratio"] == pytest.approx(
            out["opportunity_abs"] / out["volume_abs"])

    def test_volume_rule_wins_absolute_capture_by_construction(self):
        """Large prescribers grow more in absolute terms whether or not anyone calls.

        This is the mechanical relationship the back-test has to reason around,
        and the reason absolute capture is reported but never a pass condition.
        """
        out = rb._metrics(_holdout(), n_budget=120)
        assert out["volume_abs"] > out["opportunity_abs"]

    def test_a_larger_budget_captures_at_least_as_much(self):
        df = _holdout()
        small = rb._metrics(df, n_budget=60)
        large = rb._metrics(df, n_budget=300)
        assert large["opportunity_abs"] >= small["opportunity_abs"]
        assert large["volume_share"] >= small["volume_share"]

    def test_no_growth_anywhere_yields_nan_not_a_divide_by_zero(self):
        df = _holdout()
        df["brand_growth_abs"] = 0.0
        df["share_growth"] = 0.0
        out = rb._metrics(df, n_budget=100)
        assert np.isnan(out["opportunity_abs"])
        assert np.isnan(out["volume_share"])

    def test_budget_covering_everyone_captures_all_positive_growth(self):
        df = _holdout(n=200)
        out = rb._metrics(df, n_budget=200)
        assert out["opportunity_abs"] == pytest.approx(1.0)
        assert out["share_ratio"] == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# bootstrap_headlines
# --------------------------------------------------------------------------- #
class TestBootstrapHeadlines:
    def test_intervals_bracket_their_point_estimates(self, recorded):
        out = rb.bootstrap_headlines(_holdout(), n_boot=40)
        assert not out.empty
        assert (out["ci_low"] <= out["estimate"]).all()
        assert (out["estimate"] <= out["ci_high"]).all()
        assert (out["ci_low"] <= out["ci_high"]).all()

    def test_standard_errors_are_non_negative(self, recorded):
        out = rb.bootstrap_headlines(_holdout(), n_boot=40)
        assert (out["se"] >= 0).all()

    def test_excludes_one_is_set_for_ratios_only(self, recorded):
        """'Beats 1.0' is the question for a ratio and meaningless for a capture."""
        out = rb.bootstrap_headlines(_holdout(), n_boot=40).set_index("metric")
        for ratio in ("share_ratio", "abs_ratio"):
            assert out.loc[ratio, "excludes_one"] in (True, False)
        for capture in ("opportunity_abs", "volume_share"):
            assert out.loc[capture, "excludes_one"] is None

    def test_excludes_one_agrees_with_the_reported_interval(self, recorded):
        out = rb.bootstrap_headlines(_holdout(), n_boot=40)
        ratios = out[out["metric"].str.endswith("_ratio")]
        for r in ratios.itertuples(index=False):
            assert r.excludes_one == (r.ci_low > 1.0)

    def test_result_is_deterministic(self, recorded):
        """A fixed seed is what lets a reviewer reproduce the interval."""
        a = rb.bootstrap_headlines(_holdout(), n_boot=30)
        b = rb.bootstrap_headlines(_holdout(), n_boot=30)
        pd.testing.assert_frame_equal(a, b)

    def test_records_every_metric_as_a_low_point_high_triple(self, recorded):
        rb.bootstrap_headlines(_holdout(), n_boot=30)
        rec = recorded["bootstrap_headlines"]
        assert rec["n_boot"] == 30
        triple = rec["share_ratio"]
        assert len(triple) == 3 and triple[0] <= triple[1] <= triple[2]


# --------------------------------------------------------------------------- #
# _smd
# --------------------------------------------------------------------------- #
class TestSmd:
    def test_identical_series_are_balanced(self):
        a = pd.Series([1.0, 2.0, 3.0, 4.0])
        assert rb._smd(a, a.copy()) == pytest.approx(0.0)

    def test_zero_variance_does_not_divide_by_zero(self):
        out = rb._smd(pd.Series([2.0, 2.0, 2.0]), pd.Series([9.0, 9.0, 9.0]))
        assert np.isfinite(out)


# --------------------------------------------------------------------------- #
# tau_sensitivity -- the band logic behind "a tuning choice, not the finding"
# --------------------------------------------------------------------------- #
def _stub_opportunity(monkeypatch, orderings: dict[float, np.ndarray], npis: np.ndarray):
    """Return a controlled ranking per tau instead of refitting the frontier."""
    state = {"tau": None}

    def fake_fit(train, tau):
        state["tau"] = tau
        return object(), object(), None

    def fake_score(train, benchmarks, model, enc):
        order = orderings[state["tau"]]
        return pd.DataFrame({
            "npi": npis,
            "opportunity": order.astype(float),
            "opportunity_decile": pd.qcut(pd.Series(order).rank(method="first"),
                                          10, labels=False).to_numpy() + 1,
        })

    monkeypatch.setattr(rb.opp, "fit_potential", fake_fit)
    monkeypatch.setattr(rb.opp, "score_opportunity", fake_score)


@pytest.fixture
def tau_params(monkeypatch):
    monkeypatch.setattr(rb, "params", lambda: {
        "years": {"train_end": 2023},
        "opportunity_model": {"tau": 0.80},
    })


def _train_frame(n: int = 300) -> pd.DataFrame:
    return pd.DataFrame({
        "npi": np.arange(n) + 1_700_000_000,
        "year": 2023,
        "class_fills": np.linspace(10.0, 5_000.0, n),
    })


@pytest.mark.usefixtures("tau_params")
class TestTauSensitivity:
    def test_identical_rankings_are_perfectly_robust(self, monkeypatch, recorded):
        train = _train_frame()
        npis = train["npi"].to_numpy()
        base = np.arange(len(npis))
        _stub_opportunity(monkeypatch, {t: base.copy() for t in rb.TAU_GRID}, npis)

        out = rb.tau_sensitivity(train, pd.DataFrame(), grid=rb.TAU_GRID)
        assert out["spearman_vs_base"].tolist() == pytest.approx([1.0] * len(rb.TAU_GRID))
        assert recorded["tau_sensitivity"]["robust_within_near_band"] is True

    def test_baseline_tau_compares_to_itself_exactly(self, monkeypatch, recorded):
        train = _train_frame()
        npis = train["npi"].to_numpy()
        rng = np.random.default_rng(3)
        orderings = {t: rng.permutation(len(npis)) for t in rb.TAU_GRID}
        orderings[0.80] = np.arange(len(npis))
        _stub_opportunity(monkeypatch, orderings, npis)

        out = rb.tau_sensitivity(train, pd.DataFrame(), grid=rb.TAU_GRID)
        row = out[out["tau"] == 0.80].iloc[0]
        assert row["spearman_vs_base"] == pytest.approx(1.0)
        assert row["same_decile_pct"] == pytest.approx(1.0)
        assert row["top3_decile_retained"] == pytest.approx(1.0)

    def test_a_reshuffled_near_band_fails_the_verdict(self, monkeypatch, recorded):
        """If +/-0.05 reshuffles the deciles, the finding is an artefact of tau."""
        train = _train_frame()
        npis = train["npi"].to_numpy()
        rng = np.random.default_rng(1)
        base = np.arange(len(npis))
        orderings = {t: base.copy() for t in rb.TAU_GRID}
        for t in (0.75, 0.85):
            orderings[t] = rng.permutation(len(npis))
        _stub_opportunity(monkeypatch, orderings, npis)

        rb.tau_sensitivity(train, pd.DataFrame(), grid=rb.TAU_GRID)
        assert recorded["tau_sensitivity"]["robust_within_near_band"] is False

    def test_far_band_instability_alone_does_not_fail_the_verdict(self, monkeypatch, recorded):
        """Graded, not binary. Degrading past +/-0.05 is expected and reported."""
        train = _train_frame()
        npis = train["npi"].to_numpy()
        rng = np.random.default_rng(2)
        base = np.arange(len(npis))
        orderings = {t: base.copy() for t in rb.TAU_GRID}
        for t in (0.65, 0.90):
            orderings[t] = rng.permutation(len(npis))
        _stub_opportunity(monkeypatch, orderings, npis)

        rb.tau_sensitivity(train, pd.DataFrame(), grid=rb.TAU_GRID)
        rec = recorded["tau_sensitivity"]
        assert rec["robust_within_near_band"] is True
        assert rec["far_band_spearman"] < rec["near_band_spearman"]

    def test_reports_one_row_per_grid_value(self, monkeypatch, recorded):
        train = _train_frame()
        npis = train["npi"].to_numpy()
        base = np.arange(len(npis))
        _stub_opportunity(monkeypatch, {t: base.copy() for t in rb.TAU_GRID}, npis)

        out = rb.tau_sensitivity(train, pd.DataFrame(), grid=rb.TAU_GRID)
        assert list(out["tau"]) == list(rb.TAU_GRID)
        assert set(out.columns) == {"tau", "spearman_vs_base", "same_decile_pct",
                                    "within_one_decile_pct", "top3_decile_retained"}

    def test_within_one_decile_is_never_below_same_decile(self, monkeypatch, recorded):
        train = _train_frame()
        npis = train["npi"].to_numpy()
        rng = np.random.default_rng(5)
        orderings = {t: rng.permutation(len(npis)) for t in rb.TAU_GRID}
        orderings[0.80] = np.arange(len(npis))
        _stub_opportunity(monkeypatch, orderings, npis)

        out = rb.tau_sensitivity(train, pd.DataFrame(), grid=rb.TAU_GRID)
        assert (out["within_one_decile_pct"] >= out["same_decile_pct"]).all()

    def test_only_the_fit_year_is_used_for_refitting(self, monkeypatch, recorded):
        """Refitting on a year the model will later be scored against leaks."""
        train = _train_frame()
        other = train.copy()
        other["year"] = 2024
        combined = pd.concat([train, other], ignore_index=True)

        seen: dict[str, int] = {}
        npis = train["npi"].to_numpy()
        base = np.arange(len(npis))

        def fake_fit(t, tau):
            seen["n"] = len(t)
            seen["years"] = set(t["year"].unique())
            return object(), object(), None

        monkeypatch.setattr(rb.opp, "fit_potential", fake_fit)
        monkeypatch.setattr(rb.opp, "score_opportunity",
                            lambda *_a, **_k: pd.DataFrame({
                                "npi": npis,
                                "opportunity": base.astype(float),
                                "opportunity_decile": pd.qcut(
                                    pd.Series(base).rank(method="first"),
                                    10, labels=False).to_numpy() + 1,
                            }))

        rb.tau_sensitivity(combined, pd.DataFrame(), grid=(0.80,))
        assert seen["years"] == {2023}
        assert seen["n"] == len(train)
