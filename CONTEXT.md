# PharmaTarget — Full Working Context

> **Purpose.** Everything a fresh session needs to continue without re-deriving
> anything. Written 2026-08-09. Read this first, then `README.md` for the
> outward-facing story and `PharmaTarget_Execution_Playbook.md` for the plan.

---

# 1. WHAT THIS PROJECT IS

A portfolio project for a **ZS Associates Decision Analytics Associate** role.
Fictional client "Northwind Pharma" markets a branded DOAC (modelled on
apixaban/Eliquis). Real US CMS data. Four questions:

1. **Who** to call on — opportunity model, not volume ranking
2. **How often** — call-plan matrix, capacity-constrained
3. **How many reps** — marginal-ROI sizing
4. **What geography** — capacitated clustering with contiguity

The intellectual thesis: *the industry ranks prescribers by volume; that is
structurally wrong, because a prescriber already at 90% brand share has no
headroom. Rank on modelled opportunity instead.*

**Location:** `D:\ZS 2\pharmatarget\`
Planning docs live one level up in `D:\ZS 2\`.

---

# 2. ENVIRONMENT — READ BEFORE RUNNING ANYTHING

| Thing | Reality |
|---|---|
| Python | 3.10.0 at `C:\Program Files\Python310\python.exe`, on PATH as `python` |
| Node | **Portable only**: `.tools\node-v22.20.0-win-x64\` (v22.20.0, npm 10.9.3) |
| System Node | **BROKEN.** PATH has `D:\RajFiles\nodejs` but the folder does not exist. `winget install` fails with 1632 (temp unwritable) because it tries to *upgrade* an orphaned registry entry. Do not fight it — use the portable copy. |
| Docker | 29.4.1, installed |
| gh CLI | installed, **not authenticated** |
| fly CLI | not installed |
| Git repo | **NOT initialised** in `pharmatarget/` |

To use Node in a shell:
```powershell
$env:Path = "D:\ZS 2\pharmatarget\.tools\node-v22.20.0-win-x64;$env:Path"
```

Missing Python packages: `statsmodels` is NOT installed (never needed — OLS is
hand-rolled with `numpy.linalg.lstsq`). `shap` is installed but **no longer
used** (replaced by permutation importance).

---

# 3. THE DATA

## 3.1 What is in `dataset/` (29 GB, user-downloaded, do not re-download)

```
MUP_DPR_RY24_P04_V10_DY22_NPIBN.csv    3.48 GB   Part D drug, data year 2022
MUP_DPR_RY25_P04_V10_DY23_NPIBN.csv    3.61 GB   Part D drug, 2023
MUP_DPR_RY26_P04_V10_DY24_NPIBN.csv    3.78 GB   Part D drug, 2024
mup_dpr_ry24_p04_v20_dy22_npi.csv      0.69 GB   Part D provider, 2022
mup_dpr_ry25_p04_v20_dy23_npi.csv      0.71 GB   Part D provider, 2023
mup_dpr_ry26_p04_v20_dy24_npi.csv      0.73 GB   Part D provider, 2024
OP_DTL_GNRL_PGYR2022_..._(1).csv       6.93 GB   Open Payments 2022
OP_DTL_GNRL_PGYR2023_....csv           7.67 GB   Open Payments 2023
OP_DTL_GNRL_PGYR2024_....csv           8.35 GB   Open Payments 2024
2024_Gaz_zcta_national.txt             6.6 MB    Census Gazetteer ZCTA
2024_Gaz_zcta_national.zip             1 KB      (either works)
PLACES__Local_Data_for_Better_Health__ZCTA_Data__2025_release.csv  229 MB
```

**CRITICAL FILENAME FACT:** Part D filenames encode BOTH a release year and a
data year. `RY26 ... DY24` = **released** 2026, **data year 2024**. Parsing the
release year would shift every year in the analysis by two. `src/ingest/download.py`
parses `_DY(\d{2})_`.

## 3.2 Years used

**2022 / 2023 / 2024.** Set in `config/params.yaml`:
- `train_start: 2022`, `train_end: 2023`, `holdout: 2024`
- 2022→2023 is the pre-trend window (tests parallel trends)
- 2023→2024 is the treatment / hold-out window

Data year 2024 was published May 2026 → **~17-month lag**, not the ~2 years
usually quoted. This is stated in the README limitations.

## 3.3 Therapeutic class

Matched on **`Gnrc_Name`, never `Brnd_Name`** (brand strings drift across
releases; the real data ships `Warfarin Sodium` and `Dabigatran Etexilate` as
*brand* names, so brand matching would silently drop them).

Real 2023 class composition (verified):

| Drug | 30-day fills | Prescribers |
|---|---|---|
| Eliquis (apixaban) — **focus brand** | 32.17M | 245,552 |
| Xarelto (rivaroxaban) | 10.29M | 132,410 |
| Warfarin Sodium + Jantoven | 9.57M | ~113,000 |
| Pradaxa + generic dabigatran | 1.14M | 12,586 |
| Savaysa (edoxaban) | 0.004M | 178 |

Eliquis ≈ **61% of a 53M-fill class** — matches published DOAC share.
**No apixaban generics in Part D through 2024** (verified).

---

# 4. THE PIPELINE — WHAT EACH MODULE DOES

Run everything with `.\run_all.ps1` (resumable, dependency-aware). Individual
modules below.

## 4.1 `src/ingest/download.py`

Streams and filters. **Does not download 40 GB.** For each drug file it:
1. keeps rows whose `Gnrc_Name` is in the class
2. **accumulates a per-NPI running total of `Tot_Clms` across ALL drugs**

Step 2 is the whole trick — the suppression reconciliation needs Σ(all drug
rows) per prescriber. Writes `npi_alldrug_totals_YYYY.csv` alongside
`partd_drug_YYYY.csv`.

Accepts `--local-dir dataset` to read the user's files instead of the network.
`--discover-manufacturers` probes Open Payments for real manufacturer strings.

Result: 80.0M drug rows in → **1.52M class rows** out, ~200 MB retained.

## 4.2 `src/ingest/geo_build.py`

Census Gazetteer × CDC PLACES → `data/raw/zip3_units.csv`.
- 33,791 ZCTAs with coordinates
- 88.7% matched to PLACES
- → **896 ZIP3 units**, 313.9M population, all state-attached
- Handles **both** PLACES formats (long with `MeasureId`, and GIS-friendly wide)
- Population-weighted centroids and prevalence

## 4.3 `src/etl/build_marts.py` + `src/sql/*.sql`

DuckDB. Five SQL files run in order. Produces `mart_hcp_metrics` (**4,129,857
rows** = 1.38M NPIs × 3 years).

## 4.4 `src/models/opportunity.py` — THE CENTREPIECE

- `HistGradientBoostingRegressor(loss="quantile", quantile=0.80)` on log class volume
- Fit on 2023 in-market prescribers (**267,171**)
- `opportunity = potential_class × achievable_share − brand_fills`
- **Deciles computed within the in-market universe only** (see §6.5)
- Leakage guard **raises**, never warns
- Driver attribution via **permutation importance on pinball loss** (not SHAP)

## 4.5 `src/models/callplan.py`

Matrix (opportunity decile × brand share → calls/month) **then a capacity cut**:
rank by opportunity, fill 60 reps' diaries from the top, everyone past that is
a no-call.

## 4.6 `src/models/backtest.py`

Fit 2022–23, freeze, score against 2024. Gate G3 now has **three** conditions
(see §6.7).

## 4.7 `src/models/challenger.py` — champion vs challenger

Trains ML models to predict growth **directly** and races them against the
frontier score. This module produced the project's most important finding
(§5.6).

## 4.8 `src/models/sizing.py`

Marginal-ROI curve + tornado. Uses `_Ranked` (sorts once, reused ~1,000 times).

## 4.9 `src/models/territory.py`

Capacitated k-means + **contiguity repair** + **balance pass** + boundary polish.

## 4.10 `src/models/segmentation.py`, `src/models/response.py`

KMeans with bootstrap-ARI stability selection; PSM + DiD + Hill saturation.

## 4.11 `src/report/make_assets.py`

Generates 6 PNGs + the 13-slide PDF **from parquet and manifest**. Nothing typed.

## 4.12 `src/utils/summary.py`

`python -m src.utils.summary` prints all findings from `data/manifest.json`.
Safe to run any time, including mid-pipeline.

---

# 5. ALL REAL-DATA FINDINGS (verified against `data/manifest.json`)

## 5.1 Scale
- 1,380,665 prescribers (2023) in Part D; **267,171 write the class**
- 4,129,857 prescriber-years in the mart
- 80.0M drug rows streamed; 1.52M class rows kept
- Open Payments: 4.77M rows kept (1.46M + 1.63M + 1.68M), **90.3% linked** to the prescriber universe

## 5.2 Suppression — a headline finding
- **13.7% of ALL claim volume is hidden**; 99.7% of prescriber-years affected
- Gradient (independently verified with a standalone DuckDB query):

| Prescriber size | Volume hidden |
|---|---|
| <100 claims | **68.7%** |
| 100–500 | 43.0% |
| 500–2,000 | 21.6% |
| 2,000+ | 8.6% |

## 5.3 Model quality
- Frontier in-sample coverage **0.800** vs τ=0.80
- SFA cross-check Spearman **0.849**
- Top driver `log_non_class_clms` at **32.4%** — market covariates carry real weight
- Max feature↔target correlation 0.534 (leak threshold 0.97)

## 5.4 The disagreement (Exhibit E1)
- **59.4%** of in-market prescribers move ≥2 deciles
- **23,615** low-volume/high-opportunity (skipped by the volume rule)
- **26,580** high-volume/low-opportunity (over-served by it)

## 5.5 Back-test (Gate G3 — PASSES)
- Spearman(decile, realised 2024 growth) = **0.927**
- Share-growth capture **1.392×** the volume rule
- Absolute-growth capture **0.726×** — volume wins this, mechanically
- **1.50× vs volume-matched controls** ← the headline
- Selected-list median base **312 fills = 61%** of the volume rule's (anti-gaming check)
- Biggest misses over-represent **Advanced Practice (+15.0 pp)**

## 5.6 Champion vs challenger — THE MOST IMPORTANT FINDING

At the real 60-rep budget (N = 8,399):

| Rule | Share capture | Absolute capture | Median base fills |
|---|---|---|---|
| ml_share | **11.7%** | 1.9% | **35** |
| opportunity (this project) | 2.4% | 10.3% | 840 |
| ml_abs | 2.1% | 14.9% | 1,052 |
| volume | 1.7% | **16.0%** | 1,470 |

**The ML challenger beat the frontier model 4.9× on the stated criterion — by
selecting prescribers writing 35 class fills a year, delivering 1.9% of actual
volume.** Share growth on a tiny denominator is arithmetic, not persuadability.

Consequences, both implemented:
1. Gate G3 no longer rests on share capture alone (§6.7)
2. The README reports all four rules and the diagnosis rather than a winner

**Also honest and unresolved:** volume ranking wins absolute capture (16.0%).
Cannot be adjudicated without call data.

## 5.7 Capacity and sizing
- 60 reps serve **8,389 of 267,171** in-market prescribers = **3.1%**, at 100% capacity
- Unconstrained demand: 106,869 prescribers → **579 reps**
- Reach @ 60 reps: opportunity **6.9%** | volume **3.2%** | geography **0.6%**
- Break-even **586 reps** (sensitivity 471–700) ← **NOT CREDIBLE, see §8.1**
- Tornado: most sensitive to `calls_per_rep_per_day`; least to `contribution_margin` (zero swing)

## 5.8 Territory
- Imbalance **157.17× → 2.51×**
- Contiguity **20% → 100%**
- Travel **−75%** (258 mi → 65 mi)
- CV 0.42 → 0.166 at 60 reps; **0.102 at 80 reps** (meets the ±10% target)

## 5.9 Segmentation
k=8, silhouette **0.807**, bootstrap ARI **0.998**.
⚠️ Silhouette this high is suspicious — likely one degenerate cluster. **Unchecked.**

## 5.10 Promotional response
- Naive OLS elasticity **0.061**
- Matched DiD **0.00209** → **selection gap of ~29×**
- **Parallel-trends test FAILED** → reported as association only, causal language removed
- This was the pre-committed response in `CHARTER.md`

---

# 6. EVERY BUG FOUND AND FIXED (the valuable part)

## 6.1 Open Payments filter silently ignored
`?query=<json>` returned HTTP 200 with `count=14,734,121` — the **entire
dataset**, unfiltered, showing Neuronetics and Mission Pharmacal. Only
**bracketed params** (`conditions[0][property]=…`) actually filter.
**Fix:** `_op_query()` + an assertion that returned rows match the requested
manufacturer, so a syntax regression breaks the build instead of poisoning data.
Also: `limit` is capped at **500**.

## 6.2 Every guessed manufacturer name was wrong

| Guessed | Actual |
|---|---|
| `Bristol-Myers Squibb Company` | `Bristol Myers Squibb Company` (no hyphen) |
| `Pfizer Inc.` | `PFIZER INC.` |
| `Janssen Pharmaceuticals, Inc.` | `Janssen Pharmaceuticals, Inc` (no period) |
| `Daiichi Sankyo, Inc.` | `Daiichi Sankyo Inc.` |

Worse: `Bristol Myers Squibb Company` has only **124** records. The apixaban
alliance reports through **`E.R. Squibb & Sons, L.L.C.` — 236,558 records.**
Names also **drift by year** (Bayer 1→2 names, Janssen 2→1→3).
**Fix:** `--discover-manufacturers`, verified config, zero-match logging.

## 6.3 Synthetic and real data about to be joined
Both ingests write identical filenames into `data/raw/`. A real 2022 drug stream
was about to be reconciled against **synthetic** 2022 provider totals.
**Fix:** `.data_mode` marker + `claim_raw_dir()`; either ingest refuses to write
into the other's directory.

## 6.4 `Bene_Age_GE_65_Cnt` does not exist
The synthetic generator **invented** this column. Pipeline ran green on
synthetic data, failed on the first real extract. CMS publishes age *bands*:
`Bene_Age_LT_65_Cnt`, `Bene_Age_65_74_Cnt`, `Bene_Age_75_84_Cnt`,
`Bene_Age_GT_84_Cnt`, plus `GE65_Tot_Benes`.
**Fix:** SQL 01 assembles the 65+ count from bands with per-band COALESCE;
`synth.py` now emits the real names.
**Lesson:** a generator that invents a schema validates your pipeline against a
world that isn't there.

## 6.5 Suppression reported 98% hidden (twice, two different causes)
1. *Synthetic:* generator emitted only class drugs, so provider totals had no
   matching drug rows. Fixed by emitting `OTHER_DRUGS`.
2. *Real:* SQL 03 summed `stg_scripts`, which after the streaming change holds
   **class rows only**. Fixed by reading `npi_alldrug_totals_*.csv`.
Correct value **13.7%**, independently verified.

## 6.6 Deciling across the whole Part D file
Deciles computed over 1.38M prescribers when only 267k write the class made
"decile 9" mean "writes the class at all". **Fix:** decile within the in-market
universe; out-of-market get decile 0 and are never called.

## 6.7 Gate G3's criterion was gameable
Originally: share capture alone. I **changed the criterion after seeing it fail**
on synthetic data (flagged at the time as methodologically uncomfortable).
The challenger then proved the criterion itself was gameable.
**Fix:** three conditions — orders correctly (Spearman ≥ 0.60) AND beats volume
on share (≥1.05×) AND **median base volume ≥25% of the volume rule's**.
On real data it passes all three with room (0.927 / 1.39× / 61%).

## 6.8 Call plan implied 4,575 reps against a force of 60
No capacity constraint. **Fix:** rank and fill 60 reps' capacity from the top.

## 6.9 Sizing read capacity-capped calls
`hcp_call_plan.parquet` is already truncated at 60 reps, so the ROI curve
flatlined above 60 and "break-even at 69" was an artefact.
**Fix:** `_Ranked` prefers `desired_calls` (unconstrained).

## 6.10 Sizing was pathologically slow
`evaluate_force` re-sorted 1.38M rows on each of ~1,000 tornado calls.
**Fix:** `_Ranked` sorts once. **>15 min → 79 s.**

## 6.11 Territory CV stuck at 0.28
Capacity is only an *upper* bound; nothing pulled territories up toward the mean.
**Fix:** `_rebalance()` with a squared-deviation objective. 0.36 → 0.166.
⚠️ The `loads[src] <= target` guard is **load-bearing** — removing it was
measured and made CV **worse** (0.165 → 0.203). Comment in code explains why.

## 6.12 Rebalance churned 40 passes at flat CV
**Fix:** stall detection (break after 3 non-improving passes). 90 s → 30 s.

## 6.13 Saturation curve fitted half-saturation at −$104
Unbounded `curve_fit` on a negative response. **Fix:** bounds + an
"unidentifiable" path that reports rather than inventing a curve.

## 6.14 Frontend: React Query stuck in `isPending` forever
A 503 rendered an infinite skeleton — the worst failure mode, because it looks
like the app is working. **Fix:** branch on `isError || error` **before**
`isPending`, and never retry a 503.

## 6.15 Frontend: SPA fallback missing
`StaticFiles` 404s `/app/targets` on hard refresh. **Fix:** catch-all route in
`api/main.py` with path-traversal guarding.

## 6.16 Frontend: query-key collision
`AppShell` used `qk.meta` for `/api/health` — two response shapes, one cache key.

## 6.17 `/api/hcps/sample` shadowed by `/api/hcps/{npi}`
FastAPI matches in declaration order → "sample" parsed as an NPI.
**Fix:** renamed to `/api/hcp-sample`.

## 6.18 `USING SAMPLE n ROWS` returned 4,736 of 24,000
DuckDB samples **per row-group**. **Fix:** `ORDER BY random() LIMIT ?`.

## 6.19 Hero exhibit didn't show the finding
Coloured by territory ID on a 20-colour map with 60 territories → hues cycled,
and before/after looked identical (alphabetical-by-state is *already*
geographically clustered). **Fix:** colour by **territory workload on a shared
scale** — before is chaotic, after is uniform.

## 6.20 Others
- `letterspacing` is not a matplotlib property
- PowerShell here-string + embedded Python = broken escaping → extracted to `src/utils/summary.py`
- `growth_share` NaN when a prescriber writes no class volume next year

---

# 7. FILE MAP

```
D:\ZS 2\
├── PharmaTarget_v2_Plan.md                 upgraded spec
├── PharmaTarget_TASKS.md                   ~90 tasks, IDs, acceptance criteria
├── PharmaTarget_Execution_Playbook.md      gates, storyline, risk register
├── PharmaTarget_Frontend_Design_Brief.md   ~7k-word design spec (18 parts)
└── pharmatarget\
    ├── CONTEXT.md                          ← this file
    ├── CHARTER.md                          pre-committed protocol
    ├── README.md                           answer-first, real numbers, exhibits
    ├── run_all.ps1                         resumable runner
    ├── Makefile  Dockerfile  pyproject.toml  requirements.txt
    ├── .github/workflows/ci.yml
    ├── config\  params.yaml  economics.yaml  manufacturers.yaml
    ├── dataset\                            29 GB user downloads (gitignored)
    ├── data\    raw\ interim\ processed\ manifest.json run.log
    ├── outputs\ figures\*.png  PharmaTarget_Recommendations.pdf
    ├── src\
    │   ├── config.py  pipeline.py
    │   ├── ingest\    download.py  geo_build.py  synth.py
    │   ├── etl\       build_marts.py
    │   ├── sql\       01…05
    │   ├── models\    opportunity callplan backtest challenger
    │   │              sizing territory segmentation response
    │   ├── report\    make_assets.py
    │   └── utils\     io.py  geo.py  summary.py
    ├── api\     main.py  db.py  schemas.py
    ├── web\     React 18 + TS + Vite + Tailwind
    │   └── src\ design/tokens.css  lib/  components/  app/  story/
    └── tests\   test_opportunity  test_territory  test_pipeline  (41 tests)
```

---

# 8. WHAT IS NOT DONE / KNOWN WEAKNESSES

## 8.1 ⚠️ The 586-rep recommendation is not credible — HIGHEST PRIORITY
Telling a CFO to grow 60 reps to 586 (~$130M) is not a business
recommendation; it reveals the response-curve assumption doing all the work.
**Fix:** cap the headline at a plausible band (60→90) and report the rest as
*unmet demand*, not a headcount ask. ~1 hour. This is the single biggest
credibility risk in the whole project.

## 8.2 Not deployed
No live URL. Docker + gh present; **gh not authenticated**, no git repo.
Blocker: `data/processed` is **798 MB** (`hcp_scored` 352 MB, `mart_hcp_metrics`
210 MB). Needs a slimming script → top ~50k prescribers + all aggregates,
target <50 MB. Then `render.yaml` + `gh repo create` + connect on Render.

## 8.3 Story-mode scroll unverified
`/` renders, canvas draws, real numbers bind. But acts did **not** advance under
programmatic scroll in the embedded preview (`window.scrollY` stayed 0 after
`scrollTo`). Could be a pane limitation or a real bug. **Check in real Chrome.**
If broken, look at `useScrollStage` in `web/src/story/Story.tsx` — try
`document.documentElement.scrollTop` or per-act `IntersectionObserver`.

## 8.4 Segmentation not sanity-checked
Silhouette 0.807 at k=8 is abnormally high. Probably a degenerate cluster.

## 8.5 60-second story not rehearsed
Written in the playbook, never said aloud. It is the only artifact graded in
the room.

## 8.6 Not built (all optional)
- HCO / IDN account rollup (CMS DAC file) — was in the plan, never built
- Story-mode acts beyond the 7 implemented (no 3D extruded map)
- `/app/segments` route
- Self-hosted webfonts (Instrument Serif / Inter Tight / IBM Plex Mono) — CSS
  references them, fallbacks are Georgia / system sans / system mono

---

# 9. COMMANDS

```powershell
# full pipeline, resumable, dependency-aware
cd "D:\ZS 2\pharmatarget"; .\run_all.ps1

# subset / force / serve after
.\run_all.ps1 -Only sizing,territory
.\run_all.ps1 -Force -Serve

# read findings any time (safe mid-run)
python -m src.utils.summary

# regenerate figures + deck
python -m src.report.make_assets

# API (serves web/dist with SPA fallback)
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000

# frontend
$env:Path = "D:\ZS 2\pharmatarget\.tools\node-v22.20.0-win-x64;$env:Path"
cd web; npm run build      # or: npm run dev  (proxies /api to :8000)

# quality
python -m ruff check src api tests
python -m pytest tests -q          # 41 tests

# watch a long run
Get-Content "D:\ZS 2\pharmatarget\data\run.log" -Wait -Tail 20
```

Runtimes on this machine: marts ~2 min · opportunity ~55 s · back-test ~50 s ·
challenger ~70 s · sizing ~79 s · territory ~62 s · segmentation ~10 min ·
assets ~20 s.

---

# 10. DESIGN DECISIONS WORTH NOT RE-LITIGATING

1. **Match on generic name, never brand.** Real data ships `Warfarin Sodium`
   and `Dabigatran Etexilate` as brand names.
2. **`Tot_30day_Fills`, not `Tot_Clms`.** Apixaban is BID, rivaroxaban QD; a
   90-day claim is one claim but three 30-day fills.
3. **Two decile ramps.** Opportunity chromatic, volume **neutral grey**. It is
   rhetoric *and* it guarantees colour-blind safety.
4. **All numerals monospaced with tabular figures.** Highest-leverage
   typographic decision in the UI.
5. **No shadows in tool mode.** Hairlines are the structural device.
6. **No component library, no charting library, no Mapbox.** Reasons in
   `web/README.md`.
7. **Filtering/sorting/pagination in SQL, never in the browser.**
   `/api/hcps` p95 = 71 ms on 1.38M rows.
8. **Canvas 2D for the particle field, not three.js.** 24k points batched by
   colour holds 60fps without 600 KB of WebGL.
9. **Permutation importance, not SHAP.** TreeExplainer does not support
   `HistGradientBoostingRegressor`, and pinball-loss permutation asks the right
   question for a quantile model.
10. **`HistGradientBoostingRegressor`, not `GradientBoostingRegressor`.** Same
    objective; minutes instead of an hour at 1.4M rows.
11. **Report all four targeting rules, declare no winner.** The evidence does
    not support one, and saying so is stronger than pretending otherwise.

---

# 11. CURRENT SCORECARD (my own brutal assessment)

| Dimension | Score |
|---|---|
| Domain fit | 9.5 |
| Analytical depth | 9.0 |
| Intellectual honesty | 10 |
| Engineering | 9.5 |
| **Business credibility** | **6.0** ← the 586-rep number |
| Communication assets | 7.5 (was 3.5 before figures + deck) |
| **Overall** | **~9.0** |

**Next three things, in order:**
1. Fix the 586-rep headline (§8.1) — 1 h, removes the one fatal objection
2. Deploy (§8.2) — 2 h, a clickable URL is worth five repos
3. Rehearse the 60-second story (§8.5) — 1 h

Story-mode polish is **not** on that list. It is upside; those three are not.
