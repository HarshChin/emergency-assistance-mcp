"""The two tables that decide what is allowed.

ROLE_PERMISSIONS   who may do which action
STATUS_TRANSITIONS which status change each action makes

Nothing else in the code decides either question. To change a permission or a
transition, edit the table here; the functions below and the rest of the code
read from it.
"""

from assistance.errors import FORBIDDEN, INVALID_TRANSITION, AppError

# Roles
CASE_WORKER = "case_worker"
PROGRAM_MANAGER = "program_manager"
FINANCE = "finance"

# Actions
READ = "read"
CREATE = "create"
APPROVE = "approve"
REJECT = "reject"
PAY = "pay"

# Request statuses
PENDING = "PENDING"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
PAID = "PAID"

# REQ: SEC-04, SEC-05
ROLE_PERMISSIONS = {
    READ: {CASE_WORKER, PROGRAM_MANAGER, FINANCE},
    CREATE: {CASE_WORKER},
    APPROVE: {PROGRAM_MANAGER},
    REJECT: {PROGRAM_MANAGER},
    PAY: {FINANCE},
}

# REQ: BR-02
# (current status, action) -> new status. Anything not listed is refused.
STATUS_TRANSITIONS = {
    (PENDING, APPROVE): APPROVED,
    (PENDING, REJECT): REJECTED,
    (APPROVED, PAY): PAID,
}


def require(role: str, action: str) -> None:
    """Raise FORBIDDEN unless this role may do this action."""
    allowed = ROLE_PERMISSIONS[action]
    if role not in allowed:
        raise AppError(
            FORBIDDEN,
            f"Your role ({role}) is not allowed to {action} requests. "
            f"Allowed: {', '.join(sorted(allowed))}.",
        )


def is_repeat(status: str, action: str) -> bool:
    """True if the request is already in the status this action leads to."""
    targets = {new for (_, act), new in STATUS_TRANSITIONS.items() if act == action}
    return status in targets


def next_status(status: str, action: str) -> str:
    """Return the status this action leads to, or raise INVALID_TRANSITION."""
    new_status = STATUS_TRANSITIONS.get((status, action))
    if new_status is None:
        needed = sorted(old for (old, act) in STATUS_TRANSITIONS if act == action)
        raise AppError(
            INVALID_TRANSITION,
            f"Cannot {action} a request whose status is {status}. "
            f"To {action}, the status must be {' or '.join(needed)}.",
        )
    return new_status
