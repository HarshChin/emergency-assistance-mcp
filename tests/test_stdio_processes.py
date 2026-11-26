"""Real server processes over stdio.

Every Client below starts its own `python -m assistance.server` process, exactly
as an MCP host does. The processes share nothing but the database file, so
these tests prove the protections hold across processes, not just inside one.
"""

import asyncio
import subprocess
import sys
from contextlib import AsyncExitStack

import pytest
from mcp import Client, StdioServerParameters, stdio_client

from assistance import service
from helpers import as_staff, fund_cents, snapshot

pytestmark = pytest.mark.anyio

TRANSPORT = "fund_rr_transport"  # $1,000.00 in the seed


@pytest.fixture
def anyio_backend():
    return "asyncio"


def server_as(staff_id: str | None, db_path) -> StdioServerParameters:
    """Launch settings for one server process. A child process gets only the variables listed here."""
    env = {"ASSISTANCE_DB_PATH": str(db_path)}
    if staff_id is not None:
        env["ASSISTANCE_STAFF_ID"] = staff_id
    return StdioServerParameters(command=sys.executable, args=["-m", "assistance.server"], env=env)


async def start_servers(stack: AsyncExitStack, staff_id: str, db_path, count: int) -> list[Client]:
    """Start `count` separate server processes, all connected and ready before any call is made."""
    return [await stack.enter_async_context(Client(server_as(staff_id, db_path))) for _ in range(count)]


def pending_requests(count: int, amount: str) -> list[str]:
    case_worker = as_staff("staff_rr_cw1")
    return [
        service.create_request(case_worker, "part_rr_1", TRANSPORT, amount, "Bus pass", f"race-{i}").request.request_id
        for i in range(count)
    ]


# ------------------------------------------------------------ end to end


@pytest.mark.req("FR-10", "NFR-01", "FR-03", "FR-04", "FR-06", "FR-09")
async def test_ac27_three_staff_take_a_request_from_creation_to_payment_over_stdio(db):
    async with Client(server_as("staff_cb_cw1", db)) as case_worker:
        tools = {tool.name for tool in (await case_worker.list_tools()).tools}
        assert {"create_request", "approve_request", "record_payment", "get_funding_summary"} <= tools
        participant = (await case_worker.call_tool("list_participants", {"name_contains": "Alex"})).structured_content["participants"][0]
        created = await case_worker.call_tool(
            "create_request",
            {
                "participant_id": participant["participant_id"],
                "fund_id": "fund_cb_rent",
                "amount_usd": "300.00",
                "purpose": "March rent",
                "idempotency_key": "e2e-1",
            },
        )
        request_id = created.structured_content["request"]["request_id"]

    async with Client(server_as("staff_cb_pm1", db)) as manager:
        approved = await manager.call_tool("approve_request", {"request_id": request_id})
        assert approved.structured_content["request"]["status"] == "APPROVED"
        after_approval = (await manager.call_tool("get_funding_summary", {"fund_id": "fund_cb_rent"})).structured_content["funds"][0]
        assert (after_approval["available_usd"], after_approval["committed_usd"]) == ("9700.00", "300.00")

    async with Client(server_as("staff_cb_fin1", db)) as finance:
        paid = await finance.call_tool("record_payment", {"request_id": request_id})
        assert paid.structured_content["request"]["status"] == "PAID"
        final = (await finance.call_tool("get_funding_summary", {"fund_id": "fund_cb_rent"})).structured_content["funds"][0]

    assert final == {
        "fund_id": "fund_cb_rent",
        "name": "Rent Relief 2026",
        "allocation_usd": "10000.00",
        "committed_usd": "0.00",
        "paid_usd": "300.00",
        "available_usd": "9700.00",
    }


@pytest.mark.req("FR-11")
async def test_ac24_data_is_still_there_after_the_server_is_stopped_and_started_again(db):
    request_id = pending_requests(1, "300.00")[0]
    async with Client(server_as("staff_rr_pm1", db)) as first_process:
        await first_process.call_tool("approve_request", {"request_id": request_id})
    # The first server process has exited. Start a new one.
    async with Client(server_as("staff_rr_fin1", db)) as second_process:
        request = (await second_process.call_tool("get_request", {"request_id": request_id})).structured_content
        fund = (await second_process.call_tool("get_funding_summary", {"fund_id": TRANSPORT})).structured_content["funds"][0]
    assert request["status"] == "APPROVED"
    assert (fund["committed_usd"], fund["available_usd"]) == ("300.00", "700.00")


@pytest.mark.req("NFR-01")
async def test_logs_are_written_to_stderr_not_to_the_protocol_stream(db, tmp_path):
    with open(tmp_path / "server-stderr.log", "w+") as stderr_file:
        async with Client(stdio_client(server_as("staff_cb_cw1", db), errlog=stderr_file)) as client:
            result = await client.call_tool("list_funds", {})  # the protocol on stdout still works
            assert result.is_error is False
        stderr_file.seek(0)
        logged = stderr_file.read()
    assert "tool=list_funds staff=staff_cb_cw1 nonprofit=np_cb request='-' outcome=ok" in logged


@pytest.mark.req("SEC-02", "SEC-03")
@pytest.mark.parametrize("staff_id", [None, "staff_nobody"])
async def test_ac19_a_server_started_without_a_valid_identity_refuses_every_call(db, staff_id):
    before = snapshot()
    async with Client(server_as(staff_id, db)) as client:
        assert len((await client.list_tools()).tools) == 9  # tools can be discovered, but not used
        for tool, arguments in [("list_funds", {}), ("approve_request", {"request_id": "req_x"})]:
            result = await client.call_tool(tool, arguments)
            assert result.is_error and "[UNAUTHENTICATED]" in result.content[0].text
    assert snapshot() == before


@pytest.mark.req("FR-12")
def test_the_server_exits_instead_of_creating_a_missing_database(tmp_path):
    missing = tmp_path / "nowhere.db"
    finished = subprocess.run(
        [sys.executable, "-m", "assistance.server"],
        env={"ASSISTANCE_DB_PATH": str(missing), "ASSISTANCE_STAFF_ID": "staff_cb_cw1"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert finished.returncode == 1
    assert "Database not found" in finished.stderr
    assert finished.stdout == ""
    assert not missing.exists()


# ------------------------------------------------------------ processes competing


@pytest.mark.req("BR-11", "BR-08", "BR-05")
@pytest.mark.parametrize("attempt", range(3))  # repeated, because a race does not show up every time
async def test_ac08_ten_processes_approving_at_once_cannot_overspend_the_fund(db, attempt):
    request_ids = pending_requests(10, "300.00")  # $3,000.00 asked of a $1,000.00 fund

    async with AsyncExitStack() as stack:
        managers = await start_servers(stack, "staff_rr_pm1", db, count=10)
        results = await asyncio.gather(
            *(manager.call_tool("approve_request", {"request_id": request_id}) for manager, request_id in zip(managers, request_ids))
        )

    approved = [r for r in results if not r.is_error]
    refused = [r.content[0].text for r in results if r.is_error]
    assert len(approved) == 3, refused
    assert all(r.structured_content["request"]["status"] == "APPROVED" and not r.structured_content["replayed"] for r in approved)
    assert len(refused) == 7
    assert all("[INSUFFICIENT_FUNDS]" in text for text in refused), refused  # refused cleanly, not crashed

    assert fund_cents(TRANSPORT) == {"allocation": 100_000, "committed": 90_000, "paid": 0, "available": 10_000}
    statuses = [r.status for r in service.list_requests(as_staff("staff_rr_pm1")).requests]
    assert (statuses.count("APPROVED"), statuses.count("PENDING")) == (3, 7)


@pytest.mark.req("BR-11", "IDM-01", "IDM-03")
async def test_ac09_ac10_eight_processes_approving_then_paying_one_request_move_money_once(db):
    (request_id,) = pending_requests(1, "300.00")

    async with AsyncExitStack() as stack:
        managers = await start_servers(stack, "staff_rr_pm1", db, count=8)
        approvals = await asyncio.gather(*(m.call_tool("approve_request", {"request_id": request_id}) for m in managers))
    assert all(not r.is_error for r in approvals), [r.content[0].text for r in approvals if r.is_error]
    assert sorted(r.structured_content["replayed"] for r in approvals) == [False] + [True] * 7
    assert fund_cents(TRANSPORT) == {"allocation": 100_000, "committed": 30_000, "paid": 0, "available": 70_000}

    async with AsyncExitStack() as stack:
        finance = await start_servers(stack, "staff_rr_fin1", db, count=8)
        payments = await asyncio.gather(*(f.call_tool("record_payment", {"request_id": request_id}) for f in finance))
    assert all(not r.is_error for r in payments), [r.content[0].text for r in payments if r.is_error]
    assert sorted(r.structured_content["replayed"] for r in payments) == [False] + [True] * 7
    assert fund_cents(TRANSPORT) == {"allocation": 100_000, "committed": 0, "paid": 30_000, "available": 70_000}


@pytest.mark.req("BR-11", "IDM-04")
async def test_ac11_eight_processes_sending_the_same_create_make_one_request(db):
    arguments = {
        "participant_id": "part_rr_1",
        "fund_id": TRANSPORT,
        "amount_usd": "25.00",
        "purpose": "Bus pass",
        "idempotency_key": "same-key",
    }
    async with AsyncExitStack() as stack:
        case_workers = await start_servers(stack, "staff_rr_cw1", db, count=8)
        results = await asyncio.gather(*(c.call_tool("create_request", arguments) for c in case_workers))

    assert all(not r.is_error for r in results), [r.content[0].text for r in results if r.is_error]
    assert len({r.structured_content["request"]["request_id"] for r in results}) == 1
    assert sorted(r.structured_content["replayed"] for r in results) == [False] + [True] * 7
    assert len(service.list_requests(as_staff("staff_rr_cw1")).requests) == 1
