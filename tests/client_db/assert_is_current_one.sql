SELECT
client_id
FROM {{ref ('stg_client')}}
GROUP BY client_id
HAVING SUM(is_current) != 1