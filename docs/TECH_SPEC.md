# Technical Specification: Emergency Assistance Funding

Version 1 (2026-11-26). Implements [PRD.md](PRD.md). Decisions are justified in [ADR.md](ADR.md).
Requirement IDs in brackets show what each part satisfies.

## 1. Stack

| Item | Choice |
|---|---|
| Language | Python 3.12 |
| MCP | Official Python SDK `mcp==2.3.0`, `MCPServer`, stdio transport [NFR-01] |
| Storage | One SQLite file, stdlib `sqlite3`, plain SQL [FR-11] |
| Validation and schemas | Pydantic v2 (through the SDK) [FR-10] |
| Tests | pytest with the anyio plugin |
| Packaging | uv, `uv.lock` committed, exact versions in `pyproject.toml` [NFR-03] |

## 2. Configuration

| Environment variable | Meaning | If missing |
|---|---|---|
| `ASSISTANCE_STAFF_ID` | Staff ID of the caller [SEC-01] | Every tool call fails with `UNAUTHENTICATED` [SEC-02] |
| `ASSISTANCE_DB_PATH` | Path to the SQLite file | Defaults to `data/assistance.db` |

The server never creates or seeds the database. If the file does not exist at startup it logs an
error to stderr and exits with code 1 [FR-12].

## 3. Data model

All tables are SQLite `STRICT` tables with `PRAGMA foreign_keys = ON`.

| Table | Columns | Constraints |
|---|---|---|
| `nonprofits` | `id` TEXT PK, `name` TEXT | |
| `staff` | `id` TEXT PK, `nonprofit_id` FK, `name` TEXT, `role` TEXT | `role IN ('case_worker','program_manager','finance')` |
| `participants` | `id` TEXT PK, `nonprofit_id` FK, `name` TEXT | |
| `funds` | `id` TEXT PK, `nonprofit_id` FK, `name` TEXT, `allocation_cents` INTEGER, `committed_cents` INTEGER default 0, `paid_cents` INTEGER default 0 | `allocation_cents >= 0`, `committed_cents >= 0`, `paid_cents >= 0`, `committed_cents + paid_cents <= allocation_cents` [BR-08] |
| `requests` | `id` TEXT PK, `nonprofit_id` FK, `participant_id` FK, `fund_id` FK, `amount_cents` INTEGER, `purpose` TEXT, `status` TEXT, `idempotency_key` TEXT, `created_by` FK staff, `created_at` TEXT, `decided_by` FK staff null, `decided_at` TEXT null, `reject_reason` TEXT null, `paid_by` FK staff null, `paid_at` TEXT null [BR-15] | `amount_cents > 0`, `status IN ('PENDING','APPROVED','REJECTED','PAID')`, `UNIQUE (created_by, idempotency_key)` [IDM-04] |

| Topic | Rule |
|---|---|
| Ownership | `staff`, `participants`, `funds` and `requests` each carry `nonprofit_id`. A request's `nonprofit_id` equals its creator's, its participant's and its fund's [BR-13]. |
| Relationships | nonprofit 1–N staff, participants, funds, requests. participant 1–N requests. fund 1–N requests. |
| IDs | Seed rows have readable IDs (`staff_cb_cw1`). Requests get `req_` + 12 random hex characters. |
| Timestamps | UTC, ISO 8601, e.g. `2026-11-26T11:45:00Z`. |
| Immutability | No statement ever updates `participant_id`, `fund_id`, `amount_cents`, `purpose` or `idempotency_key` of a request [BR-09]. |
| Fixed allocation | No statement outside the seed command writes `allocation_cents`. |

## 4. Money

| Topic | Rule |
|---|---|
| Storage | Integer cents everywhere. No floats and no rounding anywhere in the code [BR-10]. |
| Input | `amount_usd`: string matching `^[0-9]{1,7}\.[0-9]{2}$`, value greater than zero. Parsed by splitting on the dot: `dollars * 100 + cents`. |
| Output | Same form, no separators: `9700.00`. Field names end in `_usd`. |
| Available | Never stored. Always `allocation_cents - committed_cents - paid_cents` [BR-08]. |
| Rejected input | The error repeats what was sent and shows the form to use, e.g. `[INVALID_AMOUNT] amount_usd must be dollars with exactly two decimals, like "300.00". You sent "300". Do not send cents, a currency symbol or commas.` [NFR-02] |

## 5. Identity, roles and nonprofit boundaries

| Step | Where | What it does |
|---|---|---|
| 1. Resolve caller | `identity.resolve_caller()` | Reads `ASSISTANCE_STAFF_ID`, selects the staff row, returns `Caller(staff_id, role, nonprofit_id)`. Missing or unknown → `UNAUTHENTICATED` [SEC-01, SEC-02, SEC-03]. Runs at the start of every tool call. |
| 2. Check role | `rules.require(role, action)` | Looks up the action in `ROLE_PERMISSIONS`, the only permission table in the code. Not allowed → `FORBIDDEN` [SEC-04, SEC-05]. Runs before any record is read, so the answer never depends on whether a record exists. |
| 3. Scope data | `service.py` | Every service function takes the `Caller`. Every SQL statement on an owned table has `nonprofit_id = :caller_nonprofit` in its `WHERE` clause. A row of another nonprofit is simply not returned → `NOT_FOUND`, same text as a missing row [SEC-06]. |
| 4. Check state | `rules.next_status(status, action)` | Looks up `STATUS_TRANSITIONS`, the only transition table [BR-02]. |

| Guarantee | How |
|---|---|
| Arguments cannot change identity [SEC-07] | No tool has a staff, role or nonprofit parameter. The `Caller` is built only in step 1. |
| Stored text cannot change identity [SEC-08] | `purpose`, `reject_reason` and names are only ever written to and read from their columns. No code branches on their content. |
| One place each [ADR-12] | `rules.py` holds `ROLE_PERMISSIONS = {action: {roles}}` and `STATUS_TRANSITIONS = {(status, action): new_status}`. |

Order of checks in every tool: schema validation (SDK) → identity → role → amount format →
scoped lookup → status (replay or invalid transition) → funds.

## 6. MCP tools

Common points [FR-10]:

- Input schema comes from the function's type hints; output schema from its Pydantic return type.
- Shape rules (types, lengths, enums, ranges) are declared in the signature and enforced by the SDK
  before our code runs. Meaning rules (amount format, existence, role, state, funds) are enforced
  by our code with an error code from section 7.
- Read tools are marked `read_only_hint`. Write tools are marked `idempotent_hint`.
- Every write tool returns `RequestResult`. `replayed: true` means the call repeated an earlier
  one and nothing changed.

| Tool | Roles | Input | Output | Side effect | Errors |
|---|---|---|---|---|---|
| `list_participants` [FR-01] | all | `name_contains?` string ≤ 100 | `ParticipantList` | none | `UNAUTHENTICATED` |
| `list_funds` [FR-02] | all | – | `FundList` | none | `UNAUTHENTICATED` |
| `get_funding_summary` [FR-09] | all | `fund_id?` string | `FundingSummary` (one fund, or all funds of the nonprofit) | none | `UNAUTHENTICATED`, `NOT_FOUND` |
| `create_request` [FR-03] | case worker | `participant_id`, `fund_id`, `amount_usd`, `purpose` (1–500, not blank), `idempotency_key` (1–64) | `RequestResult` | Inserts one `PENDING` request. No fund change [BR-01, BR-03] | `UNAUTHENTICATED`, `FORBIDDEN`, `INVALID_AMOUNT`, `NOT_FOUND`, `IDEMPOTENCY_CONFLICT` |
| `approve_request` [FR-04] | program manager | `request_id` | `RequestResult` | Request → `APPROVED`; fund `committed += amount` [BR-04] | `UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `INVALID_TRANSITION`, `INSUFFICIENT_FUNDS` |
| `reject_request` [FR-05] | program manager | `request_id`, `reason?` string ≤ 500 | `RequestResult` | Request → `REJECTED`. No fund change [BR-06] | `UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `INVALID_TRANSITION` |
| `record_payment` [FR-06] | finance | `request_id` | `RequestResult` | Request → `PAID`; fund `committed -= amount`, `paid += amount` [BR-07] | `UNAUTHENTICATED`, `FORBIDDEN`, `NOT_FOUND`, `INVALID_TRANSITION` |
| `get_request` [FR-07] | all | `request_id` | `Request` | none | `UNAUTHENTICATED`, `NOT_FOUND` |
| `list_requests` [FR-08] | all | `status?` one of the four statuses, `limit?` 1–200, default 50 | `RequestList`, newest first | none | `UNAUTHENTICATED` |

### Output shapes

| Model | Fields |
|---|---|
| `Participant` | `participant_id`, `name` |
| `ParticipantList` | `participants: Participant[]` (ordered by name, at most 100) |
| `Fund` | `fund_id`, `name`, `allocation_usd` |
| `FundList` | `funds: Fund[]` |
| `FundBalance` | `fund_id`, `name`, `allocation_usd`, `committed_usd`, `paid_usd`, `available_usd` |
| `FundingSummary` | `funds: FundBalance[]` |
| `Request` | `request_id`, `status`, `participant_id`, `fund_id`, `amount_usd`, `purpose`, `created_by`, `created_at`, `decided_by?`, `decided_at?`, `reject_reason?`, `paid_by?`, `paid_at?` |
| `RequestResult` | `request: Request`, `replayed: bool` |
| `RequestList` | `requests: Request[]` |

The JSON Schemas the server actually publishes are generated from these models and are printed
by the demo script, so they are not duplicated here.

## 7. Errors

Business errors are raised as the SDK's `ToolError`. The client receives `is_error: true` and the
text `Error executing tool <tool>: [CODE] message` [NFR-02, ADR-11]. A failed call has no
structured content.

| Code | When | Message tells the caller |
|---|---|---|
| `UNAUTHENTICATED` | No staff ID configured, or not a known staff member | The operator must set `ASSISTANCE_STAFF_ID`; retrying will not help |
| `FORBIDDEN` | Caller's role may not do this action | Their role and which role can |
| `NOT_FOUND` | Record does not exist in the caller's nonprofit | Which argument, and which list tool finds valid IDs |
| `INVALID_AMOUNT` | `amount_usd` is not in the required form or is zero | What was sent and the correct form |
| `INVALID_TRANSITION` | Action not allowed from the request's current status | Current status and what the action needs |
| `INSUFFICIENT_FUNDS` | Amount is greater than the fund's available balance | Amount requested and amount available |
| `IDEMPOTENCY_CONFLICT` | Key already used by this case worker with different details | Reuse a key only to retry the same request; otherwise send a new key |

Other failures:

| Case | Behaviour |
|---|---|
| Arguments break the input schema (missing, wrong type, too long, unknown status) | Refused by the SDK before our code runs, with its own text naming the field and the rule. No code prefix. Reveals nothing beyond the published schema. |
| Unexpected exception | SDK returns `Error executing tool <tool>` with no detail; the traceback goes to the log. The transaction is rolled back. |

Every error path rolls back, so a refused action changes nothing [BR-12].

## 8. Write operations

Every write is one transaction opened with `BEGIN IMMEDIATE`, which takes the database write lock
at once. A second process doing the same waits (up to `busy_timeout`, 5 s) and then sees the first
one's committed result [BR-11, ADR-03]. Any error rolls the transaction back.

| Operation | Steps inside the transaction |
|---|---|
| create | 1. Select request by `(created_by, idempotency_key)`. Found with same participant, fund, amount and purpose → return it, `replayed: true` [IDM-04]. Found with different details → `IDEMPOTENCY_CONFLICT` [IDM-05]. 2. Select participant and fund scoped to the caller's nonprofit; either missing → `NOT_FOUND` [BR-13]. 3. Insert the request as `PENDING`. |
| approve | 1. Select request scoped to nonprofit; none → `NOT_FOUND`. 2. Status `APPROVED` → return, `replayed: true` [IDM-01, IDM-06]. 3. Status not `PENDING` → `INVALID_TRANSITION`. 4. `UPDATE funds SET committed_cents = committed_cents + :amt WHERE id = :fund AND allocation_cents - committed_cents - paid_cents >= :amt`. Zero rows → `INSUFFICIENT_FUNDS` [BR-05]. 5. `UPDATE requests SET status = 'APPROVED', decided_by, decided_at WHERE id = :id AND status = 'PENDING'`. |
| reject | Steps 1–3 as approve, with `REJECTED` as the replay status [IDM-02]. Then update the request to `REJECTED` with `decided_by`, `decided_at`, `reject_reason`. No fund statement. |
| pay | 1. Select request; none → `NOT_FOUND`. 2. Status `PAID` → return, `replayed: true` [IDM-03]. 3. Status not `APPROVED` → `INVALID_TRANSITION`. 4. `UPDATE funds SET committed_cents = committed_cents - :amt, paid_cents = paid_cents + :amt WHERE id = :fund AND committed_cents >= :amt`. 5. Update the request to `PAID` with `paid_by`, `paid_at`. |

| Connection setting | Value | Why |
|---|---|---|
| One connection per tool call | open, use, close | The SDK runs plain `def` tools in worker threads; nothing is shared between calls. |
| `isolation_level=None` | explicit `BEGIN IMMEDIATE` / `COMMIT` / `ROLLBACK` | The transaction boundaries are visible in our code, not chosen by the driver. |
| `journal_mode=WAL` | set once by the seed command | Readers are not blocked while a write commits. |
| `busy_timeout=5000` | per connection | Writers queue instead of failing. |

## 9. Logging

| Topic | Rule |
|---|---|
| Destination | Python `logging` to stderr. Stdout carries only MCP protocol messages [NFR-01]. |
| Content | One line per tool call: tool, staff ID, nonprofit ID, request ID if any, outcome (`ok`, `replayed` or the error code). |
| Not logged | Purpose text, reject reasons, participant names. |

## 10. Seed and reset

Command: `uv run python -m assistance.seed --reset`. It deletes the database file, recreates the
schema and inserts the rows below. Without `--reset` it refuses to touch an existing file. The same
command always produces the same data [FR-12].

| Nonprofit | Staff | Participants | Funds |
|---|---|---|---|
| Community Bridge (`np_cb`) | `staff_cb_cw1`, `staff_cb_cw2` (case workers); `staff_cb_pm1`, `staff_cb_pm2` (program managers); `staff_cb_fin1` (finance) | `part_cb_1`, `part_cb_2`, `part_cb_3` | `fund_cb_rent` $10,000.00; `fund_cb_util` $2,500.00 |
| Riverside Relief (`np_rr`) | `staff_rr_cw1`, `staff_rr_pm1`, `staff_rr_fin1` | `part_rr_1`, `part_rr_2` | `fund_rr_transport` $1,000.00; `fund_rr_housing` $5,000.00 |

## 11. Production security: HTTP and OAuth (not built)

| Topic | Approach |
|---|---|
| Transport | Same server run with `transport="streamable-http"`. Tools, service and rules do not change. |
| OAuth role | The MCP server is a resource server only. It never signs users in or issues tokens; the existing authorization server does. |
| SDK wiring | `MCPServer(token_verifier=..., auth=AuthSettings(issuer_url, resource_server_url, required_scopes))`. The SDK then serves RFC 9728 protected-resource metadata and answers a missing or bad token with 401 and a `WWW-Authenticate` header pointing to it, which is how clients discover the authorization server. |
| Token validation | In `TokenVerifier.verify_token`: verify the JWT signature against the provider's JWKS (or call its introspection endpoint); check issuer, expiry, and that the audience/resource is this server, so a token minted for another service is refused; check required scopes. Tokens are never forwarded to other services. |
| Caller mapping | Token subject → staff row in our database → nonprofit and role. Membership and business permissions stay server-side in `staff` and `rules.py`; scopes are only a coarse gate (for example `assistance:read`, `assistance:write`). |
| What changes in code | Only `identity.resolve_caller()`: it reads the verified token (`get_access_token()`) instead of an environment variable, per request instead of per process. |

## 12. SDK behaviour assumed from the docs

Taken from the SDK documentation on 2026-11-26 and not yet run. Each is confirmed by a test in
implementation; any difference is logged in [REVISIONS.md](REVISIONS.md).

| # | Assumption | Matters for |
|---|---|---|
| S1 | A JSON number sent for a `str` parameter is refused, not converted to a string | AC-21 (`300` as a number) |
| S2 | Unknown extra arguments never reach our function | AC-22, SEC-07 |
| S3 | `ToolError` text reaches the client as `Error executing tool <tool>: <message>` with `is_error: true` | Section 7 |
| S4 | Plain `def` tools run in worker threads | Section 8, one connection per call |

## 13. Requirement coverage

| Requirements | Section |
|---|---|
| FR-01 to FR-10 | 6 |
| FR-11, FR-12 | 1, 2, 10 |
| BR-01 to BR-07 | 6, 8 |
| BR-08 | 3, 4 |
| BR-09, BR-13, BR-15 | 3 |
| BR-10 | 4 |
| BR-11, BR-12 | 7, 8 |
| BR-14 | 6 (`purpose` and `reason` limits) |
| IDM-01 to IDM-06 | 8 |
| SEC-01 to SEC-08 | 5 |
| NFR-01 | 1, 9 |
| NFR-02 | 4, 7 |
| NFR-03 | 1 |
