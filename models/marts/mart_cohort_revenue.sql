SELECT 
*,
MIN(billing_period_start) OVER (PARTITION BY client_id) AS onboarding_period,
DATE_DIFF('month', onboarding_period, billing_period_start) AS periods_since_onboarding,
(EXTRACT(year FROM onboarding_period) || '-Q' || EXTRACT(quarter FROM onboarding_period)) AS cohort_quarter
FROM {{ref ('int_fee_invoice')}}