# Revision log

Changes made to a specification document after its first commit, with the reason.
Design decisions behind a change are recorded in [ADR.md](ADR.md).

| # | Date | Document / section | What changed | Why |
|---|---|---|---|---|
| 1 | 2026-11-26 | PRD NFR-02, AC-21 | NFR-02 now says business refusals carry an error code, and schema-invalid arguments are refused by schema validation with its own message. AC-21 now says the number `300` is refused by schema validation while the string cases return `INVALID_AMOUNT`. | Found while writing the tech spec: the SDK validates arguments against the input schema before our code runs, so those refusals cannot carry our error code. The first wording promised something the design cannot deliver. |
| 2 | 2026-11-26 | Architecture section 1 | `rules.py` and `money.py` are now listed as depending on `errors.py` instead of on nothing. | Found in task 5: both raise `AppError` (for `FORBIDDEN`, `INVALID_TRANSITION`, `INVALID_AMOUNT`), which lives in `errors.py`. No behaviour change. |
