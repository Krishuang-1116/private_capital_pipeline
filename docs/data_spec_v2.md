# pc_pipeline — Synthetic Data Spec v2

**Status:** Active — September 2026
**Prerequisite:** v1 spec (`docs/pc_pipeline_synthetic_data_spec.md`) frozen and complete.
This document covers only the four v2 items activated for the September 2026 build.
All other §5 deferrals in the v1 spec remain frozen and are not referenced here.

---

## 0. Activated v2 Items

| Item | What it demonstrates | Lands in |
|---|---|---|
| `status_change_date` column in pns_raw | Pipeline-to-revenue lag; time-to-won analytics | pns_raw generator + stg_pns |
| `source_extract_timestamp` + late-arriving rows in fee_invoice_raw | Incremental model with correct idempotency; Stripe webhook problem class | fee_invoice generator + stg_fee_invoice + mart_fee_revenue |
| `fee_invoice_raw` as third source | Galaxy schema with two fact tables; MRR/churn/cohort modeling; drill-across through conformed dim_service | New source, full dbt layer |
| `dim_group` with group-level metrics | Revenue concentration by group; drill-down from group → client in MetricFlow | dim_group mart + sem_fee_revenue |

---

## 1. pns_raw Addition — `status_change_date`

### Column Spec

| Column | Type | Null % | Notes |
|---|---|---|---|
| `status_change_date` | date | ~60% | Populated only when `deal_status` is a terminal value: Won / Lost / Rejected. Null for all non-terminal deals. |

### Generator Rules

- Assign `status_change_date` within the reporting window (Aug 2025 – Aug 2026) for
  all terminal deals.
- `status_change_date` must be less than or equal to the `reporting_date` of the
  first snapshot where the terminal status appears — a deal cannot be recorded as
  Won before its status_change_date.
- Distribution: spread plausibly across the reporting window; avoid clustering all
  Won deals at the same date.
- Non-terminal deals (`deal_status` IN ('Under analysis', 'Fee proposal sent',
  'Submitted RFP', 'Upcoming RFP', 'TBD')): `status_change_date` = null by design.
  This is not a defect — the conditional not_null test in staging scopes to terminal
  deals only, same pattern as `main_reason_for_loss`.

### Staging Handler

Add a conditional not_null test in `stg_pns` schema.yml:
assert `status_change_date` IS NOT NULL where `deal_status` IN ('Won', 'Lost',
'Rejected').

### Why This Column Exists

`status_change_date` on Won deals + first `invoice_date` in fee_invoice_raw =
measurable pipeline-to-revenue lag. This is the private capital analogue of
trial-to-paid conversion time in SaaS. Without this column, the lag is
uncomputable from the data.

---

## 2. Source 3 — fee_invoice_raw

### 2.1 Framing

Source framing in `sources.yml`:
`fee_invoice_raw` → "Billing system extract — invoice lines for Won deals"

Only Won deals generate invoices. Every `client_id` in fee_invoice_raw has at
least one deal with `deal_status = 'Won'` in pns_raw. This constraint is enforced
by the generator reading `pns_raw_manifest.json` to identify the Won deal
population before generating invoices.

Known Won deal population from v1 data: 35 Won deals across 20 unique clients.
These 20 clients are the invoice-generating population.

### 2.2 Grain

`(invoice_id)` — one row per invoice line. One billing event for one client, one
service, one billing period. `invoice_id` is system-assigned and always populated.

Note: a client can receive multiple invoices for the same service in the same
month (e.g. a regular management fee invoice and a prior-period credit note).
`(client_id, service_id, invoice_date)` is therefore NOT unique and must not be
treated as the grain key. `invoice_id` is the only safe unique identifier.

### 2.3 Column Spec

#### Identity / Grain Columns

| Column | Type | Null % | Notes |
|---|---|---|---|
| `invoice_id` | text | 0% | Format: `INV-YYYYMM-NNNN` (e.g. `INV-202601-0001`). System-assigned, globally unique. Natural key — no surrogate needed. |
| `client_id` | text | 0% | FK to `client_db_raw`. Always a Won-deal client. |
| `service_id` | text | 0% | FK to `dim_service` seed. Format: `SVC-DEP`, `SVC-CUS`, `SVC-TA`, `SVC-FA`, `SVC-MO`. ~3% of rows carry an unrecognized code (Defect D). |
| `invoice_date` | date | 0% | Date the invoice was issued. Not the billing period start. |
| `source_extract_timestamp` | timestamp | 0% | When this row entered the extract. ~5% of rows have a timestamp > 45 days after `invoice_date` — late-arriving rows (Defect C). |

#### Billing Period Columns

| Column | Type | Null % | Notes |
|---|---|---|---|
| `billing_period_start` | date | 0% | First day of the period being billed. |
| `billing_period_end` | date | 0% | Last day of the period being billed. `billing_period_end >= billing_period_start` enforced by generator. |

Note: `billing_period_label` (e.g. `2026-01`) is NOT present in the raw source.
It is derived in staging from `billing_period_start` using date formatting functions
— not CASE WHEN logic. Staging re-derives it cleanly rather than trusting a
pre-computed source column.

#### Financial Columns

| Column | Type | Null % | Notes |
|---|---|---|---|
| `fee_amount_eur` | numeric | 0% | Signed. Positive = invoice. Negative = credit note. Never zero. |
| `fee_basis` | text | 0% | Fee calculation basis: `AUM` / `commitment` / `flat` / `NAV`. Dimension property of the invoice — non-summarizable. Do not SUM. |
| `is_paid` | boolean | 0% | Whether the invoice has been settled. Enables cash-flow analytics: unpaid invoices = revenue recognized but not yet collected. |

Note: `fee_line_type` (`invoice` / `credit_note`) is NOT present in the raw
source. It is derived in staging via `CASE WHEN fee_amount_eur > 0 THEN 'invoice'
ELSE 'credit_note' END`. This is the Defect E handler — it lives in staging, not
in the generator.

### 2.4 Defect Classes

| Defect | Class | Injection | Handler |
|---|---|---|---|
| A — Duplicate rows | Extract re-run | ~3% of rows are byte-identical duplicates of an existing `invoice_id` | Dedup in staging on `invoice_id` via `ROW_NUMBER() OVER (PARTITION BY invoice_id ORDER BY source_extract_timestamp DESC) = 1`. `qa_duplicate_invoices` surfaces count and `invoice_id` list. |
| C — Late-arriving rows | Incremental timing | ~5% of rows have `source_extract_timestamp` > 45 days after `invoice_date` | Incremental model keys off `source_extract_timestamp`, not `invoice_date`. A date-based filter would silently drop these rows. |
| D — Unrecognized service_id | Broken conformed dimension | ~3% of rows carry a `service_id` not present in `dim_service` (e.g. `SVC-OTC`) | `qa_unmatched_services` surfaces unmatched rows. Excluded from mart aggregations. No sentinel row for services — an unrecognized service cannot be safely attributed to any known category. |
| E — Credit notes | Business-event ambiguity | ~8% of rows are credit notes (`fee_amount_eur < 0`) | `fee_line_type` derived in staging. MRR mart exposes both `gross_fee_revenue` (invoices only) and `net_fee_revenue` (invoices + credit notes). Both exposed as separate MetricFlow metrics. |

### 2.5 Generator Rules

- Read `pns_raw_manifest.json` to identify the 20 Won-deal clients before
  generating any invoice rows.
- Billing period coverage: generate invoices starting from the month after each
  client's earliest Won deal `status_change_date` through August 2026.
- Volume: approximately 80–100 rows before defect injection (~4–5 invoices per
  client across services and periods). After Defect A injection: ~85–105 rows.
- Not every client is billed for every service every month — vary coverage
  realistically. A client with Depositary = Yes in pns_raw should have SVC-DEP
  invoices; a client with Transfer_Agency = No should not have SVC-TA invoices.
  The generator uses the Won deal's service columns from pns_raw to determine
  which service_ids to generate invoices for.
- Defect C injection: select ~5% of rows after generation and shift their
  `source_extract_timestamp` forward by 46–90 days while leaving `invoice_date`
  unchanged.
- Defect A injection: duplicate ~3% of rows exactly (same `invoice_id`, same all
  columns including `source_extract_timestamp`).
- Defect D injection: replace `service_id` on ~3% of rows with `SVC-OTC`
  (not present in dim_service).

### 2.6 dbt Layer Placement

```
fee_invoice_raw
    → stg_fee_invoice           type casts, fee_line_type derivation,
                                 billing_period_label derivation,
                                 dedup on invoice_id (Defect A handler)

        → qa_duplicate_invoices  surfaces Defect A: invoice_ids that
                                 appeared more than once before dedup

        → qa_unmatched_services  surfaces Defect D: rows where service_id
                                 has no match in dim_service

        → int_fee_invoice        joins stg_fee_invoice to dim_service,
                                 excludes unmatched service_id rows,
                                 stamps dim_service attributes onto invoice rows

            → mart_fee_revenue   incremental model; MRR aggregation:
                                 gross + net by client, service, period

            → mart_client_retention  which clients appear in period N and N+1

            → mart_cohort_revenue    fee revenue by client onboarding cohort
                                     across periods since first invoice
```

### 2.7 README Framing

"fee_invoice_raw is a billing system extract at invoice-line grain. Only Won deals
generate invoices, making pipeline-to-revenue conversion measurable across the two
fact tables through the shared client dimension."

"Duplicate invoice rows from extract re-runs are deduplicated in staging and
surfaced by qa_duplicate_invoices. Late-arriving invoices — rows whose extract
timestamp significantly post-dates their invoice date — are handled correctly by
the incremental model's timestamp-based filter rather than a date-based filter,
which would silently drop them."

"Unrecognized service codes are surfaced by qa_unmatched_services and excluded
from mart aggregations. dim_service is the conformed dimension enabling
drill-across between the deal pipeline and fee revenue fact tables — without it,
the two sources cannot be compared on the service axis."

"Fee revenue is exposed as both gross (invoices only) and net (invoices plus
credit notes) to avoid the aggregation ambiguity that arises when credit notes
are summed alongside invoices without distinguishing them."

---

## 3. dim_service Seed

### Purpose

Conformed dimension linking the billing system's service codes to the CRM's
service column names. Both fact tables join through dim_service — pns_raw through
`pns_column_name` after unpivoting its Yes/No service columns; fee_invoice through
`service_id` directly.

### Structure

| Column | Type | Notes |
|---|---|---|
| `service_id` | text | PK. Format: `SVC-DEP`, `SVC-CUS`, `SVC-TA`, `SVC-FA`, `SVC-MO`. |
| `service_name` | text | Human-readable label: Depositary, Custody, Transfer Agency, Fund Administration, Middle Office. |
| `pns_column_name` | text | Exact column name as it appears in pns_raw: `Depositary`, `Custody`, `Transfer_Agency`, `Fund_Administration`, `Middle_Office`. |

### Rows (all 5)

| service_id | service_name | pns_column_name |
|---|---|---|
| SVC-DEP | Depositary | Depositary |
| SVC-CUS | Custody | Custody |
| SVC-TA | Transfer Agency | Transfer_Agency |
| SVC-FA | Fund Administration | Fund_Administration |
| SVC-MO | Middle Office | Middle_Office |

### Commit Status

Committed to `main` — treated as a managed data artifact, same as
`seeds/fund_name_corrections.csv`. Do not edit manually. Document in README
as a seed file.

---

## 4. dim_group Addition (client_db_raw)

### Context

`group_id` and `group_name` are already present in `client_db_raw` as denormalized
columns (v1 spec §3.2). The 3NF violation (`client_id → group_id → group_name`)
is documented in the v1 spec. v2 resolves it by extracting `dim_group` as a proper
dimension table.

### dim_group Structure

| Column | Type | Notes |
|---|---|---|
| `group_id` | text | PK. Format: `G01`, `G02` etc. |
| `group_name` | text | Human-readable group label. |
| `client_count` | integer | Derived in mart: number of current clients in this group. |

### Generator Rules

No generator change needed — `group_id` and `group_name` already exist in
`client_db_raw`. ~30% of clients have no group affiliation (`group_id` null) per
v1 spec. dim_group is built in the marts layer by selecting distinct
`(group_id, group_name)` from `dim_client` where `group_id` is not null.

### dbt Layer Placement

```
dim_client (existing)
    → dim_group     SELECT DISTINCT group_id, group_name FROM dim_client
                    WHERE group_id IS NOT NULL
                    + COUNT(client_id) AS client_count
```

---

## 5. Semantic Layer — MetricFlow

### 5.1 Semantic Models

Four semantic models. Three are new (fee_invoice sources); one is a minimal
addition to the existing fact_deal_snapshot to enable the cross-model fee_yield
metric.

**sem_fee_revenue**
Source mart: `mart_fee_revenue`
Primary entity: `client_id`
Grain: `(client_id, service_id, billing_period_start)`

| Measure | Aggregation | Description |
|---|---|---|
| `gross_fee_amount` | `sum` | fee_amount_eur where fee_line_type = 'invoice' |
| `net_fee_amount` | `sum` | fee_amount_eur across all line types |
| `invoice_count` | `count` | Count of invoice rows only |
| `credit_note_count` | `count` | Count of credit note rows |

Dimensions: `client_id`, `service_id`, `billing_period_start`, `billing_period_label`,
`fee_basis`, `is_paid`

---

**sem_client_retention**
Source mart: `mart_client_retention`
Primary entity: `client_id`
Grain: `(client_id, billing_period_start)`

| Measure | Aggregation | Description |
|---|---|---|
| `active_clients` | `count_distinct` | Clients present in a given period |
| `churned_clients` | `count_distinct` | Clients present in period N, absent in N+1 |
| `retained_clients` | `count_distinct` | Clients present in both period N and N+1 |

Dimensions: `client_id`, `billing_period_start`, `billing_period_label`

---

**sem_cohort_revenue**
Source mart: `mart_cohort_revenue`
Primary entity: `client_id`
Grain: `(cohort_quarter, periods_since_onboarding)`

| Measure | Aggregation | Description |
|---|---|---|
| `cohort_gross_revenue` | `sum` | Gross fee revenue by cohort and period offset |
| `cohort_client_count` | `count_distinct` | Clients in cohort still active at each period offset |

Dimensions: `cohort_quarter`, `periods_since_onboarding`, `client_id`

---

**sem_deal_snapshot** *(minimal addition to existing fact_deal_snapshot)*
Source mart: `fact_deal_snapshot` (v1, existing)
Primary entity: `client_id`
Minimal measure added for cross-model join only:

| Measure | Aggregation | Description |
|---|---|---|
| `aum_eur` | `sum` | AUM from fact_deal_snapshot — semi-additive; use with period filter |

Note: `aum_eur` is a stock measure (semi-additive). Do not SUM across time periods.
Always filter to a single reporting_date when using this measure. The MetricFlow
definition should include a note on aggregation type.

### 5.2 Metrics

| Metric | Type | Semantic Model | Definition |
|---|---|---|---|
| `gross_mrr` | `simple` | `sem_fee_revenue` | SUM(gross_fee_amount) — monthly recurring gross fee revenue |
| `net_mrr` | `simple` | `sem_fee_revenue` | SUM(net_fee_amount) — net of credit notes |
| `credit_note_ratio` | `ratio` | `sem_fee_revenue` | credit_note_count / invoice_count |
| `client_retention_rate` | `ratio` | `sem_client_retention` | retained_clients / active_clients |
| `client_churn_rate` | `ratio` | `sem_client_retention` | churned_clients / active_clients |
| `cohort_revenue_retention` | `ratio` | `sem_cohort_revenue` | cohort_gross_revenue at period N / cohort_gross_revenue at period 0 — private capital analogue of NRR |
| `fee_yield` | `ratio` | `sem_fee_revenue` + `sem_deal_snapshot` | gross_mrr / aum_eur — cross-model metric; MetricFlow resolves join through shared client_id entity |

### 5.3 Cross-Model Join Note

`fee_yield` is the only metric requiring a cross-model join. MetricFlow handles
this through the shared `client_id` entity — both semantic models declare
`client_id` as their primary entity. Do not pre-join the marts. Let MetricFlow
manage the join at query time. The sem_deal_snapshot definition for this purpose
is defined inline when building the MetricFlow layer in week 2 — not pre-specified
here.

---

## 6. What This Spec Does NOT Cover

The following remain frozen in v1 spec §5 and are not part of this build:

- Currency defect (MetricFlow v1 prerequisite; deferred to after semantic layer
  is stable)
- SCD Type 2 on `top_priority` (pattern already demonstrated in v1)
- Split pns_raw into two physical files (explicitly out of scope per v1 spec
  design rationale)
- Alias coverage rate metric
- `dim_fund` extraction of fund-level attributes
- AI agent artifact — designed on top of the semantic layer once MetricFlow is
  stable; not a data spec item
- Airflow DAG structure and GitHub Actions CI config — implementation artifacts,
  not data spec content
