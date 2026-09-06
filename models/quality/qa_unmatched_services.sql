SELECT
a.invoice_id, a.service_id
FROM {{ref ('stg_fee_prededup')}} a 
LEFT JOIN {{ref ('dim_service')}} b 
ON a.service_id = b.service_id 
WHERE b.service_id IS NULL