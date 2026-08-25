WITH dedup AS (
    SELECT *,
    ROW_NUMBER()OVER(PARTITION BY deal_id ORDER BY reporting_date DESC) AS rnk
    FROM {{ref ('stg_pns')}}
)
SELECT 
    deal_id, client_name,fund_name,deal_status, reporting_date,revenue,asset, 
    (CASE WHEN revenue IS NULL AND asset IS NULL THEN 'both'
         WHEN revenue IS NULL AND asset IS NOT NULL THEN 'revenue'
         WHEN revenue IS NOT NULL AND asset IS NULL THEN 'asset'
    END) AS missing_fields
FROM dedup
WHERE rnk = 1 AND deal_status IN ('Won', 'Rejected','Lost') AND (revenue IS NULL OR asset IS NULL)