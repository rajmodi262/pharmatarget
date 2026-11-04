# Model card: PharmaTarget prescriber ranking

*Generated 2026-10-31 from `data/manifest.json` by `python -m src.report.ds_report`.*

## What it is
A ranking of Medicare Part D anticoagulant prescribers for field-force targeting:
the **50/50 hybrid** of (a) modelled opportunity -- a tau = 0.8 quantile
gradient-boosted frontier of class volume from practice and market covariates, times a
peer-achievable share, minus current branded fills -- and (b) current class volume.

## Intended use
Prioritising which prescribers a fixed field force calls on, and how territories are drawn.
**Not** for: estimating the causal effect of a call (see the pilot design), individual
clinical decisions, or any use outside Medicare Part D prescribers of the class.

## Evaluation (out of time: state 2023, outcomes 2023 -> 2024)
| Metric at k = 8878 (60-rep list) | Hybrid | Volume (today) |
|---|---|---|
| Value capture (primary, pre-declared) | 14.9% | 14.7% |
| Absolute growth capture | 15.2% | 16.7% |
| Precision@k | 0.516 | 0.507 |
| NDCG@k | 0.514 | 0.508 |

Winner of the primary metric among rules keeping >= 90% of volume's absolute growth:
**hybrid**. Full ladder: `docs/TECHNICAL_REPORT.md`.

## Uncertainty
Two-part forecast per prescriber: P(still writes the brand next year), AUC
0.870; then a conformalised 90% interval given that.
Coverage 90.0% in period, 89.3%
out of time (worst size band 87.1%).

## Explanations
Exact TreeSHAP from an XGBoost replica of the frontier: fidelity rho
0.973 to production, agreement with permutation importance rho
0.937.

## Known failure modes
* **Regression to the mean.** Any model trained on raw share change chases small prescribers
  at unusually low share; targets must be value-aligned (share change x volume).
* **The long tail.** The list under-represents primary care and NP/PA prescribers relative
  to where value sits; no 60-rep list can reach them (non-personal channels).
* **Largest prescribers** carry the most year-to-year drift (lowest interval coverage).
* Forecast bias overall -3.1%; worst segment
  specialty_group=Other at -5.1%.

## Fairness check
Rural prescribers are 24.0% of the list vs
25.7% of realised value (ratio
0.93).

## Monitoring and retraining rule
Refit at each CMS release if any input's PSI >= 0.25, the score's PSI >= 0.10, or the
score-outcome rank correlation moves by > 0.05. Latest: score PSI 0.000,
worst input brand_share at 0.027; retrain
triggered: **False**.

## Pre-declared for the next refresh
median, not frontier (tau 0.50), no peer benchmark (national share) scored higher on this
holdout; adopting them now would be choosing on the test set. They are scored
prospectively on the 2025 release.
