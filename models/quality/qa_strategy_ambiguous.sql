WITH unpivoted AS (
    {{ dbt_utils.unpivot(
    relation=ref('int_backfill_anchor'), cast_to='varchar', 
    exclude=['deal_id','reporting_date','client_name','fund_name','first_enter_date'],
    remove=['location', 'client_type','client_nature','deal_type','deal_qualification','fund_structuration','financial_sponsor',
    'fund_jurisdiction','owner','main_reason_for_loss','deal_status', 'asset', 'revenue', 'currency', 'expected_outcome_date','private_equity', 'private_debt','real_estate','infrastructure', 
    'lookup_pe','lookup_pd','lookup_re','lookup_infra','listed_assets_in_portfolio','OTC_instruments_in_portfolio','revenue_eur_equiv',
    'Depositary','Custody','Transfer_Agency','Fund_Administration','Corporate_Secretary','Middle_Office_Investor_Reporting',
    'Middle_Office_Portfolio_Monitoring','Middle_Office_Loan_Administration','Middle_Office_Collateral_Management','Other_MO_services','digital_reporting_platform','SFDR_eligibility']
    ) }}
),
change AS (
    SELECT 
    u.*,
    LAG(value) OVER(PARTITION BY deal_id, field_name ORDER BY reporting_date) AS previous_value
    FROM unpivoted u
    WHERE first_enter_date < DATE '2026-01-01' AND reporting_date > DATE '2026-01-01'
)
SELECT 
    deal_id, client_name, fund_name, field_name AS column_name, 
    previous_value, 
    value AS new_value,
    reporting_date AS change_reporting_date,
    'sub-strategy change on pre-cutover deal; cannot distinguish backfill correction from genuine strategy update' AS ambiguity_reason
FROM change
WHERE value != previous_value
