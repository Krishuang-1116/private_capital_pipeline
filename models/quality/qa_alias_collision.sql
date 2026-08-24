SELECT 
DISTINCT a.deal_id AS deal_id, a.client_name AS client_name, a.fund_name AS fund_name,
string_agg(DISTINCT b.client_id) AS matched_client_ids, 
COUNT(DISTINCT b.client_id) AS match_count
FROM {{ref ('stg_pns')}} a 
LEFT JOIN {{ref ('client_aliases')}} b 
ON a.client_name = b.alias 
GROUP BY a.deal_id, a.client_name, a.fund_name
HAVING COUNT(DISTINCT b.client_id) > 1