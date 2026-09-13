# v2 AI Agent Spec — Ask-the-Metrics Agent

## 1. Purpose and Positioning

A small "ask-the-metrics" agent that accepts natural-language questions about fee revenue
and client retention, translates them into governed SQL queries against the pc_pipeline
marts layer, and returns a plain-language interpretation of the result.

This is a proof-of-concept, not a production agent. Its purpose is to demonstrate that:

1. A semantic layer built on well-modeled dbt marts enables governed, auditable AI queries.
2. Complexity belongs at the modeling layer, not the query layer — the agent generates
   simple, deterministic SQL because the dbt marts have already encoded the hard logic
   (gross/net distinction, retention flags, cohort period-0 propagation, SCD resolution).
   This is not a limitation; it is the architecture working as intended.
3. The governance boundary lives in the metric definitions (the YAML semantic models and
   the Python lookup table derived from them), not in which tool happens to execute them.

**On MetricFlow:** this agent implements a governed query layer that replicates the
governance boundary — metric validation, dimension validation, deterministic SQL
compilation — without the full MetricFlow runtime. `dbt sl query` was unavailable in
the local DuckDB environment with dbt Fusion preview. The agent is an explicit workaround,
documented as such. Cross-model metrics that require MetricFlow's join engine are
excluded from v2 scope and targeted for v3.

The guardrail framing — what the agent trusts vs. verifies — is the primary interview
talking point. The code is the evidence behind it.

---

## 2. Architecture — Four-Step Flow

```
User natural-language question
    │
    ▼
[LLM Call 1 — Translation]
Extract structured JSON: metric_name, group_by, where, time_grain
    │
    ▼
[Python — Guardrail Validation]
Check metric_name against governed lookup table
Check group_by against valid dimensions for that metric
    │
    ├── NOT FOUND → Python returns hardcoded refusal message to user. STOP.
    │               "I can only answer questions about these governed metrics: ..."
    │               Refusal is deterministic Python, not a second LLM call.
    │
    └── FOUND → Python compiles SQL deterministically from lookup table + JSON params
                    │
                    ▼
               [Python — SQL Execution]
               Execute compiled SQL against DuckDB
                    │
                    ▼
               [LLM Call 2 — Interpretation]
               Pass raw result table to LLM for plain-language interpretation
                    │
                    ▼
               Return interpretation to user
```

**Key principle:** the LLM never touches SQL in either call. LLM Call 1 classifies
intent only. SQL is compiled deterministically by Python from a governed spec it
controls. LLM Call 2 interprets results only. The guardrail sits between LLM Call 1
and SQL compilation — this is the control point that prevents hallucinated or ungoverned
queries from executing.

---

## 3. Governed Metric Lookup Table

Built dynamically from `sem_*.yml` semantic model files at agent startup by `parser.py`.
**Not hardcoded.** Single source of truth is the YAML files — adding a new metric to
the semantic model automatically makes it available to the agent without prompt changes.

### YAML extraction path

For each semantic model file, Python extracts:

```
semantic_models:
  - name: <semantic_model_name>           # model identifier
    model: ref('<source_mart_name>')       # → source_mart
    entities:
      - name: <entity_name>               # → valid group_by value
    dimensions:
      - name: <dimension_name>            # → valid group_by value
        type: categorical | time
        # time dimensions → NOT added to group_by list (handled by time_grain field)
    measures:
      - name: <measure_name>              # intermediate key linking metrics → models — NOT the column to aggregate
        agg: sum | count_distinct | sum_boolean | average | percentile | median | count
        expr: <column_name>               # → the actual column to aggregate (often differs from measure_name)
        filter: "{{ Dimension('...') }} = '...'"   # optional — part of the measure's definition, not the query's

metrics:
  - name: <metric_name>                   # → governed metric name
    type: simple | ratio
    type_params:
      measure: <measure_name>             # simple: links to semantic_model via measure
      numerator:
        measure: <measure_name>           # ratio: links to semantic_model via measure
      denominator:
        measure: <measure_name>
```

### Measure → semantic model linking

The metrics block references measure names, not semantic model names directly.
Python resolves the link by:
1. Finding the measure name(s) referenced in the metric
2. Looking up which semantic model declares that measure in its `measures:` block
3. Pulling that semantic model's entities + categorical dimensions as valid `group_by`
4. **Pulling `expr` (the real column) and `filter` (if present) from that same measure
   declaration** — both are part of the measure's definition, exactly as load-bearing
   as `agg`. A measure's `name:` is an identifier for linking metrics to semantic
   models; it is frequently *not* the column being aggregated (`gross_fee_amount`'s
   `expr` is `fee_amount_eur`; `active_clients`/`retained_clients`/`churned_clients`
   all share `expr: client_id` and are distinguished *only* by `filter`). Treating
   `name` as if it were the column, or dropping `filter` because it seems like an
   optional annotation, both produce a lookup table that cannot represent the actual
   difference between several of the six governed metrics — see `docs/v2_ai_agent.md`
   for the full reasoning.

Time dimensions (`type: time`) are excluded from the `group_by` list — they are
already handled by the `time_grain` field and `DATE_TRUNC` in the SQL template.

### Cross-model metrics

`fee_yield` references measures from two semantic models (`sem_fee_revenue` and
`sem_deal_snapshot`). Handling cross-model joins requires MetricFlow's join engine
or a pre-joined mart — neither available in v2. `fee_yield` is excluded from the
v2 governed metric list. See Section 8 for v3 roadmap.

### Runtime lookup table structure

```python
# Built by parser.py at startup — not hardcoded
# Each measure slot is (agg, column, filter) — column comes from the measure's
# `expr:`, never its `name:`. filter is None when the measure has none (e.g. net_mrr,
# invoice_count, active_clients) — it is not omitted as a key, so compiler.py has one
# uniform shape to template against regardless of which measures a metric involves.
METRIC_LOOKUP = {
    "gross_mrr": {
        "source_mart": "mart_fee_revenue",
        "type": "simple",
        "agg": "sum",
        "column": "fee_amount_eur",
        "filter": "fee_line_type = 'invoice'",
        "time_column": "billing_period_start",
        "valid_dimensions": ["client_id", "service_id", "fee_line_type", "fee_basis", "is_paid", "billing_period_label"]
    },
    "net_mrr": {
        "source_mart": "mart_fee_revenue",
        "type": "simple",
        "agg": "sum",
        "column": "fee_amount_eur",
        "filter": None,
        "time_column": "billing_period_start",
        "valid_dimensions": ["client_id", "service_id", "fee_line_type", "fee_basis", "is_paid", "billing_period_label"]
    },
    "client_retention_rate": {
        "source_mart": "mart_client_retention",
        "type": "ratio",
        "numerator": {"agg": "count_distinct", "column": "client_id", "filter": "is_retained = true"},
        "denominator": {"agg": "count_distinct", "column": "client_id", "filter": None},
        "time_column": "billing_period_start",
        "valid_dimensions": ["client_id", "billing_period_label"]
    },
    "cohort_revenue_retention": {
        "source_mart": "mart_cohort_revenue",
        "type": "ratio",
        "numerator": {"agg": "sum", "column": "fee_amount_eur", "filter": None},
        "denominator": {"agg": "average", "column": "cohort_baseline_rev", "filter": None},
        "time_column": "cohort_quarter",
        "valid_dimensions": ["client_id", "cohort_quarter", "periods_since_onboarding"]
    },
    # ... all six governed metrics — client_churn_rate mirrors client_retention_rate
    # with numerator filter "is_retained = false"; credit_note_ratio mirrors
    # cohort_revenue_retention's ratio shape on mart_fee_revenue (count of invoice_id,
    # filtered to fee_line_type = 'credit_note' over unfiltered count of invoice_id)
}
```

Note the ratio entries have no top-level `agg`/`column`/`filter` — each side of the
ratio carries its own, because (as `client_retention_rate` shows) the two sides can
have different filters on the *same* column, and (as `cohort_revenue_retention` shows)
they can have different aggregation functions on *different* columns. A ratio schema
that only has one `agg`/`filter` for the whole metric cannot represent either case.

---

## 4. Governed Metric List (v2)

Six metrics. `fee_yield` explicitly excluded — cross-model, requires MetricFlow or
pre-joined mart, targeted for v3.

- `gross_mrr`
- `net_mrr`
- `credit_note_ratio`
- `client_retention_rate`
- `client_churn_rate`
- `cohort_revenue_retention`

---

## 5. LLM JSON Schema — Translation Step (Call 1)

The LLM extracts four fields from the user's natural-language question. Nothing else.

```json
{
  "metric_name": "gross_mrr",
  "group_by": "client_id",
  "where": null,
  "time_grain": "month"
}
```

| Field | LLM responsibility | Example |
|---|---|---|
| `metric_name` | Identify which governed metric the user is asking about | `"gross_mrr"` |
| `group_by` | Extract the dimension the user wants to slice by | `"client_id"`, `"service_id"` |
| `where` | Extract any filter condition from the question | `"client_id = 'C001'"`, `null` |
| `time_grain` | Infer temporal granularity implied by the question | `"month"`, `"quarter"`, `"year"` |

The LLM does not decide which mart to query, which column to aggregate, or what SQL
to write. Those are Python's responsibilities, derived deterministically from the lookup
table after validation.

**Separation of concerns:** the LLM JSON schema is not the same as the lookup table
schema. The lookup table is internal to Python — the LLM never sees mart names, column
names, or aggregation logic.

---

## 6. System Prompt — LLM Translation Step (Call 1)

The system prompt must contain exactly three things:

**1. The governed metric list** — injected dynamically from `parser.py` output at
runtime. Not hardcoded. If a new metric is added to the YAML, the prompt updates
automatically on next startup.

**2. The exact JSON schema** — field names, types, and valid values explicitly specified.
Without this, the LLM invents field names inconsistently and breaks downstream validation.

**3. The refusal instruction** — if the user's question cannot be mapped to a governed
metric, return `UNGOVERNED` as `metric_name`. Without explicit instruction, the LLM
approximates rather than refuses — which is the hallucination the guardrail exists to
prevent.

Draft system prompt template (metric list injected at runtime by `translator.py`):

```
You are a query translation layer for a governed analytics system.

Your only job is to extract a structured JSON object from the user's question.
You do not generate SQL. You do not answer questions directly. You only classify intent.

Governed metrics (the only valid values for metric_name):
{governed_metrics_list}

Output format — return ONLY valid JSON, no preamble, no explanation:
{{
  "metric_name": "<one of the governed metrics above, or UNGOVERNED>",
  "group_by": "<dimension name as a string, or null if not specified>",
  "where": "<SQL-style filter condition as a string, or null if not specified>",
  "time_grain": "<month | quarter | year, inferred from the question,
                  or month if not specified>"
}}

If the user's question cannot be mapped to any governed metric, set metric_name to
UNGOVERNED and leave all other fields null. Do not approximate or suggest alternatives.
```

---

## 7. Python Guardrail Validation

Two checks, in order, before any SQL is compiled:

**Check 1 — metric name:**
Is `metric_name` in the lookup table? If not → hardcoded refusal message listing
governed metrics. Stop. No SQL generated.

**Check 2 — group_by dimension:**
Is `group_by` in the `valid_dimensions` list for this metric? If not →
hardcoded refusal message listing valid dimensions for the requested metric. Stop.

Both refusal messages come from Python directly, not from a second LLM call.
Deterministic, zero-latency, cannot hallucinate.

---

## 8. SQL Compilation — Deterministic Python Layer

F-string templating only. No LLM involvement. No dynamic SQL generation.

**Two different filters are in play here, and the template must keep them separate:**
the measure's own `filter` (part of the metric's *definition* — e.g. `gross_mrr`
always excludes credit notes, non-negotiable, never comes from the user) and the
LLM-extracted `where` (the user's *optional* additional condition — e.g. "for client
C001" — layered on top). They apply at different points: the measure filter scopes
which rows count *toward a specific aggregate*; `where` scopes which rows are visible
to the query *at all*, before any aggregation happens. Collapsing them into one slot
loses the distinction between "this metric's definition" and "what the user asked for
this time."

**Aggregation function names aren't literal SQL keywords in every case** —
`count_distinct` compiles to `COUNT(DISTINCT column)`, not a `COUNT_DISTINCT(column)`
function that doesn't exist. `compiler.py` needs a small mapping from a measure's
`agg` value to how it actually renders in SQL (`sum` → `SUM`, `count`/`average` →
`COUNT`/`AVG`, `count_distinct` → the two-token `COUNT(DISTINCT ...)` form) rather
than assuming `{agg}({column})` always drops in cleanly.

**Simple metric**, using DuckDB's `FILTER (WHERE ...)` clause on the aggregate itself
to apply the measure's own filter — this is what actually lets `gross_mrr` differ from
`net_mrr` despite both aggregating the same `fee_amount_eur` column:
```python
agg_expr = render_agg(agg, column)  # e.g. "SUM(fee_amount_eur)" or "COUNT(DISTINCT client_id)"
measure_filter_clause = f" FILTER (WHERE {filter})" if filter else ""

f"""
SELECT
    DATE_TRUNC('{time_grain}', {time_column}) AS period,
    {group_by},
    {agg_expr}{measure_filter_clause} AS {metric_name}
FROM {source_mart}
{f"WHERE {where}" if where else ""}
GROUP BY 1, 2
ORDER BY 1
"""
```

**Ratio metric** — each side renders its *own* `agg_expr`/filter independently, since
(per Section 3) the two sides can differ in both column and aggregation function:
```python
num_expr = render_agg(numerator["agg"], numerator["column"])
num_filter_clause = f" FILTER (WHERE {numerator['filter']})" if numerator["filter"] else ""
den_expr = render_agg(denominator["agg"], denominator["column"])
den_filter_clause = f" FILTER (WHERE {denominator['filter']})" if denominator["filter"] else ""

f"""
SELECT
    DATE_TRUNC('{time_grain}', {time_column}) AS period,
    {group_by},
    {num_expr}{num_filter_clause} * 1.0
        / NULLIF({den_expr}{den_filter_clause}, 0) AS {metric_name}
FROM {source_mart}
{f"WHERE {where}" if where else ""}
GROUP BY 1, 2
ORDER BY 1
"""
```

`NULLIF(..., 0)` on the denominator prevents division-by-zero. Beyond that and the
`render_agg`/filter-clause construction above, everything else is pure templating —
no LLM involvement, no dynamic SQL generation beyond substituting these already-governed
values.

---

## 9. File Structure

```
streamlit_app/
├── app.py              # UI layer + workflow orchestration only
├── parser.py           # YAML parser — builds lookup table at startup
├── translator.py       # LLM Call 1 — translation + system prompt
├── validator.py        # Guardrail — metric + dimension validation
├── compiler.py         # SQL template compilation
├── interpreter.py      # LLM Call 2 — plain-language interpretation
└── profiles/
    ├── private_capital.yaml   # department config profile
    └── risk.yaml
```

**Workflow in `app.py`:**
```python
context = parser.load_governed_context()        # reads sem_*.yml at startup
json_output = translator.translate(user_question, context)
result = validator.validate(json_output, context)
if result.is_refused:
    display(result.refusal_message)
else:
    sql = compiler.compile(result.query_spec)
    raw = duckdb.execute(sql)
    interpretation = interpreter.interpret(raw)
    display(interpretation, sql, raw)
```

---

## 10. Learning Contract — Who Writes What

This section governs the build session discipline in CC.

| Component | Who writes first | CC role |
|---|---|---|
| `translator.py` | Kris writes system prompt + LLM Call 1 structure | CC validates, corrects |
| `interpreter.py` | Kris writes LLM Call 2 prompt + response handling | CC validates, corrects |
| `parser.py` | Kris writes pseudocode for YAML extraction logic | CC gives skeleton, Kris fills blanks |
| `validator.py` | Kris writes pseudocode for guardrail logic | CC gives skeleton, Kris fills blanks |
| `compiler.py` | Kris writes pseudocode for SQL templates | CC gives skeleton, Kris fills blanks |
| `app.py` | CC scaffolds Streamlit layout + imports | Kris fills in workflow orchestration |
| Trust/verify Obsidian note | Kris writes entirely | CC never touches |

**Evaluation dimensions for CC when reviewing Kris's first attempts:**
1. Correctness — does the logic produce the right output given the spec?
2. Trap avoidance — has an edge case been missed?
3. Separation of concerns — is business logic leaking into the wrong module?

---

## 11. Streamlit UI Spec

### Base interface
- Text input: user types a natural-language question
- Submit button
- Result area: plain-language interpretation from LLM Call 2
- Expandable "SQL used" section: compiled SQL — deliberate trust signal, not hidden
- Expandable "Raw result" section: DuckDB result table before interpretation

### Department config profiles (Version A — static YAML, build first)
Sidebar dropdown selects a department profile. Each profile is a YAML file:

```yaml
# profiles/private_capital.yaml
title: "Private Capital Analytics"
description: "Fee revenue and client retention metrics for the PC team."
accent_color: "#009464"
suggested_questions:
  - "What was gross MRR last quarter by client?"
  - "Which clients churned in the last 6 months?"
  - "Show me credit note ratio by service this year."
```

To add a department: write a new YAML file. No code changes required.

### Version B — LLM-generated config (add after Version A ships)
Department describes reporting needs in natural language. LLM generates config JSON
conforming to profile schema. Python validates against schema before rendering.
Same governance principle as the metric guardrail — LLM classifies, Python validates,
rendering is deterministic. Build only if Version A is stable and time allows.

---

## 12. Deployment

- **Target:** Streamlit Community Cloud (free tier)
- **Repo:** `pc_pipeline` — `main` branch, `streamlit_app/` directory
- **Database:** DuckDB file committed to repo. Synthetic data only — no confidentiality risk
- **Build order:**
  1. Build and test agent locally against DuckDB
  2. Deploy base Streamlit app to Streamlit Community Cloud
  3. Verify live URL works end-to-end
  4. Add department config profiles (Version A)
  5. Add LLM config generation (Version B) if time allows

---

## 13. v3 Roadmap (out of scope for v2)

- **Snowflake migration** → one connection string change; agent is warehouse-agnostic
- **`fee_yield` metric** → requires Snowflake + MetricFlow runtime or pre-joined mart;
  excluded from v2 because the workaround (Option C separate template) adds complexity
  without demonstrating anything new architecturally
- **Structured input mode toggle** → a "build a query" mode alongside the natural
  language interface; user selects metric, group_by, time grain, and filter from
  dropdowns rather than typing a question. No LLM call needed in this mode — Python
  compiles SQL directly from the UI selections. Demonstrates that the LLM translation
  layer is a deliberate choice for natural language handling, not a dependency of the
  governance architecture itself. The governed lookup table, validation, and SQL
  compilation are identical in both modes — the LLM is the translation layer only,
  not the governance layer. Two-line UI addition in Streamlit; the backend is unchanged.
- **FastAPI extraction** → expose agent as REST API on GCP Cloud Run
- **LLM config generation hardening** → tighter schema, validation, error handling
- **Dynamic prompt injection** → already designed for v2 (governed_metrics_list injected
  at runtime); v3 extends to dimension lists per metric

---

## 14. Trust / Verify Framework (Obsidian write-up — drafted post-build)

Content outline for the Obsidian note in Modern Stack vault:

**Where the agent is trusted:**
- Governed metric definitions — lookup table is the single source of truth, derived
  from YAML at startup, not hardcoded
- SQL compilation — deterministic, not LLM-generated, auditable by inspection
  (shown in "SQL used" expander in UI)
- Known grain — marts encode grain explicitly; agent cannot query at wrong grain
  because it only queries marts, not staging or intermediate models
- Refusal behavior — ungoverned metric names and invalid dimensions are caught before
  any SQL executes; refusal messages are deterministic Python, not LLM-generated

**Where the agent is verified:**
- LLM translation accuracy — does extracted JSON actually match user intent?
  Edge cases: ambiguous metric names, compound questions, multi-metric requests
- Filter conditions — LLM-extracted WHERE clauses passed through to SQL without
  sanitization in v2; acceptable for local PoC, needs parameterized queries in production
- Time grain inference — "last quarter" is ambiguous (calendar quarter vs. rolling 90
  days); agent defaults to calendar truncation
- Novel calculations — questions not mapping to a single governed metric (cross-metric
  ratios, period-over-period comparisons, ranking) should be refused, not approximated
- Cross-model metrics — `fee_yield` and any future cross-model metric are outside v2
  governed boundary; correctly refused with explanation

**The core principle:**
Trust the agent where the answer is determined by governed definitions upstream.
Verify the agent where the answer requires novel reasoning at query time.
Complexity governed upstream, not generated on the fly.

---

## 15. CC Session Opening Checklist

1. Read `docs/v2_ai_agent_spec.md` (this file) first
2. Read `docs/data_spec_v2.md` for mart schema reference
3. Read `sem_*.yml` files to understand semantic model structure before touching parser.py
4. Confirm `feature/v2-semantic-layer` merged to `main`
5. Confirm `feature/v2-ai-agent` branch created off `main`
6. Confirm DuckDB file present and `dbt build` passes on `main`
7. Create `streamlit_app/` directory as working directory for this branch
8. Create empty `docs/v2_ai_agent.md` — learning notes go here as build progresses
9. State planned file structure and creation order before writing any code
   (per CLAUDE.md "flag divergence immediately" rule)
