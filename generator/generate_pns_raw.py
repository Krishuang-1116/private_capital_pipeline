"""
generate_pns_raw.py — synthetic monthly deal pipeline extract.

Consumes ``shared_state.rng`` FIRST in the fixed generator order (pns_raw,
then client_db_raw — see shared_state.py docstring). Every random draw in
this file must happen before generate_client_db_raw.py runs, or the RNG
stream shifts and output stops being reproducible run-to-run.

Design notes not pinned down by the spec (documented here, not silently
assumed):
  - deal_status progression is a simple per-deal Markov-style trajectory
    (see build_status_trajectory) — the spec gives allowed values and
    terminal semantics but not a transition model.
  - Most deal-level attributes (deal_qualification, fund_structuration,
    financial_sponsor, fund_jurisdiction, owner, service columns) are drawn
    once per deal and held constant across snapshots ("sticky"), since
    nothing in the spec suggests a business reason for a client-facing
    service scope to change monthly. Measures (asset, revenue) and
    deal_status are redrawn/advanced per snapshot.
  - Schema evolution (Defect 3) is modeled as one wide CSV: pre-cutover rows
    populate real_estate/infrastructure and leave the six post-cutover-era
    columns null; post-cutover rows populate the post-cutover column set and
    leave real_estate/infrastructure null. Backfill resolution itself is
    staging-layer logic, not generated here.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from shared_state import (
    rng,
    SNAPSHOTS,
    CUTOVER_DATE,
    TOTAL_DEALS,
    LOCATIONS,
    DEAL_COHORTS,
    CLIENT_ROSTER,
    CLIENT_BY_ID,
    COLLISION_PAIRS,
    UNMATCHED_CLIENT_NAMES,
    FUND_NAME_MUTATIONS,
    UNRESOLVABLE_STRATEGY_DEALS,
    GENUINE_CHANGE_DEALS,
    TERMINAL_MEASURE_GAPS,
    SCD_CLIENT_IDS,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_OUT = REPO_ROOT / "data" / "raw" / "pns_raw.csv"
SEED_OUT = REPO_ROOT / "seeds" / "fund_name_corrections.csv"
MANIFEST_OUT = REPO_ROOT / "data" / "raw" / "pns_raw_manifest.json"

# ── Column enumerations (local to pns_raw; not shared with client_db_raw) ────

CLIENT_TYPES = ["AO", "AO-Insurance", "AO-Pension Funds", "AO-SWF", "GP-Direct", "GP-FoF"]
DEAL_TYPES = ["Solicitation", "Formal process - RFP or RFI"]
DEAL_QUALIFICATIONS = ["New fund launch", "Prospective approach", "Existing fund migration", "TBD"]
FUND_STRUCTURATIONS = ["Closed-end fund", "Open-end fund", "Hybrid", "Institutional Evergreen"]
FUND_JURISDICTIONS = [
    "France", "Spain", "Luxembourg", "Italy", "Cayman Islands", "Singapore",
    "Hong Kong", "Others", "Australia", "United Kingdom", "United States",
    "Germany", "Channel Islands", "TBD",
]
OWNER_INITIALS = ["JDM", "KZ", "DL", "MR", "PB", "AS", "TC", "RH", "EW", "NF"]
LOSS_REASONS = [
    "Other reasons", "Pricing", "Client abandoned", "Initiative postponed or cancelled",
    "Product gap", "Incumbent provider selected", "Timing", "AML or KYC process", "Below Threshold",
]

STRATEGY_4 = ["Yes", "No", "TBD", "tbd"]
YES_NO_TBD = ["Yes", "No", "TBD"]
SFDR_VALUES = ["Article 8", "Article 9", "No", "TBD"]
LISTED_ASSETS_VALUES = ["Yes", "No", "TBD", "Yes (1 listed asset)", "tbd"]

FUND_NAME_STEMS = [
    "Orion", "Meridian", "Vantage", "Solstice", "Ironbridge", "Coastal", "Helix",
    "Pinnacle", "Summit", "Artemis", "Polaris", "Luminary", "Thornfield", "Redwood",
    "Constellation", "Equinox", "Harbinger", "Zenith", "Sterling", "Beacon",
    "Anchor", "Crown", "Falcon", "Granite", "Horizon", "Juniper",
]
FUND_NAME_SUFFIXES = [
    "Fund", "Fund II", "Fund III", "Capital Partners Fund", "Growth Fund",
    "Real Estate Fund", "Infrastructure Fund", "Credit Fund", "Opportunities Fund",
]

COLLISION_ALIAS_STRINGS = {p["collision_alias"] for p in COLLISION_PAIRS}

NONTERMINAL_SOLICITATION = ["Under analysis", "Fee proposal sent"]
NONTERMINAL_FORMAL = ["Upcoming RFP", "Submitted RFP", "Under analysis", "Fee proposal sent"]
TERMINAL_STATUSES = ["Won", "Lost", "Rejected"]
TERMINAL_WEIGHTS = [0.5, 0.35, 0.15]

# Post-cutover-era columns (present only on reporting_date >= CUTOVER_DATE rows)
POST_CUTOVER_STRATEGY_COLS = [
    "real_estate_equity", "real_estate_debt", "infrastructure_equity", "infrastructure_debt",
    "listed_assets_in_portfolio", "OTC_instruments_in_portfolio",
]
# Pre-cutover-era columns (present only on reporting_date < CUTOVER_DATE rows)
PRE_CUTOVER_STRATEGY_COLS = ["real_estate", "infrastructure"]

FIELDNAMES = [
    "reporting_date", "location", "client_name", "fund_name",
    "client_type", "client_nature", "deal_type", "deal_qualification", "deal_status",
    "fund_structuration", "financial_sponsor", "fund_jurisdiction", "owner",
    "expected_outcome_date", "main_reason_for_loss",
    "private_equity", "private_debt",
    *PRE_CUTOVER_STRATEGY_COLS, *POST_CUTOVER_STRATEGY_COLS,
    "Depositary", "Custody", "Transfer_Agency", "Fund_Administration", "Corporate_Secretary",
    "Middle_Office_Investor_Reporting", "Middle_Office_Portfolio_Monitoring",
    "Middle_Office_Loan_Administration", "Middle_Office_Collateral_Management",
    "Other_MO_services", "digital_reporting_platform", "SFDR_eligibility",
    "asset", "revenue", "currency",
]


def draw(options, weights=None, null_rate=0.0):
    if null_rate and rng.random() < null_rate:
        return None
    if weights is None:
        return rng.choice(options)
    return rng.choice(options, p=weights)


def is_pre_cutover_deal(i: int) -> bool:
    return DEAL_COHORTS[i] < CUTOVER_DATE


def deal_snapshot_list(i: int) -> list:
    entry = DEAL_COHORTS[i]
    return [s for s in SNAPSHOTS if s >= entry]


# ── Reservation: assign special-defect deals without disturbing others ───────

_shuffled = iter(rng.permutation(TOTAL_DEALS).tolist())
_reserved: set[int] = set()


def reserve(n: int, cohort_filter=None) -> list[int]:
    picked = []
    while len(picked) < n:
        idx = next(_shuffled)
        if idx in _reserved:
            continue
        if cohort_filter and not cohort_filter(idx):
            continue
        _reserved.add(idx)
        picked.append(idx)
    return picked


collision_idx = reserve(len(COLLISION_PAIRS))
unmatched_idx = reserve(len(UNMATCHED_CLIENT_NAMES))
mutation_idx = reserve(len(FUND_NAME_MUTATIONS))
unresolvable_idx = reserve(len(UNRESOLVABLE_STRATEGY_DEALS), is_pre_cutover_deal)
terminal_gap_idx = reserve(len(TERMINAL_MEASURE_GAPS))

genuine_change_idx = []
for entry in GENUINE_CHANGE_DEALS:
    flt = (lambda i: not is_pre_cutover_deal(i)) if entry["cohort"] == "post_cutover" else None
    genuine_change_idx.append(reserve(1, flt)[0])

# Transfer_Agency rogue-value deals (pre-cutover rows only) — not a hardcoded
# shared_state constant since it's a pure statistical injection, not a
# branch-mix defect requiring precise control.
ta_rogue_pool = [i for i in range(TOTAL_DEALS) if is_pre_cutover_deal(i)]
ta_rogue_deals = rng.choice(ta_rogue_pool, size=6, replace=False)
ta_rogue_values = {}
for n, i in enumerate(ta_rogue_deals):
    ta_rogue_values[int(i)] = "FATCA" if n % 2 == 0 else "B7765"

# One Aug-2025-cohort deal per SCD client, so the client's Prospect->Existing
# transition (decided later, by generate_client_db_raw.py) always has fact
# data spanning it. Deal client assignment happens here, before client_db_raw
# picks transition dates — without a guaranteed early-cohort deal, a client
# with only a couple of deals could easily end up with none of them predating
# its transition, leaving the SCD scenario dimensionally present but
# untestable against fact data.
scd_coverage_idx = reserve(len(SCD_CLIENT_IDS), lambda i: DEAL_COHORTS[i] == SNAPSHOTS[0])
scd_coverage_map = {idx: SCD_CLIENT_IDS[k] for k, idx in enumerate(scd_coverage_idx)}

collision_map = {idx: COLLISION_PAIRS[k] for k, idx in enumerate(collision_idx)}
unmatched_map = {idx: UNMATCHED_CLIENT_NAMES[k] for k, idx in enumerate(unmatched_idx)}
mutation_map = {idx: FUND_NAME_MUTATIONS[k] for k, idx in enumerate(mutation_idx)}
unresolvable_map = {idx: UNRESOLVABLE_STRATEGY_DEALS[k] for k, idx in enumerate(unresolvable_idx)}
terminal_gap_map = {idx: TERMINAL_MEASURE_GAPS[k] for k, idx in enumerate(terminal_gap_idx)}
genuine_change_map = {idx: entry for idx, entry in zip(genuine_change_idx, GENUINE_CHANGE_DEALS)}


def build_status_trajectory(snaps: list, deal_type: str) -> list[str]:
    seq = NONTERMINAL_FORMAL if deal_type == "Formal process - RFP or RFI" else NONTERMINAL_SOLICITATION
    statuses, stage, terminal = [], 0, None
    for _ in snaps:
        if terminal:
            statuses.append(terminal)
            continue
        if stage < len(seq):
            statuses.append(seq[stage])
            if rng.random() < 0.35:
                stage += 1
        else:
            terminal = draw(TERMINAL_STATUSES, TERMINAL_WEIGHTS)
            statuses.append(terminal)
    return statuses


# ── Per-deal row construction ────────────────────────────────────────────────

def strategy_pair(has_anchor: bool, force_unresolvable_yes: bool) -> str:
    """Draws a pre-cutover real_estate/infrastructure value respecting the
    'Yes requires a financing anchor' constraint, unless intentionally violated."""
    if force_unresolvable_yes:
        return "Yes"
    options = STRATEGY_4 if has_anchor else ["No", "TBD", "tbd"]
    weights = [0.35, 0.45, 0.15, 0.05] if has_anchor else [0.7, 0.2, 0.1]
    return draw(options, weights)


def build_deal_rows(i: int) -> tuple[list[dict], dict]:
    snaps = deal_snapshot_list(i)
    deal_type = draw(DEAL_TYPES, [0.6, 0.4])

    defect_tags = []
    if i in collision_map:
        defect_tags.append("collision")
    if i in unmatched_map:
        defect_tags.append("unmatched")
    if i in mutation_map:
        defect_tags.append("mutation")
    if i in unresolvable_map:
        defect_tags.append("unresolvable_strategy")
    if i in genuine_change_map:
        defect_tags.append("genuine_change")
    if i in terminal_gap_map:
        defect_tags.append("terminal_gap")
    if i in ta_rogue_values:
        defect_tags.append("ta_rogue")
    if i in scd_coverage_map:
        defect_tags.append("scd_coverage_anchor")

    if i in unmatched_map:
        client = None
        client_name = unmatched_map[i]
    elif i in collision_map:
        entry = collision_map[i]
        client = CLIENT_BY_ID[entry["primary_client_id"]]
        client_name = entry["collision_alias"]
    elif i in mutation_map:
        entry = mutation_map[i]
        client = CLIENT_BY_ID[entry["client_id"]]
        client_name = entry["pns_client_name"]
    elif i in scd_coverage_map:
        client = CLIENT_BY_ID[scd_coverage_map[i]]
        client_name = client["aliases"][0]
    else:
        client = CLIENT_ROSTER[rng.integers(0, len(CLIENT_ROSTER))]
        # Collision aliases are reserved exclusively for their injected
        # collision deal — an ordinary deal must not draw one by chance,
        # or qa_alias_collision balloons past the intended 2-3 rows.
        safe_aliases = [a for a in client["aliases"] if a not in COLLISION_ALIAS_STRINGS]
        client_name = safe_aliases[rng.integers(0, len(safe_aliases))]

    client_type = draw(CLIENT_TYPES, null_rate=0.03) if client is None else draw([client["client_type"]], null_rate=0.03)
    client_nature = "TBD" if i in unmatched_map else draw(["Prospect", "Existing", "TBD"], [0.40, 0.55, 0.05])

    location = draw(LOCATIONS)
    deal_qualification = draw(DEAL_QUALIFICATIONS, [0.35, 0.30, 0.15, 0.20], null_rate=0.27)
    fund_structuration = draw(FUND_STRUCTURATIONS, null_rate=0.47)
    financial_sponsor = draw(YES_NO_TBD, [0.5, 0.3, 0.2], null_rate=0.96)
    fund_jurisdiction = draw(FUND_JURISDICTIONS, null_rate=0.01)
    owner = draw(OWNER_INITIALS, null_rate=0.13)

    # Fund name (base). Mutation deals override with dirty/canonical pair below.
    fund_name_base = f"{draw(FUND_NAME_STEMS)} {draw(FUND_NAME_SUFFIXES)}"

    # Pre-cutover strategy baseline — sticky for the deal's whole pre-cutover run,
    # unless a genuine-change deal touches private_equity/private_debt (applied later).
    private_equity = draw(["Yes", "No", "TBD", "tbd"], [0.42, 0.42, 0.11, 0.05])
    private_debt = draw(["Yes", "No", "TBD", "tbd"], [0.42, 0.42, 0.11, 0.05])
    has_anchor = private_equity == "Yes" or private_debt == "Yes"
    unresolvable = unresolvable_map.get(i)
    real_estate = strategy_pair(has_anchor, unresolvable and unresolvable["unresolvable_column"] == "real_estate")
    infrastructure = strategy_pair(has_anchor, unresolvable and unresolvable["unresolvable_column"] == "infrastructure")
    if unresolvable:
        # Forcing Yes with no anchor is the defect itself — anchor must read No/No.
        private_equity, private_debt = "No", "No"
        has_anchor = False

    # Service columns — sticky per deal.
    depositary = draw(YES_NO_TBD, [0.55, 0.35, 0.10], null_rate=0.01)
    custody = draw(YES_NO_TBD, [0.5, 0.3, 0.2], null_rate=0.90)
    fund_administration = draw(YES_NO_TBD, [0.6, 0.3, 0.1], null_rate=0.07)
    corporate_secretary = draw(["Yes", "No"], [0.4, 0.6], null_rate=0.57)
    mo_investor_reporting = draw(YES_NO_TBD, [0.5, 0.35, 0.15], null_rate=0.12)
    mo_portfolio_monitoring = draw(["No", "TBD"], [0.85, 0.15], null_rate=0.86)
    mo_loan_admin = draw(YES_NO_TBD, [0.4, 0.4, 0.2], null_rate=0.24)
    mo_collateral_mgmt = draw(YES_NO_TBD, [0.35, 0.4, 0.25], null_rate=0.60)
    other_mo_services = draw(YES_NO_TBD, [0.3, 0.5, 0.2], null_rate=0.54)
    digital_reporting = draw(YES_NO_TBD, [0.55, 0.3, 0.15], null_rate=0.40)
    sfdr_eligibility = draw(SFDR_VALUES, [0.25, 0.1, 0.5, 0.15], null_rate=0.08)
    transfer_agency_baseline = draw(YES_NO_TBD, [0.6, 0.3, 0.1], null_rate=0.12)

    # Post-cutover-cohort deals (never had a legacy schema) draw their own
    # private_equity/private_debt independently instead of carrying a
    # pre-cutover baseline forward.
    if not is_pre_cutover_deal(i):
        private_equity = draw(["Yes", "No", "TBD", "tbd"], [0.42, 0.42, 0.11, 0.05], null_rate=0.01)
        private_debt = draw(["Yes", "No", "TBD", "tbd"], [0.42, 0.42, 0.11, 0.05], null_rate=0.01)

    statuses = build_status_trajectory(snaps, deal_type)
    loss_reason = draw(LOSS_REASONS)

    rows = []
    for snap, status in zip(snaps, statuses):
        pre_era = snap < CUTOVER_DATE
        row = {f: None for f in FIELDNAMES}
        row["reporting_date"] = snap
        row["location"] = location
        row["client_name"] = client_name
        row["fund_name"] = fund_name_base
        row["client_type"] = client_type
        row["client_nature"] = client_nature
        row["deal_type"] = deal_type
        row["deal_qualification"] = deal_qualification
        row["deal_status"] = status
        row["fund_structuration"] = fund_structuration
        row["financial_sponsor"] = financial_sponsor
        row["fund_jurisdiction"] = fund_jurisdiction
        row["owner"] = owner
        row["private_equity"] = private_equity
        row["private_debt"] = private_debt

        if pre_era:
            row["real_estate"] = real_estate
            row["infrastructure"] = infrastructure
        else:
            # Sub-strategy columns: unbackfilled for pre-cutover-cohort deals
            # (null by design — Defect 3); genuinely drawn for post-cutover-
            # cohort deals, where null means "No" per spec §1.1.
            if is_pre_cutover_deal(i):
                for col in POST_CUTOVER_STRATEGY_COLS:
                    row[col] = None
            else:
                row["real_estate_equity"] = draw(STRATEGY_4, [0.3, 0.5, 0.15, 0.05], null_rate=0.60)
                row["real_estate_debt"] = draw(STRATEGY_4, [0.3, 0.5, 0.15, 0.05], null_rate=0.60)
                row["infrastructure_equity"] = draw(STRATEGY_4, [0.3, 0.5, 0.15, 0.05], null_rate=0.60)
                row["infrastructure_debt"] = draw(STRATEGY_4, [0.3, 0.5, 0.15, 0.05], null_rate=0.60)
                row["listed_assets_in_portfolio"] = draw(LISTED_ASSETS_VALUES, [0.25, 0.45, 0.15, 0.1, 0.05], null_rate=0.70)
                row["OTC_instruments_in_portfolio"] = draw(STRATEGY_4, [0.3, 0.5, 0.15, 0.05], null_rate=0.70)

        row["Depositary"] = depositary
        row["Custody"] = custody
        row["Transfer_Agency"] = ta_rogue_values.get(i) if pre_era and i in ta_rogue_values else transfer_agency_baseline
        row["Fund_Administration"] = fund_administration
        row["Corporate_Secretary"] = corporate_secretary
        row["Middle_Office_Investor_Reporting"] = mo_investor_reporting
        row["Middle_Office_Portfolio_Monitoring"] = mo_portfolio_monitoring
        row["Middle_Office_Loan_Administration"] = mo_loan_admin
        row["Middle_Office_Collateral_Management"] = mo_collateral_mgmt
        row["Other_MO_services"] = other_mo_services
        row["digital_reporting_platform"] = digital_reporting
        row["SFDR_eligibility"] = sfdr_eligibility

        if status in ("Won", "Lost", "Rejected"):
            row["expected_outcome_date"] = None
            row["main_reason_for_loss"] = loss_reason if status in ("Lost", "Rejected") else None
        else:
            row["expected_outcome_date"] = None if rng.random() < 0.95 else snap
            row["main_reason_for_loss"] = None

        # Measures — redrawn per snapshot.
        row["asset"] = None if rng.random() < 0.01 else round(float(rng.uniform(0.05, 5.0)), 3)
        row["revenue"] = None if rng.random() < 0.05 else round(float(rng.uniform(50, 5000)), 1)
        row["currency"] = draw(["EUR", "USD", "AUD", "SGD", "UAD"], [0.78, 0.08, 0.05, 0.05, 0.04], null_rate=0.25)

        rows.append(row)

    # Fund-name mutation (Defect 1): dirty before corrected_date, canonical from
    # corrected_date's snapshot onward.
    if i in mutation_map:
        entry = mutation_map[i]
        for r in rows:
            r["fund_name"] = entry["dirty_name"] if r["reporting_date"] < entry["corrected_date"] else entry["canonical_name"]

    # Genuine strategy/service change (spec §2.5): old_value before the change
    # point, new_value from the change point onward.
    if i in genuine_change_map:
        entry = genuine_change_map[i]
        col = entry["column"]
        if len(rows) > 1:
            change_at = int(rng.integers(1, len(rows)))
            for r in rows[:change_at]:
                r[col] = entry["old_value"]
            for r in rows[change_at:]:
                r[col] = entry["new_value"]

    # Terminal deal with a missing measure at latest snapshot (qa_terminal_revenue_asset).
    if i in terminal_gap_map:
        entry = terminal_gap_map[i]
        term_idx = max(1, int(len(rows) * 0.6))
        reason = draw(LOSS_REASONS) if entry["deal_status"] in ("Lost", "Rejected") else None
        for r in rows[term_idx:]:
            r["deal_status"] = entry["deal_status"]
            r["main_reason_for_loss"] = reason
            r["expected_outcome_date"] = None
        last = rows[-1]
        if entry["missing"] in ("asset", "both"):
            last["asset"] = None
        if entry["missing"] in ("revenue", "both"):
            last["revenue"] = None

    meta = {
        "deal_index": i,
        # Ambiguous by design for collision deals — genuinely no single
        # authoritative client_id, which is the point of the defect.
        "client_id": None if i in collision_map else (client["client_id"] if client else None),
        "client_name": client_name,
        "entry_snapshot": snaps[0].isoformat(),
        "snapshots": [s.isoformat() for s in snaps],
        "defect_tags": defect_tags,
    }
    return rows, meta


def main() -> None:
    all_rows: list[dict] = []
    deal_manifest: list[dict] = []
    for i in range(TOTAL_DEALS):
        rows, meta = build_deal_rows(i)
        all_rows.extend(rows)
        deal_manifest.append(meta)

    structural_row_count = len(all_rows)

    # Defect 4 — byte-identical duplicates: ~3% of each snapshot's rows.
    by_snapshot: dict = {}
    for r in all_rows:
        by_snapshot.setdefault(r["reporting_date"], []).append(r)
    dup_rows = []
    duplicated_natural_keys = []
    for snap, snap_rows in by_snapshot.items():
        n_dup = max(1, round(len(snap_rows) * 0.03))
        chosen = rng.choice(len(snap_rows), size=n_dup, replace=False)
        for k in chosen:
            dup_rows.append(dict(snap_rows[k]))
            duplicated_natural_keys.append({
                "reporting_date": snap_rows[k]["reporting_date"].isoformat(),
                "location": snap_rows[k]["location"],
                "client_name": snap_rows[k]["client_name"],
                "fund_name": snap_rows[k]["fund_name"],
            })
    all_rows.extend(dup_rows)

    # Defect 5a — asset as currency-string format ("$0.54bn") on ~15 rows.
    populated_asset_idx = [k for k, r in enumerate(all_rows) if r["asset"] is not None]
    for k in rng.choice(populated_asset_idx, size=min(15, len(populated_asset_idx)), replace=False):
        all_rows[k]["asset"] = f"${all_rows[k]['asset']:.2f}bn"

    # Operational row order: the real file is a monthly roll-up of 7 separate
    # location questionnaires, not a deal-ordered export. Sort by
    # (reporting_date, location) — stable, so within a bucket rows keep their
    # generation order (a duplicate lands right after the row it copied).
    all_rows.sort(key=lambda r: (r["reporting_date"], r["location"]))

    RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
    with RAW_OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for r in all_rows:
            writer.writerow(r)

    SEED_OUT.parent.mkdir(parents=True, exist_ok=True)
    with SEED_OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["dirty_fund_name", "canonical_fund_name", "client_name", "corrected_by", "corrected_date"])
        writer.writeheader()
        for entry in FUND_NAME_MUTATIONS:
            writer.writerow({
                "dirty_fund_name": entry["dirty_name"],
                "canonical_fund_name": entry["canonical_name"],
                "client_name": entry["pns_client_name"],
                "corrected_by": entry["corrected_by"],
                "corrected_date": entry["corrected_date"],
            })

    manifest = {
        "total_rows": len(all_rows),
        "structural_rows": structural_row_count,
        "duplicate_rows": len(dup_rows),
        "deals": deal_manifest,
        "duplicated_natural_keys": duplicated_natural_keys,
    }
    with MANIFEST_OUT.open("w") as f:
        json.dump(manifest, f, indent=2)

    print(f"pns_raw: {len(all_rows)} rows -> {RAW_OUT.relative_to(REPO_ROOT)}")
    print(f"pns_raw_manifest: -> {MANIFEST_OUT.relative_to(REPO_ROOT)}")
    print(f"fund_name_corrections: {len(FUND_NAME_MUTATIONS)} rows -> {SEED_OUT.relative_to(REPO_ROOT)}")
    print(f"  collision deals:     {sorted(collision_idx)}")
    print(f"  unmatched deals:     {sorted(unmatched_idx)}")
    print(f"  mutation deals:      {sorted(mutation_idx)}")
    print(f"  unresolvable deals:  {sorted(unresolvable_idx)}")
    print(f"  genuine-change deals:{sorted(genuine_change_idx)}")
    print(f"  terminal-gap deals:  {sorted(terminal_gap_idx)}")
    print(f"  TA rogue deals:      {sorted(int(x) for x in ta_rogue_deals)}")
    print(f"  duplicate rows injected: {len(dup_rows)}")


if __name__ == "__main__":
    main()
