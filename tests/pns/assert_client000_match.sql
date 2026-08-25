WITH a AS (
    SELECT COUNT(DISTINCT deal_id) AS a_count
FROM {{ref('int_pns_deals')}} 
WHERE client_id = 'CLIENT-000'
),
b AS (
    SELECT COUNT(client_name) AS b_count
    FROM {{ref ('qa_unmatched_clients')}}
),
c AS (
    SELECT COUNT(client_name) AS c_count
    FROM {{ref ('qa_alias_collision')}}
)

SELECT * 
FROM a
CROSS JOIN b 
CROSS JOIN c
WHERE a_count != b_count + c_count
