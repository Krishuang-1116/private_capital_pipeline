 {{ config(severity='warn') }}

SELECT 
    a.*, b.client_type
FROM {{ref ('int_latest_client_type_pns')}} a 
LEFT JOIN {{ref ('dim_client')}} b 
ON a.client_id = b.client_id AND b.is_current = true
WHERE a.client_type IS DISTINCT FROM b.client_type