"""The permission table and the transition table (PRD sections 6 and 7)."""

import pytest

from assistance import rules
from assistance.errors import FORBIDDEN, INVALID_TRANSITION, AppError
from assistance.rules import (
    APPROVE, APPROVED, CASE_WORKER, CREATE, FINANCE, PAID, PAY, PENDING,
    PROGRAM_MANAGER, READ, REJECT, REJECTED,
)

ALL_ROLES = [CASE_WORKER, PROGRAM_MANAGER, FINANCE]
ALL_STATUSES = [PENDING, APPROVED, REJECTED, PAID]

# PRD section 6, written out in full. The first two tests below compare the real tables with
# these as a whole, so adding, changing or removing a rule fails until this file is edited too.
EXPECTED_PERMISSIONS = {
    (READ, CASE_WORKER): True, (READ, PROGRAM_MANAGER): True, (READ, FINANCE): True,
    (CREATE, CASE_WORKER): True, (CREATE, PROGRAM_MANAGER): False, (CREATE, FINANCE): False,
    (APPROVE, CASE_WORKER): False, (APPROVE, PROGRAM_MANAGER): True, (APPROVE, FINANCE): False,
    (REJECT, CASE_WORKER): False, (REJECT, PROGRAM_MANAGER): True, (REJECT, FINANCE): False,
    (PAY, CASE_WORKER): False, (PAY, PROGRAM_MANAGER): False, (PAY, FINANCE): True,
}

# PRD section 7: the only three allowed changes.
EXPECTED_TRANSITIONS = {
    (PENDING, APPROVE): APPROVED,
    (PENDING, REJECT): REJECTED,
    (APPROVED, PAY): PAID,
}


@pytest.mark.req("SEC-04", "SEC-05")
def test_the_permission_table_holds_exactly_the_prd_table_and_nothing_more():
    actual = {
        (action, role): role in allowed
        for action, allowed in rules.ROLE_PERMISSIONS.items()
        for role in ALL_ROLES
    }
    assert actual == EXPECTED_PERMISSIONS
    for action, allowed in rules.ROLE_PERMISSIONS.items():
        assert allowed <= set(ALL_ROLES), f"{action} is allowed for a role the PRD does not have"


@pytest.mark.req("BR-02")
def test_the_transition_table_holds_exactly_the_three_prd_transitions_and_nothing_more():
    assert rules.STATUS_TRANSITIONS == EXPECTED_TRANSITIONS


@pytest.mark.req("SEC-04", "SEC-05")
@pytest.mark.parametrize("action, role", list(EXPECTED_PERMISSIONS))
def test_each_role_can_do_exactly_what_the_prd_table_says(action, role):
    if EXPECTED_PERMISSIONS[(action, role)]:
        rules.require(role, action)  # does not raise
    else:
        with pytest.raises(AppError) as error:
            rules.require(role, action)
        assert error.value.code == FORBIDDEN


@pytest.mark.req("BR-02")
@pytest.mark.parametrize("status", ALL_STATUSES)
@pytest.mark.parametrize("action", [APPROVE, REJECT, PAY])
def test_only_the_three_listed_transitions_are_allowed(status, action):
    if (status, action) in EXPECTED_TRANSITIONS:
        assert rules.next_status(status, action) == EXPECTED_TRANSITIONS[(status, action)]
    else:
        with pytest.raises(AppError) as error:
            rules.next_status(status, action)
        assert error.value.code == INVALID_TRANSITION
        assert status in error.value.message  # says what the current status is


@pytest.mark.req("IDM-01", "IDM-02", "IDM-03")
@pytest.mark.parametrize("status", ALL_STATUSES)
@pytest.mark.parametrize("action, target", [(APPROVE, APPROVED), (REJECT, REJECTED), (PAY, PAID)])
def test_an_action_is_a_repeat_only_when_the_request_is_already_in_its_target_status(status, action, target):
    assert rules.is_repeat(status, action) == (status == target)
