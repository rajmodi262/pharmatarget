"""Champion vs challenger: is the frontier framing actually the best model?

THE QUESTION
------------
The opportunity score is built the pharma way -- estimate an achievable frontier
from market and practice covariates, then subtract what the brand already has.
It is interpretable: you can show a rep WHY a prescriber scored, in terms of
panel size, patient age mix and local disease prevalence.

But interpretable is not the same as accurate, and the obvious machine-learning
alternative was never tested: train a model to predict next-year branded growth
DIRECTLY, with the full observable state as features, and rank on the
prediction. No frontier, no subtraction, no theory -- just supervised learning
on the outcome we actually care about.

This module runs both against the same held-out year and reports which wins.

THE DESIGN, AND WHY IT IS A FAIR FIGHT
--------------------------------------
    CHAMPION   frontier opportunity scored at t, evaluated against t->t+1 growth
    CHALLENGER trained on (state at t-1 -> growth t-1->t), applied to state at t,
               evaluated against the same t->t+1 growth

Both are strictly out-of-time: the challenger learns the growth relationship
from an EARLIER period and is applied to a later one, exactly as it would be in
production. Neither sees the holdout year during fitting.

The challenger is deliberately given MORE information than the champion's
potential model: current class volume, brand volume and brand share are all
features. The frontier model is forbidden those (they would leak its target);
the challenger is not, because its target is growth rather than level. If the
frontier framing still wins under that handicap, it has earned its place.

Two targets are fitted, because the choice of target is itself a modelling
decision worth testing:
    absolute growth      change in branded 30-day fills
    share-point growth   change in brand share -- volume-neutral

Every result is reported. If the challenger wins, the README says so.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.preprocessing import OneHotEncoder

from src.config import params, path
from src.models import opportunity as opp
from src.utils.io import get_logger, read_parquet, record, write_parquet

log = get_logger(__name__)

# The challenger's design matrix: the potential model's covariates PLUS the
# brand-state variables the frontier model is not allowed to see.
STATE_FEATURES = [
    "log_class_fills",
    "log_brand_fills",
    "brand_share",
    "log_potential_gap",     # how far below the frontier -- the champion's signal
]


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    """Feature engineering shared by train and apply, so they cannot diverge."""
    out = opp.build_features(df)
    out["log_class_fills"] = np.log1p(out["class_fills"].clip(lower=0))
    out["log_brand_fills"] = np.log1p(out["brand_fills"].clip(lower=0))
    out["brand_share"] = out["brand_share"].fillna(0.0)
    gap = (out.get("potential_brand", pd.Series(0.0, index=out.index))
           - out["brand_fills"]).clip(lower=0)
    out["log_potential_gap"] = np.log1p(gap)
    return out


def _design(frame: pd.DataFrame, enc: OneHotEncoder, numeric: list[str],
            fit: bool = False) -> np.ndarray:
    cats = frame[opp.CATEGORICAL_FEATURES]
    cat = enc.fit_transform(cats) if fit else enc.transform(cats)
    return np.hstack([frame[numeric].to_numpy(dtype=float), cat])


def build_panels(scored: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(train, apply) frames with next-year outcomes attached.

    train  state at t-1 with realised growth t-1 -> t   (the learning period)
    apply  state at t   with realised growth t   -> t+1 (the holdout)
    """
    p = params()["years"]
    y0, y1, y2 = p["train_start"], p["train_end"], p["holdout"]

    def outcomes(year: int) -> pd.DataFrame:
        return (scored[scored["year"] == year]
                [["npi", "brand_fills", "brand_share"]]
                .rename(columns={"brand_fills": "brand_fills_next",
                                 "brand_share": "brand_share_next"}))

    def state(year: int) -> pd.DataFrame:
        return scored[(scored["year"] == year) & (scored["class_fills"] > 0)].copy()

    train = state(y0).merge(outcomes(y1), on="npi", how="inner")
    apply_ = state(y1).merge(outcomes(y2), on="npi", how="inner")

    for frame in (train, apply_):
        # A prescriber with no class volume next year has an UNDEFINED brand
        # share, not a zero one. For a growth target the right reading is that
        # they stopped writing the brand, so both sides are floored at zero and
        # the change is measured from there. Leaving them NaN would silently
        # drop exactly the prescribers who churned -- the ones a targeting model
        # most needs to learn from.
        frame["brand_fills"] = frame["brand_fills"].fillna(0.0)
        frame["brand_fills_next"] = frame["brand_fills_next"].fillna(0.0)
        frame["brand_share"] = frame["brand_share"].fillna(0.0)
        frame["brand_share_next"] = frame["brand_share_next"].fillna(0.0)
        frame["growth_abs"] = frame["brand_fills_next"] - frame["brand_fills"]
        frame["growth_share"] = frame["brand_share_next"] - frame["brand_share"]

    log.info("challenger panels: train %s (%d->%d), apply %s (%d->%d)",
             f"{len(train):,}", y0, y1, f"{len(apply_):,}", y1, y2)
    return train, apply_


def fit_challenger(train: pd.DataFrame, target: str) -> tuple:
    cfg = params()["opportunity_model"]
    numeric = opp.NUMERIC_FEATURES.copy()
    numeric = [c for c in numeric if c in _prep(train.head(50)).columns]
    numeric += STATE_FEATURES

    tr = _prep(train)
    enc = OneHotEncoder(handle_unknown="ignore", sparse_output=False)
    X = _design(tr, enc, numeric, fit=True)
    y = tr[target].to_numpy(dtype=float)

    model = HistGradientBoostingRegressor(
        loss="squared_error",
        max_iter=cfg["n_estimators"],
        max_depth=cfg["max_depth"],
        learning_rate=cfg["learning_rate"],
        min_samples_leaf=cfg["min_samples_leaf"],
        random_state=cfg["random_state"],
        early_stopping=False,
    )
    model.fit(X, y)
    log.info("  challenger[%s] fitted on %s rows, %d features",
             target, f"{len(y):,}", X.shape[1])
    return model, enc, numeric


def score_rules(apply_: pd.DataFrame, models: dict) -> pd.DataFrame:
    """Attach every competing score to the holdout frame."""
    out = apply_.copy()
    ap = _prep(apply_)
    for name, (model, enc, numeric) in models.items():
        out[f"score_{name}"] = model.predict(_design(ap, enc, numeric))
    out["score_opportunity"] = out["opportunity"]
    out["score_volume"] = out["class_fills"]
    return out


def evaluate(df: pd.DataFrame, rules: list[str], n_budget: int) -> pd.DataFrame:
    """Head-to-head on the metrics the back-test already uses.

    Capture is measured at a FIXED N -- the number of prescribers a real force
    can actually cover. Comparing rules at unlimited depth would flatter every
    one of them equally and answer a question nobody is asking.
    """
    total_abs = df.loc[df["growth_abs"] > 0, "growth_abs"].sum()
    total_share = df.loc[df["growth_share"] > 0, "growth_share"].sum()

    rows = []
    for rule in rules:
        col = f"score_{rule}"
        top = df.nlargest(n_budget, col)
        decile = pd.qcut(df[col].rank(method="first"), 10, labels=False) + 1
        lift = df.assign(_d=decile).groupby("_d")["growth_abs"].mean()

        rows.append({
            "rule": rule,
            "abs_capture": round(float(top["growth_abs"].clip(lower=0).sum() / total_abs), 4),
            "share_capture": round(float(top["growth_share"].clip(lower=0).sum() / total_share), 4),
            "mean_share_growth": round(float(top["growth_share"].mean()), 5),
            "spearman_decile_growth": round(
                float(pd.Series(lift.index).corr(pd.Series(lift.to_numpy()), method="spearman")), 4),
            # THE DIAGNOSTIC THAT DECIDES WHETHER A SHARE-CAPTURE WIN IS REAL.
            #
            # Share growth has a denominator. A prescriber writing 2 class fills
            # who moves from 0 to 1 branded fill posts +50 share points; one
            # writing 400 fills cannot post that whatever they do. So a model
            # trained to maximise share growth can win the metric by finding
            # microscopic prescribers whose share is volatile because the base
            # is tiny -- and deliver almost no actual volume.
            #
            # The mean base volume of the selected list is what separates
            # "found persuadable prescribers" from "found small denominators".
            "mean_base_class_fills": round(float(top["class_fills"].mean()), 1),
            "median_base_class_fills": round(float(top["class_fills"].median()), 1),
            "total_base_class_fills": float(top["class_fills"].sum()),
        })
    return pd.DataFrame(rows)


def run() -> pd.DataFrame:
    proc = path("processed")
    scored = read_parquet(proc / "hcp_scored.parquet")
    train, apply_ = build_panels(scored)

    models = {
        "ml_abs": fit_challenger(train, "growth_abs"),
        "ml_share": fit_challenger(train, "growth_share"),
    }
    scored_apply = score_rules(apply_, models)

    # Budget = what 60 reps actually cover, from the capacity-constrained plan.
    from src.models.callplan import apply_call_plan
    n_budget = int(apply_call_plan(apply_)["is_target"].sum()) or int(0.03 * len(apply_))

    results = evaluate(
        scored_apply,
        ["opportunity", "volume", "ml_abs", "ml_share"],
        n_budget,
    )
    results = results.sort_values("share_capture", ascending=False).reset_index(drop=True)

    log.info("=" * 74)
    log.info("HEAD-TO-HEAD at N=%s prescribers (what %d reps can cover)",
             f"{n_budget:,}", params()["territory"]["n_reps_default"])
    log.info("=" * 74)
    log.info("%-14s %14s %14s %14s", "rule", "share capture", "abs capture", "spearman")
    for r in results.itertuples(index=False):
        log.info("%-14s %13.1f%% %13.1f%% %14.3f",
                 r.rule, 100 * r.share_capture, 100 * r.abs_capture,
                 r.spearman_decile_growth)

    champion = results[results["rule"] == "opportunity"].iloc[0]
    winner = results.iloc[0]
    margin = winner["share_capture"] - champion["share_capture"]

    if winner["rule"] == "opportunity":
        log.info("CHAMPION HOLDS: the frontier framing wins on share-growth capture "
                 "despite the challenger seeing brand state it is denied.")
    else:
        log.warning("CHALLENGER WINS on share-growth capture: '%s' beats the frontier "
                    "score by %.1f pp (%.1f%% vs %.1f%%).",
                    winner["rule"], 100 * margin,
                    100 * winner["share_capture"], 100 * champion["share_capture"])

    # --- and now the part that decides whether that win means anything ------
    #
    # Read the base-volume column before believing any share-capture number.
    # A rule selecting prescribers with a tiny median base is not finding
    # persuadable doctors, it is finding small denominators: share moves easily
    # when almost nothing is being written, and moving it produces no volume.
    base = results.set_index("rule")["median_base_class_fills"]
    win_base = float(base.get(winner["rule"], 0.0))
    champ_base = float(base.get("opportunity", 0.0))

    if winner["rule"] != "opportunity" and win_base < 0.25 * champ_base:
        log.warning(
            "BUT THE METRIC IS GAMED. '%s' selects prescribers with a median base of "
            "%.0f class fills against %.0f for the frontier score, and captures only "
            "%.1f%% of absolute growth against %.1f%%. Share growth on a tiny "
            "denominator is arithmetic, not persuadability -- visiting those "
            "prescribers produces no volume.\n"
            "    CONCLUSION: the share-capture criterion is gameable and should not "
            "stand alone as gate G3. Report absolute capture alongside it, and state "
            "plainly that plain VOLUME ranking wins on absolute growth -- which the "
            "back-test cannot separate from growth that would have happened anyway, "
            "because CMS contains no call data.",
            winner["rule"], win_base, champ_base,
            100 * float(results.set_index("rule")["abs_capture"].get(winner["rule"], 0)),
            100 * float(results.set_index("rule")["abs_capture"].get("opportunity", 0)))
        record("challenger_verdict",
               metric_gamed=True,
               winner_median_base=win_base,
               champion_median_base=champ_base,
               note="share-capture win driven by small denominators, not persuadability")

    write_parquet(results, proc / "challenger_results.parquet")
    record("challenger",
           n_budget=n_budget,
           winner=str(winner["rule"]),
           champion_share_capture=float(champion["share_capture"]),
           winner_share_capture=float(winner["share_capture"]),
           margin_pp=round(float(100 * margin), 2),
           results=results.to_dict(orient="records"))
    return results


if __name__ == "__main__":
    run()
