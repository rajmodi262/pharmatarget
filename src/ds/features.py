"""One design matrix for every supervised model in the data-science layer.

Same covariates as the challenger (practice, market, specialty, region, and the
brand state the frontier model is forbidden), built by the same function, so a
difference between two models is a difference in the model, never in the
features it happened to be handed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.preprocessing import OneHotEncoder

from src.models import opportunity as opp
from src.models.challenger import STATE_FEATURES, _prep


def numeric_features(extra: list[str] | None = None) -> list[str]:
    return list(opp.NUMERIC_FEATURES) + list(STATE_FEATURES) + list(extra or [])


def design(frame: pd.DataFrame, enc: OneHotEncoder | None = None,
           extra: list[str] | None = None) -> tuple[np.ndarray, OneHotEncoder, list[str]]:
    """(X, encoder, names). Pass the encoder back in to transform a later panel."""
    p = _prep(frame)
    for c in extra or []:
        p[c] = pd.to_numeric(frame[c], errors="coerce").fillna(0.0).to_numpy()
    num = [c for c in numeric_features(extra) if c in p.columns]
    fit = enc is None
    if fit:
        enc = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
        cat = enc.fit_transform(p[opp.CATEGORICAL_FEATURES])
    else:
        cat = enc.transform(p[opp.CATEGORICAL_FEATURES])
    X = np.hstack([p[num].to_numpy(dtype=np.float32), cat.astype(np.float32)])
    names = num + list(enc.get_feature_names_out(opp.CATEGORICAL_FEATURES))
    return X, enc, names


def gbm(loss: str = "squared_error", quantile: float | None = None, seed: int = 0,
        max_iter: int = 200) -> HistGradientBoostingRegressor:
    kw = {"quantile": quantile} if loss == "quantile" else {}
    return HistGradientBoostingRegressor(
        loss=loss, max_iter=max_iter, max_depth=6, learning_rate=0.06,
        min_samples_leaf=80, l2_regularization=1.0, random_state=seed,
        early_stopping=False, **kw)


def gbm_classifier(seed: int = 0) -> HistGradientBoostingClassifier:
    return HistGradientBoostingClassifier(
        max_iter=200, max_depth=5, learning_rate=0.06, min_samples_leaf=100,
        l2_regularization=1.0, random_state=seed, early_stopping=False)


def folds(n: int, k: int = 5, seed: int = 0) -> np.ndarray:
    """Fold id per row, for cross-fitting."""
    return np.random.default_rng(seed).integers(0, k, n)
