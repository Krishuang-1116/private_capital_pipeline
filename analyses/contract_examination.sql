-- fact_deal_snapshot
-- DESCRIBE 'fact_deal_snapshot' won't work

SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_name IN ('fact_deal_snapshot', 'mart_fee_revenue')

-- SELECT c.table_name, c.column_name, c.data_type
-- FROM information_schema.columns c
-- JOIN information_schema.tables t
--   ON c.table_name = t.table_name AND c.table_schema = t.table_schema
-- WHERE t.table_schema = 'dbt_pc_pipeline'
--   AND t.table_type = 'BASE TABLE'
-- ORDER BY c.table_name, c.ordinal_position

-- SELECT *
-- FROM information_schema.tables
-- WHERE table_type = 'BASE TABLE'