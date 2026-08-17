"""
generate_client_db_raw.py — synthetic CRM client master extract.

Consumes ``shared_state.rng`` SECOND in the fixed generator order (after
generate_pns_raw.py — see shared_state.py docstring). True joint-stream
reproducibility (one continuous draw sequence across both generators) only
holds when both are run in the same Python process, since each script
re-seeds independently at SEED=42 when run as a standalone `python3 x.py`
invocation. Either way, output is deterministic given the seed.

Design notes not pinned down by the spec (documented here, not silently
assumed):
  - client_key is a plain sequential integer (1..N version rows) — "opaque,
    system-assigned" doesn't require any particular numbering scheme.
  - effective_from for every client's first version row uses a fixed
    "since always" anchor date well before the reporting window, since the
    spec only constrains the *transition* date for SCD clients, not the
    origin date for single-version clients.
  - financial_sponsor / sponsor_evidence / sponsor_confirmed_* are Type 1
    (one value per client_id, held constant across all its version rows) —
    per README framing (spec §6): "financial_sponsor and top_priority are
    maintained as Type 1 attributes."
  - group_id/group_name, hq_country, aum_description: spec defines the
    columns and null rates but not a concrete value pool. Small synthetic
    pools are invented here; not spec-derived.
"""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

from shared_state import (
    rng,
    SNAPSHOTS,
    CLIENT_ROSTER,
    COLLISION_PAIRS,
    SCD_CLIENT_IDS,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_OUT = REPO_ROOT / "data" / "raw" / "client_db_raw.csv"
MANIFEST_OUT = REPO_ROOT / "data" / "raw" / "client_db_raw_manifest.json"

CLIENT_INCEPTION_ANCHOR = date(2015, 1, 1)
# Aligned to the first/second-to-last snapshot (not just "within the
# reporting window") so a transition date can never fall before any fact
# data exists at all — see the scd_coverage_anchor mechanism in
# generate_pns_raw.py, which guarantees an Aug-2025-cohort deal per SCD
# client but only helps if the transition itself is reachable by fact data.
WINDOW_START = SNAPSHOTS[0]
WINDOW_END = SNAPSHOTS[-2]

HQ_COUNTRIES = [
    "France", "Germany", "United Kingdom", "Luxembourg", "Switzerland",
    "Netherlands", "Spain", "Italy", "United States", "Singapore",
    "Hong Kong", "United Arab Emirates", "Australia", "Sweden", "Ireland",
]

GROUP_NAMES = [
    ("G01", "Meridian Holdings Group"), ("G02", "Continental Financial Group"),
    ("G03", "Northbridge Capital Group"), ("G04", "Solstice Holdings"),
    ("G05", "Pinnacle Financial Group"), ("G06", "Cascade Investment Group"),
    ("G07", "Anchor Capital Holdings"), ("G08", "Sterling Group Holdings"),
]

AUM_DESCRIPTIONS = [
    "<€1bn AUM", "€1-5bn AUM", "€5-10bn AUM", "€10-50bn AUM",
    "€50bn+ AUM", "Undisclosed AUM",
]

SPONSOR_INITIALS = ["AS", "TC", "RH", "EW", "NF", "LM", "GK", "VP"]

SPONSOR_EVIDENCE_VALUES = ["internal_watchlist", "group_is_sponsor", "preqin", "manual_research", "pending"]
SPONSOR_EVIDENCE_WEIGHTS = [0.15, 0.15, 0.25, 0.30, 0.15]

FIELDNAMES = [
    "client_key", "client_id", "official_name", "client_type",
    "group_id", "group_name", "hq_country", "aum_description", "top_priority",
    "client_nature", "effective_from", "effective_to", "is_current",
    "financial_sponsor", "sponsor_evidence", "sponsor_confirmed_by", "sponsor_confirmed_date",
    "Alias_1", "Alias_2", "Alias_3",
]

COLLISION_ALIAS_STRINGS = {p["collision_alias"] for p in COLLISION_PAIRS}


def draw(options, weights=None, null_rate=0.0):
    if null_rate and rng.random() < null_rate:
        return None
    if weights is None:
        return rng.choice(options)
    return rng.choice(options, p=weights)


def random_date(start: date, end: date) -> date:
    span = (end - start).days
    return start + timedelta(days=int(rng.integers(0, span + 1)))


def build_aliases(client: dict) -> tuple[str | None, str | None, str | None]:
    aliases = client["aliases"]
    alias_1 = aliases[0]

    def slot(idx: int, null_rate: float) -> str | None:
        if idx >= len(aliases):
            return None
        value = aliases[idx]
        # Collision aliases are load-bearing for qa_alias_collision — they
        # must survive regardless of the normal sparsity roll, or the
        # downstream unpivot loses the fan-out on one side of the pair.
        if value in COLLISION_ALIAS_STRINGS:
            return value
        return None if rng.random() < null_rate else value

    alias_2 = slot(1, null_rate=0.40)  # ~60% populated
    alias_3 = slot(2, null_rate=0.75)  # ~25% populated
    return alias_1, alias_2, alias_3


def build_sponsor_fields(force_evidence: str | None) -> tuple[str, str, str | None, date | None]:
    evidence = force_evidence or draw(SPONSOR_EVIDENCE_VALUES, SPONSOR_EVIDENCE_WEIGHTS)
    if evidence == "pending":
        return "pending", evidence, None, None
    sponsor = draw(["Yes", "No"], [0.35, 0.65])
    confirmed_by = draw(SPONSOR_INITIALS)
    confirmed_date = random_date(date(2024, 1, 1), date(2026, 8, 1))
    return sponsor, evidence, confirmed_by, confirmed_date


def build_client_rows(client: dict, client_key_start: int, force_evidence: str | None) -> tuple[list[dict], int]:
    client_id = client["client_id"]
    if rng.random() < 0.30:
        group_id, group_name = None, None
    else:
        group_id, group_name = GROUP_NAMES[rng.integers(0, len(GROUP_NAMES))]
    hq_country = draw(HQ_COUNTRIES)
    aum_description = draw(AUM_DESCRIPTIONS)
    top_priority = draw(["Yes", "No"], [0.20, 0.80])
    financial_sponsor, sponsor_evidence, sponsor_confirmed_by, sponsor_confirmed_date = build_sponsor_fields(force_evidence)
    alias_1, alias_2, alias_3 = build_aliases(client)

    base = {
        "client_id": client_id,
        "official_name": client["official_name"],
        "client_type": client["client_type"],
        "group_id": group_id,
        "group_name": group_name,
        "hq_country": hq_country,
        "aum_description": aum_description,
        "top_priority": top_priority,
        "financial_sponsor": financial_sponsor,
        "sponsor_evidence": sponsor_evidence,
        "sponsor_confirmed_by": sponsor_confirmed_by,
        "sponsor_confirmed_date": sponsor_confirmed_date,
        "Alias_1": alias_1,
        "Alias_2": alias_2,
        "Alias_3": alias_3,
    }

    key = client_key_start
    if client_id in SCD_CLIENT_IDS:
        transition = random_date(WINDOW_START, WINDOW_END)
        v1 = {**base, "client_key": key, "client_nature": "Prospect",
              "effective_from": CLIENT_INCEPTION_ANCHOR, "effective_to": transition, "is_current": False}
        v2 = {**base, "client_key": key + 1, "client_nature": "Existing",
              "effective_from": transition, "effective_to": None, "is_current": True}
        return [v1, v2], key + 2

    client_nature = draw(["Prospect", "Existing"], [0.35, 0.65])
    v1 = {**base, "client_key": key, "client_nature": client_nature,
          "effective_from": CLIENT_INCEPTION_ANCHOR, "effective_to": None, "is_current": True}
    return [v1], key + 1


def main() -> None:
    all_rows: list[dict] = []
    next_key = 1

    # Guarantee variation across all sponsor_evidence values (spec §3.2):
    # force one client per value among the first N clients, in roster order.
    forced_evidence = {CLIENT_ROSTER[i]["client_id"]: v for i, v in enumerate(SPONSOR_EVIDENCE_VALUES)}

    for client in CLIENT_ROSTER:
        rows, next_key = build_client_rows(client, next_key, forced_evidence.get(client["client_id"]))
        all_rows.extend(rows)

    # Operational order: CRM export sorted by client, oldest version first.
    all_rows.sort(key=lambda r: (r["client_id"], r["effective_from"]))

    RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
    with RAW_OUT.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for r in all_rows:
            writer.writerow(r)

    clients_manifest: dict[str, list[dict]] = {}
    for r in all_rows:
        clients_manifest.setdefault(r["client_id"], []).append({
            "client_key": r["client_key"],
            "effective_from": r["effective_from"].isoformat(),
            "effective_to": r["effective_to"].isoformat() if r["effective_to"] else None,
            "is_current": r["is_current"],
            "client_nature": r["client_nature"],
        })
    manifest = {
        "total_rows": len(all_rows),
        "clients": [
            {"client_id": cid, "versions": sorted(v, key=lambda x: x["effective_from"])}
            for cid, v in clients_manifest.items()
        ],
    }
    with MANIFEST_OUT.open("w") as f:
        json.dump(manifest, f, indent=2)

    scd_rows = [r for r in all_rows if r["client_id"] in SCD_CLIENT_IDS]
    print(f"client_db_raw: {len(all_rows)} rows ({len(CLIENT_ROSTER)} clients, {len(scd_rows)} SCD2 version rows) -> {RAW_OUT.relative_to(REPO_ROOT)}")
    print(f"client_db_raw_manifest: -> {MANIFEST_OUT.relative_to(REPO_ROOT)}")
    evidence_counts = {v: sum(1 for r in all_rows if r["sponsor_evidence"] == v) for v in SPONSOR_EVIDENCE_VALUES}
    print(f"  sponsor_evidence coverage: {evidence_counts}")


if __name__ == "__main__":
    main()
