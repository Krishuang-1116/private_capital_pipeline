WITH dedup AS (
    SELECT DISTINCT client_id, billing_period_start, billing_period_label FROM {{ref ('int_fee_invoice')}}
),
cohort AS (
    SELECT
    client_id,
    billing_period_start,
    billing_period_label,
    LEAD(billing_period_start)OVER(PARTITION BY client_id ORDER BY billing_period_start) AS next_billing_period
    FROM dedup
),
retain AS(
SELECT 
    client_id,
    billing_period_start,
    billing_period_label,
    next_billing_period,
CASE WHEN billing_period_start + INTERVAL '1 month' = next_billing_period THEN True 
     WHEN billing_period_start + INTERVAL '1 month' < next_billing_period THEN False
     END AS is_retained
FROM cohort
)
SELECT 
* EXCLUDE (next_billing_period) REPLACE(
    CASE WHEN is_retained IS NULL AND billing_period_start < (SELECT MAX(billing_period_start) FROM retain) THEN False
    ELSE is_retained END AS is_retained
) 
FROM retain
