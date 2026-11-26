"""Database access: where the file is, how to open it, how to run a write.

Each tool call opens its own connection and closes it when done. Server
processes share nothing except the database file, so all coordination between
them happens here, through SQLite's own locking.
"""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DB_PATH_VARIABLE = "ASSISTANCE_DB_PATH"
DEFAULT_DB_PATH = "data/assistance.db"
SCHEMA_FILE = Path(__file__).with_name("schema.sql")
BUSY_TIMEOUT_MS = 5000  # how long a writer waits for another process to finish


def db_path() -> Path:
    """The one SQLite file that holds all data between server runs."""  # REQ: FR-11
    return Path(os.environ.get(DB_PATH_VARIABLE, DEFAULT_DB_PATH))


def connect() -> sqlite3.Connection:
    """Open the existing database. Never creates one (only the seed command does)."""  # REQ: FR-12
    path = db_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Database not found at {path}. Create it with: uv run python -m assistance.seed --reset"
        )
    # isolation_level=None: the driver starts no transactions on its own.
    # We write BEGIN / COMMIT / ROLLBACK ourselves, in transaction() below.
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    return conn


@contextmanager
def reading() -> Iterator[sqlite3.Connection]:
    """A connection for read-only work."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """One write transaction: commit if the block finishes, roll back if it raises.

    BEGIN IMMEDIATE takes the database's write lock straight away. If another
    server process is in the middle of a write, this one waits (up to
    BUSY_TIMEOUT_MS) and then sees that process's committed result. That is
    what stops two approvals from both spending the same money.
    """  # REQ: BR-11, BR-12
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
