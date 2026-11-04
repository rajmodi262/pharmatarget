"""Decision lab: blend frontier, weight selection and pilot power."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.models import decision as d


def _panel(n: int = 4000, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    vol = rng.lognormal(5, 1, n)
    opp = rng.lognormal(3, 1, n) + 0.05 * vol
    return pd.DataFrame({
        "class_fills": vol,
        "opportunity": opp,
        "growth_abs": 0.02 * vol + 0.3 * opp + rng.normal(0, 10, n),
        "growth_share": 0.002 * np.log(opp) + rng.normal(0, 0.01, n),
    })


def test_frontier_is_relative_to_volume():
    f = d.blend_frontier(_panel(), n_budget=300)
    assert f.iloc[0]["weight"] == 0.0
    assert f.iloc[0]["abs_vs_volume"] == 1.0 and f.iloc[0]["share_vs_volume"] == 1.0
    assert len(f) == len(d.WEIGHTS)
    assert f["clears_floor"].iloc[0]


def test_choose_weight_respects_floor():
    f = pd.DataFrame({
        "weight": [0.0, 0.5, 1.0],
        "abs_vs_volume": [1.0, 0.92, 0.80],
        "share_capture": [0.10, 0.12, 0.20],
    })
    # 1.0 has the most share but breaks the 90% floor, so 0.5 is chosen.
    assert d.choose_weight(f) == 0.5


def test_power_rises_with_sample_and_effect():
    p_small = d.power(1.0, 10.0, 100, 100)
    p_big = d.power(1.0, 10.0, 10_000, 10_000)
    assert 0.0 < p_small < p_big <= 1.0
    assert d.power(2.0, 10.0, 500, 500) > d.power(1.0, 10.0, 500, 500)
    # A design effect above one costs power.
    assert d.power(1.0, 10.0, 2000, 2000, deff=3.0) < d.power(1.0, 10.0, 2000, 2000)
    # No effect: power collapses to the one-sided false-positive rate.
    assert d.power(0.0, 10.0, 1000, 1000) < 0.03


def test_icc_detects_clustering():
    rng = np.random.default_rng(1)
    groups = np.repeat(np.arange(50), 40)
    noise = rng.normal(0, 1, groups.size)
    assert d._icc(noise, groups) < 0.05
    clustered = rng.normal(0, 3, 50)[groups] + noise
    assert d._icc(clustered, groups) > 0.6


def test_bootstrap_frontier_probabilities_bounded():
    b = d.bootstrap_frontier(_panel(1500), n_budget=150, n_boot=20,
                             weights=np.array([0.0, 0.5, 1.0]))
    assert b["p_clears_floor"].between(0, 1).all()
    assert b.iloc[0]["p_clears_floor"] == 1.0          # volume always clears its own floor
    assert (b["abs_vs_volume_lo"] <= b["abs_vs_volume_hi"]).all()
