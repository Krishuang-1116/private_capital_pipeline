WITH current AS (
    SELECT *
    FROM {{ref ('stg_client')}}
    WHERE is_current = true
),
unpivoted AS (
    SELECT client_id, Alias_1 AS alias FROM current 
    UNION ALL 
    SELECT client_id, Alias_2 AS alias FROM current 
    UNION ALL 
    SELECT client_id, Alias_3 AS alias FROM current 
)
SELECT * FROM unpivoted WHERE alias IS NOT NULL