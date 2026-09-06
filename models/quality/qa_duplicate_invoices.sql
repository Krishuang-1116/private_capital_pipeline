SELECT 
invoice_id, COUNT(*) AS occurrence_count
FROM {{ref ('stg_fee_prededup')}}
GROUP BY invoice_id
HAVING COUNT(*) > 1