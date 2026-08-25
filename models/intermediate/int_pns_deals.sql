WITH pre_sentinel AS (
    SELECT a.*,
    b.client_id,
    COUNT(DISTINCT b.client_id)OVER(PARTITION BY deal_id, reporting_date) AS count
FROM {{ref ('stg_pns')}} a 
LEFT JOIN {{ref ('client_aliases')}} b 
ON a.client_name = b.alias 
)
SELECT 
DISTINCT p.* EXCLUDE (count) REPLACE (
(CASE WHEN count = 1 AND client_id IS NOT NULL THEN client_id
        WHEN count > 1 OR client_id IS NULL THEN 'CLIENT-000' 
    END) AS client_id
) 
FROM pre_sentinel p 


