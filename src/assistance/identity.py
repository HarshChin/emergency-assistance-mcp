"""Who is calling.

The caller's staff ID comes from one environment variable, set by whoever
launches the server. The server looks that ID up and decides the role and
nonprofit itself. Nothing a tool receives as an argument, and nothing stored in
the database as text, is ever used to build a Caller.
"""  # REQ: SEC-01, SEC-07

import os
from dataclasses import dataclass

from assistance import db
from assistance.errors import UNAUTHENTICATED, AppError

STAFF_ID_VARIABLE = "ASSISTANCE_STAFF_ID"


@dataclass(frozen=True)
class Caller:
    staff_id: str
    role: str
    nonprofit_id: str


def resolve_caller() -> Caller:
    """Return the Caller for this server process, or raise UNAUTHENTICATED."""
    staff_id = os.environ.get(STAFF_ID_VARIABLE, "").strip()
    if not staff_id:  # REQ: SEC-02
        raise AppError(
            UNAUTHENTICATED,
            f"No staff identity is configured. The person who launches this server must set "
            f"the {STAFF_ID_VARIABLE} environment variable. Retrying the call will not help.",
        )
    with db.reading() as conn:
        row = conn.execute("SELECT id, role, nonprofit_id FROM staff WHERE id = ?", (staff_id,)).fetchone()
    if row is None:  # REQ: SEC-03
        raise AppError(
            UNAUTHENTICATED,
            f"The configured staff identity is not a known staff member. The person who launches "
            f"this server must correct {STAFF_ID_VARIABLE}. Retrying the call will not help.",
        )
    return Caller(staff_id=row["id"], role=row["role"], nonprofit_id=row["nonprofit_id"])
