"""Tests for behavioural segmentation.

This module was at 0% coverage, and the thing that most needed pinning is not
the clustering -- it is the FILTER in front of it.

`build_panel` used to segment all 1.59M prescribers in the Part D file. Run
that way, the clustering spent 83% of its capacity splitting people who write
NO anticoagulants into near-identical all-zero groups: "Untapped Potential"
came back as 64.2% of the universe at a brand share of 0.000006. Worse, the
trivially separable zero clusters inflated the silhouette to 0.807, so the
geometry looked excellent while the segmentation said nothing. The deciling
had already been restricted to in-market prescribers; the fix simply was not
propagated here. `TestAddressableMarket` makes sure it stays propagated.

The second invariant worth a test is in `name_clusters`. It assigns business
names from centroid position by a greedy rule, and the whole point of the
greedy pass is that each name is claimed ONCE. A segmentation where two
clusters are both called "Untapped Potential" is not a segmentation a brand
team can act on, and nothing in the type system stops that from happening.

`record()` writes to data/manifest.json, so anything touching a function that
records monkeypatches it. Tests must not mutate the run manifest.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.models import segmentation
from src.models.segmentation import FEATURES, STRATEGIES, build_panel, choose_k, name_clusters


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
def _scored(rows: list[dict]) -> pd.DataFrame:
    """Long-format scored frame: one row per (npi, year)."""
    return pd.DataFrame(rows)


def _prescriber(npi: int, *, fills: dict[int, float], share: dict[int, float],
                opp: float = 0.5) -> list[dict]:
    """Three years of one prescriber, in the long format build_panel pivots."""
    return [
        {"npi": npi, "year": y,
         "brand_share": share.get(y, 0.0),
         "class_fills": fills.get(y, 0.0),
         "opportunity_pct_of_potential": opp}
        for y in (2022, 2023, 2024)
    ]


@pytest.fixture
def payments_empty() -> pd.DataFrame:
    return pd.DataFrame({"npi": pd.Series(dtype="int64"),
                         "pay_total": pd.Series(dtype="float64")})


# --------------------------------------------------------------------------- #
# build_panel -- the addressable-market filter
# --------------------------------------------------------------------------- #
class TestAddressableMarket:
    def test_out_of_market_prescribers_are_excluded(self, payments_empty):
        """A prescriber writing zero of the class in the latest year is not a
        behavioural segment, they are the out-of-market population."""
        rows = (_prescriber(1, fills={2022: 10, 2023: 12, 2024: 15}, share={2024: 0.4})
                + _prescriber(2, fills={2022: 0, 2023: 0, 2024: 0}, share={}))
        panel = build_panel(_scored(rows), payments_empty)

        assert list(panel["npi"]) == [1]

    def test_a_prescriber_who_stopped_writing_is_excluded(self, payments_empty):
        """The filter is on the LATEST year, not on any year. Someone who wrote
        the class in 2022 but nothing in 2024 is no longer addressable."""
        rows = _prescriber(3, fills={2022: 50, 2023: 20, 2024: 0}, share={2022: 0.3})
        panel = build_panel(_scored(rows), payments_empty)

        assert panel.empty

    def test_an_entrant_is_kept(self, payments_empty):
        """Zero in the base year but writing now is exactly the growth target."""
        rows = _prescriber(4, fills={2022: 0, 2023: 5, 2024: 30}, share={2024: 0.1})
        panel = build_panel(_scored(rows), payments_empty)

        assert list(panel["npi"]) == [4]


# --------------------------------------------------------------------------- #
# build_panel -- trajectory features
# --------------------------------------------------------------------------- #
class TestTrajectoryFeatures:
    def test_share_deltas_are_directional(self, payments_empty):
        """Clustering on the CHANGE in share is what makes the groups mean
        'winning them' rather than 'big'. A rising prescriber must produce a
        positive recent delta."""
        rows = _prescriber(1, fills={2022: 10, 2023: 10, 2024: 10},
                           share={2022: 0.10, 2023: 0.20, 2024: 0.50})
        panel = build_panel(_scored(rows), payments_empty).iloc[0]

        assert panel["brand_share"] == pytest.approx(0.50)
        assert panel["share_delta_recent"] == pytest.approx(0.30)   # 2024 - 2023
        assert panel["share_delta_prior"] == pytest.approx(0.10)    # 2023 - 2022

    def test_falling_share_produces_a_negative_delta(self, payments_empty):
        rows = _prescriber(1, fills={2022: 10, 2023: 10, 2024: 10},
                           share={2022: 0.60, 2023: 0.40, 2024: 0.10})
        panel = build_panel(_scored(rows), payments_empty).iloc[0]

        assert panel["share_delta_recent"] < 0
        assert panel["share_delta_prior"] < 0

    def test_missing_payments_are_zero_not_dropped(self, payments_empty):
        """A prescriber with no Open Payments record has zero promotional
        exposure -- that is a real value, not a missing one. Dropping them
        would silently remove every un-promoted prescriber from the panel."""
        rows = _prescriber(1, fills={2022: 10, 2023: 10, 2024: 10}, share={2024: 0.2})
        panel = build_panel(_scored(rows), payments_empty).iloc[0]

        assert panel["pay_total"] == 0.0
        assert panel["log_payments"] == pytest.approx(0.0)

    def test_payments_are_summed_and_logged(self):
        rows = _prescriber(1, fills={2022: 10, 2023: 10, 2024: 10}, share={2024: 0.2})
        pay = pd.DataFrame({"npi": [1, 1], "pay_total": [100.0, 50.0]})
        panel = build_panel(_scored(rows), pay).iloc[0]

        assert panel["pay_total"] == pytest.approx(150.0)
        assert panel["log_payments"] == pytest.approx(np.log1p(150.0))

    def test_class_growth_does_not_divide_by_zero(self, payments_empty):
        """The prior year is clipped at 1.0 before division. Without the clip a
        prescriber who wrote nothing last year and something this year yields
        an infinity that propagates into StandardScaler and poisons the fit."""
        rows = _prescriber(1, fills={2022: 0, 2023: 0, 2024: 40}, share={2024: 0.2})
        panel = build_panel(_scored(rows), payments_empty).iloc[0]

        assert np.isfinite(panel["class_growth"])

    def test_every_declared_feature_is_present_and_finite(self, payments_empty):
        rows = (_prescriber(1, fills={2022: 10, 2023: 20, 2024: 30}, share={2024: 0.3})
                + _prescriber(2, fills={2022: 5, 2023: 4, 2024: 3}, share={2024: 0.7}))
        panel = build_panel(_scored(rows), payments_empty)

        for col in FEATURES:
            assert col in panel.columns, f"declared feature {col} missing from panel"
            assert np.isfinite(panel[col]).all(), f"{col} contains a non-finite value"


# --------------------------------------------------------------------------- #
# name_clusters -- the one-name-per-cluster invariant
# --------------------------------------------------------------------------- #
def _profile(rows: list[dict]) -> pd.DataFrame:
    """Centroid profile, indexed by cluster id, as name_clusters expects."""
    return pd.DataFrame(rows, index=range(len(rows)))


class TestNameClusters:
    def test_no_business_name_is_claimed_twice(self):
        """The greedy pass exists so that a name is used once. Two clusters
        both labelled 'Untapped Potential' is not actionable in a brand
        meeting, and nothing in the types prevents it."""
        profile = _profile([
            {"brand_share": 0.8, "share_delta_recent": 0.01, "share_delta_prior": 0.0,
             "log_class_fills": 5.0, "opportunity_pct": 0.1},
            {"brand_share": 0.1, "share_delta_recent": 0.30, "share_delta_prior": 0.20,
             "log_class_fills": 4.0, "opportunity_pct": 0.8},
            {"brand_share": 0.05, "share_delta_recent": -0.25, "share_delta_prior": -0.10,
             "log_class_fills": 3.0, "opportunity_pct": 0.9},
        ])
        assigned = name_clusters(profile)

        assert len(set(assigned.values())) == len(assigned)

    def test_every_cluster_gets_a_name(self):
        profile = _profile([
            {"brand_share": 0.5, "share_delta_recent": 0.0, "share_delta_prior": 0.0,
             "log_class_fills": 4.0, "opportunity_pct": 0.5},
            {"brand_share": 0.2, "share_delta_recent": 0.1, "share_delta_prior": 0.1,
             "log_class_fills": 3.0, "opportunity_pct": 0.6},
        ])
        assigned = name_clusters(profile)

        assert set(assigned) == set(profile.index)

    def test_more_clusters_than_names_falls_back_to_a_numbered_segment(self):
        """Six business names exist. A seventh cluster must still be named, and
        an unnamed key would KeyError downstream in the profile join."""
        n = len(STRATEGIES) + 1
        profile = _profile([
            {"brand_share": 0.1 * i, "share_delta_recent": 0.01 * i,
             "share_delta_prior": 0.0, "log_class_fills": float(i),
             "opportunity_pct": 0.1 * i}
            for i in range(n)
        ])
        assigned = name_clusters(profile)

        assert len(assigned) == n
        assert any(v.startswith("Segment ") for v in assigned.values())

    def test_named_clusters_use_the_declared_strategy_vocabulary(self):
        """Names that are not fallbacks must come from STRATEGIES, because the
        run() profile joins the strategy text on exactly these keys."""
        profile = _profile([
            {"brand_share": 0.9, "share_delta_recent": 0.0, "share_delta_prior": 0.0,
             "log_class_fills": 6.0, "opportunity_pct": 0.05},
            {"brand_share": 0.05, "share_delta_recent": 0.4, "share_delta_prior": 0.3,
             "log_class_fills": 5.0, "opportunity_pct": 0.9},
        ])
        assigned = name_clusters(profile)

        for name in assigned.values():
            assert name in STRATEGIES or name.startswith("Segment ")

    def test_naming_is_deterministic(self):
        """Refreshing the data must not reshuffle the labels for identical
        centroids -- the namer is rule-based precisely so it reproduces."""
        profile = _profile([
            {"brand_share": 0.7, "share_delta_recent": -0.2, "share_delta_prior": -0.1,
             "log_class_fills": 5.0, "opportunity_pct": 0.2},
            {"brand_share": 0.1, "share_delta_recent": 0.3, "share_delta_prior": 0.1,
             "log_class_fills": 4.0, "opportunity_pct": 0.7},
        ])

        assert name_clusters(profile) == name_clusters(profile)


# --------------------------------------------------------------------------- #
# choose_k -- both metrics, not just silhouette
# --------------------------------------------------------------------------- #
@pytest.fixture
def fast_segmentation_params(monkeypatch):
    """Two candidate k and three bootstrap runs. The real config is 6 candidate
    k at 25 bootstrap refits each, which is a full-scale fit, not a unit test."""
    def fake_params():
        return {"segmentation": {"k_candidates": [2, 3], "bootstrap_runs": 3,
                                 "bootstrap_frac": 0.8, "random_state": 42}}
    monkeypatch.setattr(segmentation, "params", fake_params)


@pytest.fixture
def separable_blobs() -> np.ndarray:
    """Three well-separated blobs in 2D."""
    rng = np.random.default_rng(0)
    return np.vstack([
        rng.normal(loc, 0.25, size=(40, 2))
        for loc in ((0.0, 0.0), (8.0, 8.0), (0.0, 8.0))
    ])


class TestChooseK:
    def test_one_row_per_candidate_k(self, fast_segmentation_params, separable_blobs):
        out = choose_k(separable_blobs)

        assert sorted(out["k"]) == [2, 3]

    def test_reports_both_silhouette_and_stability(self, fast_segmentation_params,
                                                   separable_blobs):
        """Silhouette rewards tight geometry and will happily endorse a k that
        reshuffles completely on a different sample. Both must be reported."""
        out = choose_k(separable_blobs)

        for col in ("silhouette", "stability_ari", "stability_sd", "inertia"):
            assert col in out.columns
            assert out[col].notna().all()

    def test_combined_rank_uses_both_metrics(self, fast_segmentation_params,
                                             separable_blobs):
        """Equal weighting of two rank-1..n columns: the best possible combined
        rank is 2.0, and no row may score below that."""
        out = choose_k(separable_blobs)

        assert out["combined_rank"].min() >= 2.0

    def test_sorted_best_first(self, fast_segmentation_params, separable_blobs):
        out = choose_k(separable_blobs)

        assert out["combined_rank"].is_monotonic_increasing

    def test_true_k_is_stable_under_resampling(self, fast_segmentation_params,
                                               separable_blobs):
        """Three genuinely separated blobs must survive a bootstrap refit. If
        k=3 is not stable here, the stability metric is not measuring anything."""
        out = choose_k(separable_blobs).set_index("k")

        assert out.loc[3, "stability_ari"] > 0.9
