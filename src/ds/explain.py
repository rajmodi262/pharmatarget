"""Exact per-prescriber explanations: why does Dr X rank where they rank?

    python -m src.ds.explain

The production frontier is a scikit-learn histogram GBM, which SHAP's tree
explainer cannot open. Rather than approximate it with KernelSHAP on 267,000
prescribers, this fits a REPLICA -- XGBoost with the same quantile objective
(tau 0.80), the same features and the same training year -- and reads exact
TreeSHAP contributions from it (pred_contribs). The replica is only trusted as
far as its FIDELITY to the production model, which is measured and reported:
rank correlation of the two potentials across every in-market prescriber.

Contributions are in log1p(class fills) space, so exp(contribution) is a
multiplier on modelled potential: "+0.40 from panel size" reads "panel size
lifts this prescriber's potential by 1.5x against the average prescriber".
One-hot columns are summed back to their parent (specialty, region).
"""
from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.preprocessing import OneHotEncoder

from src.config import params, path
from src.ds.tracking import log_run
from src.models import opportunity as opp
from src.utils.io import get_logger, record, write_parquet

log = get_logger(__name__)

TOP_N = 5
LABEL = {
    "log_panel_benes": "Medicare panel size",
    "log_non_class_clms": "Total prescribing volume (other drugs)",
    "risk_score": "Patient risk score",
    "log_age65_cnt": "Patients aged 65+",
    "pct_panel_65": "Share of panel aged 65+",
    "log_zip3_population": "Local population",
    "log_pop_density": "Population density",
    "prev_stroke": "Local stroke prevalence",
    "prev_chd": "Local heart-disease prevalence",
    "prev_bp": "Local hypertension prevalence",
    "specialty_group": "Specialty",
    "region": "Region",
}


def load_year(year: int) -> pd.DataFrame:
    f = (path("processed") / "hcp_scored.parquet").as_posix()
    cols = ["npi", "class_fills", "potential_class", "specialty_group", "region", "panel_benes",
            "non_class_clms", "age65_cnt", "risk_score", "pct_panel_65", "zip3_population",
            "zip3_pop_density", "prev_stroke", "prev_chd", "prev_bp"]
    con = duckdb.connect()
    try:
        return con.execute(f"SELECT {', '.join(cols)} FROM read_parquet('{f}') "
                           f"WHERE year = {year} AND class_fills > 0").df()
    finally:
        con.close()


def matrix(df: pd.DataFrame, enc: OneHotEncoder | None = None):
    feat = opp.build_features(df)
    num = opp.active_features(feat)
    if enc is None:
        enc = OneHotEncoder(handle_unknown="ignore", sparse_output=False).fit(
            feat[opp.CATEGORICAL_FEATURES])
    cat = enc.transform(feat[opp.CATEGORICAL_FEATURES])
    X = np.hstack([feat[num].to_numpy(dtype=np.float32), cat.astype(np.float32)])
    names = num + list(enc.get_feature_names_out(opp.CATEGORICAL_FEATURES))
    return X, names, enc, feat


def parent(name: str) -> str:
    for c in opp.CATEGORICAL_FEATURES:
        if name.startswith(c + "_"):
            return c
    return name


def run() -> dict:
    cfg = params()["opportunity_model"]
    year = params()["years"]["train_end"]
    df = load_year(year)
    X, names, enc, feat = matrix(df)
    y = np.log1p(df["class_fills"].to_numpy(dtype=float))

    model = xgb.XGBRegressor(
        objective="reg:quantileerror", quantile_alpha=cfg["tau"],
        n_estimators=cfg["n_estimators"], max_depth=cfg["max_depth"],
        learning_rate=cfg["learning_rate"], min_child_weight=cfg["min_samples_leaf"] / 10,
        tree_method="hist", nthread=2, random_state=cfg["random_state"])
    model.fit(X, y)
    pred = model.predict(X)
    fidelity = float(pd.Series(np.expm1(pred)).corr(df["potential_class"], method="spearman"))
    coverage = float((y <= pred).mean())

    contrib = model.get_booster().predict(xgb.DMatrix(X), pred_contribs=True)
    base = float(contrib[0, -1])
    phi = pd.DataFrame(contrib[:, :-1], columns=names)
    grouped = phi.T.groupby([parent(n) for n in names]).sum().T

    # Global importance: mean |SHAP| per parent feature.
    glob = grouped.abs().mean().sort_values(ascending=False)
    glob_df = pd.DataFrame({"feature": glob.index, "label": [LABEL.get(f, f) for f in glob.index],
                            "mean_abs_shap": glob.to_numpy(),
                            "share": (glob / glob.sum()).to_numpy()})

    # Per prescriber: the TOP_N drivers by magnitude, with the feature's value.
    vals = feat.reindex(columns=[c for c in grouped.columns if c in feat.columns])
    arr = grouped.to_numpy(dtype=np.float32)
    top = np.argsort(-np.abs(arr), axis=1)[:, :TOP_N]
    cols = np.array(grouped.columns)
    rows_npi = np.repeat(df["npi"].to_numpy(), TOP_N)
    feat_names = cols[top].ravel()
    contribs = np.take_along_axis(arr, top, axis=1).ravel()
    raw_vals = []
    for i, fname in zip(np.repeat(np.arange(len(df)), TOP_N), feat_names, strict=True):
        v = vals.iloc[i][fname] if fname in vals.columns else None
        raw_vals.append(str(v) if not isinstance(v, (float, np.floating)) else f"{float(v):.3g}")
    expl = pd.DataFrame({"npi": rows_npi, "rank": np.tile(np.arange(1, TOP_N + 1), len(df)),
                         "feature": feat_names, "label": [LABEL.get(f, f) for f in feat_names],
                         "contribution": contribs, "multiplier": np.exp(contribs).astype("float32"),
                         "value": raw_vals})

    proc = path("processed")
    write_parquet(expl, proc / "ds_explanations.parquet")
    write_parquet(glob_df, proc / "ds_shap_global.parquet")

    perm = pd.read_parquet(proc / "shap_drivers.parquet") if (proc / "shap_drivers.parquet").exists() else None
    agree = None
    if perm is not None:
        p = perm.assign(parent=perm["feature"].map(parent)).groupby("parent")["share_of_total"].sum()
        common = glob.index.intersection(p.index)
        agree = float(pd.Series(glob[common]).corr(p[common], method="spearman"))
    res = {
        "replica": "XGBoost reg:quantileerror, same features, tau and year",
        "fidelity_spearman": round(fidelity, 4),
        "replica_coverage": round(coverage, 4),
        "base_value_log": round(base, 4),
        "top_global": glob_df.head(5).round(4).to_dict(orient="records"),
        "agreement_with_permutation_importance": round(agree, 3) if agree is not None else None,
        "rows": int(len(expl)),
    }
    log.info("EXPLAIN: replica fidelity rho %.3f to the production frontier (coverage %.3f). "
             "Top global driver: %s (%.0f%% of mean |SHAP|). Agreement with permutation "
             "importance: rho %s.", fidelity, coverage, glob_df.iloc[0]["label"],
             100 * glob_df.iloc[0]["share"], res["agreement_with_permutation_importance"])
    record("ds_explain", **res)
    log_run("ds_explain", params={"replica": "xgboost quantile", "tau": cfg["tau"]},
            metrics={"fidelity_spearman": fidelity, "replica_coverage": coverage},
            artifacts=[proc / "ds_shap_global.parquet"])
    return res


if __name__ == "__main__":
    run()
