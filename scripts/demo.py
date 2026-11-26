"""A walk through the server as an MCP client. No language model is involved.

    uv run python scripts/demo.py

It resets a separate demo database (data/demo.db), then starts a real server
process over stdio for each staff member in turn: a case worker creates a
request, a program manager approves it, finance records the payment, and the
final funding summary is checked against the example in the brief.
Exit code 0 means the final summary was exactly as expected.

For every step the output shows the complete tool call (name and every
argument, exactly as sent) and then what came back. Fields are aligned, lists
are tables, and fields that are not set yet are left out. Colour is used only
when the output is a terminal (and NO_COLOR is not set).
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

from mcp import Client, StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent
DEMO_DB = ROOT / "data" / "demo.db"
SERVER_LOG = ROOT / "data" / "demo-server.log"
FUND = "fund_cb_rent"

# ---------------------------------------------------------------- printing

# Lay out for the terminal's width, but never narrower than 80 or wider than 110 columns:
# a very narrow panel would otherwise cut the descriptions short and squeeze the error text.
WIDTH = max(80, min(shutil.get_terminal_size().columns, 110))
USE_COLOUR = sys.stdout.isatty() and "NO_COLOR" not in os.environ
BOLD, DIM, RED, GREEN, YELLOW, CYAN = "1", "2", "31", "32", "33", "1;36"


def paint(text: str, colour: str) -> str:
    return f"\033[{colour}m{text}\033[0m" if USE_COLOUR else text


def title(text: str) -> None:
    # flush so that output from child processes appears in the right place
    print("\n" + paint(text, CYAN) + "\n" + paint("─" * WIDTH, DIM), flush=True)


def as_text(value) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


def format_call(tool: str, arguments: dict) -> str:
    """The call as it was sent: tool(name='value', ...). One argument per line if it is long."""
    parts = [f"{name}={value!r}" for name, value in arguments.items()]
    one_line = f"{tool}({', '.join(parts)})"
    if len(one_line) <= WIDTH - 4:
        return one_line
    return f"{tool}(\n" + "".join(f"        {part},\n" for part in parts) + "    )"


def print_fields(fields: dict, indent: int = 6) -> None:
    """A record as aligned "name  value" lines. Unset (null) fields are left out."""
    # {"request": {...}, "replayed": false} is shown as one list of fields.
    flat = {}
    for name, value in fields.items():
        flat.update(value if isinstance(value, dict) else {name: value})
    shown = {name: value for name, value in flat.items() if value is not None}
    name_width = max(len(name) for name in shown)
    for name, value in shown.items():
        if isinstance(value, list):
            print_table(value, indent)
        else:
            print(" " * indent + paint(name.ljust(name_width), DIM) + "  " + as_text(value))


def print_table(rows: list[dict], indent: int = 6) -> None:
    """A list of records as a table with a header row. Money columns are right-aligned."""
    if not rows:
        print(" " * indent + paint("(none)", DIM))
        return
    columns = list(rows[0])
    widths = {c: max(len(c), *(len(as_text(row[c])) for row in rows)) for c in columns}

    def cell(column: str, text: str) -> str:
        return text.rjust(widths[column]) if column.endswith("_usd") else text.ljust(widths[column])

    print(" " * indent + paint("  ".join(cell(c, c) for c in columns).rstrip(), DIM))
    for row in rows:
        print(" " * indent + "  ".join(cell(c, as_text(row[c])) for c in columns).rstrip())


async def call(client: Client, tool: str, arguments: dict, note: str = "") -> dict | None:
    """Call one tool. Print exactly what was sent, then what came back.

    Returns the structured result, or None if the call was refused.
    """
    result = await client.call_tool(tool, arguments)

    print()
    if note:
        print("  " + paint(f"# {note}", DIM))
    print("  " + paint("▸ " + format_call(tool, arguments), BOLD))

    if result.is_error:
        print("  " + paint("✗ refused", RED))
        for line in textwrap.wrap(result.content[0].text, WIDTH - 6):
            print("      " + line)
        return None
    data = result.structured_content
    print("  " + (paint("↻ replayed (nothing changed)", YELLOW) if data.get("replayed") else paint("✓ ok", GREEN)))
    print_fields(data)
    return data


# ---------------------------------------------------------------- the demo


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
                first_line = tool.description.splitlines()[0]
                print(f"  {paint(tool.name.ljust(21), BOLD)}{textwrap.shorten(first_line, WIDTH - 23, placeholder=' …')}")

            create_tool = next(tool for tool in tools if tool.name == "create_request")
            print("\n  " + paint("create_request: input schema of amount_usd", BOLD))
            print(textwrap.indent(json.dumps(create_tool.input_schema["properties"]["amount_usd"], indent=2), "      "))
            print("  " + paint("create_request: output fields", BOLD))
            print("      " + ", ".join(create_tool.output_schema["properties"]))

            title("Case worker looks up a participant and a fund, then creates a request")
            await call(case_worker, "list_participants", {"name_contains": "Alex"})
            await call(case_worker, "list_funds", {})
            await call(case_worker, "get_funding_summary", {"fund_id": FUND}, note="the fund before anything happens")
            new_request = {
                "participant_id": "part_cb_1",
                "fund_id": FUND,
                "amount_usd": "300.00",
                "purpose": "March rent",
                "idempotency_key": "demo-request-1",
            }
            created = await call(case_worker, "create_request", new_request)
            request_id = created["request"]["request_id"]

            title("Things that are refused or have no second effect")
            await call(case_worker, "create_request", new_request, note="the same call again, same idempotency_key")
            await call(
                case_worker,
                "create_request",
                {**new_request, "amount_usd": "300", "idempotency_key": "demo-request-2"},
                note="amount without decimals: dollars or cents?",
            )
            await call(case_worker, "approve_request", {"request_id": request_id}, note="a case worker tries to approve")

        title("Program manager staff_cb_pm1 approves it (a new server process)")
        async with server_as("staff_cb_pm1", log_file) as manager:
            await call(manager, "approve_request", {"request_id": request_id})
            await call(manager, "approve_request", {"request_id": request_id}, note="the same call again: nothing is reserved twice")
            await call(manager, "get_funding_summary", {"fund_id": FUND}, note="the fund after approval")

        title("A manager of the other nonprofit cannot see the request at all")
        async with server_as("staff_rr_pm1", log_file) as outsider:
            await call(outsider, "get_request", {"request_id": request_id}, note="called by staff_rr_pm1 of Riverside Relief")

        title("Finance staff_cb_fin1 records the payment (a new server process)")
        async with server_as("staff_cb_fin1", log_file) as finance:
            await call(finance, "record_payment", {"request_id": request_id})
            final = await call(finance, "get_funding_summary", {"fund_id": FUND}, note="the fund at the end")

    title("Server log (stderr of the server processes, kept apart from the protocol)")
    log_lines = [line for line in SERVER_LOG.read_text().splitlines() if "tool=" in line]
    # each line looks like: tool=approve_request staff=staff_cb_pm1 nonprofit=np_cb request='req_1' outcome=ok
    rows = [dict(re.findall(r"(\w+)=('[^']*'|\S+)", line)) for line in log_lines]
    print_table([{name: value.strip("'") for name, value in row.items()} for row in rows], indent=2)

    title("Check against the brief's example")
    expected = {"allocation_usd": "10000.00", "committed_usd": "0.00", "paid_usd": "300.00", "available_usd": "9700.00"}
    actual = {key: final["funds"][0][key] for key in expected}
    print_table([{"": "expected", **expected}, {"": "actual", **actual}], indent=2)
    if actual != expected:
        print("\n  " + paint("✗ MISMATCH", RED))
        return 1
    print("\n  " + paint("✓ OK: $300 paid, $0 committed, $9,700 available", GREEN))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
