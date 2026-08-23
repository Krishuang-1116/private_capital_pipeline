WITH a AS (
SELECT 
DISTINCT deal_id
FROM {{ref('int_backfill_anchor')}} 
WHERE real_estate_equity = 'strategy_unresolvable' OR real_estate_debt = 'strategy_unresolvable' OR infrastructure_equity = 'strategy_unresolvable' OR infrastructure_debt = 'strategy_unresolvable'
)
SELECT 
a.*
FROM a
LEFT JOIN {{ref ('qa_unresolvable_strategy')}} b
ON a.deal_id = b.deal_id
WHERE b.deal_id IS NULL