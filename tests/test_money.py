"""Amount parsing and formatting (PRD BR-10, AC-20, AC-21)."""

import pytest

from assistance.errors import INVALID_AMOUNT, AppError
from assistance.money import format_usd, parse_usd


@pytest.mark.req("BR-10")
@pytest.mark.parametrize(
    "text, cents",
    [
        ("300.00", 30000),
        ("0.01", 1),
        ("0.50", 50),
        ("19.99", 1999),
        ("9999999.99", 999999999),
    ],
)
def test_valid_amounts_become_exact_cents(text, cents):
    assert parse_usd(text) == cents


@pytest.mark.req("BR-10", "NFR-02")
@pytest.mark.parametrize(
    "text",
    [
        "300",  # could be dollars or cents: refuse rather than guess
        "300.5",
        "300.000",
        "$300.00",
        "1,000.00",
        "-5.00",
        "+5.00",
        "10000000.00",  # over the maximum
        " 300.00",
        "300.00 ",
        "300.00\n",
        "3e2",
        ".50",
        "",
        "abc",
    ],
)
def test_other_forms_are_refused_with_the_correct_form_shown(text):
    with pytest.raises(AppError) as error:
        parse_usd(text)
    assert error.value.code == INVALID_AMOUNT
    assert '"300.00"' in error.value.message  # the message shows what to send instead


@pytest.mark.req("BR-10")
def test_zero_is_refused():
    with pytest.raises(AppError) as error:
        parse_usd("0.00")
    assert error.value.code == INVALID_AMOUNT
    assert "greater than zero" in error.value.message


@pytest.mark.req("BR-10")
@pytest.mark.parametrize("cents, text", [(30000, "300.00"), (1, "0.01"), (0, "0.00"), (970000, "9700.00")])
def test_cents_are_formatted_with_two_decimals_and_no_separators(cents, text):
    assert format_usd(cents) == text


@pytest.mark.req("BR-10")
def test_parse_and_format_round_trip_for_every_cent_value_up_to_twenty_dollars():
    for cents in range(1, 2001):
        assert parse_usd(format_usd(cents)) == cents
