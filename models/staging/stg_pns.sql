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
)
SELECT * FROM asset_revenue


