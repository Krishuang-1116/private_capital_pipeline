SELECT 
a.*,
b.service_name,
b.pns_column_name
FROM {{ref ('stg_fee_invoice')}}  a 
INNER JOIN  {{ref ('dim_service')}} b 
ON a.service_id = b.service_id
