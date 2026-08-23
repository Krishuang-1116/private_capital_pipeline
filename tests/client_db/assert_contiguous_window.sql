WITH rnk AS (
    SELECT *,
    ROW_NUMBER()OVER(PARTITION BY client_id ORDER BY effective_from) AS rnk
FROM {{ref ('stg_client')}} 
)

SELECT * 
FROM rnk a
LEFT JOIN rnk b
ON a.client_id = b.client_id AND a.rnk = b.rnk  + 1 
WHERE a.effective_from != b.effective_to

