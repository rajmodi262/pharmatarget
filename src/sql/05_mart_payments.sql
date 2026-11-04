-- 05_mart_payments.sql
-- Source: D3, Open Payments general payments.
--
-- Manufacturer names are normalised through config/manufacturers.yaml rather
-- than fuzzy-matched. Fuzzy matching here is how a competitor's speaker-program
-- spend gets attributed to your own brand, which would invert the sign of the
-- entire response analysis.
--
-- PRODUCT, NOT JUST COMPANY. A manufacturer filter alone is not a brand filter:
-- Pfizer logs ~870k food-and-beverage events a year across vaccines, oncology
-- and everything else, and Janssen's include immunology and psychiatry. Counting
-- those as "Eliquis promotion" would make a vaccine lunch a DOAC detail. Each
-- payment is therefore attributed to a PRODUCT from the five product-name fields
-- Open Payments carries, and only product-attributed events count as focus or
-- competitor promotion.
--
-- The NPI match rate is MEASURED and written to the manifest. Never quote a
-- match rate you have not computed on your own extract.

CREATE OR REPLACE TABLE stg_payments_raw AS
SELECT
    TRY_CAST(Covered_Recipient_NPI AS BIGINT)                                   AS npi,
    CAST(Program_Year AS INTEGER)                                               AS year,
    TRIM(Applicable_Manufacturer_or_Applicable_GPO_Making_Payment_Name)         AS manufacturer_raw,
    TRIM(Nature_of_Payment_or_Transfer_of_Value)                                AS nature,
    CAST(Total_Amount_of_Payment_USDollars AS DOUBLE)                           AS amount,
    UPPER(CONCAT_WS(' | ',
        Name_of_Drug_or_Biological_or_Device_or_Medical_Supply_1,
        Name_of_Drug_or_Biological_or_Device_or_Medical_Supply_2,
        Name_of_Drug_or_Biological_or_Device_or_Medical_Supply_3,
        Name_of_Drug_or_Biological_or_Device_or_Medical_Supply_4,
        Name_of_Drug_or_Biological_or_Device_or_Medical_Supply_5))              AS products
FROM read_csv_auto(
    '{{RAW}}/open_payments_*.csv',
    union_by_name = true,
    header = true,
    ignore_errors = true,
    all_varchar = true
)
-- Prescribers only: physicians AND non-physician practitioners. NPs and PAs
-- write roughly a fifth of DOAC volume in Part D and are detailed like anyone
-- else; an earlier physician-only filter dropped every one of their payments.
-- Teaching-hospital rows carry no usable NPI and are excluded.
WHERE Covered_Recipient_Type IN ('Covered Recipient Physician',
                                 'Covered Recipient Non-Physician Practitioner');


CREATE OR REPLACE TABLE mart_payments AS
WITH mapped AS (
    SELECT
        r.npi,
        r.year,
        r.amount,
        r.nature,
        COALESCE(m.parent, 'UNMAPPED')                         AS parent,
        m.parent IS NULL                                       AS is_unmapped,
        regexp_matches(COALESCE(r.products, ''), '{{FOCUS_PRODUCT_RE}}') AS is_focus_product,
        regexp_matches(COALESCE(r.products, ''), '{{COMP_PRODUCT_RE}}')  AS is_comp_product,
        r.nature ILIKE '%Food%'                                AS is_food
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
    -- Brand-attributed spend. pay_focus is Eliquis-named payments only.
    SUM(CASE WHEN is_focus_product THEN amount ELSE 0 END)               AS pay_focus,
    SUM(CASE WHEN is_comp_product  THEN amount ELSE 0 END)               AS pay_competitor,
    -- Company-level spend, kept for transparency: the gap between this and
    -- pay_focus is the non-DOAC promotion a company filter would have counted.
    SUM(CASE WHEN parent IN ({{FOCUS_PARENTS}}) THEN amount ELSE 0 END)  AS pay_focus_company,
    SUM(CASE WHEN is_food THEN amount ELSE 0 END)                        AS pay_food,

    -- COUNT of food-and-beverage transactions, not just their value.
    --
    -- This is the closest public proxy to a rep call that exists. A
    -- food-and-beverage transfer is logged when a representative buys a meal
    -- during a detailing visit, so the COUNT of those events approximates the
    -- number of promotional touchpoints a prescriber received in a year.
    -- Dollars are the wrong unit: a $12 sandwich and a $12 coffee are two
    -- visits, while one $2,400 consulting fee is not a visit at all.
    --
    -- pay_food_count_focus is the one the call-response fit uses: food events
    -- that NAME the focus brand. Competitor-named visits are counted
    -- separately because they push share the other way.
    COUNT(*) FILTER (WHERE is_food)                                      AS pay_food_count,
    COUNT(*) FILTER (WHERE is_food AND is_focus_product)                 AS pay_food_count_focus,
    COUNT(*) FILTER (WHERE is_food AND is_comp_product)                  AS pay_food_count_comp,
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
