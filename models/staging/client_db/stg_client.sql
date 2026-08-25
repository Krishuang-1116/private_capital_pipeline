WITH raw AS (
    SELECT *
    FROM {{ source('client_data', 'client_db_raw') }}
),
type_cast AS (
    SELECT
    raw.* REPLACE(
        CAST(client_key AS INTEGER) AS client_key,
        CAST(effective_from AS DATE) AS effective_from,
        CAST(effective_to AS DATE) AS effective_to,
        CAST(is_current AS BOOLEAN) AS is_current,
        CAST(sponsor_confirmed_date AS DATE) AS sponsor_confirmed_date
    )
    FROM raw
)
SELECT * FROM type_cast
