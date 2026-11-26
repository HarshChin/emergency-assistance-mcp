"""Business errors.

Every refusal the business rules can produce has one of these codes. The code is
stable (tests and callers rely on it); the message explains how to fix the call.
"""

UNAUTHENTICATED = "UNAUTHENTICATED"
FORBIDDEN = "FORBIDDEN"
NOT_FOUND = "NOT_FOUND"
INVALID_AMOUNT = "INVALID_AMOUNT"
INVALID_TRANSITION = "INVALID_TRANSITION"
INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"


class AppError(Exception):
    """A refused action. Shown to the caller as "[CODE] message"."""  # REQ: NFR-02

    def __init__(self, code: str, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
