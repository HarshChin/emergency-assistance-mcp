"""The MCP server: nine tools over stdio.

    ASSISTANCE_STAFF_ID=staff_cb_cw1 uv run python -m assistance.server

Each tool is deliberately thin: work out who is calling, run one service
function, return its result. No tool has a parameter for staff, role or
nonprofit; the caller comes only from identity.resolve_caller().  # REQ: SEC-07

Logs go to stderr through the logging module. Stdout carries only MCP protocol
messages.  # REQ: NFR-01
"""

import logging
import sys
from collections.abc import Callable
from typing import Annotated, Literal, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from assistance import db, service
from assistance.errors import AppError
from assistance.identity import Caller, resolve_caller
from assistance.models import (
    FundingSummary, FundList, ParticipantList, Request, RequestList, RequestResult,
)

log = logging.getLogger("assistance")

mcp = MCPServer(
    "Emergency Assistance Funding",
    instructions=(
        "Assistance requests for one nonprofit. Case workers create requests, program managers "
        "approve or reject them, finance records payments; everyone can read. "
        'Amounts are US dollars as text with two decimals, such as "300.00". '
        "Errors start with a code in square brackets and say how to fix the call."
    ),
)

# ---------------------------------------------------------------- argument types
# Shape rules (type, length, allowed values) are declared here and enforced by the
# SDK before a tool runs. Meaning rules (amount format, role, status, funds) are in
# service.py and are reported with an error code.

RequestId = Annotated[
    str, Field(min_length=1, max_length=64, description="Request ID, from create_request or list_requests.")
]
AmountUsd = Annotated[
    str,
    Field(
        description='US dollars as text with exactly two decimals: "300.00" means three hundred dollars. '
        'Not cents, not a number, no "$", no commas.',
        examples=["300.00", "45.50"],
    ),
]
Purpose = Annotated[  # REQ: BR-14
    str, Field(min_length=1, max_length=500, pattern=r"\S", description="What the money is for. Stored as written.")
]
IdempotencyKey = Annotated[  # REQ: IDM-04
    str,
    Field(
        min_length=1,
        max_length=64,
        description="Any unique text you choose for this new request, such as a UUID. "
        "If you retry the same call, send the same key so that no duplicate is created.",
    ),
]
Status = Literal["PENDING", "APPROVED", "REJECTED", "PAID"]

READ_ONLY = ToolAnnotations(read_only_hint=True)
# Write tools change data but are safe to repeat: a repeat returns replayed=true.
REPEATABLE_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True)

Result = TypeVar("Result")


def _run(tool: str, operation: Callable[[Caller], Result], request_id: str | None = None) -> Result:
    """Resolve the caller, run one service operation, log the outcome.

    A business refusal (AppError) becomes a ToolError, which the MCP client
    receives as is_error=true with the text "[CODE] message".  # REQ: NFR-02
    """
    caller = None
    try:
        caller = resolve_caller()
        result = operation(caller)
    except AppError as error:
        _log_outcome(tool, caller, request_id, error.code)
        raise ToolError(str(error)) from None
    if isinstance(result, RequestResult):
        request_id = result.request.request_id
    _log_outcome(tool, caller, request_id, "replayed" if getattr(result, "replayed", False) else "ok")
    return result


def _log_outcome(tool: str, caller: Caller | None, request_id: str | None, outcome: str) -> None:
    # IDs and outcome only: never purpose text, reasons or participant names.
    # %r quotes the request ID, because on a failed call it is whatever text the client sent.
    log.info(
        "tool=%s staff=%s nonprofit=%s request=%r outcome=%s",
        tool,
        caller.staff_id if caller else "-",
        caller.nonprofit_id if caller else "-",
        request_id or "-",
        outcome,
    )


# ---------------------------------------------------------------- read tools


@mcp.tool(annotations=READ_ONLY)
def list_participants(
    name_contains: Annotated[
        str | None, Field(max_length=100, description="Optional: only names containing this text.")
    ] = None,
) -> ParticipantList:
    """List participants of your nonprofit, to find the participant_id for a request."""
    return _run("list_participants", lambda caller: service.list_participants(caller, name_contains))


@mcp.tool(annotations=READ_ONLY)
def list_funds() -> FundList:
    """List the funds of your nonprofit, to find the fund_id for a request."""
    return _run("list_funds", service.list_funds)


@mcp.tool(annotations=READ_ONLY)
def get_funding_summary(
    fund_id: Annotated[
        str | None, Field(max_length=64, description="Optional: one fund. Leave out for all funds.")
    ] = None,
) -> FundingSummary:
    """Show allocation, committed, paid and available amounts for one fund or all funds of your nonprofit."""
    return _run("get_funding_summary", lambda caller: service.get_funding_summary(caller, fund_id))


@mcp.tool(annotations=READ_ONLY)
def get_request(request_id: RequestId) -> Request:
    """Get one assistance request: its status, amount, and who created, decided and paid it."""
    return _run("get_request", lambda caller: service.get_request(caller, request_id), request_id)


@mcp.tool(annotations=READ_ONLY)
def list_requests(
    status: Annotated[Status | None, Field(description="Optional: only requests with this status.")] = None,
    limit: Annotated[int, Field(ge=1, le=200, description="Maximum number of requests to return.")] = 50,
) -> RequestList:
    """List assistance requests of your nonprofit, newest first."""
    return _run("list_requests", lambda caller: service.list_requests(caller, status, limit))


# ---------------------------------------------------------------- write tools


@mcp.tool(annotations=REPEATABLE_WRITE)
def create_request(
    participant_id: Annotated[str, Field(min_length=1, max_length=64, description="From list_participants.")],
    fund_id: Annotated[str, Field(min_length=1, max_length=64, description="From list_funds.")],
    amount_usd: AmountUsd,
    purpose: Purpose,
    idempotency_key: IdempotencyKey,
) -> RequestResult:
    """Case workers only. Submit an assistance request. It starts as PENDING and reserves no money.
    The request cannot be edited afterwards."""
    return _run(
        "create_request",
        lambda caller: service.create_request(caller, participant_id, fund_id, amount_usd, purpose, idempotency_key),
    )


@mcp.tool(annotations=REPEATABLE_WRITE)
def approve_request(request_id: RequestId) -> RequestResult:
    """Program managers only. Approve a PENDING request and reserve its full amount on the fund.
    Fails with INSUFFICIENT_FUNDS if the fund has less available than the amount."""
    return _run("approve_request", lambda caller: service.approve_request(caller, request_id), request_id)


@mcp.tool(annotations=REPEATABLE_WRITE)
def reject_request(
    request_id: RequestId,
    reason: Annotated[str | None, Field(max_length=500, description="Optional: why it was rejected.")] = None,
) -> RequestResult:
    """Program managers only. Reject a PENDING request. The fund is not changed."""
    return _run("reject_request", lambda caller: service.reject_request(caller, request_id, reason), request_id)


@mcp.tool(annotations=REPEATABLE_WRITE)
def record_payment(request_id: RequestId) -> RequestResult:
    """Finance only. Record that an APPROVED request was paid in full (simulated; no real payment is made).
    The amount moves from committed to paid."""
    return _run("record_payment", lambda caller: service.record_payment(caller, request_id), request_id)


# ---------------------------------------------------------------- startup


def main() -> None:
    # The server never creates or seeds the database.  # REQ: FR-12
    if not db.db_path().exists():
        log.error("Database not found at %s. Create it with: uv run python -m assistance.seed --reset", db.db_path())
        sys.exit(1)
    mcp.run()  # stdio is the default transport


if __name__ == "__main__":
    main()
