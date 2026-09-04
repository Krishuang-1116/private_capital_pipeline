"""
validate_outputs.py — Level 1 assertion pass over the generated raw files.

Run after all three generators, before dbt ever sees the data:

    python generator/generate_pns_raw.py
    python generator/generate_client_db_raw.py
    python generator/generate_fee_invoice_raw.py
    python generator/validate_outputs.py

Every assertion here checks something the *generator* is responsible for
getting right — structural invariants, defect injection volumes, era-column
hygiene. It deliberately does NOT re-derive deal identity from client_name
text (alias matching, fund-name canonicalization) the way staging will —
that logic belongs to stg_pns/stg_client/int_pns_deals, written later, and
duplicating it here would mean testing a shadow copy of staging instead of
the raw data. Identity-dependent checks (snapshot population, duplicate
rows, deal-to-client mapping) instead read the ground truth the generators
already know and wrote to *_manifest.json.

Static defect-map constants (COLLISION_PAIRS, FUND_NAME_MUTATIONS, etc.)
are imported directly from shared_state.py rather than duplicated into the
manifests, since they never touch rng and are already the source of truth.

Exits non-zero if any assertion fails.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from shared_state import (
    SNAPSHOTS,
    CUTOVER_DATE,
    DEAL_POPULATION,
    TOTAL_DEALS,
    N_CLIENTS,
    COLLISION_PAIRS,
    UNMATCHED_CLIENT_NAMES,
    FUND_NAME_MUTATIONS,
    UNRESOLVABLE_STRATEGY_DEALS,
    GENUINE_CHANGE_DEALS,
    TERMINAL_MEASURE_GAPS,
    SCD_CLIENT_IDS,
    DIM_SERVICE_ROWS,
    UNRECOGNIZED_SERVICE_ID,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
PNS_CSV = REPO_ROOT / "data" / "raw" / "pns_raw.csv"
PNS_MANIFEST = REPO_ROOT / "data" / "raw" / "pns_raw_manifest.json"
CLIENT_CSV = REPO_ROOT / "data" / "raw" / "client_db_raw.csv"
CLIENT_MANIFEST = REPO_ROOT / "data" / "raw" / "client_db_raw_manifest.json"
CORRECTIONS_SEED = REPO_ROOT / "seeds" / "fund_name_corrections.csv"
FEE_CSV = REPO_ROOT / "data" / "raw" / "fee_invoice_raw.csv"
FEE_MANIFEST = REPO_ROOT / "data" / "raw" / "fee_invoice_raw_manifest.json"
SERVICE_SEED = REPO_ROOT / "seeds" / "dim_service.csv"

POST_CUTOVER_STRATEGY_COLS = [
    "real_estate_equity", "real_estate_debt", "infrastructure_equity", "infrastructure_debt",
]
PRE_CUTOVER_STRATEGY_COLS = ["real_estate", "infrastructure"]

# Mirrors generate_pns_raw.py's own TERMINAL_STATUSES/REPORTING_WINDOW_START —
# not exported from shared_state.py since they're local design choices of
# that one generator, same as this file's own POST/PRE_CUTOVER_STRATEGY_COLS
# above already being a local mirror rather than a shared import.
TERMINAL_STATUSES = ["Won", "Lost", "Rejected"]
REPORTING_WINDOW_START = SNAPSHOTS[0].replace(day=1)
COVERAGE_END = SNAPSHOTS[-1]
SERVICE_IDS = {r["service_id"] for r in DIM_SERVICE_ROWS}

results: list[tuple[bool, str]] = []


def check(condition: bool, label: str, detail: str = "") -> None:
    results.append((condition, f"{label}" + (f" — {detail}" if detail and not condition else "")))


def d(s: str):
    return date.fromisoformat(s) if s else None


def month_end(dt: date) -> date:
    next_month = date(dt.year + 1, 1, 1) if dt.month == 12 else date(dt.year, dt.month + 1, 1)
    return next_month - timedelta(days=1)


def main() -> None:
    if not (PNS_CSV.exists() and CLIENT_CSV.exists() and FEE_CSV.exists() and SERVICE_SEED.exists()):
        print("Raw files missing — run all three generators first.")
        sys.exit(2)

    pns_rows = list(csv.DictReader(open(PNS_CSV)))
    pns_manifest = json.load(open(PNS_MANIFEST))
    client_rows = list(csv.DictReader(open(CLIENT_CSV)))
    client_manifest = json.load(open(CLIENT_MANIFEST))
    fee_rows = list(csv.DictReader(open(FEE_CSV)))
    fee_manifest = json.load(open(FEE_MANIFEST))
    service_seed_rows = list(csv.DictReader(open(SERVICE_SEED)))

    # ── pns_raw: structural ──────────────────────────────────────────────
    check(len(pns_rows) == pns_manifest["total_rows"],
          "pns_raw row count matches its own manifest",
          f"csv={len(pns_rows)} manifest={pns_manifest['total_rows']}")

    expected_structural = sum(DEAL_POPULATION.values())
    check(pns_manifest["structural_rows"] == expected_structural,
          "structural row count matches the growth-model sum",
          f"got={pns_manifest['structural_rows']} expected={expected_structural}")

    dup_rate = pns_manifest["duplicate_rows"] / pns_manifest["structural_rows"]
    check(0.02 <= dup_rate <= 0.04,
          "Defect 4 duplicate rate within ~3% band",
          f"rate={dup_rate:.3%}")

    for dk in pns_manifest["duplicated_natural_keys"]:
        matches = [r for r in pns_rows if r["reporting_date"] == dk["reporting_date"]
                   and r["location"] == dk["location"] and r["client_name"] == dk["client_name"]
                   and r["fund_name"] == dk["fund_name"]]
        check(len(matches) >= 2, "duplicated row present at least twice in CSV", str(dk))

    # Snapshot population: cumulative deal count by entry_snapshot should
    # match the growth model exactly (every deal appears at every snapshot
    # from entry through Aug 2026 — deals never leave the population).
    entry_dates = sorted(d(dl["entry_snapshot"]) for dl in pns_manifest["deals"])
    for snap, expected_cum in DEAL_POPULATION.items():
        actual_cum = sum(1 for e in entry_dates if e <= snap)
        check(actual_cum == expected_cum, f"cumulative deal population at {snap}",
              f"got={actual_cum} expected={expected_cum}")

    check(len(pns_manifest["deals"]) == TOTAL_DEALS, "deal count matches TOTAL_DEALS",
          f"got={len(pns_manifest['deals'])} expected={TOTAL_DEALS}")

    # ── pns_raw: era-column hygiene ──────────────────────────────────────
    pre_rows = [r for r in pns_rows if d(r["reporting_date"]) < CUTOVER_DATE]
    post_rows = [r for r in pns_rows if d(r["reporting_date"]) >= CUTOVER_DATE]

    leaked_post_cols = [r for r in pre_rows if any(r[c] for c in POST_CUTOVER_STRATEGY_COLS)]
    check(len(leaked_post_cols) == 0, "no post-cutover sub-strategy values on pre-cutover rows",
          f"{len(leaked_post_cols)} violations")

    leaked_legacy_cols = [r for r in post_rows if any(r[c] for c in PRE_CUTOVER_STRATEGY_COLS)]
    check(len(leaked_legacy_cols) == 0, "no legacy real_estate/infrastructure values on post-cutover rows",
          f"{len(leaked_legacy_cols)} violations")

    empty_strategy = [r for r in pre_rows if r["private_equity"] == "" or r["private_debt"] == ""
                       or r["real_estate"] == "" or r["infrastructure"] == ""]
    check(len(empty_strategy) == 0, "0% null on the 4 pre-cutover strategy columns",
          f"{len(empty_strategy)} rows with a blank")

    # ── pns_raw: TA rogue values confined to pre-cutover ─────────────────
    rogue_post = [r for r in post_rows if r["Transfer_Agency"] in ("FATCA", "B7765")]
    check(len(rogue_post) == 0, "Transfer_Agency rogue values only in pre-cutover rows",
          f"{len(rogue_post)} leaked into post-cutover rows")

    # ── pns_raw: status_change_date (v2 spec §1) ──────────────────────────
    sc_mismatch = [r for r in pns_rows
                   if (r["deal_status"] in TERMINAL_STATUSES) != bool(r["status_change_date"])]
    check(len(sc_mismatch) == 0, "status_change_date populated iff that row's deal_status is terminal",
          f"{len(sc_mismatch)} violations")

    sc_null_rate = sum(1 for r in pns_rows if not r["status_change_date"]) / len(pns_rows)
    check(0.5 <= sc_null_rate <= 0.7, "status_change_date row-level null rate near spec's ~60%",
          f"rate={sc_null_rate:.1%}")

    # Per-deal: the manifest's recorded status_change_date must actually show
    # up on that deal's own first_terminal_snapshot row in the CSV, and fall
    # within [REPORTING_WINDOW_START, first_terminal_snapshot]. Membership,
    # not exact-match, on (client_name, reporting_date) — client_name is not
    # unique per deal (a client can carry several deals sharing the same
    # alias text, confirmed concretely for deal_index 0/52 both "Vantage
    # Infrastructure"), so other deals' unrelated rows can share the same
    # candidate set. Membership still correctly catches a real mismatch,
    # since this deal's own row is always included in the candidates.
    sc_not_found = []
    sc_bounds_violations = []
    for dl in pns_manifest["deals"]:
        if dl["status_change_date"] is None:
            continue
        candidates = {r["status_change_date"] for r in pns_rows
                      if r["client_name"] == dl["client_name"]
                      and r["reporting_date"] == dl["first_terminal_snapshot"]}
        if dl["status_change_date"] not in candidates:
            sc_not_found.append((dl["deal_index"], candidates))
        sc_date = d(dl["status_change_date"])
        fts = d(dl["first_terminal_snapshot"])
        if not (REPORTING_WINDOW_START <= sc_date <= fts):
            sc_bounds_violations.append(dl["deal_index"])
    check(len(sc_not_found) == 0,
          "manifest's status_change_date is present on that deal's own first_terminal_snapshot row",
          str(sc_not_found[:3]))
    check(len(sc_bounds_violations) == 0,
          "status_change_date within [REPORTING_WINDOW_START, first_terminal_snapshot]",
          str(sc_bounds_violations[:5]))

    # ── pns_raw manifest: v2 per-deal fields (true_client_id, terminal_status,
    # first_terminal_snapshot, service_flags_at_terminal) ─────────────────
    tci_bad = [dl["deal_index"] for dl in pns_manifest["deals"]
               if (dl["true_client_id"] is None) != ("unmatched" in dl["defect_tags"])]
    check(len(tci_bad) == 0, "true_client_id is null iff the deal is tagged unmatched",
          f"deal_index(es): {tci_bad[:5]}")

    collision_primary_by_alias = {p["collision_alias"]: p["primary_client_id"] for p in COLLISION_PAIRS}
    collision_bad = [
        dl["deal_index"] for dl in pns_manifest["deals"]
        if "collision" in dl["defect_tags"]
        and dl["true_client_id"] != collision_primary_by_alias.get(dl["client_name"])
    ]
    check(len(collision_bad) == 0, "collision deals' true_client_id resolves to COLLISION_PAIRS' primary_client_id",
          f"deal_index(es): {collision_bad}")

    terminal_field_bad = [
        dl["deal_index"] for dl in pns_manifest["deals"]
        if not ((dl["terminal_status"] is None) == (dl["status_change_date"] is None)
                == (dl["first_terminal_snapshot"] is None) == (dl["service_flags_at_terminal"] is None))
    ]
    check(len(terminal_field_bad) == 0,
          "terminal_status/status_change_date/first_terminal_snapshot/service_flags_at_terminal all null together or all populated together",
          f"deal_index(es): {terminal_field_bad[:5]}")

    terminal_status_bad = [dl["deal_index"] for dl in pns_manifest["deals"]
                            if dl["terminal_status"] is not None and dl["terminal_status"] not in TERMINAL_STATUSES]
    check(len(terminal_status_bad) == 0, "terminal_status, when populated, is one of TERMINAL_STATUSES",
          f"deal_index(es): {terminal_status_bad}")

    fts_bad = [dl["deal_index"] for dl in pns_manifest["deals"]
               if dl["first_terminal_snapshot"] is not None
               and dl["first_terminal_snapshot"] not in dl["snapshots"]]
    check(len(fts_bad) == 0, "first_terminal_snapshot, when populated, is one of the deal's own snapshots",
          f"deal_index(es): {fts_bad}")

    sfat_bad = [dl["deal_index"] for dl in pns_manifest["deals"]
                if dl["service_flags_at_terminal"] is not None
                and set(dl["service_flags_at_terminal"].keys()) != SERVICE_IDS]
    check(len(sfat_bad) == 0, "service_flags_at_terminal, when populated, has exactly DIM_SERVICE_ROWS' service_ids as keys",
          f"deal_index(es): {sfat_bad}")

    # ── pns_raw: row order is (reporting_date, location) ─────────────────
    keys = [(r["reporting_date"], r["location"]) for r in pns_rows]
    check(keys == sorted(keys), "rows ordered by (reporting_date, location)")

    # ── pns_raw: defect deal counts, by manifest tag ─────────────────────
    tag_counts = Counter(tag for dl in pns_manifest["deals"] for tag in dl["defect_tags"])
    check(tag_counts["collision"] == len(COLLISION_PAIRS), "collision deal count matches COLLISION_PAIRS",
          f"got={tag_counts['collision']} expected={len(COLLISION_PAIRS)}")
    check(tag_counts["unmatched"] == len(UNMATCHED_CLIENT_NAMES), "unmatched deal count matches UNMATCHED_CLIENT_NAMES",
          f"got={tag_counts['unmatched']} expected={len(UNMATCHED_CLIENT_NAMES)}")
    check(tag_counts["mutation"] == len(FUND_NAME_MUTATIONS), "mutation deal count matches FUND_NAME_MUTATIONS",
          f"got={tag_counts['mutation']} expected={len(FUND_NAME_MUTATIONS)}")
    check(tag_counts["unresolvable_strategy"] == len(UNRESOLVABLE_STRATEGY_DEALS),
          "unresolvable-strategy deal count matches UNRESOLVABLE_STRATEGY_DEALS",
          f"got={tag_counts['unresolvable_strategy']} expected={len(UNRESOLVABLE_STRATEGY_DEALS)}")
    check(tag_counts["genuine_change"] == len(GENUINE_CHANGE_DEALS),
          "genuine-change deal count matches GENUINE_CHANGE_DEALS",
          f"got={tag_counts['genuine_change']} expected={len(GENUINE_CHANGE_DEALS)}")
    check(tag_counts["terminal_gap"] >= len(TERMINAL_MEASURE_GAPS),
          "terminal-measure-gap deals at least cover TERMINAL_MEASURE_GAPS (incidental extras from base null rates are expected)",
          f"got={tag_counts['terminal_gap']} minimum={len(TERMINAL_MEASURE_GAPS)}")

    # unresolvable-strategy: content-level check — the actual defect condition
    for dl in pns_manifest["deals"]:
        if "unresolvable_strategy" not in dl["defect_tags"]:
            continue
        deal_rows = [r for r in pns_rows if r["client_name"] == dl["client_name"]
                     and d(r["reporting_date"]) < CUTOVER_DATE]
        hit = any(r["private_equity"] == "No" and r["private_debt"] == "No"
                  and (r["real_estate"] == "Yes" or r["infrastructure"] == "Yes") for r in deal_rows)
        check(hit, f"unresolvable-strategy condition present for deal {dl['deal_index']}", dl["client_name"])

    # ── pns_raw: fund_name_corrections seed covers every mutation ────────
    seed_rows = list(csv.DictReader(open(CORRECTIONS_SEED)))
    seed_pairs = {(s["client_name"], s["dirty_fund_name"]) for s in seed_rows}
    dirty_names_in_csv = {(r["client_name"], r["fund_name"]) for r in pns_rows
                           if r["fund_name"] in {m["dirty_name"] for m in FUND_NAME_MUTATIONS}}
    orphaned = dirty_names_in_csv - seed_pairs
    check(len(orphaned) == 0, "every dirty fund_name in pns_raw is covered by fund_name_corrections",
          f"orphaned: {orphaned}")

    # ── client_db_raw: structural ────────────────────────────────────────
    check(len(client_manifest["clients"]) == N_CLIENTS, "client count matches N_CLIENTS",
          f"got={len(client_manifest['clients'])} expected={N_CLIENTS}")

    all_keys = [v["client_key"] for c in client_manifest["clients"] for v in c["versions"]]
    check(len(all_keys) == len(set(all_keys)), "client_key globally unique")

    scd_count = sum(1 for c in client_manifest["clients"] if len(c["versions"]) == 2)
    check(scd_count == len(SCD_CLIENT_IDS), "SCD2 client count matches SCD_CLIENT_IDS",
          f"got={scd_count} expected={len(SCD_CLIENT_IDS)}")
    non_scd_bad = [c["client_id"] for c in client_manifest["clients"] if len(c["versions"]) not in (1, 2)]
    check(len(non_scd_bad) == 0, "every client has exactly 1 or 2 version rows", str(non_scd_bad))

    for c in client_manifest["clients"]:
        versions = sorted(c["versions"], key=lambda v: v["effective_from"])
        n_current = sum(1 for v in versions if v["is_current"])
        check(n_current == 1, f"exactly one is_current=true for {c['client_id']}", f"got={n_current}")
        check(versions[-1]["effective_to"] is None, f"current version effective_to is null for {c['client_id']}")
        for a, b in zip(versions, versions[1:]):
            check(a["effective_to"] == b["effective_from"],
                  f"contiguous SCD windows for {c['client_id']}",
                  f"{a['effective_to']} != {b['effective_from']}")
        if c["client_id"] in SCD_CLIENT_IDS:
            check(versions[0]["client_nature"] == "Prospect" and versions[-1]["client_nature"] == "Existing",
                  f"{c['client_id']} transitions Prospect->Existing")
            t = d(versions[0]["effective_to"])
            check(date(2025, 8, 1) <= t <= date(2026, 8, 31),
                  f"{c['client_id']} transition date within reporting window", str(t))

    # ── client_db_raw: alias sparsity ────────────────────────────────────
    # Alias_2/Alias_3's population rate is no longer just the raw null_rate
    # roll (~60%/~25%) — build_aliases() also protects any alias a pns_raw
    # deal actually drew as its client_name from being nulled (same
    # protection collision aliases already had), so the true rate runs
    # higher and depends on how many deals happen to use a slot-2/3 alias.
    # Upper bound widened accordingly; ~60%/~25% are floors, not targets.
    a1_missing = [r for r in client_rows if not r["Alias_1"]]
    check(len(a1_missing) == 0, "Alias_1 always populated", f"{len(a1_missing)} blanks")
    a2_rate = sum(1 for r in client_rows if r["Alias_2"]) / len(client_rows)
    a3_rate = sum(1 for r in client_rows if r["Alias_3"]) / len(client_rows)
    check(0.4 <= a2_rate <= 0.95, "Alias_2 population rate at or above ~60% floor", f"rate={a2_rate:.1%}")
    check(0.1 <= a3_rate <= 0.5, "Alias_3 population rate at or above ~25% floor", f"rate={a3_rate:.1%}")

    # ── cross-file: collision aliases present for both parties ───────────
    for pair in COLLISION_PAIRS:
        for cid in (pair["primary_client_id"], pair["secondary_client_id"]):
            row = next(r for r in client_rows if r["client_id"] == cid)
            present = pair["collision_alias"] in (row["Alias_1"], row["Alias_2"], row["Alias_3"])
            check(present, f"{cid} carries collision alias '{pair['collision_alias']}' in client_db_raw")

    # ── cross-file: client_type consistency (pns_raw normal deals vs client_db_raw) ─
    client_type_by_id = {}
    for r in client_rows:
        client_type_by_id.setdefault(r["client_id"], set()).add(r["client_type"])
    mismatches = []
    for dl in pns_manifest["deals"]:
        cid = dl["client_id"]
        if cid is None or cid not in client_type_by_id:
            continue
        deal_rows = [r for r in pns_rows if r["client_name"] == dl["client_name"] and r["client_type"]]
        for r in deal_rows:
            if r["client_type"] not in client_type_by_id[cid]:
                mismatches.append((dl["deal_index"], cid, r["client_type"]))
    check(len(mismatches) == 0, "client_type in pns_raw matches client_db_raw for the same client_id",
          f"{len(mismatches)} mismatches, e.g. {mismatches[:3]}")

    # ── cross-file: SCD clients are actually exercised by fact data ──────
    # Not a full deal->client_key-at-date join (that's staging's job) —
    # just confirms at least one deal tied to each SCD client has snapshots
    # spanning the transition date, so the SCD scenario is genuinely testable.
    for c in client_manifest["clients"]:
        if c["client_id"] not in SCD_CLIENT_IDS:
            continue
        transition = d(sorted(c["versions"], key=lambda v: v["effective_from"])[0]["effective_to"])
        spanning = [
            dl for dl in pns_manifest["deals"]
            if dl["client_id"] == c["client_id"]
            and d(dl["snapshots"][0]) < transition < d(dl["snapshots"][-1])
        ]
        check(len(spanning) > 0, f"at least one pns_raw deal spans {c['client_id']}'s SCD transition ({transition})",
              "no deal found — SCD scenario not exercised by fact data")

    # ── dim_service seed ──────────────────────────────────────────────────
    check(len(service_seed_rows) == len(DIM_SERVICE_ROWS), "dim_service seed row count matches DIM_SERVICE_ROWS",
          f"got={len(service_seed_rows)} expected={len(DIM_SERVICE_ROWS)}")
    seed_content = [(r["service_id"], r["service_name"], r["pns_column_name"]) for r in service_seed_rows]
    expected_content = [(r["service_id"], r["service_name"], r["pns_column_name"]) for r in DIM_SERVICE_ROWS]
    check(seed_content == expected_content, "dim_service seed content matches DIM_SERVICE_ROWS exactly, same order")

    # Guards against a repeat of the SVC-MO/Middle_Office mismatch (data_spec_v2.md
    # §3's correction note): every pns_column_name the seed claims must be a
    # real column in pns_raw.csv.
    pns_columns = set(pns_rows[0].keys()) if pns_rows else set()
    missing_cols = [r["pns_column_name"] for r in DIM_SERVICE_ROWS if r["pns_column_name"] not in pns_columns]
    check(len(missing_cols) == 0, "every dim_service pns_column_name is a real pns_raw.csv column",
          f"missing: {missing_cols}")

    # ── fee_invoice_raw: structural ───────────────────────────────────────
    check(len(fee_rows) == fee_manifest["total_rows"], "fee_invoice_raw row count matches its own manifest",
          f"csv={len(fee_rows)} manifest={fee_manifest['total_rows']}")
    check(fee_manifest["total_rows"] == fee_manifest["base_row_count"] + len(fee_manifest["duplicated_invoice_ids"]),
          "fee_invoice_raw total_rows = base_row_count + Defect A duplicates",
          f"total={fee_manifest['total_rows']} base={fee_manifest['base_row_count']} dup={len(fee_manifest['duplicated_invoice_ids'])}")

    bad_ids = [r["invoice_id"] for r in fee_rows if not re.fullmatch(r"INV-\d{6}-\d{4}", r["invoice_id"])]
    check(len(bad_ids) == 0, "invoice_id matches INV-YYYYMM-NNNN format", f"{len(bad_ids)} malformed")

    fee_dates = [d(r["invoice_date"]) for r in fee_rows]
    check(all(REPORTING_WINDOW_START <= dt <= COVERAGE_END for dt in fee_dates),
          "invoice_date within the reporting window", f"min={min(fee_dates)} max={max(fee_dates)}")

    zero_amount = [r["invoice_id"] for r in fee_rows if float(r["fee_amount_eur"]) == 0]
    check(len(zero_amount) == 0, "no zero-amount fee_amount_eur rows", f"{len(zero_amount)} rows")

    credit_rate = sum(1 for r in fee_rows if float(r["fee_amount_eur"]) < 0) / len(fee_rows)
    check(0.04 <= credit_rate <= 0.14, "Defect E credit-note rate near spec's ~8%", f"rate={credit_rate:.1%}")

    bad_periods = [
        r["invoice_id"] for r in fee_rows
        if d(r["billing_period_start"]).day != 1
        or d(r["billing_period_end"]) != month_end(d(r["billing_period_start"]))
    ]
    check(len(bad_periods) == 0, "billing_period_start/end form one whole calendar month",
          f"{len(bad_periods)} malformed: {bad_periods[:5]}")

    # ── fee_invoice_raw: defect content checks, by manifest tag ──────────
    dup_rate_fee = len(fee_manifest["duplicated_invoice_ids"]) / fee_manifest["base_row_count"]
    check(0.01 <= dup_rate_fee <= 0.06, "Defect A duplicate rate near spec's ~3%", f"rate={dup_rate_fee:.1%}")
    for inv_id in fee_manifest["duplicated_invoice_ids"]:
        matches = [r for r in fee_rows if r["invoice_id"] == inv_id]
        check(len(matches) >= 2, f"duplicated invoice_id {inv_id} present at least twice in CSV")
        if len(matches) >= 2:
            check(matches[0] == matches[1], f"duplicated invoice_id {inv_id} rows are byte-identical")

    late_rate = len(fee_manifest["late_arriving_invoice_ids"]) / fee_manifest["base_row_count"]
    check(0.02 <= late_rate <= 0.09, "Defect C late-arriving rate near spec's ~5%", f"rate={late_rate:.1%}")
    for inv_id in fee_manifest["late_arriving_invoice_ids"]:
        r = next((r for r in fee_rows if r["invoice_id"] == inv_id), None)
        if r is None:
            check(False, f"late-arriving invoice_id {inv_id} present in CSV")
            continue
        lag = (datetime.fromisoformat(r["source_extract_timestamp"]).date() - d(r["invoice_date"])).days
        check(lag > 45, f"late-arriving invoice_id {inv_id} has >45-day extract lag", f"lag={lag}")

    unmatched_rate = len(fee_manifest["unmatched_service_invoice_ids"]) / fee_manifest["total_rows"]
    check(0.01 <= unmatched_rate <= 0.06, "Defect D unrecognized-service rate near spec's ~3%",
          f"rate={unmatched_rate:.1%}")
    for inv_id in fee_manifest["unmatched_service_invoice_ids"]:
        matches = [r for r in fee_rows if r["invoice_id"] == inv_id]
        check(all(r["service_id"] == UNRECOGNIZED_SERVICE_ID for r in matches),
              f"unmatched-service invoice_id {inv_id} carries UNRECOGNIZED_SERVICE_ID")

    unmatched_ids_set = set(fee_manifest["unmatched_service_invoice_ids"])
    stray_service_ids = {
        r["service_id"] for r in fee_rows
        if r["invoice_id"] not in unmatched_ids_set and r["service_id"] not in SERVICE_IDS
    }
    check(len(stray_service_ids) == 0, "every non-Defect-D row carries a real dim_service service_id",
          f"stray: {stray_service_ids}")

    # ── cross-file: fee_invoice_raw only bills services the client's Won ──
    # deal(s) flagged eligible (pns_raw_manifest.json's service_flags_at_terminal,
    # unioned across a client's Won deals), Defect D rows excluded since that
    # defect deliberately corrupts service_id to something dim_service can't
    # even resolve.
    eligible_by_client: dict[str, set[str]] = {}
    for dl in pns_manifest["deals"]:
        if dl["terminal_status"] != "Won" or dl["true_client_id"] is None:
            continue
        cid = dl["true_client_id"]
        eligible = {svc for svc, val in dl["service_flags_at_terminal"].items() if val == "Yes"}
        eligible_by_client.setdefault(cid, set()).update(eligible)

    ineligible_billed = [
        r["invoice_id"] for r in fee_rows
        if r["invoice_id"] not in unmatched_ids_set
        and r["service_id"] not in eligible_by_client.get(r["client_id"], set())
    ]
    check(len(ineligible_billed) == 0, "no fee_invoice_raw row bills a service the client wasn't flagged eligible for",
          f"{len(ineligible_billed)} rows, e.g. {ineligible_billed[:5]}")

    # ── report ─────────────────────────────────────────────────────────
    n_fail = sum(1 for ok, _ in results if not ok)
    for ok, label in results:
        print(f"[{'PASS' if ok else 'FAIL'}] {label}")
    print(f"\n{len(results) - n_fail}/{len(results)} checks passed.")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
