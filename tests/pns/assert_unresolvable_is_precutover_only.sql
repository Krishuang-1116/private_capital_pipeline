WITH a AS (
SELECT 
DISTINCT deal_id
FROM {{ref('int_backfill_anchor')}} 
WHERE real_estate_equity = 'strategy_unresolvable' OR real_estate_debt = 'strategy_unresolvable' OR infrastructure_equity = 'strategy_unresolvable' OR infrastructure_debt = 'strategy_unresolvable'
), 
-- post-cutover 
b AS (
    SELECT DISTINCT deal_id
    FROM {{ref ('int_backfill_anchor')}}
    WHERE first_enter_date >= DATE '2026-01-01'
)
SELECT 
a.deal_id 
FROM a 
LEFT JOIN b ON a.deal_id = b.deal_id
WHERE b.deal_id IS NOT NULL