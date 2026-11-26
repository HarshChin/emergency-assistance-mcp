"""A walk through the server as an MCP client. No language model is involved.

    uv run python scripts/demo.py

It resets a separate demo database (data/demo.db), then starts a real server
process over stdio for each staff member in turn: a case worker creates a
request, a program manager approves it, finance records the payment, and the
final funding summary is checked against the example in the brief.
Exit code 0 means the final summary was exactly as expected.
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent
DEMO_DB = ROOT / "data" / "demo.db"
SERVER_LOG = ROOT / "data" / "demo-server.log"
FUND = "fund_cb_rent"


def title(text: str) -> None:
    print(f"\n=== {text}", flush=True)  # flush so output from child processes appears in order


def show(label: str, result) -> dict | None:
    """Print one tool result: structured data on success, the error text on refusal."""
    if result.is_error:
        print(f"  {label}\n      REFUSED  {result.content[0].text}")
        return None
    print(f"  {label}\n      {json.dumps(result.structured_content)}")
    return result.structured_content


def server_as(staff_id: str, log_file):
    """One server process for one staff member. Its stderr (the logs) goes to log_file."""
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "assistance.server"],
        env={"ASSISTANCE_STAFF_ID": staff_id, "ASSISTANCE_DB_PATH": str(DEMO_DB)},
    )
    return Client(stdio_client(parameters, errlog=log_file))


async def main() -> int:
    title("Reset the demo database (the setup command, separate from the server)")
    subprocess.run(
        [sys.executable, "-m", "assistance.seed", "--reset"],
        env={**os.environ, "ASSISTANCE_DB_PATH": str(DEMO_DB)},
        check=True,
    )

    with open(SERVER_LOG, "w") as log_file:
        title("Case worker staff_cb_cw1 connects and discovers the tools")
        async with server_as("staff_cb_cw1", log_file) as case_worker:
            tools = (await case_worker.list_tools()).tools
            for tool in tools:
                print(f"  {tool.name:<22}{tool.description.splitlines()[0]}")
            create_tool = next(tool for tool in tools if tool.name == "create_request")
            print("\n  Input schema of create_request:")
            print("     ", json.dumps(create_tool.input_schema["properties"]["amount_usd"]))
            print("  Output schema of create_request has:", list(create_tool.output_schema["properties"]))

            title("Case worker looks up a participant and a fund, then creates a request")
            show("list_participants(name_contains='Alex')", await case_worker.call_tool("list_participants", {"name_contains": "Alex"}))
            show("list_funds()", await case_worker.call_tool("list_funds", {}))
            show(f"get_funding_summary('{FUND}')  [before]", await case_worker.call_tool("get_funding_summary", {"fund_id": FUND}))
            request_arguments = {
                "participant_id": "part_cb_1",
                "fund_id": FUND,
                "amount_usd": "300.00",
                "purpose": "March rent",
                "idempotency_key": "demo-request-1",
            }
            created = show("create_request($300.00, 'March rent')", await case_worker.call_tool("create_request", request_arguments))
            request_id = created["request"]["request_id"]

            title("Things that are refused or have no second effect")
            show("create_request again, same key  -> the same request, replayed", await case_worker.call_tool("create_request", request_arguments))
            show("create_request with amount '300'", await case_worker.call_tool("create_request", {**request_arguments, "amount_usd": "300", "idempotency_key": "demo-request-2"}))
            show("approve_request as a case worker", await case_worker.call_tool("approve_request", {"request_id": request_id}))

        title("Program manager staff_cb_pm1 approves it (a new server process)")
        async with server_as("staff_cb_pm1", log_file) as manager:
            show("approve_request", await manager.call_tool("approve_request", {"request_id": request_id}))
            show("approve_request again  -> replayed, nothing reserved twice", await manager.call_tool("approve_request", {"request_id": request_id}))
            show(f"get_funding_summary('{FUND}')  [after approval]", await manager.call_tool("get_funding_summary", {"fund_id": FUND}))

        title("A manager of the other nonprofit cannot see the request at all")
        async with server_as("staff_rr_pm1", log_file) as outsider:
            show("get_request as staff_rr_pm1", await outsider.call_tool("get_request", {"request_id": request_id}))

        title("Finance staff_cb_fin1 records the payment (a new server process)")
        async with server_as("staff_cb_fin1", log_file) as finance:
            show("record_payment", await finance.call_tool("record_payment", {"request_id": request_id}))
            show("get_request", await finance.call_tool("get_request", {"request_id": request_id}))
            final = show(f"get_funding_summary('{FUND}')  [final]", await finance.call_tool("get_funding_summary", {"fund_id": FUND}))

    title("Server log (stderr of the server processes, kept apart from the protocol)")
    for line in SERVER_LOG.read_text().splitlines():
        if "tool=" in line:
            print("  " + line)

    title("Check against the brief's example")
    expected = {"allocation_usd": "10000.00", "committed_usd": "0.00", "paid_usd": "300.00", "available_usd": "9700.00"}
    actual = {key: final["funds"][0][key] for key in expected}
    print(f"  expected {expected}\n  actual   {actual}")
    if actual != expected:
        print("  MISMATCH")
        return 1
    print("  OK: $300 paid, $0 committed, $9,700 available")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
