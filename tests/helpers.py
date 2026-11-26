"""Small helpers shared by the tests."""

import sqlite3
from contextlib import contextmanager

import pytest

from assistance import db
from assistance.errors import AppError
from assistance.identity import Caller


def as_staff(staff_id: str) -> Caller:
    """The Caller for a seeded staff member, read from the database."""
    with db.reading() as conn:
        row = conn.execute("SELECT id, role, nonprofit_id FROM staff WHERE id = ?", (staff_id,)).fetchone()
    return Caller(staff_id=row["id"], role=row["role"], nonprofit_id=row["nonprofit_id"])


def snapshot() -> dict:
    """Every request row and every fund row. Used to prove a refused action changed nothing."""
    with db.reading() as conn:
        return {
            "requests": [tuple(r) for r in conn.execute("SELECT * FROM requests ORDER BY id")],
            "funds": [tuple(r) for r in conn.execute("SELECT * FROM funds ORDER BY id")],
        }


def fund_cents(fund_id: str) -> dict:
    """The stored counters of one fund, plus the derived available amount, all in cents."""
    with db.reading() as conn:
        row = conn.execute("SELECT * FROM funds WHERE id = ?", (fund_id,)).fetchone()
    return {
        "allocation": row["allocation_cents"],
        "committed": row["committed_cents"],
        "paid": row["paid_cents"],
        "available": row["allocation_cents"] - row["committed_cents"] - row["paid_cents"],
    }


def set_allocation(fund_id: str, cents: int) -> None:
    """Shrink or grow a fund for a test. (The product itself has no way to do this.)"""
    conn = sqlite3.connect(db.db_path())
    conn.execute("UPDATE funds SET allocation_cents = ? WHERE id = ?", (cents, fund_id))
    conn.commit()
    conn.close()


def insert_request(request_id, nonprofit_id, participant_id, fund_id, created_by, status="PENDING", amount_cents=30000):
    """Put a request row straight into the database, bypassing the service."""
    conn = sqlite3.connect(db.db_path())
    conn.execute(
        "INSERT INTO requests (id, nonprofit_id, participant_id, fund_id, amount_cents, purpose, status, "
        "idempotency_key, created_by, created_at) VALUES (?, ?, ?, ?, ?, 'test', ?, ?, ?, '2026-01-01T00:00:00Z')",
        (request_id, nonprofit_id, participant_id, fund_id, amount_cents, status, f"key-{request_id}", created_by),
    )
    conn.commit()
    conn.close()


@contextmanager
def refused(code: str):
    """Assert the block is refused with this error code."""
    with pytest.raises(AppError) as error:
        yield error
    assert error.value.code == code, f"expected {code}, got {error.value.code}: {error.value.message}"
