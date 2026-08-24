SELECT 
DISTINCT a.deal_id, a.client_name, a.fund_name
FROM {{ref ('stg_pns')}} a 
LEFT JOIN {{ref('client_aliases')}} b 
ON a.client_name = b.alias 
WHERE b.client_id IS NULL