"""Data-science layer: the statistical pieces, on small synthetic data with known answers."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.ds import causal, conformal, contracts, drift, evaluation, network, shrinkage, uplift

# ------------------------------------------------------------- shrinkage

def test_prior_recovers_beta_mean_and_strength():
    rng = np.random.default_rng(0)
    p = rng.beta(6, 4, 20_000)                       # mean 0.6, kappa 10
    n = rng.integers(30, 300, 20_000)
    brand = rng.binomial(n, p)
    a, b = shrinkage.fit_prior(brand.astype(float), n.astype(float))
    assert abs(a / (a + b) - 0.6) < 0.01
    assert 7 < a + b < 13


def test_shrinkage_pulls_small_denominators_hardest():
    priors = pd.DataFrame({"specialty_group": ["X"], "a": [5.0], "b": [5.0]})
    f = pd.DataFrame({"specialty_group": ["X", "X"], "brand": [2.0, 200.0], "n": [2.0, 200.0]})
    s = shrinkage.shrink(f, priors, "brand", "n")
    assert s[0] < 0.65                               # 2/2 pulled far from 100%
    assert s[1] > 0.95                               # 200/200 barely moves


# ------------------------------------------------------------ evaluation

def test_ndcg_perfect_and_reversed():
    rel = np.array([3.0, 2.0, 1.0, 0.0])
    assert evaluation.ndcg_at_k(rel, rel, 3) == pytest.approx(1.0)
    assert evaluation.ndcg_at_k(-rel, rel, 3) < 0.5


def test_metrics_at_k_capture_bounds():
    rng = np.random.default_rng(1)
    n = 2000
    f = pd.DataFrame({"growth_abs": rng.normal(0, 5, n), "eb_growth_share": rng.normal(0, .02, n),
                      "class_fills": rng.integers(1, 500, n).astype(float)})
    f["eb_share_fills"] = f["eb_growth_share"] * f["class_fills"]
    oracle = evaluation.metrics_at_k(f["eb_share_fills"].to_numpy(), f, 200)
    rand = evaluation.metrics_at_k(rng.random(n), f, 200)
    assert 0 <= rand["value_capture"] < oracle["value_capture"] <= 1
    assert oracle["precision_at_k"] == pytest.approx(1.0)


# ------------------------------------------------------------- conformal

def test_conformal_qhat_gives_finite_sample_coverage():
    rng = np.random.default_rng(2)
    scores = rng.normal(size=999)
    q = conformal.qhat(scores, alpha=0.1)
    fresh = rng.normal(size=50_000)
    assert (fresh <= q).mean() >= 0.895


def test_conformity_score_sign():
    lo, hi = np.array([0.0, 0.0]), np.array([1.0, 1.0])
    s = conformal.conformity(lo, hi, np.array([0.5, 2.0]))
    assert s[0] < 0 < s[1]


# ---------------------------------------------------------------- causal

def test_plr_recovers_known_effect_under_confounding():
    rng = np.random.default_rng(3)
    n = 4000
    x = rng.normal(size=(n, 3))
    d = (x[:, 0] + rng.normal(size=n) > 0).astype(float)          # treatment depends on x0
    y = 0.5 * d + 2.0 * x[:, 0] + rng.normal(size=n)               # true effect 0.5
    naive = y[d == 1].mean() - y[d == 0].mean()
    ry, rd = causal.crossfit_residuals(x, y, d, binary=True)
    est = causal.plr(ry, rd)
    assert naive > 1.5                                             # badly confounded
    assert abs(est["theta"] - 0.5) < 3 * est["se"] + 0.1


def test_robustness_value_monotone_in_t():
    assert causal.robustness_value(2.0, 10_000) < causal.robustness_value(10.0, 10_000)
    assert causal.robustness_value(1.0, 10_000, alpha_t=1.96) == 0.0


# ---------------------------------------------------------------- uplift

def test_dr_learner_ranks_true_heterogeneity():
    rng = np.random.default_rng(4)
    n = 6000
    x = rng.normal(size=(n, 2))
    t = (rng.random(n) < 1 / (1 + np.exp(-x[:, 1]))).astype(float)
    tau_true = np.where(x[:, 0] > 0, 1.0, 0.0)
    y = tau_true * t + x[:, 1] + rng.normal(size=n)
    phi, _, fold = uplift.dr_pseudo_outcome(x, y, t)
    tau = uplift.cate_out_of_fold(x, phi, fold)
    assert np.corrcoef(tau, tau_true)[0, 1] > 0.5
    q = uplift.qini(tau, phi)
    mid = q.iloc[len(q) // 2]
    assert mid["uplift_model"] > mid["uplift_random"]


# ----------------------------------------------------------------- drift

def test_psi_zero_for_same_distribution_and_large_for_shift():
    rng = np.random.default_rng(5)
    a = rng.normal(size=20_000)
    assert drift.psi(a, rng.normal(size=20_000)) < 0.01
    assert drift.psi(a, rng.normal(1.0, 1, 20_000)) > 0.25


def test_categorical_psi():
    a = pd.Series(["x"] * 50 + ["y"] * 50)
    assert drift.psi_categorical(a, a) == pytest.approx(0.0, abs=1e-9)
    assert drift.psi_categorical(a, pd.Series(["x"] * 90 + ["y"] * 10)) > 0.25


# -------------------------------------------------------------- network

def test_loo_peer_excludes_self():
    members = pd.DataFrame({"npi": [1, 2, 3], "practice": [9, 9, 9]})
    vals = pd.Series([0.0, 0.3, 0.6], index=pd.Index([1, 2, 3], name="npi"))
    loo = network.loo_peer(members, vals, "peer")
    assert loo.loc[1] == pytest.approx(0.45)
    assert loo.loc[3] == pytest.approx(0.15)


def test_icc_detects_practice_clustering():
    rng = np.random.default_rng(6)
    practice = np.repeat(np.arange(200), 10)
    members = pd.DataFrame({"npi": np.arange(2000), "practice": practice})
    clustered = pd.Series(rng.normal(size=200)[practice] + 0.3 * rng.normal(size=2000),
                          index=pd.Index(np.arange(2000), name="npi"))
    assert network.icc(members, clustered) > 0.7
    noise = pd.Series(rng.normal(size=2000), index=pd.Index(np.arange(2000), name="npi"))
    assert network.icc(members, noise) < 0.1


# ------------------------------------------------------------ contracts

def test_contracts_catch_violations(tmp_path):
    good = pd.DataFrame({"npi": [1, 2], "year": [2023, 2023], "x": [0.5, 0.7]})
    bad = pd.DataFrame({"npi": [1, 1], "year": [2023, 2023], "x": [0.5, 3.0]})
    good.to_parquet(tmp_path / "good.parquet")
    bad.to_parquet(tmp_path / "bad.parquet")
    spec = {"min_rows": 1, "key": ["npi", "year"],
            "columns": {"x": {"type": "numeric", "nullable": 0.0, "min": 0, "max": 1}},
            "rules": ["x >= 0"]}
    res = contracts.validate({"good": spec, "bad": spec}, tmp_path)
    assert res[res["table"] == "good"]["passed"].all()
    failed = set(res[(res["table"] == "bad") & ~res["passed"]]["check"])
    assert any(c.startswith("unique") for c in failed)
    assert "x: range" in failed


def test_contracts_report_missing_table(tmp_path):
    res = contracts.validate({"absent": {"min_rows": 1}}, tmp_path)
    assert not res["passed"].any()
