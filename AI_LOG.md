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
| How it was checked | First from the published docs. Then, at task 4, a throwaway script (not committed) called a one-tool `MCPServer` through the in-memory `Client`: a number sent for a string field was refused, an extra `role` argument never reached the function, `ToolError` text arrived as `Error executing tool echo: [CODE] ...`, and the tool ran in an `AnyIO worker thread`. All four matched the docs. Three now have permanent tests (TECH_SPEC section 12). |

## 3. Planning (2026-11-26)

| | |
|---|---|
| Asked | A plan in the order PRD → tech spec → architecture → code, with my concerns handled: overspending across processes, duplicates, access, the money invariant, amount format. |
| AI suggested | 16 small tasks with dependencies and "done when" checks; overspending stopped by SQLite (`BEGIN IMMEDIATE` + guarded `UPDATE` + `CHECK`); a test that starts real server processes; a seeded random-sequence test. |
| My input | I raised that stdio means one server process per client, so an in-memory lock cannot work; the AI confirmed and built the design on the database. |
| How it was checked | Plan reviewed and approved by me before any file was created. The concurrency claim was then proven by the multi-process test, including deliberate breaks of the guard (section 4 below). |

## 4. Verifying the overspending protection (2026-11-26)

| | |
|---|---|
| Asked | "I want a test that actually starts multiple server processes and makes them fight over the same fund." |
| AI wrote | `tests/test_stdio_processes.py`: ten real `python -m assistance.server` processes each approve a different $300.00 request against a $1,000.00 fund at the same moment. Expected: exactly 3 approved, 7 `INSUFFICIENT_FUNDS`, $900.00 committed. Also eight processes approving, then paying, one request; and eight processes sending the same create. |
| Result | Passed on the first run and on 5 further runs of the race tests (25 race test executions, 0 failures). |
| Why a pass alone was not trusted | A race test that always passes might simply not be racing. So the protection was broken on purpose three ways and the same test was rerun each time. Source was restored with `git checkout -- src/` after each. |

| Deliberate break | What was changed | What the test did |
|---|---|---|
| A | Approval checks the balance in Python with no lock held, then adds to committed; the `CHECK` constraint on `funds` removed | Failed, all 3 attempts. In the failure shown, only 1 of 10 approvals was refused: 9 approved, $2,700.00 against a $1,000.00 fund. This is the overspend the design prevents. |
| B | Same naive approval, `CHECK` constraint kept | Failed, all 3 attempts, but differently: exactly 3 were approved and 7 refused, and some refusals were crashes (`Error executing tool approve_request`) instead of `INSUFFICIENT_FUNDS`. The constraint stopped the overspend on its own. |
| C | Only `BEGIN IMMEDIATE` changed to plain `BEGIN` | Failed, all 3 attempts: the wrong number were approved and the refusals were crashes with no error code. The cause of the crashes was not inspected further (expected to be SQLite refusing a late lock upgrade). |

With the code restored the test passed again. Conclusion: the test does race, the guarded
`UPDATE` under `BEGIN IMMEDIATE` is what gives the clean result, and the `CHECK` constraint is a
working backstop.

## Corrections

| # | Date | What was wrong | How it was noticed | Fix |
|---|---|---|---|---|
| 1 | 2026-11-26 | The AI-written PRD said in NFR-02 that every refusal carries an error code, and in AC-21 that every bad amount, including the number `300`, gets an error showing the expected form. | While writing the tech spec the AI compared this with the SDK docs: arguments are validated against the input schema before tool code runs, so a wrong type is refused by the SDK with its own text. | PRD NFR-02 and AC-21 reworded; logged as revision 1 in `docs/REVISIONS.md`. The SDK behaviour was later confirmed by running it: test `test_ac21_an_amount_sent_as_a_number_is_refused_and_creates_nothing` (TECH_SPEC section 12, S1). |
| 2 | 2026-11-26 | The AI's first version of the random-sequence test passed, but when its outcome counts were printed only 82 of 1,200 steps were successful actions and 514 were `NOT_FOUND`: it picked participants, funds and requests from both nonprofits at random, so most steps were refused before reaching any money logic. | The AI printed the outcome counts over 10 seeds instead of relying on the green result. | Records are now picked from the caller's own nonprofit 75% of the time. Same 10 seeds afterwards: 210 successful, 178 replays, 44 `INSUFFICIENT_FUNDS`, 164 `NOT_FOUND`. A second test fails if any outcome stops occurring. A deliberate bug in payment (committed not reduced) made the test fail at seed 0. |
| 3 | 2026-11-26 | The AI's `tests/test_rules.py` carried a comment saying the expected tables were written out in full "so a change to the table must be deliberate". That was only true for a changed or removed entry. Nothing asserted the tables held only the expected entries, so an added permission or transition passed every test. | After the build, the AI rehearsed a requirement change in a scratch copy (a cancel action). Editing only the two tables in `rules.py` left all tests green, which should not have happened. | Two tests now compare the whole permission table and the whole transition table with the expected ones. Checked by mutation: adding "finance may approve", and adding the cancel rows, each fail them. Suite is 248 tests; re-verified from a fresh clone. |
