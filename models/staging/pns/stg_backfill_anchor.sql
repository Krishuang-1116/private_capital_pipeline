    SELECT *
    FROM {{ref ('stg_pns')}}
    WHERE reporting_date = DATE '2025-12-31'
