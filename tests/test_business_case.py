"""Tests for the pieces the recommendation now rests on.

Each one pins a defect that reached the README before it was caught:

  * the test suite wrote fixture values into the real manifest
  * prescribers who write no anticoagulants carried 74% of all "opportunity"
  * the recommended rule was chosen by reading the results, not by a rule
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import ROOT
from src.models import opportunity as opp
from src.models.challenger import ABS_FLOOR_VS_VOLUME, recommend_rule
from src.utils import io


class TestManifestIsolation:
    def test_tests_never_point_at_the_real_manifest(self):
        assert io.MANIFEST != ROOT / "data" / "manifest.json"

    def test_record_writes_to_the_throwaway_manifest(self):
        io.record("probe", value=1)
        assert io.manifest()["probe"] == {"value": 1}


def _results(opp_abs: float, hyb_abs: float, vol_abs: float = 0.16) -> pd.DataFrame:
    return pd.DataFrame([
        {"rule": "volume", "share_capture": 0.017, "abs_capture": vol_abs},
        {"rule": "opportunity", "share_capture": 0.024, "abs_capture": opp_abs},
        {"rule": "hybrid", "share_capture": 0.021, "abs_capture": hyb_abs},
        {"rule": "ml_share", "share_capture": 0.117, "abs_capture": 0.019},
    ])


class TestRecommendRule:
    def test_best_share_rule_wins_when_it_keeps_the_base(self):
        r = recommend_rule(_results(opp_abs=0.15, hyb_abs=0.155))
        assert r["recommended_rule"] == "opportunity"

    def test_a_rule_that_gives_up_the_base_is_not_eligible(self):
        """Opportunity wins share but keeps only 64% of volume's absolute growth."""
        r = recommend_rule(_results(opp_abs=0.103, hyb_abs=0.150))
        assert "opportunity" not in r["eligible"]
        assert r["recommended_rule"] == "hybrid"

    def test_volume_is_the_fallback_when_nothing_else_qualifies(self):
        r = recommend_rule(_results(opp_abs=0.05, hyb_abs=0.06))
        assert r["recommended_rule"] == "volume"

    def test_ml_challengers_are_never_recommended(self):
        """Highest share capture of all, but not an explainable rule."""
        r = recommend_rule(_results(opp_abs=0.15, hyb_abs=0.15))
        assert r["recommended_rule"] != "ml_share"

    def test_floor_is_the_declared_constant(self):
        r = recommend_rule(_results(opp_abs=0.15, hyb_abs=0.15))
        assert r["abs_floor"] == round(ABS_FLOOR_VS_VOLUME * 0.16, 4)


class TestHybridScore:
    def test_bounded_and_monotone_in_both_inputs(self):
        df = pd.DataFrame({"opportunity": [1.0, 2.0, 3.0, 4.0],
                           "class_fills": [10.0, 20.0, 30.0, 40.0]})
        h = opp.hybrid_score(df)
        assert h.between(0, 1).all()
        assert h.is_monotonic_increasing

    def test_is_the_equal_weight_rank_blend(self):
        df = pd.DataFrame({"opportunity": [4.0, 1.0], "class_fills": [1.0, 4.0]})
        h = opp.hybrid_score(df)
        assert h.iloc[0] == h.iloc[1], "equal weights: a pure-opportunity and a pure-volume " \
                                       "prescriber must tie"


def _frame(n: int = 400, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    panel = rng.lognormal(4.8, 0.7, n)
    fills = rng.lognormal(3.5, 1.0, n)
    fills[: n // 4] = 0.0                      # a quarter write no anticoagulants
    return pd.DataFrame({
        "npi": np.arange(n), "year": 2023,
        "panel_benes": panel, "non_class_clms": panel * 12, "age65_cnt": panel * 0.7,
        "risk_score": rng.normal(1.4, 0.3, n), "pct_panel_65": rng.uniform(0.4, 0.9, n),
        "prev_stroke": rng.uniform(2, 8, n), "prev_chd": rng.uniform(3, 14, n),
        "prev_bp": rng.uniform(25, 60, n),
        "specialty_group": rng.choice(["Cardiology", "Primary Care"], n),
        "region": rng.choice(["South", "West"], n),
        "class_fills": fills, "brand_fills": fills * 0.5,
    })


class TestNoOpportunityOutsideTheMarket:
    def test_non_writers_score_zero(self):
        df = _frame()
        model, enc, _ = opp.fit_potential(df[df["class_fills"] > 0])
        bench = pd.DataFrame([{"specialty_group": s, "region": r, "year": 2023,
                               "achievable_share": 0.6}
                              for s in ("Cardiology", "Primary Care") for r in ("South", "West")])
        scored = opp.score_opportunity(df, bench, model, enc)
        out = scored[scored["class_fills"] <= 0]
        assert (out["opportunity"] == 0).all()
        assert (out["opportunity_decile"] == 0).all()
        assert (scored.loc[scored["class_fills"] > 0, "opportunity"] > 0).any()
