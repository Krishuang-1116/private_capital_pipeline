SELECT 
deal_id, client_name, fund_name, private_equity, private_debt, real_estate, infrastructure
FROM {{ref ('stg_backfill_anchor')}}
WHERE (real_estate = 'Yes' OR infrastructure = 'Yes') AND (private_equity = 'No' AND private_debt = 'No' )