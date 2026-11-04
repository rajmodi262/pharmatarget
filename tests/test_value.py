"""Business case under uncertainty: switching costs, posterior, regret."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.models import value as v


def _grid() -> pd.DataFrame:
    reps = np.arange(40, 92, 2)
    # Concave contribution per unit ceiling, linear cost.
    K = 2e9 * (1 - np.exp(-reps / 60.0))
    return pd.DataFrame({"n_reps": reps, "contribution_per_ceiling": K,
                         "field_cost": reps * 250_000.0})


def _eco(hire=60_000.0, ramp=6.0, sep=50_000.0) -> v.Economics:
    return v.Economics(_grid(), 60, hire, ramp, sep)


def test_holding_is_the_zero_line():
    eco = _eco()
    V = eco.value(np.array([0.001, 0.01, 0.1]), 2.0)
    assert np.allclose(V[eco.i0], 0.0)


def test_switching_costs_make_change_dearer():
    free, costly = _eco(0, 0, 0), _eco()
    c = np.array([0.02])
    assert (costly.value(c, 2.0)[:, 0] <= free.value(c, 2.0)[:, 0] + 1e-6).all()
    # Releasing reps when calls do nothing still pays, net of severance.
    assert costly.value(np.array([0.0]), 2.0)[0, 0] > 0


def test_value_is_linear_in_response_without_ramp():
    eco = _eco(ramp=0)
    a = eco.value(np.array([0.01]), 2.0)[:, 0]
    b = eco.value(np.array([0.02]), 2.0)[:, 0]
    c = eco.value(np.array([0.03]), 2.0)[:, 0]
    assert np.allclose(b - a, c - b)


def test_posterior_mean_shrinks_towards_prior():
    f = v.posterior_mean_fn(median=0.02, log_sd=1.0, se=0.01)
    assert f(np.array([0.2]))[0] < 0.2          # a high reading is pulled down
    precise = v.posterior_mean_fn(median=0.02, log_sd=1.0, se=0.0005)
    assert abs(precise(np.array([0.05]))[0] - 0.05) < 0.003   # precise data dominates


def test_holdout_cost_fraction_bounded():
    planned = pd.DataFrame({"opportunity": np.linspace(1000, 1, 5000)})
    f = v.holdout_cost_fraction(planned, n_list=1000, holdout=0.2)
    assert 0 < f < 0.2


def test_regret_is_non_negative_and_zero_for_the_best():
    eco = _eco()
    pay = v.payoff_matrix(eco, 0.02, {"cut": 40, "hold": 60, "grow": 90})
    assert (pay["regret"] >= -1e-6).all()
    assert (pay.groupby("response_x")["regret"].min().abs() < 1e-6).all()


def test_grow_needs_more_than_break_even_when_hiring_costs():
    eco = _eco()
    x = v.grow_threshold(eco, 0.02)
    assert x is None or x >= 1.0
