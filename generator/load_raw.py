"""
load_raw.py — loads the raw source CSVs into duckdb as the `raw` schema.

Run after all three generators produce the CSVs (validate_outputs.py optional
but recommended first):

    python generator/generate_pns_raw.py
    python generator/generate_client_db_raw.py
    python generator/generate_fee_invoice_raw.py
    python generator/load_raw.py

Design decision: every column loads as VARCHAR (`read_csv(..., all_varchar=true)`),
not duckdb's auto-typing. The raw layer should be exactly what's in the file —
deciding a column is safely a DATE/INTEGER/BOOLEAN is a staging decision (spec
says e.g. "cast to date in staging" for expected_outcome_date), not something
a loader should pre-empt via type sniffing. It also sidesteps duckdb guessing
DOUBLE for asset/revenue and then choking on the currency-string asset rows
(Defect 5a) — those rows failing to parse as a plain number is the whole
point of that defect, not something that should error out before staging
even sees it.

Does NOT touch seeds/fund_name_corrections.csv — that file is loaded natively
by `dbt seed`, since it already lives under dbt_project.yml's seed-paths.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "dev.duckdb"
RAW_DIR = REPO_ROOT / "data" / "raw"

SOURCES = {
    "pns_raw": RAW_DIR / "pns_raw.csv",
    "client_db_raw": RAW_DIR / "client_db_raw.csv",
    "fee_invoice_raw": RAW_DIR / "fee_invoice_raw.csv",
}


def main() -> None:
    for name, path in SOURCES.items():
        if not path.exists():
            raise FileNotFoundError(f"{path} not found — run the generators first.")

    con = duckdb.connect(str(DB_PATH))
    con.execute("CREATE SCHEMA IF NOT EXISTS raw")

    for table, path in SOURCES.items():
        con.execute(f"""
            CREATE OR REPLACE TABLE raw.{table} AS
            SELECT * FROM read_csv('{path.as_posix()}', all_varchar=true, header=true)
        """)
        n = con.execute(f"SELECT COUNT(*) FROM raw.{table}").fetchone()[0]
        print(f"raw.{table}: {n} rows loaded from {path.relative_to(REPO_ROOT)}")

    con.close()


if __name__ == "__main__":
    main()
