WITH dedup AS (
    SELECT 
    a.* EXCLUDE (real_estate_equity, real_estate_debt, infrastructure_equity, infrastructure_debt,
    listed_assets_in_portfolio, OTC_instruments_in_portfolio, Depositary, Custody,
    Transfer_Agency, Fund_Administration, Corporate_Secretary,
    Middle_Office_Investor_Reporting, Middle_Office_Portfolio_Monitoring,
    Middle_Office_Loan_Administration, Middle_Office_Collateral_Management,
    Other_MO_services, digital_reporting_platform, SFDR_eligibility,
    asset, revenue, currency, revenue_eur_equiv),
    b.* EXCLUDE(deal_id, reporting_date, location, client_name, fund_name, client_type,
    client_nature, deal_type, deal_qualification, deal_status, fund_structuration,
    financial_sponsor, fund_jurisdiction, owner, expected_outcome_date,
    main_reason_for_loss, private_equity, private_debt, real_estate, infrastructure,
    first_enter_date, lookup_pe, lookup_pd, lookup_re, lookup_infra),
    ROW_NUMBER()OVER(PARTITION BY a.deal_id ORDER BY a.reporting_date DESC) AS rnk 
FROM {{ref ('int_pns_deals')}} a 
LEFT JOIN {{ref ('int_backfill_anchor')}} b 
ON a.deal_id = b.deal_id AND a.reporting_date = b.reporting_date
) 
SELECT * EXCLUDE(reporting_date, rnk) FROM dedup WHERE rnk = 1