"""
generate_fee_invoice_raw.py — synthetic billing-system invoice-line extract.

Consumes ``shared_state.rng`` THIRD in the fixed generator order (after
generate_pns_raw.py and generate_client_db_raw.py). Note: as documented in
generate_client_db_raw.py's own docstring, each generator script re-seeds
``rng`` independently at SEED=42 when run as a standalone `python3 x.py`
invocation, so "runs third" is a data dependency, not an RNG-ordering one —
this script reads pns_raw_manifest.json (Won population, service coverage,
status_change_date), which must already reflect the current pns_raw.csv.
It does not read client_db_raw.csv at all; nothing in v2 spec §2 needs a
client attribute beyond client_id itself.

Design notes not pinned down by the spec (documented here, not silently
assumed):
  - Won population and service eligibility come from pns_raw_manifest.json's
    `true_client_id` / `service_flags_at_terminal` fields (added this
    session specifically for this script) — not re-derived by re-parsing
    pns_raw.csv, and not from dim_deal/int_pns_deals (a different source
    system's own identity-resolution problem; see this session's true_client_id
    discussion in docs/v2_generator_models.md once written).
  - A client with multiple Won deals: billing starts from the *earliest*
    status_change_date across all of them (spec §2.5), and is eligible for
    the *union* of services flagged Yes across all of them — spec describes
    "the Won deal's service columns" at deal grain, but fee_invoice_raw's own
    grain has no deal_id at all (§2.2), so client-level union is the only
    coherent reading once a client can have more than one Won deal.
  - Billing periods are calendar months, `billing_period_start`/`_end` are
    that month's first/last day. Not every (client, eligible service,
    period) combination gets an invoice — a random subset per client is
    sampled to hit spec's ~4-5 invoices/client volume target (§2.5).
  - Defect E (credit notes, §2.4) has no dedicated injection bullet in §2.5
    the way A/C/D do — it's baked into fee_amount_eur's draw at generation
    time (~8% of rows drawn negative), not a post-hoc mutation of a subset.
  - Defect order follows §2.5's listed order exactly: C (late-arriving),
    then A (duplicate), then D (unrecognized service_id) — each selects its
    ~N% from whatever the row population is at that point in the pipeline.
  - invoice_id (`INV-YYYYMM-NNNN`) is assigned after sorting rows by
    invoice_date, so NNNN increases with real issuance order within a month
    — the realistic reading of "system-assigned."
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from shared_state import rng, SNAPSHOTS, DIM_SERVICE_ROWS, UNRECOGNIZED_SERVICE_ID

REPO_ROOT = Path(__file__).resolve().parent.parent
PNS_MANIFEST_IN = REPO_ROOT / "data" / "raw" / "pns_raw_manifest.json"
RAW_OUT = REPO_ROOT / "data" / "raw" / "fee_invoice_raw.csv"
MANIFEST_OUT = REPO_ROOT / "data" / "raw" / "fee_invoice_raw_manifest.json"

COVERAGE_END = SNAPSHOTS[-1]  # 2026-08-31
SERVICE_IDS = [r["service_id"] for r in DIM_SERVICE_ROWS]

FEE_BASIS_OPTIONS = ["AUM", "commitment", "NAV", "flat"]
FEE_BASIS_WEIGHTS = [0.45, 0.25, 0.15, 0.15]

FIELDNAMES = [
    "invoice_id", "client_id", "service_id", "invoice_date",
    "source_extract_timestamp", "billing_period_start", "billing_period_end",
    "fee_amount_eur", "fee_basis", "is_paid",
]


def month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def month_after(d: date) -> date:
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def month_end(d: date) -> date:
    return month_after(d) - timedelta(days=1)


def billing_periods(start: date, end: date) -> list[tuple[date, date]]:
    periods = []
    cur = month_start(start)
    while cur <= end:
        periods.append((cur, month_end(cur)))
        cur = month_after(cur)
    return periods


# ── 1. Load the Won population + service eligibility from pns_raw's manifest ─

manifest = json.loads(PNS_MANIFEST_IN.read_text())
won_deals = [
    d for d in manifest["deals"]
    if d["terminal_status"] == "Won" and d["true_client_id"] is not None
]

by_client: dict[str, dict] = {}
for d in won_deals:
    cid = d["true_client_id"]
    entry = by_client.setdefault(cid, {"status_change_dates": [], "eligible_services": set()})
    entry["status_change_dates"].append(date.fromisoformat(d["status_change_date"]))
    for svc_id, val in d["service_flags_at_terminal"].items():
        if val == "Yes":
            entry["eligible_services"].add(svc_id)

# ── 2. Per client: billing window + candidate (service, period) pairs ────────

client_plan: dict[str, dict] = {}
for cid, entry in by_client.items():
    earliest = min(entry["status_change_dates"])
    start = month_after(earliest)
    if start > COVERAGE_END:
        continue  # won too close to the end of the reporting window to bill
    periods = billing_periods(start, COVERAGE_END)
    eligible = sorted(entry["eligible_services"])
    if not eligible or not periods:
        continue
    client_plan[cid] = {"periods": periods, "eligible_services": eligible}

# ── 3. Generate base invoice lines ────────────────────────────────────────────

rows: list[dict] = []
for cid, plan in client_plan.items():
    candidates = [(svc, per) for svc in plan["eligible_services"] for per in plan["periods"]]
    n = min(int(rng.integers(3, 7)), len(candidates))
    chosen_idx = rng.choice(len(candidates), size=n, replace=False)
    for idx in chosen_idx:
        svc_id, (period_start, period_end) = candidates[idx]
        invoice_date = min(COVERAGE_END, period_end + timedelta(days=int(rng.integers(1, 16))))
        extract_ts = datetime.combine(invoice_date, datetime.min.time()) + timedelta(
            hours=float(rng.uniform(0, 48))
        )
        is_credit_note = rng.random() < 0.08
        amount = round(float(rng.uniform(1000, 45000)), 2)
        if is_credit_note:
            amount = -amount

        rows.append({
            "client_id": cid,
            "service_id": svc_id,
            "invoice_date": invoice_date,
            "source_extract_timestamp": extract_ts,
            "billing_period_start": period_start,
            "billing_period_end": period_end,
            "fee_amount_eur": amount,
            "fee_basis": rng.choice(FEE_BASIS_OPTIONS, p=FEE_BASIS_WEIGHTS),
            "is_paid": bool(rng.random() < 0.80),
        })

# ── 4. Assign invoice_id in issuance order (sorted by invoice_date) ──────────

rows.sort(key=lambda r: (r["invoice_date"], r["client_id"], r["service_id"]))
counters: dict[str, int] = defaultdict(int)
for r in rows:
    yyyymm = r["invoice_date"].strftime("%Y%m")
    counters[yyyymm] += 1
    r["invoice_id"] = f"INV-{yyyymm}-{counters[yyyymm]:04d}"

base_row_count = len(rows)

# ── 5. Defect C — late-arriving rows: ~5%, shift source_extract_timestamp ────
# forward by 46-90 days, invoice_date untouched.

late_arriving_ids: list[str] = []
n_late = max(1, round(base_row_count * 0.05))
late_idx = rng.choice(base_row_count, size=n_late, replace=False)
for idx in late_idx:
    r = rows[idx]
    r["source_extract_timestamp"] += timedelta(days=int(rng.integers(46, 91)))
    late_arriving_ids.append(r["invoice_id"])

# ── 6. Defect A — duplicate rows: ~3%, byte-identical copy under the same ────
# invoice_id (including whatever Defect C already did to that row).

duplicated_ids: list[str] = []
n_dup = max(1, round(base_row_count * 0.03))
dup_idx = rng.choice(base_row_count, size=n_dup, replace=False)
for idx in dup_idx:
    rows.append(dict(rows[idx]))
    duplicated_ids.append(rows[idx]["invoice_id"])

# ── 7. Defect D — unrecognized service_id: ~3% of the current row population ─
# (post-duplication), replaced with a code absent from dim_service.

unmatched_service_ids: list[str] = []
final_row_count = len(rows)
n_unmatched = max(1, round(final_row_count * 0.03))
unmatched_idx = rng.choice(final_row_count, size=n_unmatched, replace=False)
for idx in unmatched_idx:
    rows[idx]["service_id"] = UNRECOGNIZED_SERVICE_ID
    unmatched_service_ids.append(rows[idx]["invoice_id"])

# ── 8. Write outputs ──────────────────────────────────────────────────────────

RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
with RAW_OUT.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
    writer.writeheader()
    for r in rows:
        out = dict(r)
        out["invoice_date"] = r["invoice_date"].isoformat()
        out["billing_period_start"] = r["billing_period_start"].isoformat()
        out["billing_period_end"] = r["billing_period_end"].isoformat()
        out["source_extract_timestamp"] = r["source_extract_timestamp"].isoformat(sep=" ")
        out["is_paid"] = "true" if r["is_paid"] else "false"
        writer.writerow(out)

manifest_out = {
    "total_rows": final_row_count,
    "base_row_count": base_row_count,
    "won_client_count": len(client_plan),
    "duplicated_invoice_ids": duplicated_ids,
    "late_arriving_invoice_ids": late_arriving_ids,
    "unmatched_service_invoice_ids": unmatched_service_ids,
}
MANIFEST_OUT.write_text(json.dumps(manifest_out, indent=2))

print(f"fee_invoice_raw: {final_row_count} rows -> {RAW_OUT}")
print(f"fee_invoice_raw_manifest: -> {MANIFEST_OUT}")
print(f"  base rows (pre-defect):   {base_row_count}")
print(f"  Won clients billed:       {len(client_plan)}")
print(f"  duplicated (Defect A):    {len(duplicated_ids)}")
print(f"  late-arriving (Defect C): {len(late_arriving_ids)}")
print(f"  unmatched service (Defect D): {len(unmatched_service_ids)}")
