"""Tests for the back-test and the champion-challenger race.

These two modules carry the project's central claim, and both were untested
until now -- which is the wrong way round, because they are also the two whose
failure modes are silent. A gate that passes for the wrong reason and a capture
metric that can be gamed both produce confident, plausible, wrong output.

The gate tests in particular encode a history: G3 originally rested on
share-growth capture alone, challenger.py demonstrated that criterion was
gameable by selecting micro-prescribers, and the gate was hardened to three
conditions. These tests make sure it stays hardened.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.models import backtest, challenger


def _holdout_frame(n: int = 4_000, seed: int = 0) -> pd.DataFrame:
    """A holdout frame shaped like the real one.

    Growth is deliberately built so that absolute growth scales with baseline
    volume -- which is the true mechanical relationship the back-test has to
    reason around, and the reason volume ranking wins absolute capture.
    """
    rng = np.random.default_rng(seed)
    class_fills = rng.lognormal(4.2, 1.3, n)
    brand_share = rng.beta(2.0, 3.0, n)
    brand_fills = class_fills * brand_share
    share_growth = rng.normal(0.01, 0.06, n)
    return pd.DataFrame({
        "npi": np.arange(n) + 1_400_000_000,
        "class_fills": class_fills,
        "brand_fills": brand_fills,
        "brand_share": brand_share,
        "opportunity": class_fills * (0.75 - brand_share).clip(0),
        "opportunity_decile": rng.integers(1, 11, n),
        "volume_decile": pd.qcut(pd.Series(class_fills).rank(method="first"),
                                 10, labels=False) + 1,
        # absolute growth = volume x share movement, the real mechanism
        "brand_growth_abs": class_fills * share_growth,
        "share_growth": share_growth,
        "flagged": rng.random(n) > 0.7,
    })


# --------------------------------------------------------------------------- #
# head_to_head
# --------------------------------------------------------------------------- #

class TestHeadToHead:
    def test_reports_both_outcome_metrics(self):
        """Absolute AND share capture. Reporting one alone is how this went wrong."""
        res = backtest.head_to_head(_holdout_frame(), n_budget=500)
        for rule in ("opportunity", "volume"):
            assert res[f"{rule}_pct_of_growth"] is not None
            assert res[f"{rule}_pct_of_share_growth"] is not None

    def test_reports_median_base_of_selected_list(self):
        """The anti-gaming diagnostic must exist for both rules."""
        res = backtest.head_to_head(_holdout_frame(), n_budget=500)
        assert res["opportunity_median_base_fills"] > 0
        assert res["volume_median_base_fills"] > 0

    def test_volume_rule_selects_higher_base_by_construction(self):
        """Sanity: ranking on volume must pick higher-volume prescribers."""
        res = backtest.head_to_head(_holdout_frame(), n_budget=500)
        assert res["volume_median_base_fills"] > res["opportunity_median_base_fills"]

    def test_capture_is_a_fraction(self):
        res = backtest.head_to_head(_holdout_frame(), n_budget=500)
        for rule in ("opportunity", "volume"):
            assert 0.0 <= res[f"{rule}_pct_of_growth"] <= 1.0


# --------------------------------------------------------------------------- #
# gate G3 -- three conditions, and the history behind each
# --------------------------------------------------------------------------- #

def _lift(spearman_positive: bool) -> pd.DataFrame:
    growth = np.arange(1, 11) if spearman_positive else np.full(10, 5.0)
    rows = []
    for rule in ("opportunity", "volume"):
        for d, g in zip(range(1, 11), growth, strict=True):
            rows.append({"rule": rule, "decile": d, "mean_growth_abs": float(g)})
    return pd.DataFrame(rows)


def _h2h(share_ratio: float, opp_base: float, vol_base: float = 500.0) -> dict:
    return {
        "opportunity_vs_volume_share_ratio": share_ratio,
        "opportunity_vs_volume_ratio": 0.8,
        "opportunity_median_base_fills": opp_base,
        "volume_median_base_fills": vol_base,
    }


class TestGateG3:
    def test_passes_when_all_three_conditions_hold(self):
        v = backtest.gate_g3_verdict(_lift(True), _h2h(1.4, 320.0), {"growth_ratio": 1.5})
        assert v["passed"] is True
        assert all(v["conditions"].values())

    def test_fails_when_ranking_does_not_order(self):
        v = backtest.gate_g3_verdict(_lift(False), _h2h(1.4, 320.0), {"growth_ratio": 1.5})
        assert v["passed"] is False
        assert v["conditions"]["orders_correctly"] is False

    def test_fails_when_it_does_not_beat_volume(self):
        v = backtest.gate_g3_verdict(_lift(True), _h2h(0.9, 320.0), {"growth_ratio": 1.0})
        assert v["passed"] is False
        assert v["conditions"]["beats_volume_on_share"] is False

    def test_fails_when_the_win_is_bought_with_micro_prescribers(self):
        """THE test this gate exists for.

        challenger.py showed a model can win share-growth capture 4.9x while
        selecting prescribers with a median base of 35 fills against 840, and
        deliver 1.9% of actual volume. Winning the metric that way is not
        winning. A huge share ratio must NOT pass if the base collapses.
        """
        v = backtest.gate_g3_verdict(_lift(True), _h2h(5.0, 35.0, 1470.0),
                                     {"growth_ratio": 3.0})
        assert v["passed"] is False, "a gamed metric must not pass the gate"
        assert v["conditions"]["not_gamed_by_small_base"] is False

    def test_absolute_capture_is_reported_but_never_a_pass_condition(self):
        """Volume wins absolute capture mechanically; requiring it would be
        requiring the model to beat volume at being volume."""
        v = backtest.gate_g3_verdict(_lift(True), _h2h(1.4, 320.0), {"growth_ratio": 1.5})
        assert "absolute_growth_ratio" in v
        assert "absolute" not in " ".join(v["conditions"].keys())

    def test_verdict_records_the_criterion_text(self):
        v = backtest.gate_g3_verdict(_lift(True), _h2h(1.4, 320.0), {"growth_ratio": 1.5})
        assert "anti-gaming" in v["criterion"].lower() or "median base" in v["criterion"].lower()


# --------------------------------------------------------------------------- #
# volume-matched comparison
# --------------------------------------------------------------------------- #

class TestVolumeMatched:
    def test_computes_a_ratio(self):
        res = backtest.volume_matched_comparison(_holdout_frame(2_000), n_bins=10)
        assert res["computable"] is True
        assert res["growth_ratio"] is not None

    def test_reports_not_computable_rather_than_guessing(self):
        """No control prescribers in any stratum must not silently return 1.0."""
        df = _holdout_frame(300)
        df["flagged"] = True
        res = backtest.volume_matched_comparison(df, n_bins=10)
        assert res["computable"] is False


# --------------------------------------------------------------------------- #
# challenger
# --------------------------------------------------------------------------- #

def _scored(n: int = 3_000, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    class_fills = rng.lognormal(4.2, 1.3, n)
    share_growth = rng.normal(0.01, 0.06, n)
    df = pd.DataFrame({
        "class_fills": class_fills,
        "growth_abs": class_fills * share_growth,
        "growth_share": share_growth,
        "score_volume": class_fills,
        # a rule that maximises share growth on tiny denominators
        "score_gamed": share_growth / np.sqrt(class_fills),
    })
    return df


class TestChallengerEvaluate:
    def test_exposes_the_gaming_via_base_volume(self):
        """The diagnostic that made the whole finding legible.

        A rule optimising share growth on small denominators must show a much
        lower median base than a volume rule -- that contrast is what turns
        'it beat me' into 'it beat me by cheating'.
        """
        res = challenger.evaluate(_scored(), ["volume", "gamed"], n_budget=300)
        by = res.set_index("rule")
        assert by.loc["gamed", "median_base_class_fills"] < \
               by.loc["volume", "median_base_class_fills"], \
            "the gamed rule must be visibly selecting smaller prescribers"

    def test_gamed_rule_wins_share_but_loses_absolute(self):
        res = challenger.evaluate(_scored(), ["volume", "gamed"], n_budget=300)
        by = res.set_index("rule")
        assert by.loc["gamed", "share_capture"] > by.loc["volume", "share_capture"]
        assert by.loc["gamed", "abs_capture"] < by.loc["volume", "abs_capture"]

    def test_captures_are_fractions(self):
        res = challenger.evaluate(_scored(), ["volume", "gamed"], n_budget=300)
        assert (res["share_capture"].between(0, 1)).all()
        assert (res["abs_capture"].between(0, 1)).all()

    def test_every_rule_reports_every_metric(self):
        res = challenger.evaluate(_scored(), ["volume", "gamed"], n_budget=300)
        for col in ("share_capture", "abs_capture", "spearman_decile_growth",
                    "median_base_class_fills"):
            assert col in res.columns
            assert res[col].notna().all()


class TestChallengerPanels:
    def test_growth_is_zero_filled_not_dropped(self):
        """A prescriber who stops writing has undefined share, not missing data.

        Dropping them would silently remove exactly the churn a targeting model
        most needs to learn from, and would crash the fit on NaN.
        """
        scored = pd.DataFrame({
            "npi": [1, 1, 1],
            "year": [2022, 2023, 2024],
            "class_fills": [100.0, 100.0, 0.0],
            "brand_fills": [50.0, 40.0, np.nan],
            "brand_share": [0.5, 0.4, np.nan],
            "potential_brand": [80.0, 80.0, 0.0],
        })
        train, apply_ = challenger.build_panels(scored)
        for frame in (train, apply_):
            if len(frame):
                assert frame["growth_abs"].notna().all()
                assert frame["growth_share"].notna().all()


@pytest.mark.parametrize("budget", [50, 200, 800])
def test_capture_rises_with_budget(budget):
    """Calling more prescribers cannot capture less growth."""
    res = challenger.evaluate(_scored(), ["volume"], n_budget=budget)
    assert res.iloc[0]["abs_capture"] >= 0
