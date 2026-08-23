SELECT *
FROM {{ref ('stg_client')}}
WHERE is_current = true AND effective_to IS NOT NULL