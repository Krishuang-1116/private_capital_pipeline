WITH raw AS (
    SELECT *
    FROM {{source ('fee_data', 'fee_invoice_raw')}}
), 
type_cast AS (
    SELECT * REPLACE(
        CAST(invoice_id AS VARCHAR) AS invoice_id,
        CAST(client_id AS VARCHAR) AS client_id,
        CAST(service_id AS VARCHAR) AS service_id,
        CAST(invoice_date AS DATE)  AS invoice_date,
        CAST(source_extract_timestamp AS TIMESTAMP) AS source_extract_timestamp, 
        CAST(billing_period_start AS DATE)  AS billing_period_start,
        CAST(billing_period_end AS DATE)  AS billing_period_end,
        CAST(fee_amount_eur AS DOUBLE) AS fee_amount_eur,
        CAST(fee_basis AS VARCHAR) AS fee_basis,
        CAST(is_paid AS BOOLEAN) AS is_paid
    )
    FROM raw
),
fee_line_type AS (
    SELECT *,
    CAST((CASE WHEN fee_amount_eur > 0 THEN 'invoice' ELSE 'credit_note' END) AS VARCHAR) AS fee_line_type
    FROM type_cast
),
billing_period AS (
    SELECT *,
    CAST(STRFTIME(billing_period_start, '%Y-%m') AS VARCHAR) AS billing_period_label 
    FROM fee_line_type
),
dedup AS (
    SELECT *,
    ROW_NUMBER()OVER(PARTITION BY invoice_id ORDER BY source_extract_timestamp DESC) AS rnk
    FROM billing_period
)
SELECT * EXCLUDE (rnk) FROM dedup WHERE rnk = 1