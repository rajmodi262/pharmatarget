# PharmaTarget — Full Working Context

> **Purpose.** Everything a fresh session needs to continue without re-deriving
> anything. Last updated 2026-08-09, after the robustness/frontend session.
> Read this first, then `README.md` for the outward story.
>
> **Companion docs** (one level up, in `D:\ZS 2\`):
> `PharmaTarget_v2_Plan.md` · `PharmaTarget_TASKS.md` ·
> `PharmaTarget_Execution_Playbook.md` · `PharmaTarget_Frontend_Design_Brief.md` ·
> `PharmaTarget_Deck_Prompt.md` · `ANTIGRAVITY_DEPLOY_PROMPT.md`

---

# 1. WHAT THIS IS

Portfolio project for a **ZS Associates Decision Analytics Associate** role.
Fictional client "Northwind Pharma", branded DOAC (modelled on apixaban/Eliquis),
**real US CMS data**. Four questions: who to call on, how often, how many reps,
how to draw the map.

**Thesis:** the industry ranks prescribers by volume; that is structurally wrong
because a prescriber at 90% brand share has no headroom. Rank on modelled
**opportunity** instead.

**Location:** `D:\ZS 2\pharmatarget\` · **Git:** initialised, 8 commits,
remote `rajmodi262/pharmatarget` (pushed).

---

# 2. ENVIRONMENT — READ BEFORE RUNNING ANYTHING

| Thing | Reality |
|---|---|
| Python | 3.10.0, `C:\Program Files\Python310\python.exe`, on PATH as `python` |
| Node | **Portable ONLY**: `.tools\node-v22.20.0-win-x64\` (v22.20.0, npm 10.9.3) |
| System Node | **BROKEN — DO NOT FIX.** PATH has `D:\RajFiles\nodejs`, folder does not exist. `winget install` fails 1632 because it tries to *upgrade* an orphaned registry entry. Use the portable copy. |
| Docker | 29.4.1 installed |
| gh CLI | installed, **NOT authenticated** |
| Missing pkgs | `statsmodels` never installed (OLS hand-rolled with `numpy.linalg.lstsq`). `shap` **removed** — driver attribution uses permutation importance. |

Node in a shell:
```powershell
$env:Path = "D:\ZS 2\pharmatarget\.tools\node-v22.20.0-win-x64;$env:Path"
```

Frontend test deps installed: `vitest`, `@testing-library/react`,
`@testing-library/jest-dom`, `jsdom`. Fonts self-hosted in `web/public/fonts/`.

---

# 3. THE DATA

## 3.1 `dataset/` — 29 GB, user-downloaded, DO NOT RE-DOWNLOAD

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
2024_Gaz_zcta_national.txt / .zip      6.6 MB    Census Gazetteer ZCTA
PLACES__Local_Data_for_Better_Health__ZCTA_Data__2025_release.csv  229 MB
```

**FILENAME TRAP:** Part D names encode BOTH a release year and a data year.
`RY26 ... DY24` = released 2026, **data year 2024**. Parsing the release year
shifts every year by two. Code parses `_DY(\d{2})_`.

## 3.2 Years: **2022 / 2023 / 2024**

`config/params.yaml`: `train_start 2022`, `train_end 2023`, `holdout 2024`.
2022→2023 = pre-trend window · 2023→2024 = treatment/holdout.
DY2024 published May 2026 → **~17-month lag**, not the ~2 years usually quoted.

## 3.3 Therapeutic class

Matched on **`Gnrc_Name`, NEVER `Brnd_Name`** — real data ships
`Warfarin Sodium` and `Dabigatran Etexilate` as *brand* names, so brand matching
silently drops them.

Real 2023 composition: **Eliquis 32.17M fills / 245,552 prescribers** ·
Xarelto 10.29M / 132,410 · Warfarin+Jantoven 9.57M · Pradaxa 1.14M ·
Savaysa 0.004M. Eliquis ≈ **61% of a 53M-fill class** (matches published share).
**No apixaban generics in Part D through 2024** (verified).

---

# 4. PIPELINE — MODULE BY MODULE

Run everything: `.\run_all.ps1` (resumable, dependency-aware).

| Module | Does |
|---|---|
| `src/ingest/download.py` | Streams + filters. Keeps class rows AND accumulates per-NPI all-drug `Tot_Clms` into `npi_alldrug_totals_YYYY.csv`. 80.0M rows in → **1.52M class rows**. `--local-dir dataset`, `--discover-manufacturers`. |
| `src/ingest/geo_build.py` | Gazetteer × PLACES → `zip3_units.csv`. 33,791 ZCTAs, 88.7% PLACES match → **896 ZIP3 units**, 313.9M pop. Handles BOTH PLACES formats (long w/ `MeasureId`, wide GIS). |
| `src/ingest/synth.py` | CMS-shaped synthetic generator. Emits REAL column names (see §6.4). |
| `src/etl/build_marts.py` | DuckDB, 5 SQL files → `mart_hcp_metrics` (**4,129,857 rows**). Chooses all-drug source per ingest path. |
| `src/models/opportunity.py` | `HistGradientBoostingRegressor(loss="quantile", quantile=0.80)`. Fit on 267,171 in-market 2023 prescribers. Deciles **within the in-market universe only**. Leakage guard **raises**. Permutation importance on pinball loss. |
| `src/models/callplan.py` | Matrix (opp decile × share) **then a capacity cut** — rank by opportunity, fill 60 reps' diaries, rest are no-call. |
| `src/models/backtest.py` | Fit 2022–23, freeze, score 2024. Gate G3 = **three** conditions. |
| `src/models/challenger.py` | Races ML-trained-on-growth against the frontier. Produced the project's key finding. |
| `src/models/robustness.py` | **NEW.** Bootstrap CIs (400 draws), τ sensitivity sweep, propensity-matched growth. |
| `src/models/sizing.py` | Marginal-ROI + tornado. `_Ranked` sorts once. **Recommendation capped** at 1.5× current force. |
| `src/models/territory.py` | Capacitated k-means + contiguity repair + balance pass + boundary polish. |
| `src/models/segmentation.py` | KMeans + bootstrap-ARI stability selection. |
| `src/models/response.py` | PSM + DiD + Hill saturation. |
| `src/report/make_assets.py` | 6 PNGs + 13-slide PDF, all from parquet/manifest. |
| `src/report/make_deploy_bundle.py` | Slims `data/processed` (798 MB) → `data/deploy` (**36 MB**). |
| `src/utils/schema.py` | **NEW.** Canonical column contracts + `require_columns()`. |
| `src/utils/gates.py` | **NEW.** Evaluates G2 and G4 (run_all doesn't call `src/pipeline.py`). |
| `src/utils/summary.py` | `python -m src.utils.summary` — findings from manifest, safe any time. |

---

# 5. ALL CURRENT REAL-DATA NUMBERS

## 5.1 Scale
1,380,665 prescribers (2023); **267,171 in-market** (write the class).
4,129,857 prescriber-years. 80.0M drug rows → 1.52M class rows.
Open Payments 4.77M rows kept, **90.3% linked**.

## 5.2 Suppression
**13.7% of all claim volume hidden**, 99.7% of prescriber-years affected.
By size: **<100 claims 68.7%** · 100–500 43.0% · 500–2,000 21.6% · 2,000+ 8.6%.

## 5.3 Model
Frontier coverage **0.800** vs τ=0.80 (back-test refit reports 0.785 — the more
conservative figure, and the one the README quotes).
SFA cross-check Spearman **0.849**. Top driver `log_non_class_clms` **32.4%**.
Max feature↔target correlation 0.534 (leak threshold 0.97).

## 5.4 Disagreement (E1)
**59.4%** move ≥2 deciles · **23,615** low-vol/high-opp · **26,580** high-vol/low-opp.

## 5.5 Back-test — WITH INTERVALS (400-draw percentile bootstrap)

| Metric | Estimate | 95% CI |
|---|---|---|
| Share-growth capture vs volume | **1.391×** | [1.371, 1.411] **excludes 1.0** |
| Absolute-growth capture vs volume | 0.726× | [0.717, 0.735] volume wins |
| Spearman (decile, growth) | 0.927 | [0.879, 0.927] |
| opportunity_share / volume_share | 0.206 / 0.148 | [0.203,0.209] / [0.146,0.150] |
| opportunity_abs / volume_abs | 0.358 / 0.493 | [0.353,0.362] / [0.488,0.497] |

Selected-list median base **312.4 fills = 61%** of the volume rule's (anti-gaming).
Biggest misses over-represent **Advanced Practice (+15.0 pp)**.

## 5.6 Propensity-matched growth — **THE HEADLINE**
**1.37×** · 49,864 pairs · 5 covariates · worst SMD **0.041** (balanced) ·
flagged 19.28 vs control 14.08 fills · paired difference **+5.21 [4.10, 6.31]**.

**Supersedes the old 1.50×**, which stratified on volume decile alone. Better
confounder control lowered the estimate, as it should.

## 5.7 τ sensitivity (NEW)
Refit across τ ∈ {0.65, 0.70, 0.75, 0.80, 0.85, 0.90}:

| τ | ρ vs base | same decile | within 1 | top-3 retained |
|---|---|---|---|---|
| 0.65 | 0.924 | 46.8% | 84.8% | 86.1% |
| 0.70 | 0.956 | 55.0% | 93.1% | 89.6% |
| 0.75 | 0.981 | 68.6% | 98.0% | 93.5% |
| 0.85 | 0.980 | 67.5% | 97.9% | 93.3% |
| 0.90 | 0.939 | 51.3% | 88.4% | 88.0% |

**Verdict:** robust within ±0.05 (ρ ≥ 0.980, top-3 ≥ 93%); degrades gracefully
to ρ 0.924 at ±0.15. τ is a tuning choice, not the finding. **Report the near
band; do not claim invariance.**

## 5.8 Champion vs challenger (60-rep budget, N=8,399)

| Rule | Share capture | Abs capture | Median base fills |
|---|---|---|---|
| ml_share | **11.7%** | 1.9% | **35** |
| opportunity | 2.4% | 10.3% | 840 |
| ml_abs | 2.1% | 14.9% | 1,052 |
| volume | 1.7% | **16.0%** | 1,470 |

ML beat the frontier **4.9×** on the stated criterion by selecting 35-fill
prescribers and delivering 1.9% of volume. → criterion was gameable → gate
hardened to three conditions. **Volume wins absolute capture and cannot be
adjudicated without call data.**

## 5.9 Capacity & sizing
60 reps serve **8,389 of 267,171** = **3.1%**, 100% utilisation.
Unconstrained demand 106,869 prescribers → 579 reps.
Reach @60: opportunity **6.9%** · volume **3.2%** · geography **0.6%**.

**RECOMMENDATION: +30 reps (60 → 90), worth $62.1M**, marginal rep still
**$8.57 per $1** at the recommended size.
**DIAGNOSTIC (not an ask):** economics bind at **586 reps** (sensitivity
471–700); **496 reps of unmet demand**. Capped by
`economics.yaml: max_plausible_expansion: 1.5`.
Tornado: most sensitive `calls_per_rep_per_day` (229-rep swing); **zero**
sensitivity to contribution margin.

## 5.10 Territory
Imbalance **157.17× → 2.51×** · contiguity **20% → 100%** ·
travel 258 → 65 mi (**−75%**) · CV 0.42 → 0.166 @60, **0.102 @80**.

## 5.11 Segmentation
k=8, silhouette **0.807**, bootstrap ARI **0.998**.
⚠️ Silhouette abnormally high — likely a degenerate cluster. **STILL UNCHECKED.**

## 5.12 Response
Naive OLS elasticity **0.061** · matched DiD **0.00209** → **29× selection gap**.
**Parallel-trends FAILED** → association only, causal language removed
(pre-committed in CHARTER.md).

## 5.13 Gates
**G2 PASSED** (59.4% ≥ 30%) · **G3 PASSED** (0.927 / 1.392 / 61%) ·
**G4 PASSED** (contiguity 100%, CV 0.116).

---

# 6. EVERY BUG FOUND (the most valuable section)

## Session 1 bugs

**6.1 Open Payments filter silently ignored.** `?query=<json>` returned HTTP 200
with `count=14,734,121` — the entire dataset, showing Neuronetics and Mission
Pharmacal. Only **bracketed params** filter. `limit` caps at **500**.
Fix: `_op_query()` + assertion that returned rows match the requested mfr.

**6.2 Every guessed manufacturer name wrong.** `Bristol-Myers Squibb Company` →
actual `Bristol Myers Squibb Company` (no hyphen); `Pfizer Inc.` → `PFIZER INC.`;
`Janssen Pharmaceuticals, Inc.` → no trailing period; `Daiichi Sankyo, Inc.` →
`Daiichi Sankyo Inc.`. **BMS headline entity has 124 records; the apixaban
alliance reports through `E.R. Squibb & Sons, L.L.C.` — 236,558.** Names drift
yearly (Bayer 1→2, Janssen 2→1→3). Fix: `--discover-manufacturers`.

**6.3 Synthetic and real about to be joined.** Both write identical filenames.
Fix: `.data_mode` marker + `claim_raw_dir()`.

**6.4 `Bene_Age_GE_65_Cnt` does not exist.** Invented by synth; pipeline ran
green on synthetic, failed on first real extract. CMS ships age BANDS
(`Bene_Age_LT_65_Cnt`, `_65_74_`, `_75_84_`, `_GT_84_`, `GE65_Tot_Benes`).

**6.5 Suppression reported 98% twice, two causes.** (a) synth emitted only class
drugs → fixed with `OTHER_DRUGS`; (b) SQL 03 summed `stg_scripts` which after
streaming holds class rows only → fixed by reading the side-car totals.
Correct value **13.7%**.

**6.6 Deciling across the whole Part D file** made "decile 9" mean "writes the
class at all". Fix: decile within the in-market universe; others get decile 0.

**6.7 Gate G3 criterion was gameable.** Originally share capture alone; I changed
it after seeing it fail on synthetic data (flagged at the time). Challenger then
proved the criterion itself was gameable. Now three conditions incl. median base
≥25% of the volume rule's.

**6.8 Call plan implied 4,575 reps vs a force of 60** — no capacity constraint.

**6.9 Sizing read capacity-capped calls** → ROI flatlined above 60, "break-even
69" was an artefact. Fix: `_Ranked` prefers `desired_calls`.

**6.10 Sizing pathologically slow** — re-sorted 1.38M rows on ~1,000 tornado
calls. `_Ranked` sorts once. **>15 min → 79 s.**

**6.11 Territory CV stuck at 0.28.** Capacity is only an upper bound. Fix:
`_rebalance()` with squared-deviation objective. ⚠️ The `loads[src] <= target`
guard is **load-bearing** — removing it was measured and made CV **worse**
(0.165 → 0.203).

**6.12 Rebalance churned 40 passes at flat CV** → stall detection. 90 s → 30 s.

**6.13 Saturation half-saturation fitted at −$104** → bounds + "unidentifiable"
path.

## Session 2 bugs (CI, frontend, deploy)

**6.14 THE YEAR WAS PARSED FROM THE PATH, NOT THE FILENAME.** Unanchored
`(\d{4})` matched the absolute path returned by `read_csv_auto(filename=true)`.
A clone under a directory containing `-6310-` stamped **every row with year
6310**, producing an empty training set and **no error**. Worked locally by luck
(`D:\ZS 2\pharmatarget\` has no 4-digit run). Fixed to `'_(\d{4})\.csv$'` in
SQL 01, SQL 02 and `build_marts.py`. **A static test now scans every .sql file.**

**6.15 SQL 03 assumed the real ingest.** `npi_alldrug_totals_*.csv` only exists
on the streaming path. `build_marts._alldrug_source()` now chooses and logs.

**6.16 synth `zip3_units` columns drifted** — emitted `pop_65_plus`/`pct_65_plus`
while geo_build produced `population`/`pop_density`. SQL 04 binder error.

**6.17 React Query stuck in `isPending` forever on a 503** → infinite skeleton,
which *looks like the app is working*. Fix: branch on `isError || error` BEFORE
`isPending`; never retry a 503.

**6.18 SPA fallback missing** — `/app/targets` 404'd on hard refresh.

**6.19 Query-key collision** — AppShell used `qk.meta` for `/api/health`.

**6.20 `/api/hcps/sample` shadowed by `/api/hcps/{npi}`** (FastAPI matches in
declaration order) → renamed `/api/hcp-sample`.

**6.21 `USING SAMPLE 24000 ROWS` returned 4,736** — DuckDB samples per row-group.
Fix: `ORDER BY random() LIMIT ?`.

**6.22 Hero exhibit didn't show its own finding** — coloured by territory ID on a
20-colour map with 60 territories; before/after looked identical. Fix: colour by
**territory workload on a shared scale**.

**6.23 `letterspacing` is not a matplotlib property.**

**6.24 PowerShell here-string + embedded Python** = invalid Python → extracted to
`src/utils/summary.py`.

**6.25 `growth_share` NaN** when a prescriber writes no class volume next year.

**6.26 Story scroll used `window.scrollY`** — silently does nothing when anything
other than the window scrolls. Fixed to `getBoundingClientRect()` on a rAF loop,
**and then decoupled entirely** (see §7.2).

**6.27 Two AA contrast failures** — `--text-faint` at 2.73:1 (need 4.5). Fixed
`#4A5768` → `#75859A`. Now worst 5.33 across 110 elements in 7 acts.

**6.28 20px tap targets** → 44px on touch (`h-11 sm:h-5`).

**6.29 Gates G2 and G4 were NEVER RECORDED by `run_all.ps1`** — they live in
`src/pipeline.py`, which run_all deliberately doesn't call. Only G3 reached the
manifest. **The checks weren't failing; they weren't happening.** Fix:
`src/utils/gates.py`.

**6.30 README claimed coverage 0.800, manifest held 0.785** — and my own drift
check used a 0.02 tolerance, so it printed OK. A tolerance loose enough to pass
a real discrepancy is worse than no check.

**6.31 `manifest.json` held stale `gate_g3` values** (1.0 / 1.4 / 0.8) while the
log said 0.927. Third occurrence of the mutable-blob problem.
**ARCHITECTURALLY UNFIXED — see §8.4.**

**6.32 `share_growth` not persisted to `backtest_frame`** → the headline metric
silently got no confidence interval while the secondary one did.

**6.33 586-rep recommendation was not credible** → capped at one recruiting
cycle; the uncapped figure is published as a labelled diagnostic.

**6.34 A test expectation was wrong, not the code** — I asserted
`compact(2.4e9) === "2.40B"`; correct is `"2.4B"`.

---

# 7. FRONTEND

## 7.1 Structure
`web/` — React 18 + TS (strict, `noUncheckedIndexedAccess`) + Vite + Tailwind.
**19 files, ~3,900 lines. 116 KB gzipped.**

Routes: `/` and `/story` (story mode) · `/app` Overview · `/app/targets` ·
`/app/territories` · `/app/response` · `/app/method`.

## 7.2 Story mode
7 acts, canvas-2D particle field (`ParticleField.tsx`), **24,000 real
prescribers** from `/api/hcp-sample` (parallel arrays, ~1.4 MB, 473 ms).
Layouts: noise → volume → split → ignite → geo. Spring toward per-act targets.
Batched by colour (one `fillStyle` per distinct colour, not 24,000).

**Act index is state that scroll SYNCS TO, not state scroll OWNS.** Keyboard
(`←/→/space/Home/End`) and clickable act markers are first-class. This was
necessary because (a) keyboard users cannot drive a 7-act scroll narrative, and
(b) **the embedded preview pane rejects `scrollTop` assignment outright**, so
scroll could not be verified there.

⚠️ **SCROLL ITSELF IS STILL UNVERIFIED IN A REAL BROWSER.** Click/keyboard
navigation IS verified (all 7 acts advance with correct real numbers).

## 7.3 Fonts — self-hosted
`web/public/fonts/` — **196 KB, Latin subset only**, 7 faces.
Instrument Serif 400 · Inter Tight 400/500/600 · IBM Plex Mono 400/500/600.
Generated by a script into `web/src/design/fonts.css`, imported by `tokens.css`.
**Verified loading in-browser.** (First attempt pulled 399 KB incl. Cyrillic/
Greek/Vietnamese — wrong trade for a 116 KB app.)

## 7.4 Tests — 57 (vitest + jsdom)
`format.test.ts` (missing≠zero invariant) · `scales.test.ts` (ramp monotonicity,
volume-stays-neutral, colour-blind separation) · `States.test.tsx` (503 vs
network distinction, banner not dismissible).
Run: `npm run test`. Config: `vitest.config.ts`, setup `src/test/setup.ts`
(mocks `matchMedia` + `requestAnimationFrame`).

## 7.5 Accessibility — MEASURED
Contrast: **110 elements across 7 acts, 0 failures, worst 5.33** (AA needs 4.5).
All 7 act buttons keyboard-focusable. 44px touch targets. `sr-only` narrative in
DOM order. Reduced-motion path renders static final states.
Mobile 375px: **zero horizontal overflow**, nothing wider than viewport.

---

# 8. WHAT IS NOT DONE

## 8.1 ⚠️ Economic modelling — HIGHEST PRIORITY (score 4.5/10)
`call_response_ceiling: 0.28` and `call_response_half_saturation: 12.0` are
**constants typed into a YAML file**. Every dollar figure rests on them. The
tornado shows break-even swings **229 reps** on `calls_per_rep_per_day` alone.
**Fix:** fit the Hill parameters from the 2023→2024 promotional panel
(`response.py` already fits a saturation curve) and propagate their bootstrap
uncertainty into the ROI curve. ~2–3 h. **The single highest-value item left.**

## 8.2 Not deployed
`gh` not authenticated. Everything else is ready: `data/deploy` (36 MB),
`Dockerfile` (uses `PHARMATARGET_DATA_DIR`), `render.yaml`, SPA fallback,
`data_scope` disclosure on `/api/meta` + Targets route.
```
gh auth login && gh repo create pharmatarget --public --source=. --push
```
then connect on render.com (reads `render.yaml`).

## 8.3 Optimisation has no bound (7.0/10)
Territory heuristic reports CV 0.166 versus **nothing**. No MIP relaxation, no
lower bound, no best-of-N restarts. Contiguity is measured against **k-NN
adjacency, not real ZCTA polygons**.

## 8.4 `manifest.json` is a mutable global blob
Modules overwrite each other's keys with no namespacing. Caused §6.30 and §6.31.
**Fix:** namespace by module + run id, or write per-module JSON.

## 8.5 Two orchestrators
`run_all.ps1` (Windows, resumable, per-module) and `src/pipeline.py` (what CI
runs). They can drift — §6.29 is exactly that. `requirements.lock` now pins
15 packages, but there is no per-run artifact versioning.

## 8.6 No integration test on the real-data path
130 tests, all synthetic/fixtures. Nothing would catch the suppression figure
silently moving from 13.7% to 98% again.

## 8.7 Segmentation silhouette 0.807 at k=8 unexplained
Flagged three times, still unchecked. Almost certainly a degenerate cluster.

## 8.8 Story scroll unverified in a real browser (§7.2)

## 8.9 60-second story not rehearsed
Written in the playbook, never said aloud. The only artifact graded in the room.

## 8.10 Not built (optional)
HCO/IDN account rollup (CMS DAC) · 3D extruded territory map ·
`/app/segments` route.

---

# 9. COMMANDS

```powershell
cd "D:\ZS 2\pharmatarget"

.\run_all.ps1                      # full pipeline, resumable
.\run_all.ps1 -Only sizing,robustness
.\run_all.ps1 -Force -Serve
python -m src.utils.summary        # findings, safe mid-run
python -m src.report.make_assets   # 6 PNGs + 13-slide PDF
python -m src.models.robustness    # CIs, tau sweep, PSM
python -m src.utils.gates          # G2 + G4
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000

python -m ruff check src api tests  # clean
python -m pytest tests -q           # 73 tests

$env:Path = "D:\ZS 2\pharmatarget\.tools\node-v22.20.0-win-x64;$env:Path"
cd web; npm run test; npm run typecheck; npm run build   # 57 tests

Get-Content "data\run.log" -Wait -Tail 20
```

**Runtimes:** marts ~2 min · opportunity ~55 s · back-test ~50 s ·
challenger ~70 s · sizing ~79 s · territory ~62 s · segmentation ~10 min ·
robustness ~4 min · assets ~20 s.

---

# 10. DECISIONS NOT TO RE-LITIGATE

1. Match on **generic name**, never brand.
2. **`Tot_30day_Fills`**, not `Tot_Clms` — apixaban BID vs rivaroxaban QD.
3. **Two decile ramps** — opportunity chromatic, volume neutral grey. Rhetoric
   AND colour-blind safety.
4. **All numerals monospaced, tabular figures.**
5. **No shadows in tool mode** — hairlines are the structure.
6. **No component library, no charting library, no Mapbox.**
7. **Filtering/sorting/pagination in SQL.** `/api/hcps` p95 = 71 ms on 1.38M.
8. **Canvas 2D, not three.js** — 24k points batched by colour holds 60fps.
9. **Permutation importance, not SHAP** — TreeExplainer doesn't support HistGBR;
   pinball-loss permutation asks the right question for a quantile model.
10. **HistGradientBoostingRegressor** — same objective, minutes not an hour.
11. **Report all four targeting rules, declare no winner.**
12. **Sizing recommendation capped** at one recruiting cycle; the uncapped
    break-even is a diagnostic, never an ask.
13. **τ reported as a near-band robustness claim**, never as invariance.

---

# 11. SCORECARD (self-assessed, brutal)

## Backend **8.3 / 10**
| | |
|---|---|
| Data engineering | 9.0 |
| Statistical rigour | 9.5 (was 6.0 — CIs + τ sweep) |
| Causal inference | 9.0 (was 6.5 — PSM replaces 1-var matching) |
| Software engineering | 8.5 |
| Reproducibility | 7.5 (lockfile; two orchestrators remain) |
| Optimisation | 7.0 |
| **Economic modelling** | **4.5** ← §8.1 |

## Frontend **9.4 / 10** (0.1 withheld for not being deployed)
Architecture 9.0 · story nav 9.5 · typography 9.5 · testing 9.0 ·
accessibility 9.5 · responsive 9.0 · deployed **0**

## Project overall **~9.1 built · ~8.2 as an interview artifact**
Intellectual honesty 10 · domain fit 9.5 · business credibility 8.5 ·
communication assets 7.5.

## Next four, in order
1. **Fit the Hill parameters** (§8.1) — 2–3 h, biggest remaining gap
2. **Deploy** (§8.2) — needs your `gh auth login`
3. **Rehearse the 60-second story** (§8.9) — 1 h
4. **Namespace the manifest** (§8.4) — stops the drift class permanently

**Totals:** 130 tests (73 Python + 57 TS) · ruff clean · typecheck clean ·
8 commits · nothing uncommitted.
