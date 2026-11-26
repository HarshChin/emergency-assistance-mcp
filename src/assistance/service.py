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
import uuid
from datetime import datetime, timezone

from assistance import db, money, rules
from assistance.errors import IDEMPOTENCY_CONFLICT, INSUFFICIENT_FUNDS, NOT_FOUND, AppError
from assistance.identity import Caller
from assistance.models import (
    Fund, FundBalance, FundingSummary, FundList, Participant, ParticipantList,
    Request, RequestList, RequestResult,
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


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _update_request(conn: sqlite3.Connection, sql: str, values: tuple) -> None:
    """Run an UPDATE that must change exactly one request row."""
    if conn.execute(sql, values).rowcount != 1:
        raise RuntimeError("request row was not updated as expected")  # rolls the transaction back


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


# ---------------------------------------------------------------- writes
# Each write is one db.transaction(): BEGIN IMMEDIATE ... COMMIT, or ROLLBACK if
# anything raises. A refused action therefore changes nothing.  # REQ: BR-12


def create_request(
    caller: Caller, participant_id: str, fund_id: str, amount_usd: str, purpose: str, idempotency_key: str
) -> RequestResult:  # REQ: FR-03
    rules.require(caller.role, rules.CREATE)
    amount_cents = money.parse_usd(amount_usd)

    with db.transaction() as conn:
        # Has this case worker already used this key?  # REQ: IDM-04, IDM-05
        earlier = conn.execute(
            "SELECT * FROM requests WHERE created_by = ? AND idempotency_key = ? AND nonprofit_id = ?",
            (caller.staff_id, idempotency_key, caller.nonprofit_id),
        ).fetchone()
        if earlier is not None:
            sent = (participant_id, fund_id, amount_cents, purpose)
            stored = (earlier["participant_id"], earlier["fund_id"], earlier["amount_cents"], earlier["purpose"])
            if sent != stored:
                raise AppError(
                    IDEMPOTENCY_CONFLICT,
                    f"idempotency_key '{idempotency_key}' was already used for request {earlier['id']} "
                    "with different details. Reuse a key only to retry the same request; "
                    "for a new request send a new key.",
                )
            return RequestResult(request=_to_request(earlier), replayed=True)

        # Participant and fund must both belong to the caller's nonprofit.  # REQ: BR-13
        participant = conn.execute(
            "SELECT id FROM participants WHERE id = ? AND nonprofit_id = ?",
            (participant_id, caller.nonprofit_id),
        ).fetchone()
        if participant is None:
            raise AppError(
                NOT_FOUND,
                f"No participant with participant_id '{participant_id}' exists in your nonprofit. "
                "Use list_participants to find valid IDs.",
            )
        _load_fund(conn, caller, fund_id)

        # A new request is PENDING and reserves nothing.  # REQ: BR-01, BR-03
        request_id = f"req_{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO requests (id, nonprofit_id, participant_id, fund_id, amount_cents, purpose, "
            "status, idempotency_key, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (request_id, caller.nonprofit_id, participant_id, fund_id, amount_cents, purpose,
             rules.PENDING, idempotency_key, caller.staff_id, _now()),  # REQ: BR-15
        )
        return RequestResult(request=_to_request(_load_request(conn, caller, request_id)), replayed=False)


def approve_request(caller: Caller, request_id: str) -> RequestResult:  # REQ: FR-04
    rules.require(caller.role, rules.APPROVE)

    with db.transaction() as conn:
        request = _load_request(conn, caller, request_id)
        # Status is checked before funds, so a retried approval is never refused
        # for insufficient funds.  # REQ: IDM-01, IDM-06
        if rules.is_repeat(request["status"], rules.APPROVE):
            return RequestResult(request=_to_request(request), replayed=True)
        new_status = rules.next_status(request["status"], rules.APPROVE)

        # Reserve the full amount, but only if the fund still has room. The check
        # and the change are one statement.  # REQ: BR-04, BR-05, BR-11
        reserved = conn.execute(
            "UPDATE funds SET committed_cents = committed_cents + :amount "
            "WHERE id = :fund AND nonprofit_id = :nonprofit "
            "AND allocation_cents - committed_cents - paid_cents >= :amount",
            {"amount": request["amount_cents"], "fund": request["fund_id"], "nonprofit": caller.nonprofit_id},
        )
        if reserved.rowcount == 0:
            fund = _to_balance(_load_fund(conn, caller, request["fund_id"]))
            raise AppError(
                INSUFFICIENT_FUNDS,
                f"Fund {fund.fund_id} has {fund.available_usd} available, but this request needs "
                f"{money.format_usd(request['amount_cents'])}. The request is still PENDING.",
            )

        _update_request(
            conn,
            "UPDATE requests SET status = ?, decided_by = ?, decided_at = ? "
            "WHERE id = ? AND nonprofit_id = ? AND status = ?",
            (new_status, caller.staff_id, _now(), request_id, caller.nonprofit_id, request["status"]),
        )
        return RequestResult(request=_to_request(_load_request(conn, caller, request_id)), replayed=False)


def reject_request(caller: Caller, request_id: str, reason: str | None = None) -> RequestResult:  # REQ: FR-05
    rules.require(caller.role, rules.REJECT)

    with db.transaction() as conn:
        request = _load_request(conn, caller, request_id)
        if rules.is_repeat(request["status"], rules.REJECT):  # REQ: IDM-02
            return RequestResult(request=_to_request(request), replayed=True)
        new_status = rules.next_status(request["status"], rules.REJECT)

        # No fund statement: rejecting moves no money.  # REQ: BR-06
        _update_request(
            conn,
            "UPDATE requests SET status = ?, decided_by = ?, decided_at = ?, reject_reason = ? "
            "WHERE id = ? AND nonprofit_id = ? AND status = ?",
            (new_status, caller.staff_id, _now(), reason, request_id, caller.nonprofit_id, request["status"]),
        )
        return RequestResult(request=_to_request(_load_request(conn, caller, request_id)), replayed=False)


def record_payment(caller: Caller, request_id: str) -> RequestResult:  # REQ: FR-06
    rules.require(caller.role, rules.PAY)

    with db.transaction() as conn:
        request = _load_request(conn, caller, request_id)
        if rules.is_repeat(request["status"], rules.PAY):  # REQ: IDM-03
            return RequestResult(request=_to_request(request), replayed=True)
        new_status = rules.next_status(request["status"], rules.PAY)

        # Move the full amount from committed to paid. Available does not change.  # REQ: BR-07
        moved = conn.execute(
            "UPDATE funds SET committed_cents = committed_cents - :amount, paid_cents = paid_cents + :amount "
            "WHERE id = :fund AND nonprofit_id = :nonprofit AND committed_cents >= :amount",
            {"amount": request["amount_cents"], "fund": request["fund_id"], "nonprofit": caller.nonprofit_id},
        )
        if moved.rowcount != 1:
            raise RuntimeError("fund has less committed than an approved request needs")

        _update_request(
            conn,
            "UPDATE requests SET status = ?, paid_by = ?, paid_at = ? "
            "WHERE id = ? AND nonprofit_id = ? AND status = ?",
            (new_status, caller.staff_id, _now(), request_id, caller.nonprofit_id, request["status"]),
        )
        return RequestResult(request=_to_request(_load_request(conn, caller, request_id)), replayed=False)
