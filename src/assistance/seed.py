"""Create or reset the database with synthetic data for two nonprofits.

    uv run python -m assistance.seed --reset

This is the only code that creates the database or sets a fund's allocation.
The server never runs it. Running it again always gives the same data.
"""  # REQ: FR-12

import argparse
import sqlite3
import sys
from pathlib import Path

from assistance.db import SCHEMA_FILE, db_path

NONPROFITS = [
    ("np_cb", "Community Bridge"),
    ("np_rr", "Riverside Relief"),
]

# (id, nonprofit, name, role)
STAFF = [
    ("staff_cb_cw1", "np_cb", "Casey Nguyen", "case_worker"),
    ("staff_cb_cw2", "np_cb", "Devon Clarke", "case_worker"),
    ("staff_cb_pm1", "np_cb", "Priya Menon", "program_manager"),
    ("staff_cb_pm2", "np_cb", "Marcus Bell", "program_manager"),
    ("staff_cb_fin1", "np_cb", "Fiona Okafor", "finance"),
    ("staff_rr_cw1", "np_rr", "Riley Santos", "case_worker"),
    ("staff_rr_pm1", "np_rr", "Paula Ivanova", "program_manager"),
    ("staff_rr_fin1", "np_rr", "Frank Osei", "finance"),
]

# (id, nonprofit, name)
PARTICIPANTS = [
    ("part_cb_1", "np_cb", "Alex Rivera"),
    ("part_cb_2", "np_cb", "Jordan Lee"),
    ("part_cb_3", "np_cb", "Sam Patel"),
    ("part_rr_1", "np_rr", "Taylor Brooks"),
    ("part_rr_2", "np_rr", "Morgan Diaz"),
]

# (id, nonprofit, name, allocation in cents)
FUNDS = [
    ("fund_cb_rent", "np_cb", "Rent Relief 2026", 1_000_000),  # $10,000.00
    ("fund_cb_util", "np_cb", "Utilities Assistance", 250_000),  # $2,500.00
    ("fund_rr_transport", "np_rr", "Emergency Transport", 100_000),  # $1,000.00
    ("fund_rr_housing", "np_rr", "Housing Stability", 500_000),  # $5,000.00
]


def reset(path: Path) -> None:
    """Delete the database at `path` (if any) and build a fresh seeded one."""
    for leftover in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        leftover.unlink(missing_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    try:
        # WAL mode is stored in the file: readers are not blocked while a write commits.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA_FILE.read_text())
        conn.executemany("INSERT INTO nonprofits (id, name) VALUES (?, ?)", NONPROFITS)
        conn.executemany("INSERT INTO staff (id, nonprofit_id, name, role) VALUES (?, ?, ?, ?)", STAFF)
        conn.executemany("INSERT INTO participants (id, nonprofit_id, name) VALUES (?, ?, ?)", PARTICIPANTS)
        conn.executemany("INSERT INTO funds (id, nonprofit_id, name, allocation_cents) VALUES (?, ?, ?, ?)", FUNDS)
        conn.commit()
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or reset the assistance database.")
    parser.add_argument("--reset", action="store_true", help="delete the existing database first")
    args = parser.parse_args(argv)

    path = db_path()
    if path.exists() and not args.reset:
        print(f"{path} already exists. Use --reset to delete it and start again.", file=sys.stderr)
        return 1
    reset(path)
    print(f"Seeded {path}: {len(NONPROFITS)} nonprofits, {len(STAFF)} staff, "
          f"{len(PARTICIPANTS)} participants, {len(FUNDS)} funds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
