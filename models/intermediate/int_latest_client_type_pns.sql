WITH latest AS (
    SELECT
    client_id, client_type,reporting_date,
    MAX(reporting_date)OVER(PARTITION BY client_id) AS latest_date
FROM {{ref ('int_pns_deals')}} 
)
SELECT  
latest.client_id, MAX(latest.client_type) AS client_type
FROM latest 
WHERE reporting_date = latest_date AND latest.client_id != 'CLIENT-000'
GROUP BY latest.client_id


-- Alternative approach (two-CTE, MAX(reporting_date) + INNER JOIN back)
-- Equivalent result, kept for reference — see docs/intermediate_models.md
-- WITH max_date AS (
--     SELECT 
--     client_id, 
--     MAX(reporting_date) AS latest_date
--     FROM {{ref ('int_pns_deals')}}
--     GROUP BY client_id
-- ),
-- join_back AS (
--     SELECT 
--     a.client_id, MAX(client_type) AS client_type
--     FROM {{ref ('int_pns_deals')}} a
--     INNER JOIN max_date m 
--     ON a.client_id = m.client_id 
--     WHERE a.reporting_date = m.latest_date AND a.client_id != 'CLIENT-000' 
--     GROUP BY a.client_id
-- )

-- SELECT * FROM join_back