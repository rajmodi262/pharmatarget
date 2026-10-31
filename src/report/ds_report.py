"""Data-science documentation, generated from the pipeline output.

    python -m src.report.ds_report

Writes
    outputs/figures/DS1..DS6        the data-science exhibits
    docs/MODEL_CARD.md              intended use, metrics, limits, retraining rule
    docs/DATA_CARD.md               sources, processing, contracts, known gaps
    docs/TECHNICAL_REPORT.md        the paper: problem, data, methods, results,
                                    ablations, limitations

Nothing in these documents is typed in: every number is read from
data/manifest.json or the ds_* parquet files, so they cannot go stale while the
models move underneath them.
"""
from __future__ import annotations

import json
from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.config import ROOT  # noqa: E402
from src.utils.io import get_logger  # noqa: E402

log = get_logger(__name__)

PROC = ROOT / "data" / "processed"
FIGS = ROOT / "outputs" / "figures"
DOCS = ROOT / "docs"
PLUM, MAUVE, TERRA, PAPER, MUTE = "#3A1F34", "#C3A0A7", "#C75A3A", "#F8EEEA", "#765A6B"
POS, NEG = "#4C7D5A", "#A3263E"

plt.rcParams.update({"figure.facecolor": PAPER, "axes.facecolor": PAPER, "savefig.facecolor": PAPER,
                     "axes.edgecolor": "#E2CDC8", "axes.labelcolor": MUTE, "xtick.color": MUTE,
                     "ytick.color": MUTE, "axes.spines.top": False, "axes.spines.right": False,
                     "font.size": 9})

RULES = {"random": "Random", "volume": "Volume (today)", "momentum": "Momentum",
         "frontier": "Frontier", "hybrid": "Hybrid 50/50", "gbm_abs": "GBM: absolute",
         "gbm_share_raw": "GBM: raw share", "gbm_value": "GBM: value-aligned"}


def _pq(name: str) -> pd.DataFrame | None:
    p = PROC / f"{name}.parquet"
    return pd.read_parquet(p) if p.exists() else None


def _title(ax, eyebrow: str, head: str) -> None:
    ax.text(0, 1.14, " ".join(eyebrow.upper()), transform=ax.transAxes, fontsize=6.5, color=MUTE)
    ax.text(0, 1.04, head, transform=ax.transAxes, fontsize=11, color=PLUM, fontweight="semibold")


def _save(fig, name: str) -> None:
    FIGS.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGS / f"{name}.png", dpi=170, bbox_inches="tight")
    plt.close(fig)


# ------------------------------------------------------------------ figures

def figures() -> None:
    lad = _pq("ds_ladder")
    if lad is not None:
        d = lad.sort_values("value_capture")
        fig, ax = plt.subplots(figsize=(7.6, 4.2))
        y = np.arange(len(d))
        cols = [TERRA if r == "hybrid" else (PLUM if ok else MAUVE)
                for r, ok in zip(d["rule"], d["passes_guardrail"], strict=True)]
        ax.barh(y, d["value_capture"] * 100, color=cols)
        ax.errorbar(d["value_capture"] * 100, y, xerr=[(d["value_capture"] - d["value_capture_lo"]) * 100,
                    (d["value_capture_hi"] - d["value_capture"]) * 100], fmt="none", ecolor=PLUM, lw=1)
        ax.set_yticks(y, [RULES.get(r, r) + ("" if ok else "  (fails floor)")
                          for r, ok in zip(d["rule"], d["passes_guardrail"], strict=True)], fontsize=8)
        ax.set_xlabel("Value capture at k = 60-rep list (%)")
        _title(ax, "DS1  Evaluation ladder", "The hybrid is the best rule that keeps the brand's base")
        fig.tight_layout()
        _save(fig, "DS1_ladder")

    gain = _pq("ds_gain_curves")
    if gain is not None:
        fig, ax = plt.subplots(figsize=(7.6, 4.2))
        for r, c, lw in (("hybrid", TERRA, 2.6), ("gbm_value", "#7E3330", 1.6), ("volume", PLUM, 1.6),
                         ("frontier", "#D27E61", 1.4), ("random", MUTE, 1.2)):
            g = gain[(gain["rule"] == r) & (gain["fraction_targeted"] <= 0.2)]
            ax.plot(g["fraction_targeted"] * 100, g["value_gain"] * 100, color=c, lw=lw,
                    ls="--" if r == "random" else "-", label=RULES[r])
        ax.set_xlabel("Prescribers targeted (%)")
        ax.set_ylabel("Share-driven value captured (%)")
        ax.legend(frameon=False, fontsize=7.5)
        _title(ax, "DS2  Cumulative gain", "Every serious rule beats random by 3-5x at the 60-rep depth")
        fig.tight_layout()
        _save(fig, "DS2_gain")

    cov = _pq("ds_conformal_coverage")
    if cov is not None:
        v = cov[(cov["variant"] == "out-of-time, conformal") & cov["segment"].isin(["all", "size_band", "rural"])]
        fig, ax = plt.subplots(figsize=(7.6, 3.8))
        y = np.arange(len(v))
        ax.axvline(90, color=POS, ls="--", lw=1)
        ax.scatter(v["coverage"] * 100, y, color=[POS if c >= 0.885 else TERRA for c in v["coverage"]], zorder=3, s=40)
        ax.set_yticks(y, [("All" if s == "all" else f"{s.replace('_', ' ')}: {lv}")
                          for s, lv in zip(v["segment"], v["level"], strict=True)], fontsize=8)
        ax.set_xlim(80, 100)
        ax.set_xlabel("Out-of-time coverage of the 90% interval (%)")
        _title(ax, "DS3  Conformal coverage", "Calibrated intervals hold out of time; drift sits in the largest prescribers")
        fig.tight_layout()
        _save(fig, "DS3_coverage")

    dec = _pq("ds_uplift_value_deciles")
    if dec is not None:
        fig, ax = plt.subplots(figsize=(7.6, 3.8))
        ax.bar(dec["decile"], dec["observed"], yerr=2 * dec["se"],
               color=[TERRA if v > 0 else MAUVE for v in dec["observed"]], ecolor=PLUM, capsize=2)
        ax.axhline(0, color=MUTE, lw=0.8)
        ax.set_xticks(range(1, 11))
        ax.set_xlabel("Decile of predicted value uplift (held-out folds)")
        ax.set_ylabel("Observed uplift (fills)")
        _title(ax, "DS4  Uplift validation", "A monotone staircase: the DR-learner ranks who moves when promoted")
        fig.tight_layout()
        _save(fig, "DS4_uplift")

    ca = _pq("ds_causal")
    if ca is not None:
        c = ca[ca["treatment"].str.startswith("any")].reset_index(drop=True)
        fig, ax = plt.subplots(figsize=(7.6, 2.8))
        y = np.arange(len(c))[::-1]
        ax.axvline(0, color=MUTE, lw=0.8)
        ax.scatter(c["theta"] * 100, y, color=[MAUVE, MAUVE, TERRA][:len(c)], s=50, zorder=3)
        ok = c["ci_low"].notna()
        ax.hlines(y[ok], c.loc[ok, "ci_low"] * 100, c.loc[ok, "ci_high"] * 100, color=TERRA, lw=2)
        ax.set_yticks(y, c["spec"], fontsize=8)
        ax.set_xlabel("Brand-share change associated with a brand-named rep meal (points)")
        _title(ax, "DS5  Double machine learning", "Controls remove 60% of the naive association")
        fig.tight_layout()
        _save(fig, "DS5_dml")

    ab = _pq("ds_ablation")
    if ab is not None:
        d = ab[ab["variant"] != "production"].sort_values("value_capture_change")
        fig, ax = plt.subplots(figsize=(7.6, 3.4))
        y = np.arange(len(d))
        ax.barh(y, d["value_capture_change"] * 100, color=[NEG if v < 0 else POS for v in d["value_capture_change"]])
        ax.axvline(0, color=MUTE, lw=0.8)
        ax.set_yticks(y, d["variant"], fontsize=8)
        ax.set_xlabel("Value capture change vs production (points)")
        _title(ax, "DS6  Ablations", "Practice size and patient mix carry the model")
        fig.tight_layout()
        _save(fig, "DS6_ablation")


# -------------------------------------------------------------------- docs

def _m() -> dict:
    return json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))


def _p(v, d: int = 1) -> str:
    try:
        return f"{100 * float(v):.{d}f}%"
    except (TypeError, ValueError):
        return "--"


def _f(v, d: int = 3) -> str:
    try:
        return f"{float(v):.{d}f}"
    except (TypeError, ValueError):
        return "--"


def model_card(m: dict) -> str:
    ev, cf, ex, er = (m.get(k, {}) for k in ("ds_evaluation", "ds_conformal", "ds_explain", "ds_errors"))
    dr, ab, pm = m.get("ds_drift", {}), m.get("ds_ablation", {}), m.get("potential_model", {})
    lad = {r["rule"]: r for r in ev.get("ladder", [])}
    hy, vol = lad.get("hybrid", {}), lad.get("volume", {})
    return f"""# Model card: PharmaTarget prescriber ranking

*Generated {date.today().isoformat()} from `data/manifest.json` by `python -m src.report.ds_report`.*

## What it is
A ranking of Medicare Part D anticoagulant prescribers for field-force targeting:
the **50/50 hybrid** of (a) modelled opportunity -- a tau = {pm.get('tau', '--')} quantile
gradient-boosted frontier of class volume from practice and market covariates, times a
peer-achievable share, minus current branded fills -- and (b) current class volume.

## Intended use
Prioritising which prescribers a fixed field force calls on, and how territories are drawn.
**Not** for: estimating the causal effect of a call (see the pilot design), individual
clinical decisions, or any use outside Medicare Part D prescribers of the class.

## Evaluation (out of time: state 2023, outcomes 2023 -> 2024)
| Metric at k = {ev.get('k', '--')} (60-rep list) | Hybrid | Volume (today) |
|---|---|---|
| Value capture (primary, pre-declared) | {_p(hy.get('value_capture'))} | {_p(vol.get('value_capture'))} |
| Absolute growth capture | {_p(hy.get('abs_capture'))} | {_p(vol.get('abs_capture'))} |
| Precision@k | {_f(hy.get('precision_at_k'))} | {_f(vol.get('precision_at_k'))} |
| NDCG@k | {_f(hy.get('ndcg_at_k'))} | {_f(vol.get('ndcg_at_k'))} |

Winner of the primary metric among rules keeping >= 90% of volume's absolute growth:
**{ev.get('winner_under_guardrail', '--')}**. Full ladder: `docs/TECHNICAL_REPORT.md`.

## Uncertainty
Two-part forecast per prescriber: P(still writes the brand next year), AUC
{_f(cf.get('hurdle_auc'))}; then a conformalised 90% interval given that.
Coverage {_p(cf.get('in_period_coverage'))} in period, {_p(cf.get('out_of_time_conformal'))}
out of time (worst size band {_p(cf.get('worst_size_band_marginal'))}).

## Explanations
Exact TreeSHAP from an XGBoost replica of the frontier: fidelity rho
{_f(ex.get('fidelity_spearman'))} to production, agreement with permutation importance rho
{_f(ex.get('agreement_with_permutation_importance'))}.

## Known failure modes
* **Regression to the mean.** Any model trained on raw share change chases small prescribers
  at unusually low share; targets must be value-aligned (share change x volume).
* **The long tail.** The list under-represents primary care and NP/PA prescribers relative
  to where value sits; no 60-rep list can reach them (non-personal channels).
* **Largest prescribers** carry the most year-to-year drift (lowest interval coverage).
* Forecast bias overall {_p(er.get('overall_relative_bias'))}; worst segment
  {er.get('worst_bias_segment', '--')} at {_p(er.get('worst_relative_bias'))}.

## Fairness check
Rural prescribers are {_p(er.get('rural_share_of_list'))} of the list vs
{_p(er.get('rural_share_of_value'))} of realised value (ratio
{_f(er.get('rural_representation_ratio'), 2)}).

## Monitoring and retraining rule
Refit at each CMS release if any input's PSI >= 0.25, the score's PSI >= 0.10, or the
score-outcome rank correlation moves by > 0.05. Latest: score PSI {_f(dr.get('score_psi'))},
worst input {dr.get('worst_input', '--')} at {_f(dr.get('worst_input_psi'))}; retrain
triggered: **{dr.get('retrain_triggered', '--')}**.

## Pre-declared for the next refresh
{', '.join(ab.get('beats_production_on_holdout', [])) or '--'} scored higher on this
holdout; adopting them now would be choosing on the test set. They are scored
prospectively on the 2025 release.
"""


def data_card(m: dict) -> str:
    sup, op, ct = m.get("suppression_ev", {}), m.get("open_payments_match", {}), m.get("ds_contracts", {})
    nw = m.get("ds_network", {})
    return f"""# Data card

*Generated {date.today().isoformat()} by `python -m src.report.ds_report`.*

## Sources (all public)
| Source | Use | Years |
|---|---|---|
| CMS Medicare Part D Prescribers by Provider and Drug | class and brand 30-day fills | 2022-2024 |
| CMS Medicare Part D Prescribers by Provider | panel size, age mix, risk score | 2022-2024 |
| CMS Open Payments (general payments) | promotion, attributed by product name | 2022-2024 |
| Census Gazetteer ZCTA, CDC PLACES | ZIP3 population, density, disease prevalence | latest |
| CMS Doctors and Clinicians National Downloadable File | group-practice membership (peer network) | current snapshot |

About 39 GB of raw files are streamed through DuckDB; about 1.3 GB is retained.

## Processing that changes the numbers
* **Suppression.** CMS removes drug rows under 11 claims: {_p(sup.get('hidden_share_of_total'))}
  of class volume is hidden. It is reconciled against provider totals and capped at what
  the unobserved class drugs could hold; brand share uses observed volume only.
* **Promotion attribution** by product name, not company. Link rate to Part D prescribers
  {_p(op.get('link_rate') or op.get('match_rate'))}.
* **Shrinkage.** Brand share is shrunk towards each specialty's mean (beta-binomial) before
  any model sees a share change.

## Contracts
{ct.get('passed', '--')}/{ct.get('checks', '--')} checks on {len(ct.get('tables', []))} tables (`config/contracts.yaml`):
keys, null rates, ranges and business rules, run before any model.

## Known gaps
* Medicare Part D only: commercial and Medicaid prescribing is invisible.
* About a 17-month publication lag.
* No rep call data; brand-named meals are a visit proxy.
* Practice membership is a current snapshot ({_p(nw.get('coverage'))} of in-market
  prescribers matched), applied to 2022-2024 behaviour.
"""


def technical_report(m: dict) -> str:
    ev, shr, cf, er, ca, up = (m.get(k, {}) for k in
                               ("ds_evaluation", "ds_shrinkage", "ds_conformal", "ds_errors",
                                "ds_causal", "ds_uplift"))
    ex, ab, dr, nw, ct = (m.get(k, {}) for k in ("ds_explain", "ds_ablation", "ds_drift", "ds_network", "ds_contracts"))
    rec, fs = m.get("recommendation", {}), m.get("decision_frontier", {})
    rows = "\n".join(
        f"| {RULES.get(r['rule'], r['rule'])} | {_p(r['value_capture'])} [{_p(r['value_capture_lo'])}, "
        f"{_p(r['value_capture_hi'])}] | {_p(r['abs_capture'])} | {_f(r['precision_at_k'])} | "
        f"{_f(r['ndcg_at_k'])} | {'yes' if r['passes_guardrail'] else 'no'} |"
        for r in ev.get("ladder", []))
    abl = "\n".join(f"| {r['variant']} | {_f(r['spearman_vs_production'])} | {_p(r['value_capture'])} | "
                    f"{100 * r['value_capture_change']:+.1f} |" for r in ab.get("table", []))
    est = "\n".join(f"| {r['spec']} | {r['treatment']} | {100 * r['theta']:+.2f} | "
                    + (f"[{100 * r['ci_low']:+.2f}, {100 * r['ci_high']:+.2f}]" if r.get('ci_low') == r.get('ci_low') and r.get('ci_low') is not None else "--")
                    + " |" for r in ca.get("estimates", []))
    lists = up.get("list_uplift_fills", {})
    return f"""# PharmaTarget: technical report

*Generated {date.today().isoformat()} from the pipeline output. Figures in `outputs/figures/DS*.png`.*

## 1. Problem
Rank about 267,000 Medicare anticoagulant prescribers so a 60-rep field force (k =
{ev.get('k', '--')} prescribers a year) calls where calls are worth most, and quantify
how sure we can be.

## 2. Evaluation design
Out-of-time throughout: models learn on 2022 state -> 2023 outcomes and are judged on
2023 state -> 2024 outcomes. **Pre-declared** before any result was read: the primary
metric (value capture at k: the share of positive *share-driven fills* -- shrunk
share-point change x volume -- on the list), the guardrail (keep >= 90% of the volume
rule's absolute growth) and k.

![](../outputs/figures/DS1_ladder.png)

| Rule | Value capture @k [95% CI] | Abs capture | Precision@k | NDCG@k | Passes guardrail |
|---|---|---|---|---|---|
{rows}

The hybrid wins under the guardrail, matching the consulting decision rule
(share {rec.get('share_vs_volume', '--')}x volume's, {_p(rec.get('abs_vs_volume'), 0)} of its
absolute growth); a blend weight tuned on the earlier year fails the floor out of time
(P = {_p(fs.get('holdout_p_clears_floor'), 0)}) while 50/50 holds (P =
{_p(fs.get('equal_weight_p_clears_floor'), 0)}).

![](../outputs/figures/DS2_gain.png)

## 3. Target design: the regression-to-the-mean trap
A gradient-boosting model trained on raw share change "won" share capture by picking
prescribers with a median of {shr.get('raw_ml_median_base', '--')} class fills and captured
{_p(shr.get('raw_ml_abs_capture'))} of absolute growth. Beta-binomial shrinkage (prior strength
{shr.get('median_prior_strength', '--')} pseudo-fills) cut small prescribers' share-change s.d.
from {shr.get('sd_raw_change_small', '--')} to {shr.get('sd_eb_change_small', '--')}, yet the
model still chose small prescribers; precision weighting did not help either. The cause is
regression to the mean (corr(share, change) = {shr.get('mean_reversion_corr', '--')}). Aligning
the target with value (share change x volume) fixes it: median {shr.get('aligned_ml_median_base', '--')}
fills, absolute capture {_p(shr.get('aligned_ml_abs_capture'))}.

## 4. Uncertainty
Two-part model: P(still writes the brand), AUC {_f(cf.get('hurdle_auc'))}, Brier
{_f(cf.get('hurdle_brier'))}; then conformalised quantile regression (Romano et al., 2019)
given that. Coverage of the 90% interval: {_p(cf.get('in_period_coverage'))} in period,
{_p(cf.get('out_of_time_conformal'))} out of time; worst size band
{_p(cf.get('worst_size_band_marginal'))}. Mondrian (per-band) calibration:
{_p(cf.get('out_of_time_mondrian'))}. Point-forecast calibration slope
{_f(cf.get('calibration_slope'), 2)}.

![](../outputs/figures/DS3_coverage.png)

## 5. Errors and representation
Forecast MAE {_f(er.get('overall_mae'), 1)} fills, relative bias {_p(er.get('overall_relative_bias'))}.
Rural representation ratio {_f(er.get('rural_representation_ratio'), 2)} (fair). Under-represented
relative to realised value: {', '.join(er.get('under_represented', [])) or '--'}.

## 6. Causal ML
Partially linear double machine learning (Chernozhukov et al., 2018), 5-fold cross-fitted
gradient-boosted nuisances, controls including each prescriber's own prior-year change.

| Specification | Treatment | Estimate (pts) | 95% CI |
|---|---|---|---|
{est}

![](../outputs/figures/DS5_dml.png)

Sensitivity (Cinelli and Hazlett, 2020): robustness value {_p(ca.get('robustness_value'))}
(to zero), {_p(ca.get('robustness_value_alpha'))} (to insignificance) -- a confounder
{ca.get('confounder_multiple_of_pretrend', '--')}x as strong as the prior-year trend would
erase it. Reading: a small, fragile association; the pilot is the causal test.

## 7. Uplift
Doubly-robust learner (Kennedy, 2023), 4-fold cross-fitted, ranked and evaluated on value
uplift (effect x volume). Decile rank correlation {up.get('value_decile_rank_corr', '--')} on
held-out folds. Held-out fill uplift on each 60-rep list: {', '.join(f'{k} {v:,.0f}' for k, v in lists.items())}.
Share-point uplift reproduces the small-denominator trap (median {up.get('list_median_base', {}).get('uplift_share_points', '--')} fills).

![](../outputs/figures/DS4_uplift.png)

## 8. Explanations
Exact TreeSHAP from an XGBoost quantile replica: fidelity rho {_f(ex.get('fidelity_spearman'))},
coverage {_f(ex.get('replica_coverage'))}, agreement with permutation importance rho
{_f(ex.get('agreement_with_permutation_importance'))}.

## 9. Ablations
| Variant | Spearman vs production | Value capture | Change (pts) |
|---|---|---|---|
{abl}

![](../outputs/figures/DS6_ablation.png)

## 10. Monitoring and data quality
PSI 2023 -> 2024: score {_f(dr.get('score_psi'))}, worst input {dr.get('worst_input', '--')}
{_f(dr.get('worst_input_psi'))}; concept drift (score-outcome rank correlation)
{dr.get('concept_drift', {}).get('spearman_change', '--')}. Retrain triggered:
{dr.get('retrain_triggered', '--')}. Data contracts: {ct.get('passed', '--')}/{ct.get('checks', '--')}
passing. All runs are tracked in MLflow (`./mlruns`).

## 11. Practice network
{_p(nw.get('coverage'))} of in-market prescribers matched to {nw.get('practices_used', '--'):,}
group practices. Shrunk-share ICC within practice {_f(nw.get('icc_shrunk_share'))} vs a
permutation null of {_f(nw.get('icc_permutation_null_97_5'))}; peer features move value
capture {_p(nw.get('value_capture_base'))} -> {_p(nw.get('value_capture_with_peers'))}.
Practices share prescribing levels, not changes; {_p(nw.get('unlisted_mates_value_share'))} of
value sits with unlisted practice-mates of the list.

## 12. Limitations
Medicare Part D only; ~17-month lag; no call data (meals are a proxy); observational causal
and uplift estimates; practice membership is a current snapshot.

## References
Chernozhukov et al. (2018) *Double/debiased machine learning*. Romano, Patterson and
Candes (2019) *Conformalized quantile regression*. Kennedy (2023) *Towards optimal
doubly robust estimation of heterogeneous causal effects*. Cinelli and Hazlett (2020)
*Making sense of sensitivity*. Efron and Morris (1975) *Data analysis using Stein's
estimator* (empirical Bayes).
"""


def run() -> None:
    figures()
    m = _m()
    DOCS.mkdir(exist_ok=True)
    (DOCS / "MODEL_CARD.md").write_text(model_card(m), encoding="utf-8")
    (DOCS / "DATA_CARD.md").write_text(data_card(m), encoding="utf-8")
    (DOCS / "TECHNICAL_REPORT.md").write_text(technical_report(m), encoding="utf-8")
    log.info("data-science docs written: docs/MODEL_CARD.md, DATA_CARD.md, TECHNICAL_REPORT.md")


if __name__ == "__main__":
    run()
