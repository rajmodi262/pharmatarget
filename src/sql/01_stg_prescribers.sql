-- 01_stg_prescribers.sql
-- Source: D2, Medicare Part D Prescribers by Provider (one row per NPI per year).
--
-- Responsibilities:
--   * union three annual files whose columns drift slightly between releases
--   * normalise ZIP (CMS ships ZIP+4 in some rows, drops leading zeros in others)
--   * collapse ~90 raw specialty strings into analysable groups
--   * carry the provider-level TOTAL claim count, which is the denominator the
--     suppression reconciliation in 03 depends on

CREATE OR REPLACE TABLE stg_prescribers AS
WITH raw AS (
    SELECT
        *,
        CAST(regexp_extract(filename, '(\d{4})', 1) AS INTEGER) AS year
    FROM read_csv_auto(
        '{{RAW}}/partd_provider_*.csv',
        filename = true,
        union_by_name = true,
        header = true
    )
),
typed AS (
    SELECT
        CAST(Prscrbr_NPI AS BIGINT)                        AS npi,
        year,
        UPPER(TRIM(Prscrbr_Last_Org_Name))                 AS last_name,
        UPPER(TRIM(Prscrbr_First_Name))                    AS first_name,
        UPPER(TRIM(Prscrbr_City))                          AS city,
        UPPER(TRIM(Prscrbr_State_Abrvtn))                  AS state,
        -- ZIP+4 arrives as '123401-5678'; numeric reads lose the leading zero.
        -- Strip to digits, left-pad to 5, then take the ZIP3 prefix.
        LPAD(regexp_replace(CAST(Prscrbr_zip5 AS VARCHAR), '[^0-9]', '', 'g'), 5, '0')
                                                           AS zip_clean,
        TRIM(Prscrbr_Type)                                 AS specialty,
        CAST(Tot_Clms AS DOUBLE)                           AS all_drug_clms,
        CAST(Tot_Benes AS DOUBLE)                          AS panel_benes,
        CAST(Bene_Avg_Risk_Scre AS DOUBLE)                 AS risk_score,
        -- CMS publishes age BANDS, not a 65+ total. Assemble it.
        -- COALESCE per band, not on the sum: any band can be individually
        -- suppressed for small counts, and NULL + 5 + 3 is NULL, which would
        -- silently blank the covariate for exactly the small prescribers the
        -- suppression analysis is about.
        COALESCE(TRY_CAST(Bene_Age_65_74_Cnt AS DOUBLE), 0)
          + COALESCE(TRY_CAST(Bene_Age_75_84_Cnt AS DOUBLE), 0)
          + COALESCE(TRY_CAST(Bene_Age_GT_84_Cnt AS DOUBLE), 0)         AS age65_cnt,
        TRY_CAST(GE65_Tot_Benes AS DOUBLE)                 AS ge65_benes,
        TRY_CAST(Bene_Avg_Age AS DOUBLE)                   AS bene_avg_age
    FROM raw
)
SELECT
    npi,
    year,
    last_name,
    first_name,
    city,
    state,
    SUBSTR(zip_clean, 1, 3)                                AS zip3,
    specialty,
    CASE
        WHEN specialty IN ('Cardiology', 'Cardiac Electrophysiology',
                           'Interventional Cardiology')         THEN 'Cardiology'
        WHEN specialty IN ('Internal Medicine', 'Geriatric Medicine',
                           'General Practice')                  THEN 'Internal Medicine'
        WHEN specialty IN ('Family Practice', 'Family Medicine') THEN 'Primary Care'
        WHEN specialty IN ('Nurse Practitioner', 'Physician Assistant',
                           'Clinical Nurse Specialist')         THEN 'Advanced Practice'
        WHEN specialty IN ('Hematology/Oncology', 'Hematology',
                           'Medical Oncology')                  THEN 'Hem/Onc'
        WHEN specialty IN ('Nephrology')                        THEN 'Nephrology'
        WHEN specialty IN ('Neurology', 'Vascular Neurology')    THEN 'Neurology'
        ELSE 'Other'
    END                                                    AS specialty_group,
    all_drug_clms,
    panel_benes,
    risk_score,
    age65_cnt,
    ge65_benes,
    bene_avg_age,
    -- Guard against divide-by-zero downstream rather than at three call sites.
    CASE WHEN panel_benes > 0 THEN age65_cnt / panel_benes END AS pct_panel_65
FROM typed
WHERE npi IS NOT NULL
  AND state IS NOT NULL
  AND LENGTH(state) = 2;
