SELECT 
a.deal_id, a.reporting_date, a.asset, a.revenue, a.revenue_eur_equiv,b.client_key
FROM {{ref ('int_pns_deals')}} a 
LEFT JOIN {{ref ('dim_client')}} b 
ON a.client_id = b.client_id AND (a.reporting_date >= b.effective_from OR b.effective_from IS NULL) AND (a.reporting_date < b.effective_to OR b.effective_to IS NULL)