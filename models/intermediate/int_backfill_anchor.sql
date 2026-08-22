WITH enter_date AS (
    SELECT *,
    MIN(reporting_date)OVER(PARTITION BY deal_id ) AS first_enter_date
    FROM {{ref ('stg_pns')}} 
),

full_map AS (
    SELECT 
    e.*,
    b.private_equity AS lookup_pe,
    b.private_debt AS lookup_pd,
    b.real_estate AS lookup_re,
    b.infrastructure AS lookup_infra
    FROM enter_date e 
    LEFT JOIN {{ref ('stg_backfill_anchor')}} b 
    ON e.deal_id = b.deal_id 
),
backfill AS (
    SELECT
    full_map.* REPLACE(
    (CASE WHEN reporting_date < DATE '2026-01-01' THEN real_estate_equity 
         WHEN first_enter_date >= DATE '2026-01-01' THEN real_estate_equity
         WHEN lookup_pe = 'Yes' AND lookup_re = 'Yes' THEN 'Yes'
         WHEN lookup_pe = 'No' AND lookup_pd = 'No' AND lookup_re = 'Yes' THEN 'strategy_unresolvable' -- resort to qa 
         ELSE 'No' END) AS real_estate_equity,
    (CASE WHEN reporting_date < DATE '2026-01-01' THEN real_estate_debt 
         WHEN first_enter_date >= DATE '2026-01-01' THEN real_estate_debt
         WHEN lookup_pd = 'Yes' AND lookup_re = 'Yes' THEN 'Yes'
         WHEN lookup_pe = 'No' AND lookup_pd = 'No' AND lookup_re = 'Yes' THEN 'strategy_unresolvable' -- resort to qa 
         ELSE 'No' END) AS real_estate_debt,
    (CASE WHEN reporting_date < DATE '2026-01-01' THEN infrastructure_equity 
         WHEN first_enter_date >= DATE '2026-01-01' THEN infrastructure_equity
         WHEN lookup_pe = 'Yes' AND lookup_infra = 'Yes' THEN 'Yes'
         WHEN lookup_pe = 'No' AND lookup_pd = 'No' AND lookup_infra = 'Yes' THEN 'strategy_unresolvable' -- resort to qa 
         ELSE 'No' END) AS infrastructure_equity,
    (CASE WHEN reporting_date < DATE '2026-01-01' THEN infrastructure_debt 
         WHEN first_enter_date >= DATE '2026-01-01' THEN infrastructure_debt
         WHEN lookup_pd = 'Yes' AND lookup_infra = 'Yes' THEN 'Yes'
         WHEN lookup_pe = 'No' AND lookup_pd = 'No' AND lookup_infra = 'Yes' THEN 'strategy_unresolvable' -- resort to qa 
         ELSE 'No' END) AS infrastructure_debt  
    ) 
    FROM full_map
)

SELECT * FROM backfill
