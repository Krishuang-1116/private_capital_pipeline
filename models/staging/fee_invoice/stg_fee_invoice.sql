WITH ranked AS (
    SELECT *,
    ROW_NUMBER()OVER(PARTITION BY invoice_id ORDER BY source_extract_timestamp DESC) AS rnk
    FROM {{ref ('stg_fee_prededup')}}
)
SELECT * EXCLUDE (rnk) FROM ranked WHERE rnk = 1

