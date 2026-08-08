-- 04_mart_hcp_metrics.sql
-- The analytical spine: one row per NPI per year, everything joined.
--
-- Note what is NOT here: no decile, no segment, no opportunity score. Those are
-- model outputs and they live in parquet written by src/models/. Keeping the
-- mart free of model output means the mart can be rebuilt without re-fitting,
-- and a model can be re-fit without rebuilding the mart.

CREATE OR REPLACE TABLE mart_hcp_metrics AS
WITH base AS (
    SELECT
        p.npi,
        p.year,
        p.last_name,
        p.first_name,
        p.city,
        p.state,
        p.zip3,
        p.specialty,
        p.specialty_group,
        p.all_drug_clms,
        p.panel_benes,
        p.risk_score,
        p.age65_cnt,
        p.pct_panel_65,

        COALESCE(i.class_fills_{{IMPUTE_MODE}}, 0)  AS class_fills,
        COALESCE(i.brand_fills_observed, 0)         AS brand_fills,
        COALESCE(i.class_drug_rows, 0)              AS class_drug_rows,
        COALESCE(i.suppressed_clms, 0)              AS suppressed_clms,

        -- Panel-size proxy with the therapeutic class REMOVED.
        -- all_drug_clms includes the class, so feeding it to the potential
        -- model would let the model read part of its own target off the input
        -- -- a high-volume DOAC writer has a high all-drug count *because* of
        -- the DOACs. Netting the class out keeps the feature a measure of
        -- practice size and nothing else. tests/test_opportunity.py asserts
        -- that no feature correlates with the target above the leak threshold.
        GREATEST(p.all_drug_clms - COALESCE(s.observed_class_clms, 0), 0) AS non_class_clms,

        u.lat,
        u.lon,
        u.region,
        -- Market size and density from the Census Gazetteer x CDC PLACES build
        -- (src/ingest/geo_build.py). CMS publishes no coordinates and no market
        -- covariates, so everything below the state field comes from there.
        u.population        AS zip3_population,
        u.pop_density       AS zip3_pop_density,
        -- Proxies for anticoagulant demand. PLACES carries no atrial
        -- fibrillation measure -- the actual DOAC indication -- so stroke, CHD
        -- and hypertension prevalence stand in. Stated as a proxy in the README.
        u.prev_stroke,
        u.prev_chd,
        u.prev_bp
    FROM stg_prescribers p
    LEFT JOIN stg_class_imputed i USING (npi, year)
    LEFT JOIN stg_suppression s USING (npi, year)
    -- ZIP3 is a STRING with meaningful leading zeros: '021' (Boston) becomes 21
    -- the moment anything reads it as numeric, and then joins to nothing.
    LEFT JOIN read_csv_auto('{{RAW}}/zip3_units.csv', header = true,
                            types = {'zip3': 'VARCHAR'}) u
           ON p.zip3 = LPAD(CAST(u.zip3 AS VARCHAR), 3, '0')
),
with_share AS (
    SELECT
        *,
        CASE WHEN class_fills > 0 THEN brand_fills / class_fills END AS brand_share
    FROM base
),
with_growth AS (
    SELECT
        *,
        LAG(class_fills) OVER w  AS class_fills_prior,
        LAG(brand_fills) OVER w  AS brand_fills_prior,
        LAG(brand_share) OVER w  AS brand_share_prior
    FROM with_share
    WINDOW w AS (PARTITION BY npi ORDER BY year)
)
SELECT
    *,
    -- Growth is expressed on a denominator floored at 1 fill. An unfloored
    -- ratio turns a 0 -> 3 fill move into infinite growth and lets a handful of
    -- microscopic prescribers dominate every growth ranking in the project.
    (class_fills - class_fills_prior) / NULLIF(GREATEST(class_fills_prior, 1.0), 0) AS class_growth_yoy,
    (brand_fills - brand_fills_prior) / NULLIF(GREATEST(brand_fills_prior, 1.0), 0) AS brand_growth_yoy,
    brand_share - brand_share_prior                                                 AS brand_share_delta,
    brand_fills - brand_fills_prior                                                 AS brand_fills_abs_growth
FROM with_growth;


-- Peer-group achievable share benchmark. The 75th percentile of brand share
-- within (specialty_group x region) is treated as what a prescriber in that
-- peer set can realistically reach. Groups thinner than 30 prescribers fall
-- back to the specialty-wide percentile so a sparse cell cannot manufacture an
-- extreme benchmark from four observations.
CREATE OR REPLACE TABLE mart_peer_benchmarks AS
WITH cell AS (
    SELECT
        specialty_group,
        region,
        year,
        COUNT(*)                                                       AS n_peers,
        QUANTILE_CONT(brand_share, {{ACHIEVABLE_PCT}})                 AS achievable_share_cell
    FROM mart_hcp_metrics
    WHERE brand_share IS NOT NULL AND class_fills > 0
    GROUP BY specialty_group, region, year
),
fallback AS (
    SELECT
        specialty_group,
        year,
        QUANTILE_CONT(brand_share, {{ACHIEVABLE_PCT}})                 AS achievable_share_spec
    FROM mart_hcp_metrics
    WHERE brand_share IS NOT NULL AND class_fills > 0
    GROUP BY specialty_group, year
)
SELECT
    c.specialty_group,
    c.region,
    c.year,
    c.n_peers,
    CASE WHEN c.n_peers >= 30 THEN c.achievable_share_cell
         ELSE f.achievable_share_spec END                              AS achievable_share,
    c.n_peers < 30                                                     AS used_fallback
FROM cell c
JOIN fallback f USING (specialty_group, year);
