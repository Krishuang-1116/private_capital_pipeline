WITH unpivoted AS (
    {{ dbt_utils.unpivot(
    relation=ref('int_backfill_anchor'), cast_to='varchar', 
    exclude=['deal_id','reporting_date','client_name','fund_name','first_enter_date'],
    remove=['location', 'client_type','client_nature','deal_type','deal_qualification','fund_structuration','financial_sponsor',
    'fund_jurisdiction','owner','main_reason_for_loss','deal_status', 'asset', 'revenue', 'currency', 'expected_outcome_date','real_estate','infrastructure', 
    'lookup_pe','lookup_pd','lookup_re','lookup_infra','listed_assets_in_portfolio','OTC_instruments_in_portfolio','revenue_eur_equiv']
    ) }}
),
change AS (
    SELECT 
    u.*,
    LAG(value) OVER(PARTITION BY deal_id, field_name ORDER BY reporting_date) AS previous_value
    FROM unpivoted u
)
SELECT 
    deal_id, client_name, fund_name, field_name AS column_name, 
    previous_value, 
    value AS new_value,
    reporting_date AS change_reporting_date
FROM change
WHERE value != previous_value
