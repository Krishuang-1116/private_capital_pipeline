SELECT 
    a.deal_id,
    COUNT(b.client_id)
FROM {{ref ('dim_deal')}} a 
LEFT JOIN {{ref ('dim_client')}} b 
ON a.client_id = b.client_id AND b.is_current = true
GROUP BY a.deal_id
HAVING COUNT(b.client_id) != 1
