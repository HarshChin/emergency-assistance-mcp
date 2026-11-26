# AI workflow log

What was asked, what the AI (Claude Code) suggested, and how it was checked. Entries are written
as the work happens. Corrections are logged only when they actually occurred.

## 1. Requirements analysis (2026-11-26)

| | |
|---|---|
| Asked | "tell me in simple words what you understood from the doc" and "list the questions you'd ask the business where the doc is unclear. give me your suggestion for each but I'll take the call" |
| AI suggested | A plain-language summary of the brief and 14 business questions, each with a suggested answer. Four were flagged as changing the tool design: create retries, repeat approve/pay, reject reason, amount format. |
| Decision (mine) | Required idempotency key on create; repeats succeed with `replayed: true`; optional reject reason; amount as a `"300.00"` string. The other ten go into the PRD as assumptions. |
| How it was checked | The summary was compared against the brief's own example ($10,000 fund, approve $300, pay it). Each assumption is listed in the PRD so a reviewer can disagree with it. |

## 2. Checking the SDK instead of trusting memory (2026-11-26)

| | |
|---|---|
| Asked | "check the sdk docs, don't go from memory" |
| AI did | Queried PyPI for the `mcp` package and read the docs at py.sdk.modelcontextprotocol.io (Tools, Structured Output, Handling errors, Running your server, Client transports, Testing, Authorization). |
| Found | Latest release is 2.3.0 and the v2 API differs from v1: `MCPServer` replaces `FastMCP`; one `Client` class connects in-memory or spawns a stdio process; a stdio child does not inherit the parent's environment; `ToolError` gives the model readable text but a failed call carries no structured content. |
| Effect on the design | ADR-01 (pin v2), ADR-11 (error code carried in the text as `[CODE] ...`), and the launcher must pass the identity through `env=`. |
| How it was checked | From the published docs only, so far. To be confirmed by running code: scaffold (task 4) and in-memory MCP tests (task 10). |

## 3. Planning (2026-11-26)

| | |
|---|---|
| Asked | A plan in the order PRD → tech spec → architecture → code, with my concerns handled: overspending across processes, duplicates, access, the money invariant, amount format. |
| AI suggested | 16 small tasks with dependencies and "done when" checks; overspending stopped by SQLite (`BEGIN IMMEDIATE` + guarded `UPDATE` + `CHECK`); a test that starts real server processes; a seeded random-sequence test. |
| My input | I raised that stdio means one server process per client, so an in-memory lock cannot work; the AI confirmed and built the design on the database. |
| How it was checked | Plan reviewed and approved by me before any file was created. The concurrency claim is to be proven by the multi-process test (task 11), including one deliberate break of the guard to see the test fail. |

## Corrections

None so far.
