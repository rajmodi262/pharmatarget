"""Calibrated prediction intervals for every prescriber's next-year branded fills.

    python -m src.ds.conformal

A point forecast is a promise nobody can check. A 90% interval that contains
the truth 90% of the time is one anybody can -- and the business case needs it:
"this prescriber will write 120 branded fills" is not the same claim as
"between 60 and 190, nine times in ten".

METHOD -- conformalised quantile regression (Romano et al. 2019)
    1. Gradient-boosted 5% and 95% quantile models on log1p(fills next year),
       fitted on half the 2022 -> 2023 panel.
    2. Calibrate on the other half: the (1-alpha) empirical quantile of
       max(lo - y, y - hi) widens (or narrows) both ends by one constant. This
       gives finite-sample marginal coverage >= 90% when calibration and test
       are exchangeable.
    3. MONDRIAN variant: one constant per size band, so small and large
       prescribers are each covered at 90%, not just on average.

TWO PARTS, because about 19% of in-market prescribers write none of the brand
the next year at a reportable volume (14% leave the class -- retirement, a move
-- and more switch or fall under CMS's 11-claim floor). A single interval has
to stretch to zero for everyone to cover them, which makes it useless. So: a
classifier for P(still writes the brand), and the conformal interval
conditional on that -- the standard hurdle structure for zero-heavy counts.

WHAT IT FOUND: in period the intervals cover exactly 90.0% in every size band
and in rural and urban practices alike (what the theory promises). Out of time
they cover 89.3%: conformal recovers a point the raw quantiles lose, and the
remaining shortfall is year-to-year drift, concentrated in the largest
prescribers (87%). Mondrian per-band constants trade a little coverage between
bands without fixing that, so production uses the simpler marginal version.


THE HONEST TEST is out of time: fit and calibrate on 2022 -> 2023, measure
coverage on 2023 -> 2024. Exchangeability does not hold across years, so any
shortfall is drift, measured -- not hidden.

The production forecast refits on the latest panel (2023 -> 2024) and predicts
2025 from 2024 state for every in-market prescriber; the Targets drawer shows it.
Point predictions are also checked for CALIBRATION (decile of prediction vs
mean outcome).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score

from src.config import params, path
from src.ds import features as F
from src.ds.data import SIZE_BANDS, SIZE_LABELS, load_scored, panels
from src.ds.tracking import log_run
from src.utils.io import get_logger, record, write_parquet

log = get_logger(__name__)

ALPHA = 0.10
SEGMENTS = ("size_band", "specialty_group", "region", "rural")


def _y(frame: pd.DataFrame) -> np.ndarray:
    return np.log1p(frame["brand_fills_next"].to_numpy(dtype=float).clip(0))


def fit_cqr(X: np.ndarray, y: np.ndarray, seed: int = 0):
    lo = F.gbm("quantile", ALPHA / 2, seed=seed, max_iter=150).fit(X, y)
    hi = F.gbm("quantile", 1 - ALPHA / 2, seed=seed, max_iter=150).fit(X, y)
    return lo, hi


def conformity(lo: np.ndarray, hi: np.ndarray, y: np.ndarray) -> np.ndarray:
    return np.maximum(lo - y, y - hi)


def qhat(scores: np.ndarray, alpha: float = ALPHA) -> float:
    n = len(scores)
    level = min(np.ceil((n + 1) * (1 - alpha)) / n, 1.0)
    return float(np.quantile(scores, level, method="higher"))


def coverage_table(frame: pd.DataFrame, lo: np.ndarray, hi: np.ndarray,
                   y: np.ndarray, label: str) -> pd.DataFrame:
    inside = (y >= lo) & (y <= hi)
    width = np.expm1(hi) - np.expm1(lo)
    d = frame[list(SEGMENTS)].copy()
    d["rural"] = np.where(d["rural"], "rural", "urban")
    d["inside"], d["width"] = inside, width
    rows = [{"variant": label, "segment": "all", "level": "all",
             "coverage": float(inside.mean()), "median_width": float(np.median(width)), "n": len(d)}]
    for seg in SEGMENTS:
        for lvl, g in d.groupby(seg):
            if len(g) >= 200:
                rows.append({"variant": label, "segment": seg, "level": str(lvl),
                             "coverage": float(g["inside"].mean()),
                             "median_width": float(g["width"].median()), "n": len(g)})
    return pd.DataFrame(rows)


def calibration(pred: np.ndarray, actual: np.ndarray, bins: int = 10) -> pd.DataFrame:
    q = pd.qcut(pd.Series(pred).rank(method="first"), bins, labels=False)
    df = pd.DataFrame({"bin": q, "pred": pred, "actual": actual})
    return df.groupby("bin").agg(mean_pred=("pred", "mean"), mean_actual=("actual", "mean"),
                                 n=("pred", "size")).reset_index()


def _active(frame: pd.DataFrame) -> np.ndarray:
    """Still writing the BRAND next year at a reportable volume (the hurdle).

    Not "still writing the class": about 6% of class writers write zero of the
    brand the next year (a switch, or brand rows under CMS's 11-claim floor), and
    that alone pins a 5% lower quantile at zero for everyone.
    """
    return (frame["brand_fills_next"].to_numpy(dtype=float) > 0)


def run() -> dict:
    train, apply_ = panels()
    rng = np.random.default_rng(0)
    half = rng.random(len(train)) < 0.5
    fit_df, cal_df = train[half], train[~half]

    Xf, enc, _ = F.design(fit_df)
    Xc, _, _ = F.design(cal_df, enc)
    Xa, _, _ = F.design(apply_, enc)

    # ---- part 1: will this prescriber still write the class next year? -------
    act_f, act_a = _active(fit_df), _active(apply_)
    clf = F.gbm_classifier(0).fit(Xf, act_f.astype(int))
    p_a = clf.predict_proba(Xa)[:, 1]
    auc = float(roc_auc_score(act_a, p_a))
    brier = float(brier_score_loss(act_a, p_a))
    hurdle_cal = calibration(p_a, act_a.astype(float))

    # ---- part 2: how many branded fills, GIVEN still writing? ----------------
    mf, mc, ma = act_f, _active(cal_df), act_a
    yf, yc, ya = _y(fit_df)[mf], _y(cal_df)[mc], _y(apply_)[ma]
    lo_m, hi_m = fit_cqr(Xf[mf], yf)
    lc, hc = lo_m.predict(Xc[mc]), hi_m.predict(Xc[mc])
    la, ha = lo_m.predict(Xa[ma]), hi_m.predict(Xa[ma])
    cal_a, app_a = cal_df[mc], apply_[ma]

    q = qhat(conformity(lc, hc, yc))
    qb = {b: qhat(conformity(lc[m], hc[m], yc[m]))
          for b in SIZE_LABELS if (m := (cal_a["size_band"] == b).to_numpy()).sum() > 50}
    qa = app_a["size_band"].map(qb).fillna(q).to_numpy()

    in_period = coverage_table(cal_a, lc - q, hc + q, yc, "in-period (calibration half)")
    raw = coverage_table(app_a, la, ha, ya, "out-of-time, uncalibrated quantiles")
    marg = coverage_table(app_a, la - q, ha + q, ya, "out-of-time, conformal")
    mond = coverage_table(app_a, la - qa, ha + qa, ya, "out-of-time, Mondrian conformal")
    cov = pd.concat([in_period, raw, marg, mond], ignore_index=True)

    # Point-forecast calibration of the unconditional mean (Poisson GBM).
    point = F.gbm("poisson", seed=0).fit(Xf, fit_df["brand_fills_next"].to_numpy(dtype=float).clip(0))
    cal = calibration(point.predict(Xa), apply_["brand_fills_next"].to_numpy(dtype=float))
    slope = float(np.polyfit(cal["mean_pred"], cal["mean_actual"], 1)[0])

    # ---- production forecast: refit on the latest panel, predict 2025 --------
    y_hold = params()["years"]["holdout"]
    scored = load_scored()
    latest = scored[(scored["year"] == y_hold) & (scored["class_fills"] > 0)].copy()
    del scored
    h2 = rng.random(len(apply_)) < 0.5
    Xf2, enc2, _ = F.design(apply_[h2])
    Xc2, _, _ = F.design(apply_[~h2], enc2)
    a2f, a2c = _active(apply_[h2]), _active(apply_[~h2])
    clf2 = F.gbm_classifier(1).fit(Xf2, a2f.astype(int))
    lo2, hi2 = fit_cqr(Xf2[a2f], _y(apply_[h2])[a2f], seed=1)
    # Point forecast = conditional MEDIAN from the same quantile family, so it
    # always sits inside its own interval.
    med2 = F.gbm("quantile", 0.5, seed=1, max_iter=150).fit(Xf2[a2f], _y(apply_[h2])[a2f])
    # Marginal, not Mondrian: the out-of-time test shows per-band constants
    # fitted on one year under-cover large prescribers the next.
    q2 = qhat(conformity(lo2.predict(Xc2[a2c]), hi2.predict(Xc2[a2c]), _y(apply_[~h2])[a2c]))
    latest["size_band"] = pd.cut(latest["class_fills"], SIZE_BANDS, labels=SIZE_LABELS,
                                 right=False).astype(str)
    XL, _, _ = F.design(latest, enc2)
    lo_l, hi_l = lo2.predict(XL) - q2, hi2.predict(XL) + q2
    lo_l, hi_l = np.minimum(lo_l, hi_l), np.maximum(lo_l, hi_l)
    mid_l = np.clip(med2.predict(XL), lo_l, hi_l)
    forecast = pd.DataFrame({
        "npi": latest["npi"].to_numpy(),
        "forecast_year": y_hold + 1,
        "p_active": clf2.predict_proba(XL)[:, 1].astype("float32"),
        "brand_fills_pred": np.expm1(mid_l).clip(0).astype("float32"),
        "brand_fills_lo": np.expm1(lo_l).clip(0).astype("float32"),
        "brand_fills_hi": np.expm1(hi_l).clip(0).astype("float32"),
    })

    proc = path("processed")
    write_parquet(cov, proc / "ds_conformal_coverage.parquet")
    write_parquet(cal, proc / "ds_calibration.parquet")
    write_parquet(hurdle_cal, proc / "ds_hurdle_calibration.parquet")
    write_parquet(forecast, proc / "ds_forecast.parquet")

    def overall(df: pd.DataFrame) -> float:
        return float(df[df["segment"] == "all"]["coverage"].iloc[0])

    mon = mond[mond["segment"] == "size_band"]
    mar = marg[marg["segment"] == "size_band"]
    res = {
        "alpha": ALPHA,
        "target_coverage": 1 - ALPHA,
        "structure": "two-part: P(still writes the brand) x conformal interval given that",
        "hurdle_auc": round(auc, 4),
        "hurdle_brier": round(brier, 4),
        "active_rate_next_year": round(float(act_a.mean()), 4),
        "in_period_coverage": round(overall(in_period), 4),
        "out_of_time_uncalibrated": round(overall(raw), 4),
        "out_of_time_conformal": round(overall(marg), 4),
        "out_of_time_mondrian": round(overall(mond), 4),
        "worst_size_band_marginal": round(float(mar["coverage"].min()), 4),
        "worst_size_band_mondrian": round(float(mon["coverage"].min()), 4),
        "median_width_fills": round(float(marg[marg["segment"] == "all"]["median_width"].iloc[0]), 1),
        "conformal_constant_log": round(q, 4),
        "calibration_slope": round(slope, 3),
        "forecast_rows": int(len(forecast)),
        "forecast_lower_bound_positive_share": round(float((forecast["brand_fills_lo"] > 0).mean()), 4),
        "production_variant": "marginal conformal, conditional on still writing",
        "forecast_year": int(y_hold + 1),
    }
    log.info("HURDLE: P(still writes the brand next year) AUC %.3f, Brier %.3f (%.1f%% do).",
             auc, brier, 100 * res["active_rate_next_year"])
    log.info("CONFORMAL given active (target %.0f%%): in-period %.1f%%; out-of-time raw %.1f%%, "
             "conformal %.1f%%, Mondrian %.1f%% (worst size band %.1f%% vs %.1f%%). Median width "
             "%.0f fills. Point calibration slope %.2f.", 100 * (1 - ALPHA),
             100 * res["in_period_coverage"], 100 * res["out_of_time_uncalibrated"],
             100 * res["out_of_time_conformal"], 100 * res["out_of_time_mondrian"],
             100 * res["worst_size_band_marginal"], 100 * res["worst_size_band_mondrian"],
             res["median_width_fills"], slope)
    record("ds_conformal", **res)
    log_run("ds_conformal", params={"alpha": ALPHA, "method": "hurdle + CQR (+ Mondrian variant)"},
            metrics={k: v for k, v in res.items() if isinstance(v, (int, float))},
            artifacts=[proc / "ds_conformal_coverage.parquet"])
    return res


if __name__ == "__main__":
    run()
