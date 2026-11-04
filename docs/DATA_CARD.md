# Data card

*Generated 2026-10-31 by `python -m src.report.ds_report`.*

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
* **Suppression.** CMS removes drug rows under 11 claims: 13.7%
  of class volume is hidden. It is reconciled against provider totals and capped at what
  the unobserved class drugs could hold; brand share uses observed volume only.
* **Promotion attribution** by product name, not company. Link rate to Part D prescribers
  89.4%.
* **Shrinkage.** Brand share is shrunk towards each specialty's mean (beta-binomial) before
  any model sees a share change.

## Contracts
58/58 checks on 5 tables (`config/contracts.yaml`):
keys, null rates, ranges and business rules, run before any model.

## Known gaps
* Medicare Part D only: commercial and Medicaid prescribing is invisible.
* About a 17-month publication lag.
* No rep call data; brand-named meals are a visit proxy.
* Practice membership is a current snapshot (71.1% of in-market
  prescribers matched), applied to 2022-2024 behaviour.
