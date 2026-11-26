# Emergency Assistance Funding MCP server

A headless MCP server for a nonprofit's emergency assistance workflow: case workers raise
requests, program managers approve or reject them, finance records simulated payments, and
everyone can see fund balances. Bonterra engineering take-home. No UI.

## Requirements

- [uv](https://docs.astral.sh/uv/) 0.12 or later (it installs Python 3.12 if needed)

## Commands

Run all of these from the repository root.

| Step | Command |
|---|---|
| Install pinned dependencies | `uv sync` |
| Create or reset the database | `uv run python -m assistance.seed --reset` |
| Run all tests | `uv run pytest` |
| Build and check the requirement mapping | `uv run python scripts/trace.py` |
| Run the client demonstration | `uv run python scripts/demo.py` |
| Start the server by hand (stdio) | `ASSISTANCE_STAFF_ID=staff_cb_cw1 uv run python -m assistance.server` |

Notes:

- The server never creates or changes the seed data. If the database file is missing it logs
  an error and exits. Reset is the only command that creates it.
- The demo uses its own database (`data/demo.db`) and resets it each run, so it is repeatable
  and does not touch `data/assistance.db`.
- Started by hand, the server prints nothing and waits: it speaks MCP on stdin/stdout. Logs go
  to stderr.

## Configuration

| Variable | Meaning | Default |
|---|---|---|
| `ASSISTANCE_STAFF_ID` | Who is calling. The server looks up the role and nonprofit. Missing or unknown: every tool call returns `UNAUTHENTICATED`. | none |
| `ASSISTANCE_DB_PATH` | SQLite file | `data/assistance.db` |

## Fixture identities

| Staff ID | Nonprofit | Role |
|---|---|---|
| `staff_cb_cw1`, `staff_cb_cw2` | Community Bridge | case worker |
| `staff_cb_pm1`, `staff_cb_pm2` | Community Bridge | program manager |
| `staff_cb_fin1` | Community Bridge | finance |
| `staff_rr_cw1` | Riverside Relief | case worker |
| `staff_rr_pm1` | Riverside Relief | program manager |
| `staff_rr_fin1` | Riverside Relief | finance |

Funds: `fund_cb_rent` $10,000.00, `fund_cb_util` $2,500.00, `fund_rr_transport` $1,000.00,
`fund_rr_housing` $5,000.00. Participants: `part_cb_1` to `part_cb_3`, `part_rr_1`, `part_rr_2`.

## Connecting an MCP client

One server entry per staff member; the identity is fixed by the entry's environment. Example for
Claude Desktop or any client that uses the `mcpServers` format (use absolute paths):

```json
{
  "mcpServers": {
    "assistance-case-worker": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/Bonterra", "python", "-m", "assistance.server"],
      "env": {
        "ASSISTANCE_STAFF_ID": "staff_cb_cw1",
        "ASSISTANCE_DB_PATH": "/absolute/path/to/Bonterra/data/assistance.db"
      }
    },
    "assistance-program-manager": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/Bonterra", "python", "-m", "assistance.server"],
      "env": {
        "ASSISTANCE_STAFF_ID": "staff_cb_pm1",
        "ASSISTANCE_DB_PATH": "/absolute/path/to/Bonterra/data/assistance.db"
      }
    }
  }
}
```

## Tools

| Tool | Who | What it does |
|---|---|---|
| `list_participants` | all | Find a participant ID |
| `list_funds` | all | Find a fund ID |
| `get_funding_summary` | all | Allocation, committed, paid, available |
| `get_request`, `list_requests` | all | Read requests |
| `create_request` | case worker | New `PENDING` request; needs an `idempotency_key` |
| `approve_request` | program manager | `PENDING` → `APPROVED`, reserves the amount |
| `reject_request` | program manager | `PENDING` → `REJECTED` |
| `record_payment` | finance | `APPROVED` → `PAID` |

Amounts are text in dollars with two decimals: `"300.00"`. Refusals start with a code:
`UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `INVALID_AMOUNT`, `INVALID_TRANSITION`,
`INSUFFICIENT_FUNDS`, `IDEMPOTENCY_CONFLICT`.

## Where things are

| Path | Contents |
|---|---|
| `docs/PRD.md` | Requirements with IDs, business rules, acceptance examples, assumptions |
| `docs/TECH_SPEC.md` | Data model, money, tools and errors, access enforcement, OAuth note |
| `docs/ARCHITECTURE.md` | Components, call flow, concurrency diagram, task breakdown |
| `docs/ADR.md`, `docs/REVISIONS.md` | Design decisions; changes to the spec and why |
| `docs/TRACEABILITY.md` | Generated requirement → code → test mapping |
| `docs/PLAN.md` | The implementation plan approved before work started |
| `docs/SUBMISSION.md` | Test results, limitations, next steps, AI workflow examples |
| `AI_LOG.md`, `TIME_LOG.md` | AI workflow record; actual clock times |
| `src/assistance/rules.py` | The permission table and the status-transition table |
| `src/assistance/service.py` | All business operations and SQL |
| `src/assistance/server.py` | The nine MCP tools |
| `tests/` | Unit, service, in-memory MCP, stdio and multi-process, random-sequence tests |

The spec documents were committed before any code; the tag `spec-v1` marks that point.
