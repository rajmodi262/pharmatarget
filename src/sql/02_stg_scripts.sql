-- 02_stg_scripts.sql
-- Source: D1, Medicare Part D Prescribers by Provider AND Drug.
--
-- Two decisions worth defending in an interview:
--
--   1. Class membership is matched on Gnrc_Name, not Brnd_Name. Brand strings
--      drift across annual releases ('ELIQUIS' vs 'ELIQUIS 2.5MG'); generic
--      strings are stable. Matching on brand silently loses rows every year.
--
--   2. The volume metric is Tot_30day_Fills, not Tot_Clms. Apixaban is dosed
--      BID and rivaroxaban QD, so a 90-day claim is one claim for both but
--      three 30-day fills. Comparing raw claim counts across a class with
--      mixed dosing regimens understates the BID product. This choice moves
--      brand share by several points and is set in config/params.yaml.

CREATE OR REPLACE TABLE stg_scripts AS
WITH raw AS (
    SELECT
        *,
        CAST(regexp_extract(filename, '_(\d{4})\.csv$', 1) AS INTEGER) AS year
    FROM read_csv_auto(
        '{{RAW}}/partd_drug_*.csv',
        filename = true,
        union_by_name = true,
        header = true
    )
)
SELECT
    CAST(Prscrbr_NPI AS BIGINT)              AS npi,
    year,
    UPPER(TRIM(Brnd_Name))                   AS brand_name,
    UPPER(TRIM(Gnrc_Name))                   AS generic_name,
    CAST(Tot_Clms AS DOUBLE)                 AS tot_clms,
    CAST(Tot_30day_Fills AS DOUBLE)          AS tot_30day_fills,
    CAST(Tot_Drug_Cst AS DOUBLE)             AS tot_drug_cst,
    UPPER(TRIM(Gnrc_Name)) IN ({{FOCUS_GENERICS}})  AS is_focus_brand,
    UPPER(TRIM(Gnrc_Name)) IN ({{CLASS_GENERICS}})  AS is_in_class
FROM raw
WHERE Prscrbr_NPI IS NOT NULL;


-- Class-only rollup: one row per NPI per year.
CREATE OR REPLACE TABLE stg_class_volume AS
SELECT
    npi,
    year,
    SUM(tot_30day_fills)                                              AS class_fills,
    SUM(CASE WHEN is_focus_brand THEN tot_30day_fills ELSE 0 END)     AS brand_fills,
    SUM(tot_clms)                                                     AS class_clms,
    SUM(CASE WHEN is_focus_brand THEN tot_clms ELSE 0 END)            AS brand_clms,
    SUM(tot_drug_cst)                                                 AS class_cost,
    COUNT(*)                                                          AS class_drug_rows
FROM stg_scripts
WHERE is_in_class
GROUP BY npi, year;

