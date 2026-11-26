"""Money is stored as whole cents (int). This module is the only place that
converts between cents and the text form used in tool inputs and outputs.

No floats are used anywhere, so there is nothing to round.
"""

import re

from assistance.errors import INVALID_AMOUNT, AppError

# One to seven digits, a dot, exactly two digits: "300.00", "0.50", "9999999.99".
_AMOUNT_FORMAT = re.compile(r"[0-9]{1,7}\.[0-9]{2}")


def parse_usd(text: str) -> int:
    """Turn "300.00" into 30000 cents, or raise INVALID_AMOUNT."""  # REQ: BR-10
    if not _AMOUNT_FORMAT.fullmatch(text):
        raise AppError(
            INVALID_AMOUNT,
            'amount_usd must be dollars with exactly two decimals, like "300.00" '
            f'for three hundred dollars. You sent "{text[:30]}". Do not send cents, '
            'a currency symbol or commas. The maximum is "9999999.99".',
        )
    dollars, cents = text.split(".")
    total_cents = int(dollars) * 100 + int(cents)
    if total_cents == 0:
        raise AppError(INVALID_AMOUNT, 'amount_usd must be greater than zero. You sent "0.00".')
    return total_cents


def format_usd(cents: int) -> str:
    """Turn 30000 cents into "300.00"."""
    return f"{cents // 100}.{cents % 100:02d}"
