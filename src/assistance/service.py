"""Business operations. All SQL lives here.

Every function takes the Caller first and follows the same order:
    1. role check            (rules.require)        -> FORBIDDEN
    2. amount format         (money.parse_usd)      -> INVALID_AMOUNT
    3. look up the record    (always filtered by the caller's nonprofit) -> NOT_FOUND
    4. status check          (rules.is_repeat / rules.next_status) -> replayed / INVALID_TRANSITION
    5. change the fund, then the request

Nonprofit boundary: every statement on staff-owned data has
"nonprofit_id = caller.nonprofit_id" in its WHERE clause, so a record of another
nonprofit looks exactly like a record that does not exist.  # REQ: SEC-06
"""

import sqlite3

from assistance import db, money, rules
from assistance.errors import NOT_FOUND, AppError
from assistance.identity import Caller
from assistance.models import (
    Fund, FundBalance, FundingSummary, FundList, Participant, ParticipantList,
    Request, RequestList,
)

# ---------------------------------------------------------------- helpers


def _to_request(row: sqlite3.Row) -> Request:
    return Request(
        request_id=row["id"],
        status=row["status"],
        participant_id=row["participant_id"],
        fund_id=row["fund_id"],
        amount_usd=money.format_usd(row["amount_cents"]),
        purpose=row["purpose"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        decided_by=row["decided_by"],
        decided_at=row["decided_at"],
        reject_reason=row["reject_reason"],
        paid_by=row["paid_by"],
        paid_at=row["paid_at"],
    )


def _to_balance(row: sqlite3.Row) -> FundBalance:
    available_cents = row["allocation_cents"] - row["committed_cents"] - row["paid_cents"]  # REQ: BR-08
    return FundBalance(
        fund_id=row["id"],
        name=row["name"],
        allocation_usd=money.format_usd(row["allocation_cents"]),
        committed_usd=money.format_usd(row["committed_cents"]),
        paid_usd=money.format_usd(row["paid_cents"]),
        available_usd=money.format_usd(available_cents),
    )


def _load_request(conn: sqlite3.Connection, caller: Caller, request_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM requests WHERE id = ? AND nonprofit_id = ?",
        (request_id, caller.nonprofit_id),
    ).fetchone()
    if row is None:
        raise AppError(
            NOT_FOUND,
            f"No request with request_id '{request_id}' exists in your nonprofit. "
            "Use list_requests to find valid IDs.",
        )
    return row


def _load_fund(conn: sqlite3.Connection, caller: Caller, fund_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM funds WHERE id = ? AND nonprofit_id = ?",
        (fund_id, caller.nonprofit_id),
    ).fetchone()
    if row is None:
        raise AppError(
            NOT_FOUND,
            f"No fund with fund_id '{fund_id}' exists in your nonprofit. "
            "Use list_funds to find valid IDs.",
        )
    return row


# ---------------------------------------------------------------- reads


def list_participants(caller: Caller, name_contains: str | None = None) -> ParticipantList:  # REQ: FR-01
    rules.require(caller.role, rules.READ)
    with db.reading() as conn:
        rows = conn.execute(
            "SELECT id, name FROM participants "
            "WHERE nonprofit_id = ? AND instr(lower(name), lower(?)) > 0 "
            "ORDER BY name LIMIT 100",
            (caller.nonprofit_id, name_contains or ""),
        ).fetchall()
    return ParticipantList(participants=[Participant(participant_id=r["id"], name=r["name"]) for r in rows])


def list_funds(caller: Caller) -> FundList:  # REQ: FR-02
    rules.require(caller.role, rules.READ)
    with db.reading() as conn:
        rows = conn.execute(
            "SELECT id, name, allocation_cents FROM funds WHERE nonprofit_id = ? ORDER BY name",
            (caller.nonprofit_id,),
        ).fetchall()
    return FundList(
        funds=[
            Fund(fund_id=r["id"], name=r["name"], allocation_usd=money.format_usd(r["allocation_cents"]))
            for r in rows
        ]
    )


def get_funding_summary(caller: Caller, fund_id: str | None = None) -> FundingSummary:  # REQ: FR-09
    rules.require(caller.role, rules.READ)
    with db.reading() as conn:
        if fund_id is not None:
            rows = [_load_fund(conn, caller, fund_id)]
        else:
            rows = conn.execute(
                "SELECT * FROM funds WHERE nonprofit_id = ? ORDER BY name",
                (caller.nonprofit_id,),
            ).fetchall()
    return FundingSummary(funds=[_to_balance(r) for r in rows])


def get_request(caller: Caller, request_id: str) -> Request:  # REQ: FR-07
    rules.require(caller.role, rules.READ)
    with db.reading() as conn:
        return _to_request(_load_request(conn, caller, request_id))


def list_requests(caller: Caller, status: str | None = None, limit: int = 50) -> RequestList:  # REQ: FR-08
    rules.require(caller.role, rules.READ)
    with db.reading() as conn:
        rows = conn.execute(
            "SELECT * FROM requests "
            "WHERE nonprofit_id = ? AND (? IS NULL OR status = ?) "
            "ORDER BY rowid DESC LIMIT ?",  # rowid grows with each insert: newest first
            (caller.nonprofit_id, status, status, limit),
        ).fetchall()
    return RequestList(requests=[_to_request(r) for r in rows])
