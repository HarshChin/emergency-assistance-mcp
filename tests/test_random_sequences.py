"""Random sequences of actions (PRD AC-26).

Each seed drives a different mix of valid and invalid actions by random staff of
both nonprofits. After every single step the money rules are checked against
numbers recomputed from the requests table, which the service never uses for
its own arithmetic. A failing run is repeated exactly by its seed.
"""

import random
from collections import Counter

import pytest

from assistance import db, money, rules, seed, service
from assistance.errors import AppError
from helpers import as_staff, set_allocation, snapshot

SEEDS = range(40)
STEPS = 120

STAFF = [s[0] for s in seed.STAFF]
PARTICIPANTS = [p[0] for p in seed.PARTICIPANTS] + ["part_nothing"]
FUNDS = [f[0] for f in seed.FUNDS]
AMOUNTS = ["0.01", "25.00", "99.99", "300.00", "450.50", "600.00", "700.00"]
BAD_AMOUNTS = ["300", "30000", "$300.00", "0.00", "-1.00", "1e3"]
ALLOCATION_CENTS = 60_000  # every fund is shrunk to $600.00 so that funds really run out


def check_money_rules():
    """BR-08, checked for every fund from two independent sources."""
    with db.reading() as conn:
        funds = conn.execute("SELECT * FROM funds").fetchall()
        sums = {
            (row["fund_id"], row["status"]): row["total"]
            for row in conn.execute("SELECT fund_id, status, SUM(amount_cents) AS total FROM requests GROUP BY fund_id, status")
        }
    for fund in funds:
        approved_total = sums.get((fund["id"], "APPROVED"), 0)  # recomputed from requests
        paid_total = sums.get((fund["id"], "PAID"), 0)
        assert fund["allocation_cents"] == ALLOCATION_CENTS, "allocation must never change"
        assert fund["committed_cents"] == approved_total, f"{fund['id']}: committed does not match approved requests"
        assert fund["paid_cents"] == paid_total, f"{fund['id']}: paid does not match paid requests"

        # What the tool reports to staff must add up too.
        owner = next(as_staff(s[0]) for s in seed.STAFF if s[1] == fund["nonprofit_id"])
        reported = service.get_funding_summary(owner, fund["id"]).funds[0]
        available = _cents(reported.available_usd)
        committed = _cents(reported.committed_usd)
        paid = _cents(reported.paid_usd)
        assert min(available, committed, paid) >= 0, f"{fund['id']}: negative amount"
        assert available + committed + paid == ALLOCATION_CENTS, f"{fund['id']}: does not add up to the allocation"
        assert available == ALLOCATION_CENTS - approved_total - paid_total


def _cents(text: str) -> int:
    return 0 if text == "0.00" else money.parse_usd(text)


def pick_staff(rng: random.Random, action: str):
    """Usually someone whose role may do the action, sometimes anyone at all."""
    if rng.random() < 0.6:
        allowed = [s[0] for s in seed.STAFF if s[3] in rules.ROLE_PERMISSIONS[action]]
        return as_staff(rng.choice(allowed))
    return as_staff(rng.choice(STAFF))


def pick(rng: random.Random, own: list, everything: list):
    """Usually something from the caller's own nonprofit, sometimes anything (another nonprofit's, or made up)."""
    return rng.choice(own) if own and rng.random() < 0.75 else rng.choice(everything)


def run_sequence(seed_number: int) -> Counter:
    """Run STEPS random actions. Returns how often each outcome happened."""
    rng = random.Random(seed_number)
    for fund_id in FUNDS:
        set_allocation(fund_id, ALLOCATION_CENTS)
    outcomes = Counter()
    request_ids = ["req_nothing"]  # every request made so far, in either nonprofit
    own_request_ids = {"np_cb": [], "np_rr": []}
    earlier_creates = []  # (caller, arguments) of creates that succeeded, for retries

    for step in range(STEPS):
        action = rng.choice([rules.CREATE, rules.CREATE, rules.APPROVE, rules.APPROVE, rules.REJECT, rules.PAY, rules.PAY])
        caller = pick_staff(rng, action)
        own_participants = [p[0] for p in seed.PARTICIPANTS if p[1] == caller.nonprofit_id]
        own_funds = [f[0] for f in seed.FUNDS if f[1] == caller.nonprofit_id]
        request_id = pick(rng, own_request_ids[caller.nonprofit_id], request_ids)
        before = snapshot()
        try:
            if action == rules.CREATE:
                kind = rng.choice(["new", "new", "new", "retry", "conflict", "bad_amount"])
                if kind in ("retry", "conflict") and earlier_creates:
                    caller, arguments = rng.choice(earlier_creates)
                    arguments = dict(arguments)
                    if kind == "conflict":
                        arguments["purpose"] += " (changed)"
                else:
                    arguments = {
                        "participant_id": pick(rng, own_participants, PARTICIPANTS),
                        "fund_id": pick(rng, own_funds, FUNDS),
                        "amount_usd": rng.choice(BAD_AMOUNTS if kind == "bad_amount" else AMOUNTS),
                        "purpose": f"seed {seed_number} step {step}",
                        "idempotency_key": f"key-{step}",
                    }
                result = service.create_request(caller, **arguments)
                if not result.replayed:
                    request_ids.append(result.request.request_id)
                    own_request_ids[caller.nonprofit_id].append(result.request.request_id)
                    earlier_creates.append((caller, arguments))
            elif action == rules.APPROVE:
                result = service.approve_request(caller, request_id)
            elif action == rules.REJECT:
                result = service.reject_request(caller, request_id, "random")
            else:
                result = service.record_payment(caller, request_id)
            outcome = "replayed" if result.replayed else "ok"
        except AppError as error:
            outcome = error.code

        outcomes[outcome] += 1
        where = f"seed {seed_number}, step {step}: {action} by {caller.staff_id} -> {outcome}"
        if outcome != "ok":  # REQ BR-12: a refusal or a repeat changes nothing at all
            assert snapshot() == before, where
        try:
            check_money_rules()
        except AssertionError as broken:
            raise AssertionError(f"{where}: {broken}") from None
    return outcomes


@pytest.mark.req("BR-08", "BR-12")
@pytest.mark.parametrize("seed_number", SEEDS)
def test_ac26_money_rules_hold_after_every_step_of_a_random_sequence(db, seed_number):
    run_sequence(seed_number)


@pytest.mark.req("BR-08", "BR-12")
def test_ac26_the_random_sequences_really_reach_every_kind_of_outcome(db):
    """Guards the test above: if the random mix stopped producing some outcome, it would be testing less than it claims."""
    seen = Counter()
    for seed_number in range(10):
        seed.reset(db)
        seen += run_sequence(seed_number)
    expected = {
        "ok", "replayed", "FORBIDDEN", "NOT_FOUND", "INVALID_AMOUNT",
        "INVALID_TRANSITION", "INSUFFICIENT_FUNDS", "IDEMPOTENCY_CONFLICT",
    }
    assert set(seen) == expected, seen
    assert all(seen[outcome] >= 10 for outcome in expected), seen
