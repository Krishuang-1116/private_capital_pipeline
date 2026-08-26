WITH dedup AS (
    SELECT 
    *,
    ROW_NUMBER()OVER(PARTITION BY deal_id ORDER BY reporting_date DESC) AS rnk
FROM {{ref ('int_backfill_anchor')}}
)
SELECT * EXCLUDE(rnk) FROM dedup WHERE rnk = 1

