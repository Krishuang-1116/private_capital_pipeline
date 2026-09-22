{{config(materialized='incremental',incremental_strategy='merge',unique_key='invoice_id',on_schema_change='append_new_columns') }}
SELECT
*
FROM {{ref ('int_fee_invoice')}}
{% if is_incremental() %} WHERE source_extract_timestamp > (SELECT MAX(source_extract_timestamp) FROM {{ this }}) {% endif %}  