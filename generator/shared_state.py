"""
shared_state.py — single source of truth for all constants, the snapshot
calendar, and the client roster shared by generate_pns_raw.py and
generate_client_db_raw.py.

RNG discipline
--------------
One global ``rng`` instance, seeded at 42.  Generators must consume it
in a fixed order (pns_raw first, client_db_raw second) to guarantee
identical output across runs.

The CLIENT_ROSTER, COLLISION_PAIRS, UNMATCHED_CLIENT_NAMES, and
FUND_NAME_MUTATIONS below are hard-coded constants — they never consume
``rng`` — so editing them does not disturb either generator's random stream.
"""

from __future__ import annotations
import numpy as np
from datetime import date

# ── RNG ───────────────────────────────────────────────────────────────────────

SEED: int = 42
rng: np.random.Generator = np.random.default_rng(SEED)

# ── Snapshot calendar ─────────────────────────────────────────────────────────

SNAPSHOTS: list[date] = [
    date(2025, 8, 31), date(2025, 9, 30), date(2025, 10, 31),
    date(2025, 11, 30), date(2025, 12, 31),
    date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31),
    date(2026, 4, 30), date(2026, 5, 31), date(2026, 6, 30),
    date(2026, 7, 31), date(2026, 8, 31),
]

# Staging cutover detection: reporting_date >= CUTOVER_DATE → post-cutover schema.
CUTOVER_DATE: date = date(2026, 1, 1)

# Last pre-cutover snapshot — used as the backfill anchor for Defect 3.
# (Spec §2.4 lists this as '2025-12-01'; that is a typo — monthly end-dates
# are always the last calendar day of the month.)
PRE_CUTOVER_ANCHOR: date = date(2025, 12, 31)

PRE_CUTOVER_SNAPSHOTS: list[date] = [s for s in SNAPSHOTS if s < CUTOVER_DATE]   # 5
POST_CUTOVER_SNAPSHOTS: list[date] = [s for s in SNAPSHOTS if s >= CUTOVER_DATE] # 8

# ── Deal population growth (spec §1.1) ───────────────────────────────────────

DEAL_POPULATION: dict[date, int] = {
    date(2025, 8, 31):  60,
    date(2025, 9, 30):  65,
    date(2025, 10, 31): 70,
    date(2025, 11, 30): 75,
    date(2025, 12, 31): 80,
    date(2026, 1, 31):  85,
    date(2026, 2, 28):  88,
    date(2026, 3, 31):  91,
    date(2026, 4, 30):  94,
    date(2026, 5, 31):  97,
    date(2026, 6, 30): 100,
    date(2026, 7, 31): 100,
    date(2026, 8, 31): 100,
}

TOTAL_DEALS: int = 100


def _build_deal_cohorts() -> dict[int, date]:
    """Maps deal index (0-based, 0–99) to the snapshot it first enters the pipeline."""
    cohorts: dict[int, date] = {}
    prev = 0
    for snap, cumulative in DEAL_POPULATION.items():
        for i in range(prev, cumulative):
            cohorts[i] = snap
        prev = cumulative
    return cohorts


DEAL_COHORTS: dict[int, date] = _build_deal_cohorts()

# ── Locations ─────────────────────────────────────────────────────────────────

LOCATIONS: list[str] = [
    "APAC", "Channel Islands", "France", "Germany",
    "Italy", "Luxembourg", "Spain",
]

# ── Client roster ─────────────────────────────────────────────────────────────
# Each record:
#   client_id    — durable entity key; repeats across SCD version rows.
#   official_name — the CRM legal name stored in client_db_raw.
#   client_type  — authoritative classification, owned by client_db_raw.
#   aliases      — list of strings that may appear as client_name in pns_raw.
#                  Alias_1 (index 0) is the default; others are secondary.
#                  Collision aliases appear here for BOTH colliding clients.
#
# Alias_2 / Alias_3 population rates (60% / 25%) are controlled by
# generate_client_db_raw.py, not here; this list only declares availability.

N_CLIENTS: int = 40

CLIENT_ROSTER: list[dict] = [
    # ── GPs ─────────────────────────────────────────────────────────────────
    {"client_id": "C001", "official_name": "Ardent Capital Partners",          "client_type": "GP-Direct",
     "aliases": ["Ardent Capital",          "Ardent CP"]},
    {"client_id": "C002", "official_name": "Meridian Private Equity",          "client_type": "GP-Direct",
     "aliases": ["Meridian PE",             "Meridian Capital",      "Meridian"]},    # "Meridian Capital" shared with C023
    {"client_id": "C003", "official_name": "Vantage Infrastructure Fund",      "client_type": "GP-Direct",
     "aliases": ["Vantage Infra Fund",      "Vantage Infrastructure"]},
    {"client_id": "C004", "official_name": "Solstice Real Estate Partners",    "client_type": "GP-Direct",
     "aliases": ["Solstice RE Partners",    "Solstice Real Estate"]},
    {"client_id": "C005", "official_name": "Nordholm Capital",                 "client_type": "GP-Direct",
     "aliases": ["Nordholm Capital"]},
    {"client_id": "C006", "official_name": "Ironbridge Growth Fund",           "client_type": "GP-FoF",
     "aliases": ["Ironbridge Growth",       "Ironbridge"]},
    {"client_id": "C007", "official_name": "Coastal Alternatives GP",          "client_type": "GP-FoF",
     "aliases": ["Coastal Alternatives GP", "Coastal Alternatives",  "Coastal Alt GP"]},   # "Coastal Alternatives" shared with C019
    {"client_id": "C008", "official_name": "Helix Ventures Capital",           "client_type": "GP-Direct",
     "aliases": ["Helix Ventures",          "Helix Capital"]},
    {"client_id": "C009", "official_name": "Pinnacle Fund of Funds",           "client_type": "GP-FoF",
     "aliases": ["Pinnacle FoF",            "Pinnacle Fund"]},
    {"client_id": "C010", "official_name": "Summit Infrastructure Partners",   "client_type": "GP-Direct",
     "aliases": ["Summit Infra Partners",   "Summit Infrastructure",  "Summit IP"]},
    {"client_id": "C021", "official_name": "Orion Capital Partners",           "client_type": "GP-Direct",
     "aliases": ["Orion Capital",           "Orion CP"]},
    {"client_id": "C022", "official_name": "Artemis Real Estate Group",        "client_type": "GP-Direct",
     "aliases": ["Artemis RE Group",        "Artemis Real Estate",   "Artemis REG"]},
    {"client_id": "C023", "official_name": "Polaris Private Markets",          "client_type": "GP-FoF",
     "aliases": ["Polaris Private Markets", "Meridian Capital",      "Polaris PM"]},   # "Meridian Capital" shared with C002
    {"client_id": "C024", "official_name": "Luminary Capital Group",           "client_type": "GP-Direct",
     "aliases": ["Luminary Capital",        "Luminary CG"]},
    {"client_id": "C025", "official_name": "Thornfield Equity Partners",       "client_type": "GP-Direct",
     "aliases": ["Thornfield Equity",       "Thornfield EP"]},
    {"client_id": "C026", "official_name": "Redwood Infrastructure GP",        "client_type": "GP-Direct",
     "aliases": ["Redwood Infrastructure",  "Redwood Infra GP"]},
    {"client_id": "C027", "official_name": "Constellation Asset Management",   "client_type": "AO",
     "aliases": ["Constellation AM",        "Constellation Assets"]},
    {"client_id": "C028", "official_name": "Equinox Fund Partners",            "client_type": "GP-FoF",
     "aliases": ["Equinox Fund Partners",   "Equinox FP"]},
    {"client_id": "C029", "official_name": "Harbinger Capital Fund",           "client_type": "GP-Direct",
     "aliases": ["Harbinger Capital",       "Harbinger CF"]},
    {"client_id": "C030", "official_name": "Zenith Investment Partners",       "client_type": "GP-Direct",
     "aliases": ["Zenith Investment",       "Zenith IP",             "Zenith Inv Partners"]},
    # ── Asset Owners ─────────────────────────────────────────────────────────
    {"client_id": "C011", "official_name": "Caledonian Pension Scheme",        "client_type": "AO-Pension Funds",
     "aliases": ["Caledonian Pension",      "Caledonian PS"]},
    {"client_id": "C012", "official_name": "Société d'Investissement du Nord", "client_type": "AO",
     "aliases": ["Soc Investissement Nord", "SI du Nord"]},
    {"client_id": "C013", "official_name": "Bavarian Institutional Investors", "client_type": "AO-Pension Funds",
     "aliases": ["Bavarian Institutional",  "Bavarian II"]},
    {"client_id": "C014", "official_name": "Gulf Sovereign Capital Vehicle",   "client_type": "AO-SWF",
     "aliases": ["Gulf Sovereign Capital",  "Gulf Capital",          "Gulf SWF Vehicle"]},   # "Gulf Capital" shared with C032
    {"client_id": "C015", "official_name": "Pacific Basin Endowment Trust",    "client_type": "AO",
     "aliases": ["Pacific Basin Endowment", "Pacific Basin Trust",   "PB Endowment"]},
    {"client_id": "C016", "official_name": "Nordic Pension Pool",              "client_type": "AO-Pension Funds",
     "aliases": ["Nordic Pension Pool",     "Nordic Pension"]},
    {"client_id": "C017", "official_name": "Levantine Sovereign Fund",         "client_type": "AO-SWF",
     "aliases": ["Levantine Sovereign",     "Levantine SF"]},
    {"client_id": "C018", "official_name": "Cascadia State Pension",           "client_type": "AO-Pension Funds",
     "aliases": ["Cascadia Pension",        "Cascadia State"]},
    {"client_id": "C019", "official_name": "Mediterranean Institutional Fund", "client_type": "AO",
     "aliases": ["Med Institutional Fund",  "Coastal Alternatives",  "Mediterranean IF"]},  # "Coastal Alternatives" shared with C007
    {"client_id": "C020", "official_name": "Alpine Pension Consortium",        "client_type": "AO-Pension Funds",
     "aliases": ["Alpine Pension",          "Alpine PC",             "Alpine Consortium"]},
    {"client_id": "C031", "official_name": "Scandinavian Institutional Pool",  "client_type": "AO-Pension Funds",
     "aliases": ["Scand Institutional",     "Scandinavian IP"]},
    {"client_id": "C032", "official_name": "Gulf Pension Alliance",            "client_type": "AO-Pension Funds",
     "aliases": ["Gulf Pension Alliance",   "Gulf Capital",          "Gulf PA"]},   # "Gulf Capital" shared with C014
    {"client_id": "C033", "official_name": "Rhenish Pension Foundation",       "client_type": "AO-Pension Funds",
     "aliases": ["Rhenish Pension",         "Rhenish PF"]},
    {"client_id": "C034", "official_name": "Iberian Institutional Fund",       "client_type": "AO",
     "aliases": ["Iberian Institutional",   "Iberian IF"]},
    {"client_id": "C035", "official_name": "Southeast Asian Sovereign Pool",   "client_type": "AO-SWF",
     "aliases": ["SEA Sovereign Pool",      "SEA Sovereign"]},
    {"client_id": "C036", "official_name": "Benelux Pension Collective",       "client_type": "AO-Pension Funds",
     "aliases": ["Benelux Pension"]},
    {"client_id": "C037", "official_name": "Central European Endowment",       "client_type": "AO",
     "aliases": ["Central European End",    "CE Endowment"]},
    {"client_id": "C038", "official_name": "AsiaPac Superannuation Fund",      "client_type": "AO-Pension Funds",
     "aliases": ["AsiaPac Super Fund",      "AsiaPac Superannuation"]},
    {"client_id": "C039", "official_name": "Transatlantic Insurance Partners", "client_type": "AO-Insurance",
     "aliases": ["Transatlantic Partners",  "Transatlantic IP"]},
    {"client_id": "C040", "official_name": "Vanguard Institutional Investors", "client_type": "AO",
     "aliases": ["Vanguard Institutional",  "Vanguard II"]},
]

# Convenience lookup: client_id → record.
CLIENT_BY_ID: dict[str, dict] = {c["client_id"]: c for c in CLIENT_ROSTER}

# ── Alias collision injection (qa_alias_collision defect, spec §3.5) ──────────
# Each entry: one alias string shared between two clients in client_db_raw,
# creating a fan-out on the alias join in int_pns_deals.
# The alias already appears in both clients' ``aliases`` lists in CLIENT_ROSTER.
# generate_pns_raw.py uses collision_alias as the client_name for exactly 1 deal
# per entry; generate_client_db_raw.py exposes both aliases via Alias columns.

COLLISION_PAIRS: list[dict] = [
    {"collision_alias": "Coastal Alternatives", "primary_client_id": "C007", "secondary_client_id": "C019"},
    {"collision_alias": "Gulf Capital",         "primary_client_id": "C014", "secondary_client_id": "C032"},
    {"collision_alias": "Meridian Capital",     "primary_client_id": "C002", "secondary_client_id": "C023"},
]

# ── Unmatched client names (qa_unmatched_clients defect, spec §3.5) ───────────
# These strings appear as client_name in pns_raw for 1 deal each.
# No alias in CLIENT_ROSTER matches them → they surface in qa_unmatched_clients.

UNMATCHED_CLIENT_NAMES: list[str] = [
    "BNP Global Advisors",
    "Crossroads Infrastructure Ltd",
    "Apex Capital Advisory",
]

# ── Fund name mutations (Defect 1, spec §2.4 + §4.1) ─────────────────────────
# Each entry covers one deal whose fund_name alternates between dirty_name
# (early snapshots) and canonical_name (later snapshots within the same deal).
# pns_client_name is the alias[0] string used as client_name in pns_raw for that
# deal — this is the join key for the fund_name_corrections seed.
# generate_pns_raw.py also writes these rows to seeds/fund_name_corrections.csv.

FUND_NAME_MUTATIONS: list[dict] = [
    {
        "client_id":       "C021",
        "pns_client_name": "Orion Capital",
        "dirty_name":      "Orion Fund II",
        "canonical_name":  "Orion Fund 2",
        "corrected_by":    "JDM",
        "corrected_date":  date(2025, 11, 15),
    },
    {
        "client_id":       "C022",
        "pns_client_name": "Artemis RE Group",
        "dirty_name":      "Artemis RE Fd",
        "canonical_name":  "Artemis RE Fund",
        "corrected_by":    "KZ",
        "corrected_date":  date(2025, 10, 3),
    },
    {
        "client_id":       "C024",
        "pns_client_name": "Luminary Capital",
        "dirty_name":      "Luminary Cap Grp",
        "canonical_name":  "Luminary Capital Fund",
        "corrected_by":    "DL",
        "corrected_date":  date(2026, 2, 8),
    },
    {
        "client_id":       "C029",
        "pns_client_name": "Harbinger Capital",
        "dirty_name":      "Harbinger Cptl Fd",
        "canonical_name":  "Harbinger Fund",
        "corrected_by":    "MR",
        "corrected_date":  date(2025, 12, 20),
    },
    {
        "client_id":       "C005",
        "pns_client_name": "Nordholm Capital",
        "dirty_name":      "Nordholm Cap II",
        "canonical_name":  "Nordholm Fund II",
        "corrected_by":    "PB",
        "corrected_date":  date(2026, 3, 14),
    },
]

# ── SCD Type 2 clients (spec §3.4) ────────────────────────────────────────────
# ~20% of 40 clients (= 8) receive a Prospect → Existing transition.
# generate_client_db_raw.py creates two version rows for each of these;
# all others get a single row.

SCD_CLIENT_IDS: list[str] = [
    "C002", "C008", "C011", "C015",
    "C019", "C023", "C031", "C037",
]

# ── Unresolvable strategy (Defect 3b, spec §2.4) ──────────────────────────────
# Pre-cutover deals with real_estate = Yes or infrastructure = Yes but no
# financing type anchor (private_equity = No AND private_debt = No). Backfill
# logic in the intermediate layer cannot resolve these — they surface via
# qa_unresolvable_strategy. generate_pns_raw.py reserves one pre-cutover-cohort
# deal per entry (deal index < 80, i.e. entered before the Jan 2026 cutover)
# and forces this condition across all of that deal's pre-cutover rows.

UNRESOLVABLE_STRATEGY_DEALS: list[dict] = [
    {"unresolvable_column": "real_estate"},
    {"unresolvable_column": "infrastructure"},
    {"unresolvable_column": "real_estate"},
    {"unresolvable_column": "infrastructure"},
]

# ── Genuine strategy/service changes (spec §2.5) ──────────────────────────────
# ~5 deals where a schema-stable column takes a real new value at some snapshot,
# proving dim_deal's latest-snapshot ROW_NUMBER() treatment and exercising
# qa_strategy_service_changes. `cohort: "post_cutover"` restricts a sub-strategy
# change to a deal whose first reporting_date >= 2026-01-01 (deal index >= 80) —
# sub-strategy changes on pre-cutover deals are excluded by design (spec §2.5,
# "why sub-strategy changes are excluded"). generate_pns_raw.py picks the
# specific deal and the snapshot at which `new_value` first appears.

GENUINE_CHANGE_DEALS: list[dict] = [
    {"column": "private_equity",    "old_value": "No",  "new_value": "Yes",       "cohort": "any"},
    {"column": "Custody",           "old_value": "TBD", "new_value": "Yes",       "cohort": "any"},
    {"column": "private_debt",      "old_value": "Yes", "new_value": "No",        "cohort": "any"},
    {"column": "real_estate_equity","old_value": "No",  "new_value": "Yes",       "cohort": "post_cutover"},
    {"column": "SFDR_eligibility",  "old_value": "No",  "new_value": "Article 8", "cohort": "any"},
]

# ── Terminal deals with missing measures (qa_terminal_revenue_asset, §2.4 Defect 5) ─
# ~5 terminal deals (Won/Lost/Rejected) with a null revenue_eur_equiv or null
# asset at their latest snapshot. Every deal's latest snapshot is Aug 2026 —
# deals never leave the population once entered (Defect 2). Mix exercises all
# branches of `missing_fields` (revenue / asset / both).

TERMINAL_MEASURE_GAPS: list[dict] = [
    {"deal_status": "Won",      "missing": "asset"},
    {"deal_status": "Won",      "missing": "asset"},
    {"deal_status": "Lost",     "missing": "revenue"},
    {"deal_status": "Lost",     "missing": "revenue"},
    {"deal_status": "Rejected", "missing": "both"},
]
