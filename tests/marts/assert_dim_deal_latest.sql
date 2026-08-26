WITH unpivoted_dim_deal AS (
    {{ dbt_utils.unpivot(
        relation=ref('dim_deal'), cast_to='varchar',
        exclude=['deal_id','client_id','client_name','fund_name'],
        remove=['location','client_type','client_nature','deal_type','deal_qualification','fund_structuration','financial_sponsor',
        'fund_jurisdiction','owner','main_reason_for_loss','deal_status','asset','revenue','currency','expected_outcome_date',
        'real_estate','infrastructure','listed_assets_in_portfolio','OTC_instruments_in_portfolio','revenue_eur_equiv']
    ) }}
),
unpivoted_ground_truth AS (
    {{ dbt_utils.unpivot(
        relation=ref('int_latest_backfill_anchor'), cast_to='varchar',
        exclude=['deal_id','reporting_date','client_name','fund_name','first_enter_date'],
        remove=['location','client_type','client_nature','deal_type','deal_qualification','fund_structuration','financial_sponsor',
        'fund_jurisdiction','owner','main_reason_for_loss','deal_status','asset','revenue','currency','expected_outcome_date',
        'real_estate','infrastructure','lookup_pe','lookup_pd','lookup_re','lookup_infra','listed_assets_in_portfolio','OTC_instruments_in_portfolio','revenue_eur_equiv']
    ) }}
),
scoped_ground_truth AS (
    SELECT g.deal_id, g.field_name, g.value
    FROM unpivoted_ground_truth g
    INNER JOIN (
        SELECT DISTINCT deal_id, column_name
        FROM {{ ref('qa_strategy_service_changes') }}
    ) q
    ON g.deal_id = q.deal_id AND g.field_name = q.column_name
)

SELECT
    a.deal_id, a.field_name, a.value AS dim_deal_value, b.value AS latest_value
FROM unpivoted_dim_deal a
INNER JOIN scoped_ground_truth b
    ON a.deal_id = b.deal_id AND a.field_name = b.field_name
WHERE a.value IS DISTINCT FROM b.value
