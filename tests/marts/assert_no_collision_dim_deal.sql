SELECT
a.deal_id, a.client_name, a.client_id
FROM {{ref ('dim_deal')}} a
LEFT JOIN {{ref ('qa_alias_collision')}} b 
ON a.deal_id = b.deal_id AND a.client_id != 'CLIENT-000'
WHERE b.deal_id IS NOT NULL
