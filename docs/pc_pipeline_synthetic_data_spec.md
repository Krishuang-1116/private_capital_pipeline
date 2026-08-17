---
title: pc_pipeline — Synthetic Data Spec
date: 2026-08-16
tags:
  - portfolio
  - dbt
  - synthetic-data
  - analytics-engineering
  - dimensional-modeling
topic: Modern Stack
source: pc_pipeline synthetic dataset specification
status: Frozen — August 2026
---

## 0. Framing

BNP's data problems are vocabulary sources for injecting realistic defects into synthetic portfolio data. The portfolio demonstrates correct architecture, not BNP's limitations. BNP is the quarry, not the deliverable.

Every defect injected ships with its handler. A defect the pipeline resolves = skill demonstration. A defect it can't resolve = a mess on GitHub.

Source framing in `sources.yml`:
- `pns_raw` → "Monthly deal pipeline extract from internal reporting system"
- `client_db_raw` → "Client master data extract from CRM"

---

## 1. Generation Parameters

| Parameter | Value |
|---|---|
| Total deals (base population) | ~100 |
| Reporting period | Aug 2025 – Aug 2026 (13 monthly snapshots) |
| Schema cutover date | Jan 2026 |
| Locations | 7: APAC / Channel Islands / France / Germany / Italy / Luxembourg / Spain |
| Total fact rows | ~1,139 (1,105 structural periodic-snapshot rows from the growth model + ~34 Defect 4 duplicate rows, ~3% per snapshot) |
| Clients (synthetic) | ~40 |
| Clients with SCD Type 2 state change | ~20% (~8 clients) |

### 1.1 — Deal Population Growth Model

| Month | Cumulative Deals | New Deals Entering |
|---|---|---|
| Aug 2025 | 60 | — (base cohort) |
| Sep 2025 | 65 | 5 |
| Oct 2025 | 70 | 5 |
| Nov 2025 | 75 | 5 |
| Dec 2025 | 80 | 5 |
| Jan 2026 | 85 | 5 (first post-cutover cohort) |
| Feb 2026 | 88 | 3 |
| Mar 2026 | 91 | 3 |
| Apr 2026 | 94 | 3 |
| May 2026 | 97 | 3 |
| Jun 2026 | 100 | 3 |
| Jul 2026 | 100 | 0 |
| Aug 2026 | 100 | 0 |

**Two generation rules derived from this model:**

Deals entering Aug 2025 – Dec 2025 (pre-cutover cohort) get pre-cutover schema rows for all their snapshots up to Dec 2025, then post-cutover schema rows from Jan 2026 onward. Legacy strategy columns are absent from post-cutover rows; sub-strategy columns are resolved via backfill logic (see Defect 3).

Deals entering Jan 2026 onward (post-cutover cohort) get post-cutover schema rows exclusively — they never have legacy strategy columns. Null sub-strategy values on these deals genuinely mean No. The cutover detection logic in staging keys off `reporting_date >= '2026-01-01'` AND `deal_first_reporting_date >= '2026-01-01'`, not off the presence or absence of legacy column values.

---

## 2. Source 1 — pns_raw

### 2.1 Grain

`(deal_id, reporting_date)` — periodic snapshot. Same deal reappears each month with potentially updated field values. No `deal_id` exists in the raw file; it is a best-effort identifier derived in staging, not a true surrogate.

### 2.2 Column Spec

#### Identity / Grain Columns

| Column           | Type | Allowed Values                                                         | Null % | Notes                                                                          |
| ---------------- | ---- | ---------------------------------------------------------------------- | ------ | ------------------------------------------------------------------------------ |
| `reporting_date` | date | Monthly end dates, Aug 2025 – Aug 2026                                 | 0%     | Manual input by managers                                                       |
| `location`       | text | APAC / Channel Islands / France / Germany / Italy / Luxembourg / Spain | 0%     | 7 locations, already standardized                                              |
| `client_name`    | text | Synthetic names                                                        | 0%     | Join key to client_db via alias lookup; ~5% have fund_name mutation injected   |
| `fund_name`      | text | Synthetic names                                                        | 1%     | ~5% mutate across snapshots (e.g. "Orion Fund II" → "Orion Fund 2") — defect 1 |

#### Client / Deal Attributes

| Column                  | Type | Allowed Values                                                                                                                                                             | Null % | Notes                                                                                                                                                                                                                                                                                                                 |
| ----------------------- | ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `client_type`           | text | AO / AO-Insurance / AO-Pension Funds / AO-SWF / GP-Direct / GP-FoF                                                                                                         | 3%     | Denormalized copy from client_db — mirrors `client_type` in `dim_client`. Enables cross-source consistency check: custom dbt test asserts `client_type` in latest pns snapshot matches `client_type` in current `dim_client` version row.                                                                             |
| `client_nature`         | text | Prospect / Existing / TBD                                                                                                                                                  | 0%     | Mirrors client_db; TBD for unresolved                                                                                                                                                                                                                                                                                 |
| `deal_type`             | text | Solicitation / Formal process - RFP or RFI                                                                                                                                 | 0%     |                                                                                                                                                                                                                                                                                                                       |
| `deal_qualification`    | text | New fund launch / Prospective approach / Existing fund migration / TBD                                                                                                     | 27%    |                                                                                                                                                                                                                                                                                                                       |
| `deal_status`           | text | Under analysis / Fee proposal sent / Won / Lost / Rejected / Submitted RFP / Upcoming RFP                                                                                  | 1%     | Terminal values: Won / Lost / Rejected. Won = mandate awarded to firm. Lost = client withdrew or chose competitor. Rejected = client rejected by firm (AML/KYC or below threshold).                                                                                                                                   |
| `fund_structuration`    | text | Closed-end fund / Open-end fund / Hybrid / Institutional Evergreen                                                                                                         | 47%    | Normalization issues in source; staging canonicalizes known variants                                                                                                                                                                                                                                                  |
| `financial_sponsor`     | text | Yes / No / TBD                                                                                                                                                             | 96%    | Linked to client_db                                                                                                                                                                                                                                                                                                   |
| `fund_jurisdiction`     | text | France / Spain / Luxembourg / Italy / Cayman Islands / Singapore / Hong Kong / Others / Australia / United Kingdom / United States / Germany / Channel Islands / TBD       | 1%     |                                                                                                                                                                                                                                                                                                                       |
| `owner`                 | text | Synthetic initials (e.g. JDM / KZ / DL)                                                                                                                                    | 13%    | Product manager abbreviations                                                                                                                                                                                                                                                                                         |
| `expected_outcome_date` | date | Plausible future dates                                                                                                                                                     | 95%    | Business-required placeholder, sparse by design; cast to date in staging                                                                                                                                                                                                                                              |
| `main_reason_for_loss`  | text | Other reasons / Pricing / Client abandoned / Initiative postponed or cancelled / Product gap / Incumbent provider selected / Timing / AML or KYC process / Below Threshold | 94%    | Populated only when deal_status = Won / Lost / Rejected is false — i.e. for terminal deals only. Custom conditional not_null test: assert not_null where deal_status IN ('Won', 'Lost', 'Rejected'). Note: Won deals will have null main_reason_for_loss by design — the test should scope to Lost and Rejected only. |

>[!note] Design rationale — `client_type` placement
>
> **Why `client_type` is in client_db_raw (not derived from pns_raw):**
> `client_type` is a fundamental classification of what kind of legal entity a client is (AO, GP, etc.). A CRM system stores this as master data — entered once at client record creation and maintained there. It is not derived from deal feeds; the deal feed is a downstream system that consumes the CRM classification. Having `client_type` in client_db_raw reflects the correct architecture.
>
> The BNP reality where `client_type` lived only in pns_raw was a gap in how the Client DB was built — the workaround was to stamp `client_type` from pns_raw back onto client_db by matching on `client_id`. This portfolio project models the correct architecture rather than replicating the gap. 
> **README documents this explicitly**: "client_type is maintained in client_db_raw as a CRM-native attribute; in the source system this field was absent from the CRM extract and had to be backfilled from the deal feed — a gap this model corrects by design."
>
> **When dimension attribute recovery from a fact source is the right pattern:**
> This argument prevails when the dimension source genuinely cannot carry the attribute and the fact source is the only place it exists. In this project the valid cases are:
> - `owner` (product manager) — a deal-level assignment, not a client entity property. The same client can have different owners across deals or over time. If a client-level owner is ever needed, it is derived from pns_raw by taking the most recent `owner` value per `client_id`. Justified because a CRM would not store deal-level assignments as a client attribute.
> - Derived client classifications from deal history — e.g. "client predominantly brings new fund launches" — computed by aggregating fact rows, not stored in any source system.
>
> **The distinguishing principle:** does the attribute describe the entity itself (belongs in CRM/client_db_raw), or does it describe the deal relationship or interaction (lives in pns_raw, potentially recoverable to dimension level by aggregation)? `client_type` describes the entity — CRM owns it. `owner` describes the relationship — fact source owns it.

>[!note]
> - `main_operating_location` and `sales_lead_location` are dropped because no analytical requirement was identified.
> - Fund-level attributes `fund_structuration` and `fund_jurisdiction` are carried in pns_raw because the source reports at deal level with one fund per deal. In a fully normalized model these belong in `dim_fund`. `dim_fund` is scaffolded as a v2 addition — at that point these columns would be extracted from `dim_deal` into the fund dimension.
#### Strategy Columns — Schema Evolution (Defect 3)

**Pre-cutover schema (Aug 2025 – Dec 2025): 4 strategy columns**

| Column | Type | Allowed Values | Null % | Generator Constraint |
|---|---|---|---|---|
| `private_equity` | text | Yes / No / TBD / tbd | 0% | |
| `private_debt` | text | Yes / No / TBD / tbd | 0% | |
| `real_estate` | text | Yes / No / TBD / tbd | 0% | If Yes, at least one of `private_equity` or `private_debt` must also be Yes — enforced by generator (see backfill assumption below) |
| `infrastructure` | text | Yes / No / TBD / tbd | 0% | Same constraint as `real_estate` |

**Generator constraint:** ~3-5 deals intentionally violate this constraint (`real_estate = Yes` or `infrastructure = Yes` with both `private_equity = No` and `private_debt = No`). These are injected as data quality defects surfaced by `qa_unresolvable_strategy` (see Defect 3).

**Post-cutover schema (Jan 2026 – Aug 2026): 6 strategy columns + 2 new columns**

| Column | Type | Allowed Values | Null % | Notes |
|---|---|---|---|---|
| `private_equity` | text | Yes / No / TBD / tbd | 1% | Carries over unchanged from pre-cutover schema |
| `private_debt` | text | Yes / No / TBD / tbd | 1% | Carries over unchanged from pre-cutover schema |
| `real_estate_equity` | text | Yes / No / TBD / tbd | 60% | New sub-column; replaces `real_estate` |
| `real_estate_debt` | text | Yes / No / TBD / tbd | 60% | New sub-column; replaces `real_estate` |
| `infrastructure_equity` | text | Yes / No / TBD / tbd | 60% | New sub-column; replaces `infrastructure` |
| `infrastructure_debt` | text | Yes / No / TBD / tbd | 60% | New sub-column; replaces `infrastructure` |
| `listed_assets_in_portfolio` | text | Yes / No / TBD / Yes (1 listed asset) / tbd | 70% | New column added at cutover |
| `OTC_instruments_in_portfolio` | text | Yes / No / TBD / tbd | 70% | New column added at cutover |

>[!note] Design rationale — one wide file, not two raw extracts
>
> In reality, a schema cutover like this usually arrives as two physically different extracts — a 4-strategy-column file pre-cutover, a 6-strategy-column file post-cutover — and staging would need to reconcile the two shapes (e.g. `UNION ALL` / `dbt_utils.union_relations`) before the backfill logic could even run.
>
> This project intentionally generates `pns_raw` as a single wide file instead: pre-cutover rows populate `real_estate`/`infrastructure` and leave the six post-cutover-era columns null; post-cutover rows do the reverse. `real_estate`/`infrastructure` never reappear once `reporting_date >= 2026-01-01` — the columns are structurally absent (null) outside their era, not rebuilt from two sources.
>
> **Why:** Defect 3's demonstration target is the backfill-resolution logic — cutover detection, the pre-cutover anchor CTE, resolving or flagging sub-strategy values — not source reconciliation. A two-file design would force staging to also solve a union/schema-reconciliation problem, which is a real and common pattern but a distinct skill, deferred to v2 (§5) rather than folded into this defect class.

#### Service Columns

| Column                                | Type | Allowed Values                   | Null % | Notes                                                                                                                                                                                                                                                                                                           |
| ------------------------------------- | ---- | -------------------------------- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `Depositary`                          | text | Yes / No / TBD                   | 1%     |                                                                                                                                                                                                                                                                                                                 |
| `Custody`                             | text | Yes / No / TBD                   | 90%    |                                                                                                                                                                                                                                                                                                                 |
| `Transfer_Agency`                     | text | Yes / No / TBD / FATCA / B7765   | 12%    | Rogue values `FATCA` and `B7765` injected in pre-cutover period only. Staging normalizes these to `Yes` — they represent TA engagements with regulatory-specific tagging, not a distinct service. `accepted_values` test on the cleaned column confirms no rogue values pass through to the intermediate layer. |
| `Fund_Administration`                 | text | Yes / No / TBD                   | 7%     |                                                                                                                                                                                                                                                                                                                 |
| `Corporate_Secretary`                 | text | Yes / No                         | 57%    |                                                                                                                                                                                                                                                                                                                 |
| `Middle_Office_Investor_Reporting`    | text | Yes / No / TBD                   | 12%    |                                                                                                                                                                                                                                                                                                                 |
| `Middle_Office_Portfolio_Monitoring`  | text | No / TBD                         | 86%    |                                                                                                                                                                                                                                                                                                                 |
| `Middle_Office_Loan_Administration`   | text | Yes / No / TBD                   | 24%    |                                                                                                                                                                                                                                                                                                                 |
| `Middle_Office_Collateral_Management` | text | Yes / No / TBD                   | 60%    |                                                                                                                                                                                                                                                                                                                 |
| `Other_MO_services`                   | text | Yes / No / TBD                   | 54%    |                                                                                                                                                                                                                                                                                                                 |
| `digital_reporting_platform`          | text | Yes / No / TBD                   | 40%    |                                                                                                                                                                                                                                                                                                                 |
| `SFDR_eligibility`                    | text | Article 8 / Article 9 / No / TBD | 8%     |                                                                                                                                                                                                                                                                                                                 |

#### Measure Columns

| Column | Type | Allowed Values | Null % | Notes |
|---|---|---|---|---|
| `asset` | text | Mostly numeric; ~5% with currency-string format e.g. "$0.54bn" | 1% | Fund-level AUM in billion EUR; mixed format is defect 5a |
| `revenue` | text | Mostly numeric | 5% | Pre-interest revenue in thousand EUR |
| `currency` | text | EUR / USD / AUD / SGD / UAD | 25% | UAD is a dirty value (likely AED); ~15.6% of all rows (~178) are non-EUR with no conversion rate available — defect 5b |

### 2.3 Columns Excluded and Rationale

| Column | Reason |
|---|---|
| `deal_timeline` | Marked for deletion in source (91% null, hard to decide) |
| `fund_size` | Marked for deletion in source (96% null, mixed format, not useful) |
| `client_size` | 94% null; orphaned value resolution requires manual archaeology outside engineering scope |
| `revised_outcome_date` | Field collision (dates + timeline strings in same column); normalization story already covered by strategy columns |
| `Date_last_fee_proposal` | 99% null (8 of 5489 values filled) |
| `Total_number_of_fee_proposals` | 99% null |
| `client_development_owner` | 88% null; abbreviation inconsistency not a new modeling pattern |
| `Main_reason_for_why_the_deal_is_lost` | INCLUDED — see above |
| `client_nature_in_2S` | Column not yet added to source; no skill signal |

### 2.4 Defect Classes — pns_raw

#### Defect 1 — No Stable Natural Key

**What:** Raw file has no `deal_id`. Client name + fund name is not a reliable composite key — fund names mutate across monthly snapshots.

**Injection:** ~5% of deals have `fund_name` mutate between snapshots (e.g. "Orion Fund II" → "Orion Fund 2", "Artemis RE Fd" → "Artemis RE Fund").

**Handler:** `fund_name_corrections` seed (see section 4.1). Staging joins pns_raw to this seed on `(client_name, dirty_fund_name)`, coalesces to `canonical_fund_name`, then passes canonical name into `dbt_utils.generate_surrogate_key(['client_name', 'canonical_fund_name', 'location'])`.

**dbt test:** `unique` + `not_null` on generated `deal_id` at snapshot grain.

**README framing:** "The source system provides no persistent identifier. Staging generates a deterministic hash from canonicalized business attributes as a stable key proxy. The `fund_name_corrections` seed is the canonicalization mechanism. This is a best-effort identifier, not a true surrogate — its stability depends on input canonicalization."

#### Defect 2 — Periodic Snapshot Grain with Monthly Repetition

**What:** Every deal row repeats monthly. Not a defect in the traditional sense — it is the inherent grain of the source. Modeling it explicitly as a periodic snapshot fact table is the Kimball pattern.

**Injection:** Structural — no additional injection needed. Every deal appears in every monthly snapshot.

**Handler:** `fact_deal_snapshot` materialized as a periodic snapshot. `asset` (AUM) declared as semi-additive — valid to SUM across clients and deals, invalid to SUM across months.

**dbt test:** `unique` on composite `(deal_id, reporting_date)`.

#### Defect 3 — Schema Evolution with Backfill Resolution

**What:** Source schema expands at Jan 2026 cutover. `real_estate` and `infrastructure` are replaced by four sub-strategy columns. `private_equity` and `private_debt` carry over unchanged. Pre-cutover deals appearing in post-cutover snapshots have null sub-strategy columns — not because they have no strategy, but because nobody backfilled them. One staging model handles both schemas, resolves the backfill via pre-cutover anchor logic, and flags unresolvable cases.

**Injection — schema evolution:** Synthetic file contains both period structures as described above. Pre-cutover deals have legacy columns in Aug–Dec 2025 snapshots and post-cutover columns (with null sub-strategy values) in Jan–Aug 2026 snapshots.

**Injection — unresolvable strategy defect:** ~3-5 pre-cutover deals have `real_estate = Yes` or `infrastructure = Yes` with both `private_equity = No` and `private_debt = No`. These cannot be backfilled by logic alone.

**Backfill mapping logic:**

| Pre-cutover condition                           | Post-cutover resolution       |
| ----------------------------------------------- | ----------------------------- |
| `private_equity = Yes` + `real_estate = Yes`    | `real_estate_equity = Yes`    |
| `private_equity = Yes` + `infrastructure = Yes` | `infrastructure_equity = Yes` |
| `private_debt = Yes` + `real_estate = Yes`      | `real_estate_debt = Yes`      |
| `private_debt = Yes` + `infrastructure = Yes`   | `infrastructure_debt = Yes`   |

Asset class (equity vs debt) is determined by the financing type anchor (`private_equity` or `private_debt`). Resolution is fully deterministic given the assumption that no pre-cutover deal has `real_estate = Yes` or `infrastructure = Yes` without a financing type anchor.

**Staging mechanism:** A CTE filtered to `reporting_date = '2025-12-01'` (last pre-cutover snapshot) provides the legacy strategy selections as the backfill anchor. The intermediate model joins post-cutover snapshots of pre-cutover deals against this CTE to resolve sub-strategy values. No new source file needed.

**Handler — resolvable deals:** Sub-strategy columns resolved via backfill mapping. `accepted_values` test on each canonical strategy column (Yes / No / TBD only — no tbd casing leakage, no null leakage on resolvable deals).

**Handler — unresolvable deals:** Sub-strategy columns set to `strategy_unresolvable` flag. Surfaced via `qa_unresolvable_strategy` model referencing the pre-cutover anchor CTE directly — never `dim_deal`. Same engineering boundary principle as `qa_unmatched_clients`: pipeline makes ambiguity visible and actionable, resolution is a business decision.

`qa_unresolvable_strategy` columns:
- `deal_id` — locates the exact deal
- `client_name` — identification context
- `fund_name` — cross-reference context
- `real_estate` — the unresolvable legacy value
- `infrastructure` — the unresolvable legacy value
- `private_equity` — confirms absence of financing anchor
- `private_debt` — confirms absence of financing anchor

**dbt tests:**
- `accepted_values` on each post-cutover sub-strategy column: Yes / No / TBD / strategy_unresolvable
- Custom assertion: `strategy_unresolvable` appears only on `deal_id`s present in `qa_unresolvable_strategy` — if it appears anywhere else, the backfill logic has a bug
- Custom assertion: no post-cutover new deal (first `reporting_date >= '2026-01-01'`) has `strategy_unresolvable` — unresolvable flag is strictly a pre-cutover deal phenomenon

**README framing:** "The schema cutover introduced four sub-strategy columns replacing two legacy columns. Pre-cutover deals were not backfilled by the source system. The pipeline resolves sub-strategy values deterministically using the financing type anchor from the last pre-cutover snapshot — `private_equity` maps to equity sub-types, `private_debt` maps to debt sub-types. Where no financing type anchor exists, the pipeline flags the deal as `strategy_unresolvable` and surfaces it via `qa_unresolvable_strategy` for manual review. The parallel structure between `qa_unmatched_clients` and `qa_unresolvable_strategy` reflects a consistent design philosophy: engineering surfaces ambiguity with full diagnostic context; resolution is a business decision."

#### Defect 4 — Byte-Identical Concat Duplicates

**What:** ~3% of deals appear twice in the same monthly snapshot with identical values across all columns — classic copy-paste double entry.

**Injection:** 3% of rows duplicated exactly within same `reporting_date`.

**Handler:** Deduplication in staging via `ROW_NUMBER() OVER (PARTITION BY client_name, fund_name, location, reporting_date) = 1`.

**dbt test:** `unique` on `(deal_id, reporting_date)` — same test as defect 2, but now it actively catches something before dedup runs.

#### Defect 5 — Mixed Currency / Revenue Corruption

**What:** Two sub-defects. (a) `asset` column contains ~5% rows with currency-string format ("$0.54bn") instead of pure numeric. (b) `currency` is 25% null and ~8% of revenue rows carry non-EUR currency with no conversion rate available.

**Injection:** (a) ~15 rows with currency-string `asset` values. (b) ~178 rows (~15.6% of all rows) with non-EUR currency and no rate — driven by the generator's currency draw weights (EUR 78% / USD 8% / AUD 5% / SGD 5% / UAD 4%), not a fixed target count.

**Handler:** (a) Regex cast in staging strips currency signs and unit suffixes to extract numeric value. (b) Staging casts `revenue` to `revenue_eur_equiv` — set to null where currency is not EUR and no rate is available. Null is the correct output: it makes the corruption visible rather than silently wrong.

**dbt test:** `not_null` on `revenue_eur_equiv` — intentionally fails on the ~24 corrupted rows, surfacing the issue. This is a documented expected failure pattern, not a broken test.

### 2.5 — dim_deal Assumption and Strategy/Service Change Injection

**dim_deal Treatment — Latest Snapshot per Deal**

Strategy and service columns are treated as finalized at the latest reporting snapshot per deal. `dim_deal` takes `ROW_NUMBER() OVER (PARTITION BY deal_id ORDER BY reporting_date DESC) = 1` to produce one static row per deal.

**Consequence:** intra-deal changes to strategy or service scope across monthly snapshots are not tracked in `dim_deal`. The analytical question "when did this deal's strategy change" is not answerable from `dim_deal` — it requires querying `fact_deal_snapshot` directly.

**Alternative considered and rejected:** moving strategy and service columns into `fact_deal_snapshot` as monthly attributes would make change tracking possible but would partially render `dim_deal` redundant as a static dimension. Deferred to v2 as a documented architectural evolution if the analytical requirement becomes real.

---

**Genuine Strategy/Service Change Injection**

~5 deals are injected with genuine strategy or service column changes across monthly snapshots. These are used to prove that `qa_strategy_service_changes` fires correctly and that `dim_deal`'s latest-snapshot treatment produces the correct final state.

**Generator constraint — which columns may change:**

Genuine strategy/service changes are only injected on:
1. `private_equity` or `private_debt` on any deal (pre- or post-cutover) — these columns carry over unchanged across the cutover boundary; a value change is unambiguously a genuine business decision
2. Any service column (`Depositary`, `Custody`, `Transfer_Agency`, `Fund_Administration`, `Corporate_Secretary`, `Middle_Office_*`, `digital_reporting_platform`, `SFDR_eligibility`) on any deal
3. Sub-strategy columns (`real_estate_equity`, `real_estate_debt`, `infrastructure_equity`, `infrastructure_debt`) only on post-cutover cohort deals (first `reporting_date >= '2026-01-01'`)

**Why sub-strategy changes are excluded on pre-cutover deals:** staging cannot distinguish between a genuine business strategy update and a late backfill correction on these columns for pre-cutover deals. Injecting this pattern would create ambiguity that the pipeline cannot resolve — surfaced instead by `qa_strategy_ambiguous` (see below). This is a known synthetic simplification documented here: in production, sub-strategy changes on pre-cutover deals would exist and would require human classification.


---

**QA Model Framework**

Four QA models implement a consistent design philosophy across the pipeline: engineering surfaces ambiguity with full diagnostic context; resolution is a business decision.

| Model                         | Ambiguity Type                                                                                  | Resolution Owner                                                      |
| ----------------------------- | ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `qa_unmatched_clients`        | Entity resolution failure — `client_name` in pns_raw has no alias match                         | Business — add alias or new client row to client_db                   |
| `qa_unresolvable_strategy`    | Backfill anchor missing — `real_estate` or `infrastructure = Yes` with no financing type anchor | Business — classify financing type manually                           |
| `qa_strategy_service_changes` | Genuine detected changes — strategy or service column value differs across snapshots            | Business — confirm change is intentional or revert                    |
| `qa_strategy_ambiguous`       | Change vs backfill indistinguishable — sub-strategy column changes on pre-cutover deals         | Business — classify as backfill correction or genuine strategy update |
| `qa_alias_collision`          | One client_name matches multiple client_ids via alias join — fan-out detected                   | Business — identify correct legal entity for each affected deal       |
| `qa_terminal_revenue_asset`   | Terminal deals with null revenue or null asset — measure integrity failure                      | Business — verify with input source and correct pns_raw directly      |

---

**`qa_strategy_service_changes`**

**Purpose:** surfaces deals where any strategy column (private_equity, private_debt, real_estate_equity, real_estate_debt, infrastructure_equity, infrastructure_debt) or any service column (Depositary, Custody, Transfer_Agency, Fund_Administration, Corporate_Secretary, Middle_Office_*, digital_reporting_platform, SFDR_eligibility) changes value across monthly snapshots. Proves dim_deal's latest-snapshot treatment is a deliberate informed choice, not silent data loss — both strategy scope and service scope are treated as finalized at the latest snapshot.

**Mechanism:** scans `fact_deal_snapshot` using `LAG()` window function to detect value changes between consecutive snapshots per deal. Filters to schema-stable columns only (see generator constraint above).

**Columns surfaced:**
- `deal_id`
- `client_name`
- `fund_name`
- `column_name` — which column changed
- `previous_value`
- `new_value`
- `change_reporting_date` — the snapshot where the change first appears

**dbt test:** custom assertion that every `deal_id` appearing in `qa_strategy_service_changes` has its latest-snapshot value correctly reflected in `dim_deal`. Proves the `ROW_NUMBER() = 1` treatment picks up the final state.

**Expected rows in synthetic data:** ~5 deals × average 1-2 column changes each = ~8-10 rows.

---

**`qa_strategy_ambiguous`**

**Purpose:** surfaces pre-cutover deals where sub-strategy columns change value after the backfill resolution snapshot (i.e. after Jan 2026). These changes are genuinely ambiguous — staging cannot determine whether they represent a late backfill correction or a real strategy update.

**Mechanism:** scans `fact_deal_snapshot` for pre-cutover deals (first `reporting_date < '2026-01-01'`) where any of `real_estate_equity`, `real_estate_debt`, `infrastructure_equity`, `infrastructure_debt` changes value between any two post-cutover consecutive snapshots.

**Columns surfaced:**
- `deal_id`
- `client_name`
- `fund_name`
- `column_name`
- `previous_value`
- `new_value`
- `change_reporting_date`
- `ambiguity_reason` — hardcoded: "sub-strategy change on pre-cutover deal; cannot distinguish backfill correction from genuine strategy update"

**Expected rows in synthetic data:** zero — generator constraint prevents injection of this pattern by design.

**README framing:** "In the synthetic dataset this query returns no rows by generator design. In production it would surface cases requiring human judgment to classify as backfill correction or genuine strategy change. The zero-row result in testing confirms the generator constraint is correctly enforced and that no accidental ambiguous rows were introduced during data generation."

---
**`qa_alias_collision`**

**Purpose:** surfaces deals where `client_name` in pns_raw matches aliases belonging to more than one distinct `client_id` in `client_aliases`. A deal appearing in this model has been fanned out by the alias join and cannot be safely assigned to a single client without human judgment.

**Mechanism:** left join `stg_pns` against `client_aliases` on `client_name = alias`, group by `deal_id`, filter where `COUNT(DISTINCT client_id) >= 2`. References `stg_pns` and `client_aliases` directly — never `dim_deal`, consistent with the engineering boundary principle.

**Columns surfaced:**
- `deal_id`
- `client_name` — the colliding alias string
- `fund_name` — cross-reference context
- `matched_client_ids` — array or comma-separated list of all `client_id` values matched
- `match_count` — number of distinct clients matched

**Injection:** 2-3 deals in pns_raw whose `client_name` string appears as `Alias_1`, `Alias_2`, or `Alias_3` for two different clients in `client_db_raw`.

**dbt test:** custom assertion that no `deal_id` in `dim_deal` has a `client_id` derived from a collision row — i.e. collision rows must be resolved before they reach the mart layer. In the synthetic dataset, collision rows are assigned `CLIENT-000` downstream (same sentinel mechanism as unmatched clients) pending human resolution.

**Expected rows in synthetic data:** 2-3 rows, one per injected collision deal.

---

**`qa_terminal_revenue_asset`**

**Purpose:** surfaces terminal deals (`deal_status IN ('Won', 'Lost', 'Rejected')`) where `revenue_eur_equiv` or `asset` is null. For a deal that has reached a terminal state, both measures should be known — null values indicate a data entry gap in the source that requires manual reconciliation.

**Mechanism:** filters `fact_deal_snapshot` to the latest snapshot per deal (same `ROW_NUMBER() = 1` logic as `dim_deal`), then filters where `deal_status IN ('Won', 'Lost', 'Rejected')` AND (`revenue_eur_equiv IS NULL` OR `asset IS NULL`). References `fact_deal_snapshot` directly.

**Columns surfaced:**
- `deal_id`
- `client_name`
- `fund_name`
- `deal_status` — confirms terminal state
- `reporting_date` — latest snapshot date
- `revenue_eur_equiv` — null value that triggered the flag
- `asset` — null value that triggered the flag
- `missing_fields` — derived: 'revenue' / 'asset' / 'both'

**Resolution path:** human verifies with input source (raw pns file or deal manager) and corrects `pns_raw` directly. Pipeline re-runs and row disappears from QA model if correction is applied. Persistent rows signal a data entry failure that cannot be resolved by engineering.

**Injection:** ~5 terminal deals with null `revenue_eur_equiv` or null `asset` in their latest snapshot. Mix of Won (null asset), Lost (null revenue), and Rejected (both null) to exercise all branches of `missing_fields`.

**dbt test:** no hard test — this is a monitoring model, not a pass/fail assertion. The model itself is the test. Row count trending upward over time signals a deteriorating data entry workflow.

**Expected rows in synthetic data:** ~5 rows matching the injection spec.

**README framing:** "Terminal deals are expected to have known revenue and AUM figures — a deal that has closed should have been measured. `qa_terminal_revenue_asset` surfaces exceptions for manual reconciliation against the source. Resolution requires correcting pns_raw directly; the pipeline does not impute missing measures."

---

## 3. Source 2 — client_db_raw

### 3.1 Structure

Structurally clean by design (Huijie-authored in BNP context). Mess lives in pns_raw, not here. The portfolio version extends the BNP version with SCD Type 2 versioning, full financial_sponsor audit trail, and explicit `dim_group` hierarchy.

### 3.2 Column Spec

#### Core Identity

| Column | Type | Notes |
|---|---|---|
| `client_key` | integer | True surrogate PK — opaque, system-assigned at record creation, never changes. Authored directly as integers in the raw generator output (`data/raw/client_db_raw.csv`, simulating a CRM-assigned surrogate key) — not a dbt seed; `client_db_raw` is loaded the same way as `pns_raw`. Globally unique across all version rows. |
| `client_id` | text | Durable entity key — repeats across version rows for the same client. Format: "C001", "C002" etc. |

**Key distinction:** `client_id` identifies the legal entity. `client_key` identifies a specific version of that entity. Facts store `client_key` to pin the client-version at deal time.

#### SCD Type 2 Versioning Columns

| Column | Type | Notes |
|---|---|---|
| `effective_from` | date | Start date of this version row |
| `effective_to` | date | End date of this version row; null for current version |
| `is_current` | boolean | True for exactly one row per `client_id` |

#### Client Attributes (stable across versions)

| Column            | Type | Notes                                                                                                                                                                                                                                                                             |
| ----------------- | ---- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `official_name`   | text | Mutable, uniqueness constraint. Repeats across version rows — accepted Kimball redundancy.                                                                                                                                                                                        |
| `client_type`     | text | Authoritative source of client type classification. AO / AO-Insurance / AO-Pension Funds / AO-SWF / GP-Direct / GP-FoF. 0% null. Stamped onto deals via dim_client join in intermediate layer. Denormalized copy also present in pns_raw for cross-source consistency validation. |
| `group_id`        | text | FK to `dim_group`. Format: "G01", "G02" etc. ~30% null (clients with no group affiliation).                                                                                                                                                                                       |
| `group_name`      | text | Denormalized alongside `group_id` for portfolio convenience. 3NF violation formally documented: transitive dependency `client_id → group_id → group_name`. Resolved in `dim_group` table.                                                                                         |
| `hq_country`      | text | Repeats across version rows.                                                                                                                                                                                                                                                      |
| `aum_description` | text | Descriptive only — no aggregation. Non-summarizable field; staging marks as such.                                                                                                                                                                                                 |
| `top_priority`    | text | Yes / No. Type 1 overwrite — current state always authoritative. No historical tracking in v1. SCD Type 2 upgrade documented as v2 addition.                                                                                                                                      |

#### Versioned Attribute (triggers new version row)

| Column | Type | Allowed Values | Notes |
|---|---|---|---|
| `client_nature` | text | Prospect / Existing | The changing attribute. A Prospect → Existing transition creates a new version row with a new `client_key`, new `effective_from`, and closes the prior row's `effective_to`. |

#### Financial Sponsor Audit Trail (portfolio addition) — Type 1, stable across version rows

One value per `client_id`, held constant across all its version rows (same treatment as `top_priority`) — confirmed by §6's README framing ("`financial_sponsor` and `top_priority` are maintained as Type 1 attributes"), called out explicitly here since this section's own header doesn't otherwise say so.

| Column | Type | Allowed Values | Notes |
|---|---|---|---|
| `financial_sponsor` | text | Yes / No / pending | Expanded from BNP's collapsed Yes/No |
| `sponsor_evidence` | text | internal_watchlist / group_is_sponsor / preqin / manual_research / pending | Source of classification — rules-as-data pattern |
| `sponsor_confirmed_by` | text | Synthetic initials | Who confirmed the classification |
| `sponsor_confirmed_date` | date | Plausible dates | When confirmation was recorded |

Variation across all `sponsor_evidence` values is required — makes the field testable and demonstrable.

#### Alias Columns (wide format)

| Column | Type | Notes |
|---|---|---|
| `Alias_1` | text | Always populated |
| `Alias_2` | text | ~60% populated |
| `Alias_3` | text | ~25% populated |

Wide format replicates the source shape that motivates the unpivot in `stg_client`. Some clients intentionally have only `Alias_1` filled — sparse alias columns test that the unpivot handles nulls correctly.

### 3.3 SCD Type 2 — Three Properties That Must Always Hold

| Property | dbt Test |
|---|---|
| `client_key` globally unique | `unique` + `not_null` on `client_key` (standard generic test) |
| Exactly one `is_current = true` per `client_id` | Custom test — partition by `client_id`, assert `SUM(is_current) = 1` |
| Contiguous non-overlapping windows per `client_id` | Custom test — assert `effective_to` of version N = `effective_from` of version N+1; assert current version `effective_to` is null |

Second and third tests are custom SQL assertions. README notes that custom tests signal understanding of where generic tests end and domain-specific validation begins.

### 3.4 Synthetic Generation Rules for SCD Type 2

- ~80% of clients: single version row (`client_nature` = Prospect or Existing throughout)
- ~20% of clients (~8): two version rows — version 1 is Prospect, version 2 is Existing
- State change timestamps must be plausible within Aug 2025 – Aug 2026 window
- Fact rows in pns_raw must reference `client_key` of the correct version at deal time, not the current version
- `effective_to` of version 1 = `effective_from` of version 2
- `effective_to` of version 2 = null; `is_current` = true
- Every SCD client must have at least one `pns_raw` deal whose snapshot range spans its transition date — otherwise the SCD scenario exists in the dimension but has no fact data to demonstrate point-in-time `client_key` resolution against. Since deal-to-client assignment happens in `generate_pns_raw.py`, which runs before transition dates are decided, this requires a deliberate coverage guarantee (one Aug-2025-cohort deal reserved per SCD client), not incidental luck — a gap here surfaced during `validate_outputs.py` development and was fixed via the `scd_coverage_anchor` mechanism in the generator.

### 3.5 Defect Class — client_db

**Alias coverage gaps:** A controlled number of `client_name` values in pns_raw have no matching alias row in `client_aliases`. These surface in `qa_unmatched_clients` and are caught by `not_null` test on `client_id` after the alias join in the intermediate layer.

**Alias collision (two clients sharing one alias):** Detectable at join output level via fan-out — one deal row multiplies into two or more rows after the alias join when two clients have independently registered the same alias string. Surfaced by `qa_alias_collision`. **What is not detectable by engineering is which client is the correct match — resolution requires human domain judgment.**

**Injection:** 2-3 deals where `client_name` in pns_raw matches an alias belonging to two different clients in `client_aliases`.

**README framing:** "The pipeline surfaces unmatched clients via `qa_unmatched_clients` and alias collisions via `qa_alias_collision`. Both make ambiguity visible and actionable. Resolution is a business decision — the pipeline's responsibility ends at surfacing the diagnostic context."

**Cross-source consistency — `client_type`:** Custom dbt test asserts that `client_type` in the latest pns_raw snapshot for each `client_id` matches `client_type` in the current `dim_client` version row. Mismatch indicates either a stale pns_raw entry or an update to client_db that was not reflected in the deal feed. Surfaces as a warning-level test (not error) — the authoritative value is always `dim_client`.

### 3.6 Query Lineage (dbt layer placement)

```
raw_client → stg_client → client_aliases (reference model, staging layer)
                        ↘
stg_pns + client_aliases → qa_unmatched_clients
stg_pns + client_aliases → int_pns_deals → fact_deal_snapshot
                                         → dim_client
```

- `stg_client` — 1:1 with source, unpivots alias columns, type corrections
- `client_aliases` — reference model off `stg_client`, staging layer (structural reshape only, no business logic)
- `int_pns_deals` — alias join stamps `client_id` onto deals; this is where business logic lives
- `qa_unmatched_clients` — references `stg_pns` and `client_aliases` directly, never `dim_deal`; insulated from CLIENT-000 sentinel coercion

### 3.7 CLIENT-000 Sentinel Row

Added to `dim_client_seed`. All attributes null except `client_id = 'CLIENT-000'`. Purpose: deals pending client classification appear as a visible "Unknown" category in every slicer rather than silently dropping from filtered views. CLIENT-000 row count after each monthly refresh is a process health indicator — should return to zero after reconciliation.

---

## 4. Seeds

### 4.1 `fund_name_corrections`

**Purpose:** Canonicalizes dirty fund names before surrogate key generation in staging. Simulates the data governance artifact that would exist in a mature source system.

**Grain:** `(dirty_fund_name, client_name)` — scoped by client to avoid false matches across clients.

**Structure:**

| Column | Type | Notes |
|---|---|---|
| `dirty_fund_name` | text | Variant as it appears in raw pns |
| `canonical_fund_name` | text | Corrected form used for surrogate generation |
| `client_name` | text | Scoping key — correction applies only for this client |
| `corrected_by` | text | Initials of person who authored the correction |
| `corrected_date` | date | When the correction was recorded |

**Volume:** 5 rows — one dirty→canonical mapping per mutating deal (~5% of 100 deals). (Earlier draft assumed ~300 deals; volume was revised down when the population was fixed at 100.)


---

## 5. v2 Additions (Documented Deferrals)

### pns_raw v2

| Addition | What it demonstrates |
|---|---|
| `source_extract_timestamp` column + late-arriving rows (~5%) | Incremental model with correct idempotency; maps to Stripe webhook problem class |
| Metric disagreement via currency defect | MetricFlow semantic layer metric that guards against naive `SUM(revenue)` across currencies; requires MetricFlow v1 implementation first |
| `status_change_date` column | Exact deal duration analytics (time-to-won, time-to-lost); unlocks forecast accuracy delta against `expected_outcome_date` |
| Move strategy and service columns from `dim_deal` into `fact_deal_snapshot` as monthly attributes | Full intra-deal change tracking; "when did this deal's strategy change" becomes a window function query on the fact table; renders `qa_strategy_service_changes` and `qa_strategy_ambiguous` redundant as separate models — change detection becomes native to the fact layer |
| Physically split `pns_raw` into separate pre-cutover (4 strategy columns) and post-cutover (6 + 2 columns) extracts, instead of one wide file with era-sparse columns | Union-based staging reconciliation (`UNION ALL` / `dbt_utils.union_relations`) of two differently-shaped raw sources before the backfill logic can run — the common real-world case when a source system's *export format itself* changes at a schema cutover, not just its column values. Deliberately out of scope for v1: orthogonal to Defect 3's backfill-resolution demonstration (see §2.2 design rationale note) |

### client_db v2

| Addition | What it demonstrates |
|---|---|
| SCD Type 2 on `top_priority` | "When was this client promoted to top priority, did deal velocity increase?" — commercially legible analytical question; low cost once SCD Type 2 pattern is in place |
| `dim_group` with group-level metrics | Revenue concentration by group; AUM by group; drill-down from group → client in semantic layer |
| Alias coverage rate metric | Process health indicator: clients with only one alias are one typo away from unmatched; surfaces as dbt exposure or mart-level metric |

### Cross-cutting v2

| Addition | What it demonstrates |
|---|---|
| Fee invoice as third source — grain `(client_id, service_id, invoice_date)` | Galaxy schema with two fact tables; drill-across between `fact_deal_snapshot` and `fact_fee_invoice` through conformed `dim_client` and `dim_activity`; pipeline-to-revenue conversion metric in MetricFlow. Prerequisite: MetricFlow on v1 first. |

---

## 6. README Framing (Key Sentences)

"This project models a private capital deal pipeline ingested from two operational sources: a monthly deal reporting system and a client master database. The pipeline handles common private markets data quality problems including: absence of a stable natural key in the deal source, periodic snapshot grain requiring semi-additive measure handling, schema evolution across a reporting cutover, byte-identical duplicate records, mixed-currency measure corruption, and alias-based entity resolution for client identity."

"The source system provides no persistent deal identifier. Staging generates a deterministic hash from canonicalized business attributes as a stable key proxy. This is a best-effort identifier, not a true surrogate — its stability depends on input canonicalization via the `fund_name_corrections` seed."

"`financial_sponsor` and `top_priority` are maintained as Type 1 attributes. Full provenance on `financial_sponsor` is captured via the `sponsor_evidence`, `sponsor_confirmed_by`, and `sponsor_confirmed_date` audit columns, which provide classification history without requiring a new dimension version row."

"The pipeline's responsibility ends at surfacing ambiguity with full diagnostic context. `qa_unmatched_clients` makes the ambiguity visible and actionable — it does not resolve it. Resolution is a business decision."
