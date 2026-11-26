# Submission notes

Results, time, limitations, next steps and AI workflow evidence. Everything in section 1 is
pasted from real runs; nothing is estimated.

## 1. Verification results

Run on 2026-11-26 from a **fresh clone** of commit `9f4fbbb` (macOS arm64, Python 3.12.13,
uv 0.12.12), using exactly the commands in the README.

| Command | Result |
|---|---|
| `uv sync` | Installed from `uv.lock` |
| `uv run python -m assistance.seed --reset` | `Seeded data/assistance.db: 2 nonprofits, 8 staff, 5 participants, 4 funds.` |
| `uv run python -m assistance.seed` (no `--reset`, file exists) | Refused, exit 1: `data/assistance.db already exists. Use --reset to delete it and start again.` |
| `uv run pytest -q` | `248 passed in 43.23s` |
| `uv run python scripts/trace.py` | `44 requirements, 89 tagged test functions, wrote docs/TRACEABILITY.md`, exit 0 |
| `uv run python scripts/demo.py` | Exit 0; last line `OK: $300 paid, $0 committed, $9,700 available` |

| Test file | Tests | What it covers |
|---|---|---|
| `test_money.py` | 26 | Amount parsing and formatting |
| `test_rules.py` | 41 | Permission table, transition table, repeat detection |
| `test_db.py` | 12 | Constraints, seed/reset, rollback |
| `test_identity.py` | 12 | Identity from environment; missing and unknown |
| `test_service_reads.py` | 18 | Reads and nonprofit scoping |
| `test_service_writes.py` | 56 | Acceptance examples AC-01 to AC-22 at service level |
| `test_mcp_tools.py` | 30 | Tools through the in-memory MCP client: schemas, results, errors |
| `test_stdio_processes.py` | 11 | Real server processes over stdio: end to end, restart, competing processes |
| `test_random_sequences.py` | 41 | 40 seeds × 120 random actions, money rules checked after every step |
| `test_setup.py` | 1 | Pinned versions |
| **Total** | **248** | **0 failed, 0 skipped** |

Requirement → code → test mapping: [TRACEABILITY.md](TRACEABILITY.md) (generated; all 44
requirements have at least one test and one code reference).

### Competing approvals: how they are handled and how that was verified

Each stdio client is its own server process, so the database does the coordination
([ARCHITECTURE.md](ARCHITECTURE.md) section 3): every write runs under `BEGIN IMMEDIATE`, the
reservation is one guarded `UPDATE`, and `CHECK` constraints on `funds` are the backstop.

| Evidence | Result |
|---|---|
| Ten real server processes approve ten $300.00 requests on a $1,000.00 fund at once | Exactly 3 approved, 7 `INSUFFICIENT_FUNDS`, $900.00 committed. 3 attempts per run. |
| Eight processes approve, then eight pay, the same request | One real change each time, seven `replayed` |
| Eight processes send the same create with the same key | One request, seven `replayed` |
| Race tests repeated 5 more times | 25 executions, 0 failures |
| Guard broken on purpose: balance checked in Python with no lock, `CHECK` removed | Test failed; 9 of 10 approved in the failure shown ($2,700.00 against $1,000.00) |
| Same, with `CHECK` kept | Test failed; exactly 3 approved, the rest crashed on the constraint instead of a clean refusal |
| Only `BEGIN IMMEDIATE` changed to `BEGIN` | Test failed; wrong count and uncoded crashes (cause not inspected further) |
| Code restored | Test passed |

### Checks that failed or were not run

| Check | Status |
|---|---|
| Any test in the final suite | None failed |
| A real MCP host (Claude Desktop, Claude Code, an LLM calling the tools) | **Not run.** Only the SDK's own `Client` was used, in memory and over stdio. The README config block is untested. |
| Other platforms | **Not run.** macOS arm64 and Python 3.12.13 only. |
| More than 10 competing processes, or writes waiting longer than the 5 s busy timeout | **Not run.** |
| Linting or type checking | **Not run.** None is configured. |
| Rendering of the Mermaid diagram | **Not checked.** |
| Assumption S4 (tools run in worker threads) | Checked once with a throwaway script; no permanent test. |

## 2. Time

From [TIME_LOG.md](../TIME_LOG.md), clock times taken with `date`.

| Part | Minutes |
|---|---|
| Recorded span of the build, 15:59 to 18:20 IST | 141 |
| Of which: review, decisions and questions (plan, PRD, tech spec, architecture) | 114 |
| Of which: AI writing specs, code, tests and this writeup (tasks 0 to 15) | 27 |
| Later the same day: fixing a test gap found in review, re-verifying, updating these notes (19:05 to 19:06) | 1 |
| Before 15:59: ideation, reading the brief, checking SDK docs | not captured |

## 3. Known limitations

| Area | Limitation |
|---|---|
| Identity | Trusted from an environment variable, as the brief specifies. Anyone who can launch the server with another staff ID acts as that person. Production needs the OAuth design in TECH_SPEC section 11. |
| Concurrency | SQLite allows one writer at a time. Writes queue for up to 5 s; beyond that a call fails with a generic error rather than a coded one. Suitable for this scale, not for heavy write load. |
| Nonprofit integrity | A request's participant and fund are checked against the caller's nonprofit in service code, not by a database constraint. |
| Audit | Only the latest who/when is kept on the request row. There is no history table, and logs go to stderr only. |
| Lists | `list_participants` caps at 100 and `list_requests` at 200, with no pagination. |
| Error wording | Arguments that break the input schema (for example an amount sent as a number) are refused by the SDK in Pydantic's wording, without one of our error codes. |
| Late retries | Approving a request that is already `PAID` returns `INVALID_TRANSITION`, not `replayed`. |
| Schema changes | No migrations. Changing the schema means running reset. |
| Idempotency keys | Kept forever, scoped per case worker. |

## 4. Next priorities

1. Connect a real MCP host with an LLM and watch whether the model recovers from each error message.
2. HTTP transport with OAuth: `TokenVerifier`, audience check, token subject → staff row.
3. Return a coded `TRY_AGAIN` error when the busy timeout is hit.
4. Composite foreign keys so the database itself enforces that a request's participant and fund belong to its nonprofit.
5. Request history table for a full audit trail.
6. CI that runs `pytest` and `scripts/trace.py`; add a linter and type checker.
7. Pagination on the list tools.

## 5. AI workflow: three examples

Claude Code was used throughout. Full record: [AI_LOG.md](../AI_LOG.md).

### Requirements analysis and specification

| | |
|---|---|
| Prompt | "tell me in simple words what you understood from the doc" and "list the questions you'd ask the business where the doc is unclear. give me your suggestion for each but I'll take the call" |
| AI output | A summary and 14 questions with suggested answers; four flagged as changing the tool design. I decided those four; the rest are listed as assumptions in the PRD. |
| Independent check | The summary was checked against the brief's own arithmetic example, which is now test `test_ac01...` and `test_ac02...`. |
| Correction | The AI's PRD said every refusal carries an error code. While writing the tech spec it found the SDK refuses schema-invalid arguments before tool code runs. PRD reworded (REVISIONS.md row 1); later confirmed by `test_ac21_an_amount_sent_as_a_number_is_refused_and_creates_nothing`. |

### Implementation planning and coding

| | |
|---|---|
| Prompt | "check the sdk docs, don't go from memory" and "with stdio every client spawns its own server process right? ... an in-memory lock won't help, the db has to be the one that stops it" |
| AI output | Found the SDK is at 2.3.0 with a different API from v1 (`MCPServer`, one `Client`, `ToolError`). Confirmed the process-per-client point and proposed `BEGIN IMMEDIATE` + a guarded `UPDATE` + `CHECK` constraints. |
| Independent check | PyPI and the published docs first; then four specific SDK behaviours were run before being relied on (TECH_SPEC section 12). The locking design was proven by the multi-process test, not by argument. |

### Debugging and verification

| | |
|---|---|
| Prompt | "I want a test that actually starts multiple server processes and makes them fight over the same fund." |
| AI output | The multi-process test, which passed first time. |
| Independent check | A first-time pass on a race test proves little, so the guard was broken three ways and each made the test fail (table in section 1). |
| Correction | The AI's first random-sequence test also passed, but its printed outcome counts showed only 82 of 1,200 steps were successful actions; most were `NOT_FOUND` before any money logic ran. The action mix was fixed (210 successful afterwards) and a second test now fails if any outcome stops occurring. A deliberate payment bug then failed at seed 0. |
| Correction found in review | After the build, rehearsing a requirement change showed that adding a permission or a transition to `rules.py` passed every test: the rules tests checked each expected entry but never that the tables held only those entries. Two whole-table assertions were added (commit `9f4fbbb`); adding a rule now fails them. This is why the total is 248 tests, not the 246 of the first full run. |
