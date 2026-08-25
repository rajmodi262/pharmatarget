"""Tests for the promotional-response model.

This module was at 0% coverage, which is the wrong way round: `fit_saturation`
produces the call-response curve that `sizing.py` consumes, and fitting that
curve rather than assuming it is what reversed the sizing recommendation from
"hire 526 more reps" to "don't hire, retarget". An untested curve fitter sits
directly underneath the project's headline number.

The saturation tests in particular encode a history. The bounds on `curve_fit`
are not cosmetic: unbounded, it returns a NEGATIVE half-saturation constant
whenever the matched response is negative -- which is exactly what the matched
DiD produces on this data. A negative half-saturation implies response rises
without limit as spend falls, and it would flow straight into sizing.py as a
Hill parameter. `test_negative_response_*` make sure that failure mode stays
closed.

`record()` writes to data/manifest.json, so every test that touches a function
which records monkeypatches it. Tests must not mutate the run manifest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.models import response


@pytest.fixture
def recorded(monkeypatch):
    """Capture record() calls instead of writing them to data/manifest.json."""
    calls: dict[str, dict] = {}

    def fake_record(key: str, **fields) -> None:
        calls[key] = fields

    monkeypatch.setattr(response, "record", fake_record)
    return calls


# --------------------------------------------------------------------------- #
# standardised_mean_diff
# --------------------------------------------------------------------------- #
class TestStandardisedMeanDiff:
    def test_identical_distributions_are_balanced(self):
        a = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        assert response.standardised_mean_diff(a, a.copy()) == pytest.approx(0.0)

    def test_recovers_a_known_one_sd_shift(self):
        rng = np.random.default_rng(0)
        a = pd.Series(rng.normal(0.0, 1.0, 20_000))
        b = pd.Series(rng.normal(1.0, 1.0, 20_000))
        # Equal variances => pooled SD == 1, so the SMD is the raw mean gap.
        assert response.standardised_mean_diff(a, b) == pytest.approx(-1.0, abs=0.05)

    def test_sign_follows_argument_order(self):
        a = pd.Series([10.0, 11.0, 12.0])
        b = pd.Series([1.0, 2.0, 3.0])
        assert response.standardised_mean_diff(a, b) > 0
        assert response.standardised_mean_diff(b, a) < 0

    def test_zero_variance_returns_zero_rather_than_dividing_by_zero(self):
        a = pd.Series([3.0, 3.0, 3.0])
        b = pd.Series([7.0, 7.0, 7.0])
        # Means differ, but pooled SD is 0. The guard must return 0.0, not inf/nan.
        out = response.standardised_mean_diff(a, b)
        assert out == 0.0
        assert np.isfinite(out)


# --------------------------------------------------------------------------- #
# fit_saturation -- the curve the sizing conclusion rests on
# --------------------------------------------------------------------------- #
def _hill_frame(n: int = 800, ceiling: float = 0.05, half: float = 2_000.0,
                noise: float = 0.0, sign: float = 1.0, seed: int = 0) -> pd.DataFrame:
    """A matched frame whose true response is a Hill curve of known parameters."""
    rng = np.random.default_rng(seed)
    pay = rng.uniform(0.0, 20_000.0, n)
    delta = sign * ceiling * pay / (half + pay)
    if noise:
        delta = delta + rng.normal(0.0, noise, n)
    return pd.DataFrame({"pay_amount": pay, "post_delta": delta})


class TestFitSaturation:
    def test_recovers_known_hill_parameters(self, recorded):
        curve = response.fit_saturation(_hill_frame(noise=0.002))
        assert not curve.empty

        rec = recorded["response_saturation"]
        assert rec["identifiable"] is True
        assert rec["ceiling"] == pytest.approx(0.05, rel=0.25)
        assert rec["half_saturation_usd"] == pytest.approx(2_000.0, rel=0.40)

    def test_ninety_percent_point_is_nine_half_saturations(self, recorded):
        response.fit_saturation(_hill_frame(noise=0.001))
        rec = recorded["response_saturation"]
        # Hill: x/(h+x) = 0.9  =>  x = 9h. This identity is quoted in the log line
        # and in the deck, so it is pinned rather than assumed.
        assert rec["ninety_pct_usd"] == pytest.approx(9 * rec["half_saturation_usd"], rel=1e-6)

    def test_curve_is_monotone_and_ci_brackets_the_estimate(self, recorded):
        curve = response.fit_saturation(_hill_frame(noise=0.002))
        assert not curve.empty

        pred = curve["predicted_share_delta"].to_numpy()
        assert np.all(np.diff(pred) >= -1e-12), "a positive-ceiling Hill curve is monotone"
        assert (curve["ci_low"] <= curve["predicted_share_delta"] + 1e-9).all()
        assert (curve["ci_high"] >= curve["predicted_share_delta"] - 1e-9).all()
        assert curve["payment_usd"].iloc[0] == pytest.approx(0.0)

    # -- the failure modes that must stay closed ---------------------------- #
    def test_negative_response_is_refused_not_fitted(self, recorded):
        """The documented bug: unbounded, curve_fit returns a negative half-saturation.

        With a genuinely negative response the honest answer is "no identifiable
        curve", not a Hill parameter that implies response rises without limit as
        spend falls.
        """
        curve = response.fit_saturation(_hill_frame(sign=-1.0, noise=0.001))
        assert curve.empty

        rec = recorded["response_saturation"]
        assert rec["identifiable"] is False
        assert rec["fitted_ceiling"] >= 0.0, "ceiling must stay inside its bound"

    def test_negative_response_never_reports_a_half_saturation(self, recorded):
        response.fit_saturation(_hill_frame(sign=-1.0, noise=0.001))
        rec = recorded["response_saturation"]
        # sizing.py reads these keys. They must be absent, not negative.
        assert "half_saturation_usd" not in rec
        assert "ninety_pct_usd" not in rec

    def test_flat_response_is_declared_unidentifiable(self, recorded):
        """Regression: a flat response used to fit a curve, not refuse one.

        curve_fit satisfies the ceiling bound by pushing half-saturation outside
        the data and returning the near-linear left tail of a Hill curve. The
        observed case was ceiling 0.0213 at half-saturation $82,125,313 against a
        $20,000 maximum payment -- reported with a "90% of response at $739M" log
        line. sizing.py would have consumed that as a Hill parameter.
        """
        flat = pd.DataFrame({
            "pay_amount": np.linspace(0.0, 20_000.0, 400),
            "post_delta": np.zeros(400),
        })
        assert response.fit_saturation(flat).empty

        rec = recorded["response_saturation"]
        assert rec["identifiable"] is False
        assert rec["reason"] == "half_saturation_outside_observed_range"
        assert rec["fitted_half_saturation_usd"] > rec["max_observed_payment_usd"]

    def test_half_saturation_beyond_observed_spend_is_refused(self, recorded):
        """The bend must be measured inside the data, not extrapolated past it."""
        # True half-saturation sits 25x beyond the largest payment, so the
        # observed range only ever sees the near-linear part of the curve.
        far = _hill_frame(n=600, ceiling=0.5, half=500_000.0, noise=0.0005)
        assert response.fit_saturation(far).empty
        assert recorded["response_saturation"]["identifiable"] is False

    def test_identifiable_fit_keeps_half_saturation_inside_the_data(self, recorded):
        response.fit_saturation(_hill_frame(noise=0.002))
        rec = recorded["response_saturation"]
        assert rec["identifiable"] is True
        assert rec["half_saturation_usd"] <= 20_000.0

    def test_too_few_rows_returns_empty(self, recorded):
        assert response.fit_saturation(_hill_frame(n=49)).empty
        assert "response_saturation" not in recorded, "no verdict should be recorded"

    def test_no_payment_variation_returns_empty(self, recorded):
        zero = pd.DataFrame({
            "pay_amount": np.zeros(200),
            "post_delta": np.full(200, 0.01),
        })
        assert response.fit_saturation(zero).empty


# --------------------------------------------------------------------------- #
# propensity_match
# --------------------------------------------------------------------------- #
def _cohort(n: int = 1_200, seed: int = 0, treated_frac: float = 0.25) -> pd.DataFrame:
    """A cohort where treatment is confounded with prescriber size.

    Big prescribers are more likely to be paid, which is the real selection
    story in Open Payments -- manufacturers pay people who were already writing.
    Matching should shrink that imbalance.
    """
    rng = np.random.default_rng(seed)
    log_fills = rng.normal(4.0, 1.2, n)
    # Propensity rises with size => confounding by construction.
    p = 1.0 / (1.0 + np.exp(-(log_fills - 4.0)))
    p = p * (treated_frac / p.mean())
    treated = rng.random(n) < np.clip(p, 0.0, 0.95)

    return pd.DataFrame({
        "npi": np.arange(n) + 1_500_000_000,
        "treated": treated,
        "log_class_fills_pre": log_fills,
        "brand_share_pre": rng.beta(2.0, 3.0, n),
        "log_panel_benes": rng.normal(5.0, 1.0, n),
        "risk_score": rng.normal(1.0, 0.2, n),
        "log_non_class_clms": rng.normal(6.0, 1.0, n),
        "pay_amount": np.where(treated, rng.uniform(100, 20_000, n), 0.0),
        "post_delta": rng.normal(0.0, 0.05, n),
    })


@pytest.mark.usefixtures("recorded")
class TestPropensityMatch:
    """Every test here uses `recorded`.

    propensity_match records n_pairs and worst_smd_after to data/manifest.json.
    Without the fixture a test run overwrites the real pipeline's matching
    figures with whatever the synthetic cohort produced -- observed once as
    n_pairs dropping from 23,850 to 310 and `balanced` flipping to false.
    """

    def test_matching_improves_covariate_balance(self):
        matched, balance = response.propensity_match(_cohort())
        assert not matched.empty
        assert len(balance) == len(response.MATCH_COVARIATES)

        # The confounder was built in on log_class_fills_pre; matching must shrink it.
        row = balance[balance["covariate"] == "log_class_fills_pre"].iloc[0]
        assert abs(row["smd_after"]) < abs(row["smd_before"])

    def test_each_control_is_used_at_most_once(self):
        """1:1 without replacement. Reusing a control silently inflates n."""
        matched, _ = response.propensity_match(_cohort())
        controls = matched[~matched["treated"]]["npi"]
        assert controls.is_unique

    def test_matched_arms_are_equal_size(self):
        matched, _ = response.propensity_match(_cohort())
        assert int(matched["treated"].sum()) == int((~matched["treated"]).sum())

    def test_balance_table_reports_before_and_after_for_every_covariate(self):
        _, balance = response.propensity_match(_cohort())
        assert set(balance["covariate"]) == set(response.MATCH_COVARIATES)
        assert balance[["smd_before", "smd_after"]].notna().all().all()

    def test_too_few_treated_units_returns_empty_rather_than_matching(self):
        df = _cohort(n=400, seed=1)
        df["treated"] = False
        df.loc[df.index[:5], "treated"] = True  # below the 10-unit floor
        matched, balance = response.propensity_match(df)
        assert matched.empty
        assert balance.empty

    def test_too_few_controls_returns_empty(self):
        df = _cohort(n=400, seed=2)
        df["treated"] = True
        df.loc[df.index[:5], "treated"] = False
        matched, balance = response.propensity_match(df)
        assert matched.empty
        assert balance.empty
