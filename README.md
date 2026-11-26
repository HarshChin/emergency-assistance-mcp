# Emergency Assistance Funding MCP server

A headless MCP server for a nonprofit's emergency assistance workflow. Case workers raise
assistance requests, program managers approve or reject them, finance records simulated
payments, and all staff can see fund balances, each only within their own nonprofit.
Bonterra engineering take-home. There is no UI.

## Start here

| If you want to | Read or run |
|---|---|
| Understand what was built and why | `docs/PRD.md`, then `docs/TECH_SPEC.md`, then `docs/ARCHITECTURE.md` |
| See the results, limitations and AI workflow evidence | `docs/SUBMISSION.md` |
| See it working in two minutes | [Run the demo](#run-the-demo) |
| Use it from a real MCP host | [Use it from Claude Code](#use-it-from-claude-code) |

The specification was committed before any code. The git tag `spec-v1` marks that point.

## Setup

Needs [uv](https://docs.astral.sh/uv/) 0.12 or later; it installs Python 3.12 if needed. Run every
command from the repository root.

```bash
uv sync
```

```bash
uv run python -m assistance.seed --reset
```

The first installs the pinned dependencies from `uv.lock`. The second creates the database
`data/assistance.db` with the synthetic data below. Running it again wipes the database and
starts over. The server itself never creates or changes the seed data.

## Run the tests

```bash
uv run pytest
```

```bash
uv run python scripts/trace.py
```

`pytest` runs every test, including tests that start real server processes and make them compete
for the same fund. `trace.py` writes `docs/TRACEABILITY.md`, the requirement → code → test
mapping, and fails if any requirement in the PRD has no test.

## Run the demo

```bash
uv run python scripts/demo.py
```

This plays the whole workflow as an MCP client, without a language model. It starts a real server
process for each staff member in turn: a case worker discovers the tools and creates a $300.00
request, a program manager approves it, and finance records the payment. Along the way it shows
a retried call that changes nothing, a badly formatted amount, a case worker trying to approve,
and a manager from the other nonprofit who cannot see the request.

For every step it prints the complete tool call, then what came back. It ends by checking the
fund against the example in the brief: $300.00 paid, $0.00 committed, $9,700.00 available.

The demo uses its own database (`data/demo.db`) and resets it each run, so it never touches
`data/assistance.db`. Use a terminal at least 100 columns wide for readable tables.

## Use it from Claude Code

The caller's identity is fixed by the environment of the server process, so each staff role is
registered as its own MCP server.

1. Reset the database:

   ```bash
   uv run python -m assistance.seed --reset
   ```

2. Register one server per role. Run these from the repository root; they fill in the full paths
   for you.

   ```bash
   claude mcp add assistance-case-worker -e ASSISTANCE_STAFF_ID=staff_cb_cw1 -e ASSISTANCE_DB_PATH="$(pwd)/data/assistance.db" -- "$(which uv)" run --directory "$(pwd)" python -m assistance.server
   ```

   ```bash
   claude mcp add assistance-manager -e ASSISTANCE_STAFF_ID=staff_cb_pm1 -e ASSISTANCE_DB_PATH="$(pwd)/data/assistance.db" -- "$(which uv)" run --directory "$(pwd)" python -m assistance.server
   ```

   ```bash
   claude mcp add assistance-finance -e ASSISTANCE_STAFF_ID=staff_cb_fin1 -e ASSISTANCE_DB_PATH="$(pwd)/data/assistance.db" -- "$(which uv)" run --directory "$(pwd)" python -m assistance.server
   ```

3. Check that all three connect. Each should show `✔ Connected`.

   ```bash
   claude mcp list
   ```

4. Start a new Claude Code session in the same folder (run `claude` there). The servers are
   registered for this folder only, and a session that was already running will not see them.
   To confirm, ask it which MCP servers it has: it should name `assistance-case-worker`,
   `assistance-manager` and `assistance-finance`.

5. Talk to it in plain language, for example:
   - "As the case worker, find Alex Rivera and raise a $300 rent request against the rent fund."
   - "As the manager, approve it and show me the fund summary."
   - "As finance, record the payment and show the summary again."
   - "As the case worker, try to approve a request." This should be refused with `FORBIDDEN`.

To remove the servers afterwards, run `claude mcp remove` with each name, for example:

```bash
claude mcp remove assistance-case-worker
```

Other MCP hosts that launch local stdio servers (Claude Desktop, IDEs) need the same three things
per role: the command `uv run --directory <repo> python -m assistance.server`, and the two
environment variables below.

## Configuration

| Variable | Meaning | Default |
|---|---|---|
| `ASSISTANCE_STAFF_ID` | Who is calling. The server looks up the role and nonprofit itself. If it is missing or unknown, every tool call returns `UNAUTHENTICATED`. | none |
| `ASSISTANCE_DB_PATH` | The SQLite file | `data/assistance.db` |

If the database file does not exist, the server logs an error and exits. Started by hand
(`ASSISTANCE_STAFF_ID=staff_cb_cw1 uv run python -m assistance.server`) it prints nothing and
waits, because it speaks MCP on stdin and stdout. Logs go to stderr.

## Synthetic data

| Staff ID | Nonprofit | Role |
|---|---|---|
| `staff_cb_cw1`, `staff_cb_cw2` | Community Bridge | case worker |
| `staff_cb_pm1`, `staff_cb_pm2` | Community Bridge | program manager |
| `staff_cb_fin1` | Community Bridge | finance |
| `staff_rr_cw1` | Riverside Relief | case worker |
| `staff_rr_pm1` | Riverside Relief | program manager |
| `staff_rr_fin1` | Riverside Relief | finance |

| Fund | Nonprofit | Allocation |
|---|---|---|
| `fund_cb_rent` | Community Bridge | $10,000.00 |
| `fund_cb_util` | Community Bridge | $2,500.00 |
| `fund_rr_transport` | Riverside Relief | $1,000.00 |
| `fund_rr_housing` | Riverside Relief | $5,000.00 |

Participants: `part_cb_1` to `part_cb_3` (Community Bridge), `part_rr_1` and `part_rr_2`
(Riverside Relief).

## Tools

| Tool | Who can use it | What it does |
|---|---|---|
| `list_participants` | everyone | Find a participant ID |
| `list_funds` | everyone | Find a fund ID |
| `get_funding_summary` | everyone | Allocation, committed, paid and available for a fund |
| `get_request`, `list_requests` | everyone | Read requests |
| `create_request` | case worker | New `PENDING` request. Reserves no money. Needs an `idempotency_key`. |
| `approve_request` | program manager | `PENDING` → `APPROVED`. Reserves the full amount, if the fund has it. |
| `reject_request` | program manager | `PENDING` → `REJECTED`. The fund is not changed. |
| `record_payment` | finance | `APPROVED` → `PAID`. Moves the amount from committed to paid. |

Amounts are text in dollars with exactly two decimals, such as `"300.00"`. Repeating an approve,
reject, payment or create (with the same key) changes nothing and returns `replayed: true`.

A refused call starts with one of these codes and says how to fix the call: `UNAUTHENTICATED`,
`FORBIDDEN`, `NOT_FOUND`, `INVALID_AMOUNT`, `INVALID_TRANSITION`, `INSUFFICIENT_FUNDS`,
`IDEMPOTENCY_CONFLICT`. A record of another nonprofit is reported as `NOT_FOUND`, exactly like a
record that does not exist.

## Where things are

| Path | Contents |
|---|---|
| `docs/PRD.md` | Users, workflows, requirements with IDs, business rules, acceptance examples, assumptions |
| `docs/TECH_SPEC.md` | Data model, money, each tool's inputs, outputs and errors, access control, OAuth in production |
| `docs/ARCHITECTURE.md` | Components, how a call flows, two approvals at once (diagram), task breakdown |
| `docs/ADR.md` | Design decisions, with the alternatives rejected |
| `docs/REVISIONS.md` | Changes to the specification after it was first committed, and why |
| `docs/TRACEABILITY.md` | Requirement → code → test mapping (generated by `scripts/trace.py`) |
| `docs/PLAN.md` | The implementation plan as approved before any file was created |
| `docs/SUBMISSION.md` | Test results, time, limitations, next priorities, AI workflow examples |
| `AI_LOG.md` | What was asked of the AI, what it suggested, how it was checked, corrections |
| `TIME_LOG.md` | Actual clock times per stage |
| `src/assistance/rules.py` | The permission table and the status-transition table |
| `src/assistance/service.py` | All business operations and all SQL |
| `src/assistance/server.py` | The nine MCP tools |
| `tests/` | Unit, service, in-memory MCP, real-process and random-sequence tests |
| `scripts/` | `demo.py` and `trace.py` |
