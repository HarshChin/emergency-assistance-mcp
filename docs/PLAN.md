# Plan: Emergency Assistance Funding MCP server

> This is the plan as approved on 2026-11-26, before any file was created. It was written by the
> AI assistant for me to review, which is why it says "you" and "I". It is kept as approved, except
> that local file paths and notes not relevant to the submission were removed. How the work
> actually went is in `TIME_LOG.md`, `AI_LOG.md` and `docs/SUBMISSION.md`; changes to the
> specification are in `docs/REVISIONS.md`.

## Context

Community Bridge tracks assistance requests and fund balances in spreadsheets. The brief asks for a headless MCP server:
case workers raise requests, program managers approve/reject, finance records simulated payments,
everyone reads fund balances, all inside their own nonprofit. The spec is a primary deliverable and
must be committed before any code. The interview will use the submission directly, so the code has
to be simple enough to explain and change live.

The project folder is empty and not yet a git repo.

## Decisions already taken (user's calls, 2026-11-26)

| Topic | Decision |
|---|---|
| Create retry | `idempotency_key` is **required** on `create_request`. Same key + same details → original request, `replayed: true`. Same key + different details → `IDEMPOTENCY_CONFLICT`. |
| Repeat approve / reject / pay | Success, no money moved, `replayed: true`. |
| Reject reason | Optional free text, stored and returned. |
| Amount input | `amount_usd` string, dollars with exactly two decimals (`"300.00"`). Stored as integer cents. |
| Business questions 5–14 | Go into the PRD as documented assumptions with my suggested answers. |

## Stack (checked against live docs, not memory)

| Item | Choice | Note |
|---|---|---|
| Python | 3.12 (`.python-version`) | 3.12.13 is installed |
| MCP SDK | `mcp==2.3.0` | v2 API: `from mcp.server import MCPServer`, `@mcp.tool()`, `mcp.run()` (stdio default) |
| Errors | `ToolError` from `mcp.server.mcpserver.exceptions` | Gives `is_error=True` + text the model reads. Message format `[CODE] what happened. How to fix.` |
| Output schemas | Pydantic models as tool return types | SDK publishes `output_schema` and fills `structured_content` |
| Client (tests, demo) | `from mcp import Client, StdioServerParameters` | `Client(mcp)` in-memory; `Client(StdioServerParameters(...))` spawns a real process. Child gets no parent env, identity passed via `env=` |
| Storage | SQLite file via stdlib `sqlite3` | no ORM |
| Tests | `pytest` + anyio plugin (ships with anyio) | no pytest-asyncio, no Hypothesis |
| Packaging | `uv`, `uv.lock` committed | |

## Design in brief

**Layout**

```
docs/        PLAN.md  PRD.md  TECH_SPEC.md  ARCHITECTURE.md  ADR.md  REVISIONS.md  TRACEABILITY.md
src/assistance/
  server.py    MCPServer + 9 thin tool functions (resolve caller → call service → return model)
  identity.py  env var → staff row → Caller(staff_id, role, nonprofit_id)
  rules.py     ROLE_PERMISSIONS table and STATUS_TRANSITIONS table (the only place for each)
  money.py     parse "300.00" → 30000 cents; format cents → "300.00"
  errors.py    AppError(code, message) and the error codes
  db.py        connect(), transaction() (BEGIN IMMEDIATE), schema.sql loader
  service.py   all business operations and all SQL; every query scoped by caller.nonprofit_id
  models.py    pydantic output models
  seed.py      reset + seed command (never run by the server)
  schema.sql
tests/         unit, service, in-memory MCP, stdio e2e, multi-process, random-sequence
scripts/       trace.py (requirement mapping)  demo.py (client walkthrough)
README.md  AI_LOG.md  TIME_LOG.md
```

**Tools (9)**: `list_participants`, `list_funds`, `get_funding_summary`, `create_request`,
`approve_request`, `reject_request`, `record_payment`, `get_request`, `list_requests`.
No tool has a staff, role or nonprofit argument.

**Overspending (multi-process safe).** In-memory locks are useless with one process per client, so
SQLite does it, in three layers:
1. Every write runs inside `BEGIN IMMEDIATE`, which takes the database write lock up front. Other
   processes wait (`busy_timeout`) instead of reading stale balances.
2. Approval is a guarded update: `UPDATE funds SET committed_cents = committed_cents + :amt WHERE
   id = :fund AND allocation_cents - committed_cents - paid_cents >= :amt`. Zero rows changed →
   roll back → `INSUFFICIENT_FUNDS`. The request update is guarded the same way with
   `WHERE status = 'PENDING'`.
3. `CHECK` constraints on `funds` (`committed >= 0`, `paid >= 0`, `committed + paid <= allocation`)
   as the last line of defence if the code is ever wrong.

**Duplicates.** Approve/reject/pay are idempotent by state: the status is read inside the
transaction first, so a repeat returns the current request with `replayed: true` before any funds
check (a retried approval never gets a false `INSUFFICIENT_FUNDS`). Create uses
`UNIQUE(created_by, idempotency_key)`.

**Access.** Identity comes only from `ASSISTANCE_STAFF_ID`, resolved against the `staff` table on
every call. Check order is fixed: identity → role → input → tenant-scoped lookup → status → funds.

| Case | Result |
|---|---|
| Env var missing or staff ID unknown | `UNAUTHENTICATED` |
| Role not allowed to do the action | `FORBIDDEN` (checked before any lookup, so it leaks nothing) |
| Record belongs to another nonprofit | `NOT_FOUND`, same text as a record that does not exist |

**Money.** `funds` stores `allocation_cents`, `committed_cents`, `paid_cents`; available is derived.
The random-sequence test checks the stored counters against sums recomputed from the `requests`
table, so the invariant is tested from two independent sources.

**Amounts.** `amount_usd` is a string; `300`, `"300"`, `"$300"`, `"300.5"`, `"1,000.00"`, zero and
negatives are rejected with a message that shows the corrected form. Responses echo `amount_usd`.

**Logs** go to stderr through `logging`; stdout carries only the MCP protocol.

## Tasks (one at a time; after each: 2–3 line summary, run tests, commit)

| # | Task | Depends on | Done when |
|---|---|---|---|
| 0 | `git init`; `.gitignore`; `docs/PLAN.md` (this plan); `docs/ADR.md` with the decisions above; `docs/REVISIONS.md`; `AI_LOG.md`; `TIME_LOG.md` | – | Committed |
| 1 | `docs/PRD.md`: users, workflows, goals / non-goals, requirement IDs, business rules, acceptance examples incl. failures, open questions + assumptions | 0 | You've read it; committed |
| 2 | `docs/TECH_SPEC.md`: data model, money storage, each tool with input/output schema + errors, role and nonprofit enforcement, OAuth-in-production note | 1 | Every PRD requirement is referenced; committed |
| 3 | `docs/ARCHITECTURE.md`: components, tool-call flow, one Mermaid diagram, concurrent approvals, task breakdown with gates, how AI-agent work is scoped and reviewed | 2 | Committed; tag `spec-v1` so "spec before code" is visible in git history |
| 4 | Scaffold: `pyproject.toml` with pinned deps, `uv.lock`, package skeleton, pytest `req` marker | 3 | `uv run pytest` runs (0 tests is fine) |
| 5 | `money.py`, `rules.py`, `errors.py` + unit tests | 4 | Tests green |
| 6 | `schema.sql`, `db.py`, `seed.py` (2 nonprofits, each with staff of all 3 roles, participants, funds) | 4 | Reset command rebuilds an identical DB twice in a row |
| 7 | `identity.py` + tests for missing / unknown identity | 6 | Tests green |
| 8 | `service.py` reads: participants, funds, get/list requests, summary, all tenant-scoped | 5, 7 | Cross-nonprofit reads return `NOT_FOUND` / empty |
| 9 | `service.py` writes: create, approve, reject, pay | 8 | Transition, funding, insufficient-funds, replay, and "failed action changes nothing" tests green |
| 10 | `server.py`: tools, output models, error mapping, stderr logging + in-memory MCP tests | 9 | Schemas published; no identity-like argument on any tool; error text is actionable |
| 11 | Stdio e2e test, and the multi-process test: N real server processes race on one fund (10 × $300 against $1,000 → exactly 3 approved, $900 committed) and on one request (approved once, paid once) | 10 | Green on repeated runs; then one deliberate break of the guard to confirm the test fails, result logged as it happened |
| 12 | Random-sequence test: seeded `random`, mixed valid/invalid actions and callers; after every step `available + committed + paid == allocation`, counters match recomputed sums, nothing negative | 9 | Green across all seeds; failing seed is printed |
| 13 | `scripts/trace.py`: reads IDs from the PRD, `# REQ:` comments in `src/`, `@pytest.mark.req(...)` in tests; writes `docs/TRACEABILITY.md`; exits 1 if a requirement has no test | 11, 12 | Script exits 0 |
| 14 | `scripts/demo.py` (discover → create → approve → pay → summary, three identities) and `README.md` (setup, reset, run, test, client config) | 10 | Demo runs clean from a fresh reset |
| 15 | Final writeup: real test output (including anything failed or not run), limitations, next priorities, three AI examples; close `TIME_LOG.md` and `AI_LOG.md` | all | Committed |

## Working rules

- Docs 1–3 are committed before task 4 starts. Any later change to behaviour gets a row in
  `docs/REVISIONS.md` with the reason, and an ADR entry if it is a design decision.
- Every test carries `@pytest.mark.req("<ID>")`.
- `TIME_LOG.md` uses real clock times taken with `date` at each stage start and stop (planning
  for this session ended around 16:00 IST; you supply anything before it).
- `AI_LOG.md` records what you asked, what I suggested, how it was checked, and real corrections
  only. First entry: checking the SDK docs showed v2's `MCPServer` API, not the older `FastMCP`.
- Nothing from the brief's out-of-scope list; no extra tools.

## Verification

```bash
uv sync
uv run python -m assistance.seed --reset
uv run pytest -v
uv run python scripts/trace.py
uv run python scripts/demo.py
```

- `pytest` covers: transitions and funding maths, insufficient funds, repeated approvals and
  payment retries, create retries, role restrictions, cross-nonprofit access, missing/unknown
  identity, invalid inputs, stdio end-to-end, multi-process contention, random-sequence invariant.
- `trace.py` must exit 0 (every requirement has at least one test).
- `demo.py` must end with the fund summary matching the brief's example arithmetic.
- The final writeup pastes the actual output of these commands.
