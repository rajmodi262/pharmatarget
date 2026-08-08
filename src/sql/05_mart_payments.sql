-- 05_mart_payments.sql
-- Source: D3, Open Payments general payments.
--
-- Manufacturer names are normalised through config/manufacturers.yaml rather
-- than fuzzy-matched. Fuzzy matching here is how a competitor's speaker-program
-- spend gets attributed to your own brand, which would invert the sign of the
-- entire response analysis.
--
-- The NPI match rate is MEASURED and written to the manifest. Never quote a
-- match rate you have not computed on your own extract.

CREATE OR REPLACE TABLE stg_payments_raw AS
SELECT
    TRY_CAST(Covered_Recipient_NPI AS BIGINT)                                   AS npi,
    CAST(Program_Year AS INTEGER)                                               AS year,
    TRIM(Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name)         AS manufacturer_raw,
    TRIM(Nature_of_Payment_or_Transfer_of_Value)                                AS nature,
    CAST(Total_Amount_of_Payment_USDollars AS DOUBLE)                           AS amount
FROM read_csv_auto(
    '{{RAW}}/open_payments_*.csv',
    union_by_name = true,
    header = true,
    ignore_errors = true
)
-- Physicians only. Teaching-hospital and third-party rows carry no usable NPI
-- and would otherwise inflate the denominator of the match-rate calculation.
WHERE Covered_Recipient_Type = 'Covered Recipient Physician';


CREATE OR REPLACE TABLE mart_payments AS
WITH mapped AS (
    SELECT
        r.npi,
        r.year,
        r.amount,
        r.nature,
        COALESCE(m.parent, 'UNMAPPED')  AS parent,
        m.parent IS NULL                AS is_unmapped
    FROM stg_payments_raw r
    LEFT JOIN mfr_map m ON r.manufacturer_raw = m.raw_name
    WHERE r.npi IS NOT NULL
)
SELECT
    npi,
    year,
    SUM(amount)                                                          AS pay_total,
    COUNT(*)                                                             AS pay_count,
    COUNT(DISTINCT parent)                                               AS n_manufacturers,
    SUM(CASE WHEN parent IN ({{FOCUS_PARENTS}}) THEN amount ELSE 0 END)  AS pay_focus,
    SUM(CASE WHEN parent IN ({{COMP_PARENTS}})  THEN amount ELSE 0 END)  AS pay_competitor,
    SUM(CASE WHEN nature ILIKE '%Food%' THEN amount ELSE 0 END)          AS pay_food,
    SUM(CASE WHEN nature ILIKE '%Consulting%'
              OR nature ILIKE '%services other than consulting%'
             THEN amount ELSE 0 END)                                     AS pay_services
FROM mapped
GROUP BY npi, year;


-- Treatment definition for the response model: the year an NPI first appears
-- with any focus-brand payment. Prescribers already receiving payments in the
-- first observed year are excluded from the treated cohort downstream -- their
-- pre-period is contaminated and there is no clean baseline to difference from.
CREATE OR REPLACE TABLE mart_payment_onset AS
SELECT
    npi,
    MIN(CASE WHEN pay_focus > 0 THEN year END)  AS first_focus_pay_year,
    MIN(CASE WHEN pay_total > 0 THEN year END)  AS first_any_pay_year,
    SUM(pay_focus)                              AS lifetime_focus_pay
FROM mart_payments
GROUP BY npi;
