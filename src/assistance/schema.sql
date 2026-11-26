-- Emergency Assistance Funding schema. See docs/TECH_SPEC.md section 3.
-- STRICT tables: SQLite refuses a value of the wrong type (for example 300.5 in a cents column).

CREATE TABLE nonprofits (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL
) STRICT;

CREATE TABLE staff (
    id           TEXT PRIMARY KEY,
    nonprofit_id TEXT NOT NULL REFERENCES nonprofits (id),
    name         TEXT NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('case_worker', 'program_manager', 'finance'))
) STRICT;

CREATE TABLE participants (
    id           TEXT PRIMARY KEY,
    nonprofit_id TEXT NOT NULL REFERENCES nonprofits (id),
    name         TEXT NOT NULL
) STRICT;

-- REQ: BR-08
-- available is never stored: it is allocation_cents - committed_cents - paid_cents.
-- The CHECK constraints make an overspent or negative fund impossible to save.
CREATE TABLE funds (
    id               TEXT PRIMARY KEY,
    nonprofit_id     TEXT NOT NULL REFERENCES nonprofits (id),
    name             TEXT NOT NULL,
    allocation_cents INTEGER NOT NULL CHECK (allocation_cents >= 0),
    committed_cents  INTEGER NOT NULL DEFAULT 0 CHECK (committed_cents >= 0),
    paid_cents       INTEGER NOT NULL DEFAULT 0 CHECK (paid_cents >= 0),
    CHECK (committed_cents + paid_cents <= allocation_cents)
) STRICT;

CREATE TABLE requests (
    id              TEXT PRIMARY KEY,
    nonprofit_id    TEXT NOT NULL REFERENCES nonprofits (id),
    participant_id  TEXT NOT NULL REFERENCES participants (id),
    fund_id         TEXT NOT NULL REFERENCES funds (id),
    amount_cents    INTEGER NOT NULL CHECK (amount_cents > 0),
    purpose         TEXT NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED', 'PAID')),
    idempotency_key TEXT NOT NULL,
    created_by      TEXT NOT NULL REFERENCES staff (id),
    created_at      TEXT NOT NULL,
    decided_by      TEXT REFERENCES staff (id),
    decided_at      TEXT,
    reject_reason   TEXT,
    paid_by         TEXT REFERENCES staff (id),
    paid_at         TEXT,
    -- REQ: IDM-04
    UNIQUE (created_by, idempotency_key)
) STRICT;
