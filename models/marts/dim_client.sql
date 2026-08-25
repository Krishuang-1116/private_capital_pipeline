SELECT 
    a.* EXCLUDE (Alias_1, Alias_2, Alias_3)
FROM {{ref ('stg_client')}} a
UNION ALL 
SELECT 
     CAST(-1 AS INTEGER) AS client_key,  
    'CLIENT-000'  AS client_id, 
    CAST(NULL AS VARCHAR) AS official_name,
    CAST(NULL AS VARCHAR) AS client_type,
    CAST(NULL AS VARCHAR) AS group_id,
    CAST(NULL AS VARCHAR) AS group_name,
    CAST(NULL AS VARCHAR) AS hq_country,
    CAST(NULL AS VARCHAR) AS aum_description,
    CAST(NULL AS VARCHAR) AS top_priority,
    CAST(NULL AS VARCHAR) AS client_nature,
    CAST(NULL AS DATE) AS effective_from,
    CAST(NULL AS DATE) AS effective_to,
    CAST(TRUE AS BOOLEAN) AS is_current,
    CAST(NULL AS VARCHAR) AS financial_sponsor,
    CAST(NULL AS VARCHAR) AS sponsor_evidence,
    CAST(NULL AS VARCHAR) AS sponsor_confirmed_by,
    CAST(NULL AS DATE) AS sponsor_confirmed_date
