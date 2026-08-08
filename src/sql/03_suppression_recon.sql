-- 03_suppression_recon.sql
--
-- THE SUPPRESSION PROBLEM, STATED CORRECTLY
-- -----------------------------------------
-- CMS does not blank low-volume cells in the Part D Provider-and-Drug file.
-- It REMOVES the row. Any NPI x drug combination with fewer than 11 claims is
-- absent from the file entirely.
--
-- The consequence most analyses get wrong: you cannot flag a censored row,
-- because there is no row to flag. Filling blanks with zero is impossible
-- (there are no blanks) and assuming the file is complete is wrong (it is not).
-- The bias is systematic and one-directional -- it hides exactly the
-- low-volume prescribers a targeting model most needs to reason about.
--
-- WHAT THIS FILE DOES
-- -------------------
-- The provider-level file (D2) reports each prescriber's TOTAL claims across
-- every drug, and is not subject to the same row suppression. So:
--
--     suppressed_clms  =  D2 total claims  -  SUM(D1 rows for that NPI)
--
-- That gap is real claim volume, spread across an unknown number of drugs, each
-- holding between 1 and 10 claims. From it we can bound the number of hidden
-- rows and estimate how much of the gap plausibly belongs to our class.
--
-- The three imputation modes (zero / ev / max) run end to end and the decile
-- movement between them is published in the README. That sensitivity table is
-- the deliverable here -- not the point estimate.

-- The all-drug observed total is read from npi_alldrug_totals_*.csv, NOT summed
-- from stg_scripts.
--
-- WHY THIS MATTERS ENORMOUSLY: the ingest streams the 4 GB drug file and keeps
-- only rows in the therapeutic class, while accumulating a per-NPI sum across
-- EVERY drug on the way past. stg_scripts therefore holds class rows alone.
-- Summing it here would compare "class claims" against "all-drug provider
-- totals" and report ~98% of volume as suppressed -- measuring the drugs we
-- chose not to keep, not the rows CMS withheld. The true figure is ~14%.
--
-- A wrong number here does not crash anything. It flows silently into every
-- imputation mode and every downstream decile. Verified against a standalone
-- reconciliation query on the raw files before this join was written.
CREATE OR REPLACE TABLE stg_alldrug_totals AS
SELECT
    CAST(Prscrbr_NPI AS BIGINT)                              AS npi,
    CAST(regexp_extract(filename, '(\d{4})', 1) AS INTEGER)  AS year,
    CAST(All_Drug_Tot_Clms_Observed AS DOUBLE)               AS observed_all_clms
FROM read_csv_auto('{{RAW}}/npi_alldrug_totals_*.csv',
                   filename = true, union_by_name = true, header = true);


CREATE OR REPLACE TABLE stg_suppression AS
WITH class_observed AS (
    SELECT
        npi,
        year,
        SUM(CASE WHEN is_in_class THEN tot_clms ELSE 0 END)      AS observed_class_clms,
        COUNT(*)                                                 AS observed_rows,
        COUNT(*) FILTER (WHERE is_in_class)                      AS observed_class_rows
    FROM stg_scripts
    GROUP BY npi, year
),
observed AS (
    SELECT
        COALESCE(a.npi, c.npi)                    AS npi,
        COALESCE(a.year, c.year)                  AS year,
        COALESCE(a.observed_all_clms, 0)          AS observed_all_clms,
        COALESCE(c.observed_class_clms, 0)        AS observed_class_clms,
        COALESCE(c.observed_rows, 0)              AS observed_rows,
        COALESCE(c.observed_class_rows, 0)        AS observed_class_rows
    FROM stg_alldrug_totals a
    FULL OUTER JOIN class_observed c USING (npi, year)
),
joined AS (
    SELECT
        p.npi,
        p.year,
        p.all_drug_clms,
        p.specialty_group,
        COALESCE(o.observed_all_clms, 0)    AS observed_all_clms,
        COALESCE(o.observed_class_clms, 0)  AS observed_class_clms,
        COALESCE(o.observed_rows, 0)        AS observed_rows,
        COALESCE(o.observed_class_rows, 0)  AS observed_class_rows,
        GREATEST(p.all_drug_clms - COALESCE(o.observed_all_clms, 0), 0) AS suppressed_clms
    FROM stg_prescribers p
    LEFT JOIN observed o USING (npi, year)
)
SELECT
    *,
    -- A hidden row holds 1..10 claims, so the gap implies at least
    -- ceil(gap/10) hidden rows and at most `gap` of them.
    CEIL(suppressed_clms / 10.0)                    AS suppressed_rows_min,
    suppressed_clms                                 AS suppressed_rows_max,
    -- Expected value under a uniform draw on 1..10 claims per hidden row.
    CASE WHEN suppressed_clms > 0
         THEN suppressed_clms / 5.5
         ELSE 0 END                                 AS suppressed_rows_ev,
    -- What share of this prescriber's hidden volume plausibly belongs to our
    -- class? Anchored on their OBSERVED class share of visible volume; a
    -- prescriber who writes no class drugs at all is assumed to hide none.
    CASE WHEN observed_all_clms > 0
         THEN observed_class_clms / observed_all_clms
         ELSE 0 END                                 AS observed_class_frac,
    suppressed_clms > 0                             AS has_suppression
FROM joined;


-- Class-level imputation under all three modes. Downstream code selects the
-- mode by name so a full sensitivity sweep is a config change, not a rewrite.
CREATE OR REPLACE TABLE stg_class_imputed AS
SELECT
    s.npi,
    s.year,
    COALESCE(v.class_fills, 0)                      AS class_fills_observed,
    COALESCE(v.brand_fills, 0)                      AS brand_fills_observed,
    COALESCE(v.class_drug_rows, 0)                  AS class_drug_rows,
    s.suppressed_clms,
    s.observed_class_frac,

    -- zero: the file is taken at face value. Conservative, biased low.
    COALESCE(v.class_fills, 0)                      AS class_fills_zero,

    -- ev: expected hidden class volume, scaled to 30-day fills by the
    --     prescriber's own observed claims-to-fills ratio where available.
    COALESCE(v.class_fills, 0)
        + s.suppressed_clms * s.observed_class_frac
          * COALESCE(v.class_fills / NULLIF(v.class_clms, 0), 1.0)  AS class_fills_ev,

    -- max: every hidden row assumed to sit at the suppression ceiling.
    COALESCE(v.class_fills, 0)
        + CEIL(s.suppressed_clms / 10.0) * 10.0 * s.observed_class_frac
          * COALESCE(v.class_fills / NULLIF(v.class_clms, 0), 1.0)  AS class_fills_max
FROM stg_suppression s
LEFT JOIN stg_class_volume v USING (npi, year);
