SELECT 
group_id, group_name,
COUNT(client_id) AS client_count
FROM {{ref ('dim_client')}}
-- exactly one row per client_id has is_current = true
WHERE group_id IS NOT NULL AND is_current = True 
GROUP BY group_id, group_name