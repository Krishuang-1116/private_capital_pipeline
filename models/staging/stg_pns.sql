WITH raw AS (
    SELECT *
    FROM {{ source('deal_data', 'pns_raw') }}
), 

fund_correct AS (
    SELECT 
    r.* REPLACE(COALESCE(f.canonical_fund_name,r.fund_name) AS fund_name)
    FROM raw r 
    LEFT JOIN  {{ref('fund_name_corrections')}} f 
    ON r.client_name = f.client_name AND r.fund_name = f.dirty_fund_name
),

fund_with_ID AS (
    SELECT 
    {{dbt_utils.generate_surrogate_key(['location','client_name','fund_name'])}} AS deal_id,
    f.*
    FROM fund_correct f 
),

pre_dedup AS (
    SELECT 
    *,
    ROW_NUMBER()OVER(PARTITION BY deal_id, reporting_date) AS rnk 
    FROM fund_with_ID
),
dedup AS (
    SELECT 
    pre_dedup.* EXCLUDE(rnk) 
    FROM pre_dedup 
    WHERE rnk = 1
),
asset_revenue AS (
    SELECT
    d.* REPLACE(
        CAST(REGEXP_EXTRACT(asset, '[0-9.]+') AS DOUBLE) AS asset
        ),
    TRY_CAST(CASE WHEN currency = 'EUR' THEN revenue ELSE NULL END AS DOUBLE) AS revenue_eur_equiv,
    FROM dedup d
),
type_cast AS (
    SELECT 
    a.* REPLACE (
        CAST(reporting_date AS DATE) AS reporting_date,
        CAST(expected_outcome_date AS DATE) AS expected_outcome_date
    )
    FROM asset_revenue a
),
name_normalization AS (
    SELECT
    t.* REPLACE(
    -- service column: no era restriction, safe to resolve null -> No
    (CASE WHEN Transfer_Agency IN ('FATCA', 'B7765') THEN 'Yes'
        WHEN Transfer_Agency IS NULL THEN 'No'
        ELSE Transfer_Agency END) AS Transfer_Agency,

    -- era-restricted (new column at cutover): fix rogue value + casing only, leave null as null
    (CASE WHEN listed_assets_in_portfolio LIKE 'Yes%' THEN 'Yes'
        WHEN LOWER(TRIM(listed_assets_in_portfolio)) = 'tbd' THEN 'TBD'
        ELSE listed_assets_in_portfolio END) AS listed_assets_in_portfolio,

    -- era-restricted (new column at cutover): casing only
    (CASE WHEN LOWER(TRIM(OTC_instruments_in_portfolio)) = 'tbd' THEN 'TBD'
        ELSE OTC_instruments_in_portfolio END) AS OTC_instruments_in_portfolio,

    -- carries over both eras, 0-1% null: safe to resolve null -> No
    (CASE WHEN LOWER(TRIM(private_equity)) = 'tbd' THEN 'TBD'
        WHEN private_equity IS NULL THEN 'No'
        ELSE private_equity END) AS private_equity,

    (CASE WHEN LOWER(TRIM(private_debt)) = 'tbd' THEN 'TBD'
        WHEN private_debt IS NULL THEN 'No'
        ELSE private_debt END) AS private_debt,

    -- era-restricted (pre-cutover only): casing only, leave null as null
    (CASE WHEN LOWER(TRIM(real_estate)) = 'tbd' THEN 'TBD'
        ELSE real_estate END) AS real_estate,

    (CASE WHEN LOWER(TRIM(infrastructure)) = 'tbd' THEN 'TBD'
        ELSE infrastructure END) AS infrastructure,

    -- era-restricted (post-cutover only, Defect 3 backfill target): casing only,
    -- null->No resolution for genuinely-post-cutover-native deals belongs in
    -- int_backfill_anchor.sql, which already handles it era-aware
    (CASE WHEN LOWER(TRIM(real_estate_equity)) = 'tbd' THEN 'TBD'
        ELSE real_estate_equity END) AS real_estate_equity,

    (CASE WHEN LOWER(TRIM(real_estate_debt)) = 'tbd' THEN 'TBD'
        ELSE real_estate_debt END) AS real_estate_debt,

    (CASE WHEN LOWER(TRIM(infrastructure_equity)) = 'tbd' THEN 'TBD'
        ELSE infrastructure_equity END) AS infrastructure_equity,

    (CASE WHEN LOWER(TRIM(infrastructure_debt)) = 'tbd' THEN 'TBD'
        ELSE infrastructure_debt END) AS infrastructure_debt
    )
    FROM type_cast t
)
SELECT * FROM name_normalization


