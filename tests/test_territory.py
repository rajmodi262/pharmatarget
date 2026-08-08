"""Tests for territory alignment.

Contiguity is the one that matters. A territory made of disconnected islands is
unimplementable in the field, and it is the defect that plain capacitated
k-means produces by default -- so it gets a test, not a comment.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.config import params
from src.models import territory as terr
from src.utils.geo import knn_adjacency


@pytest.fixture(scope="module")
def units() -> pd.DataFrame:
    """A grid of units, so adjacency is unambiguous and contiguity is checkable."""
    rng = np.random.default_rng(3)
    rows = []
    for i in range(14):
        for j in range(14):
            rows.append({
                "unit": f"{i:02d}{j:02d}",
                "lat": 35.0 + i * 0.6,
                "lon": -100.0 + j * 0.6,
                "workload": float(rng.uniform(5, 60)),
                "n_hcps": int(rng.integers(10, 100)),
                "n_targets": int(rng.integers(5, 50)),
                "opportunity": float(rng.uniform(100, 900)),
                "class_fills": float(rng.uniform(500, 5000)),
                "brand_fills": float(rng.uniform(100, 2000)),
                "high_decile_hcps": int(rng.integers(0, 30)),
                "state": "XX",
            })
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def edges(units):
    return knn_adjacency(units[["unit", "lat", "lon"]], k=4)


class TestPartition:
    def test_every_unit_is_assigned(self, units, edges):
        """An unowned ZIP3 is not a valid map."""
        assign, _ = terr.solve(units, n_reps=8, edges=edges)
        assert len(assign) == len(units)
        assert (assign >= 0).all()

    def test_assignment_is_a_partition(self, units, edges):
        assign, _ = terr.solve(units, n_reps=8, edges=edges)
        assert len(assign) == len(set(range(len(units)))), "units duplicated or dropped"


class TestContiguity:
    def test_optimised_meets_threshold(self, units, edges):
        """The headline claim. Fails loudly if the repair step regresses."""
        _assign, stats = terr.solve(units, n_reps=8, edges=edges)
        floor = params()["territory"]["min_contiguity_rate"]
        assert stats["contiguity_rate"] >= floor, (
            f"contiguity {stats['contiguity_rate']:.3f} below the {floor} floor -- "
            f"_repair_contiguity has regressed and the map has detached islands")

    def test_beats_the_naive_baseline(self, units, edges):
        base = terr.baseline_alignment(units, 8)
        base_stats = terr.evaluate(units, base, edges)
        _a, opt_stats = terr.solve(units, n_reps=8, edges=edges)
        assert opt_stats["contiguity_rate"] >= base_stats["contiguity_rate"]

    def test_components_detects_a_split(self):
        """The primitive the contiguity metric rests on."""
        edges = {("a", "b"), ("c", "d")}
        comps = terr._components({"a", "b", "c", "d"}, edges)
        assert len(comps) == 2
        comps = terr._components({"a", "b"}, {("a", "b")})
        assert len(comps) == 1


class TestBalance:
    def test_cv_within_configured_max(self, units, edges):
        _a, stats = terr.solve(units, n_reps=8, edges=edges)
        max_cv = params()["territory"]["max_cv"]
        assert stats["workload_cv"] <= max_cv, (
            f"workload CV {stats['workload_cv']:.3f} exceeds max_cv {max_cv}. "
            f"Fix _rebalance or raise unit resolution -- do NOT relax max_cv to "
            f"make this pass.")

    def test_improves_on_baseline(self, units, edges):
        base = terr.baseline_alignment(units, 8)
        base_stats = terr.evaluate(units, base, edges)
        _a, opt_stats = terr.solve(units, n_reps=8, edges=edges)
        assert opt_stats["workload_cv"] < base_stats["workload_cv"], (
            "the optimiser did not beat alphabetical-by-state assignment on balance")

    def test_travel_improves_on_baseline(self, units, edges):
        base = terr.baseline_alignment(units, 8)
        base_stats = terr.evaluate(units, base, edges)
        _a, opt_stats = terr.solve(units, n_reps=8, edges=edges)
        assert (opt_stats["mean_weighted_distance_mi"]
                < base_stats["mean_weighted_distance_mi"])


class TestGeo:
    def test_haversine_known_distance(self):
        from src.utils.geo import haversine_miles
        # New York to Los Angeles, ~2450 miles.
        d = haversine_miles(40.7128, -74.0060, 34.0522, -118.2437)
        assert 2400 < float(d) < 2500

    def test_zip_normalisation(self):
        from src.utils.geo import zip3, zip5
        assert zip5("02134-5678") == "02134"
        assert zip5(2134) == "02134", "leading zero lost on a numeric ZIP"
        assert zip3("902101") == "902"
        assert zip5(None) is None

    def test_adjacency_is_symmetric(self, units):
        e = knn_adjacency(units[["unit", "lat", "lon"]], k=4)
        assert all(a < b for a, b in e), "edges must be stored in canonical order"
