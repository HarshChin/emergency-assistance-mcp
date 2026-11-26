"""Read operations: what each nonprofit's staff can and cannot see."""

import pytest

from assistance import service
from assistance.errors import NOT_FOUND
from helpers import as_staff, insert_request, refused

CB_STAFF = ["staff_cb_cw1", "staff_cb_pm1", "staff_cb_fin1"]


@pytest.fixture
def two_nonprofits_with_requests(db):
    """Two requests in Community Bridge (one approved) and one in Riverside Relief."""
    insert_request("req_cb_old", "np_cb", "part_cb_1", "fund_cb_rent", "staff_cb_cw1", status="APPROVED")
    insert_request("req_cb_new", "np_cb", "part_cb_2", "fund_cb_util", "staff_cb_cw2")
    insert_request("req_rr_1", "np_rr", "part_rr_1", "fund_rr_housing", "staff_rr_cw1")


@pytest.mark.req("SEC-05")
@pytest.mark.parametrize("staff_id", CB_STAFF)
def test_every_role_can_read_everything_in_its_own_nonprofit(two_nonprofits_with_requests, staff_id):
    caller = as_staff(staff_id)
    assert len(service.list_participants(caller).participants) == 3
    assert len(service.list_funds(caller).funds) == 2
    assert len(service.get_funding_summary(caller).funds) == 2
    assert service.get_request(caller, "req_cb_old").status == "APPROVED"
    assert len(service.list_requests(caller).requests) == 2


@pytest.mark.req("FR-01", "SEC-06")
def test_participants_are_listed_by_name_for_the_callers_nonprofit_only(db):
    cb = service.list_participants(as_staff("staff_cb_cw1")).participants
    rr = service.list_participants(as_staff("staff_rr_cw1")).participants
    assert [p.name for p in cb] == ["Alex Rivera", "Jordan Lee", "Sam Patel"]
    assert [p.participant_id for p in rr] == ["part_rr_2", "part_rr_1"]  # Morgan, Taylor


@pytest.mark.req("FR-01")
@pytest.mark.parametrize(
    "text, expected",
    [("jordan", ["Jordan Lee"]), ("RIVERA", ["Alex Rivera"]), ("a", ["Alex Rivera", "Jordan Lee", "Sam Patel"]),
     ("zzz", []), ("%", []), ("Taylor", [])],  # "%" is not a wildcard; Taylor is in the other nonprofit
)
def test_participants_can_be_filtered_by_part_of_the_name(db, text, expected):
    found = service.list_participants(as_staff("staff_cb_cw1"), name_contains=text).participants
    assert [p.name for p in found] == expected


@pytest.mark.req("FR-02", "SEC-06")
def test_funds_are_listed_for_the_callers_nonprofit_only(db):
    funds = service.list_funds(as_staff("staff_rr_fin1")).funds
    assert {(f.fund_id, f.allocation_usd) for f in funds} == {
        ("fund_rr_transport", "1000.00"),
        ("fund_rr_housing", "5000.00"),
    }


@pytest.mark.req("FR-09", "BR-08")
def test_summary_of_an_untouched_fund_is_all_available(db):
    summary = service.get_funding_summary(as_staff("staff_cb_pm1"), "fund_cb_rent")
    (fund,) = summary.funds
    assert (fund.allocation_usd, fund.committed_usd, fund.paid_usd, fund.available_usd) == (
        "10000.00", "0.00", "0.00", "10000.00",
    )


@pytest.mark.req("FR-09", "SEC-06")
def test_summary_without_a_fund_id_covers_only_the_callers_funds(db):
    summary = service.get_funding_summary(as_staff("staff_cb_cw1"))
    assert {f.fund_id for f in summary.funds} == {"fund_cb_rent", "fund_cb_util"}


@pytest.mark.req("FR-07", "BR-15")
def test_a_request_shows_its_status_and_who_created_it(two_nonprofits_with_requests):
    request = service.get_request(as_staff("staff_cb_fin1"), "req_cb_new")
    assert (request.status, request.created_by, request.amount_usd) == ("PENDING", "staff_cb_cw2", "300.00")
    assert request.decided_by is None and request.paid_by is None


@pytest.mark.req("FR-08", "SEC-06")
def test_requests_are_listed_newest_first_for_the_callers_nonprofit_only(two_nonprofits_with_requests):
    cb = service.list_requests(as_staff("staff_cb_cw1")).requests
    rr = service.list_requests(as_staff("staff_rr_cw1")).requests
    assert [r.request_id for r in cb] == ["req_cb_new", "req_cb_old"]
    assert [r.request_id for r in rr] == ["req_rr_1"]


@pytest.mark.req("FR-08")
def test_requests_can_be_filtered_by_status_and_limited(two_nonprofits_with_requests):
    caller = as_staff("staff_cb_pm1")
    assert [r.request_id for r in service.list_requests(caller, status="APPROVED").requests] == ["req_cb_old"]
    assert service.list_requests(caller, status="PAID").requests == []
    assert [r.request_id for r in service.list_requests(caller, limit=1).requests] == ["req_cb_new"]


@pytest.mark.req("SEC-06")
def test_another_nonprofits_request_looks_exactly_like_one_that_does_not_exist(two_nonprofits_with_requests):
    outsider = as_staff("staff_cb_pm1")
    with refused(NOT_FOUND) as other_nonprofit:
        service.get_request(outsider, "req_rr_1")  # exists, but in Riverside Relief
    with refused(NOT_FOUND) as does_not_exist:
        service.get_request(outsider, "req_nothing")
    assert other_nonprofit.value.message.replace("req_rr_1", "X") == does_not_exist.value.message.replace("req_nothing", "X")
    # The owner can read it, so the request really is there.
    assert service.get_request(as_staff("staff_rr_pm1"), "req_rr_1").request_id == "req_rr_1"


@pytest.mark.req("SEC-06")
def test_another_nonprofits_fund_looks_exactly_like_one_that_does_not_exist(db):
    outsider = as_staff("staff_cb_fin1")
    with refused(NOT_FOUND) as other_nonprofit:
        service.get_funding_summary(outsider, "fund_rr_housing")
    with refused(NOT_FOUND) as does_not_exist:
        service.get_funding_summary(outsider, "fund_nothing")
    assert other_nonprofit.value.message.replace("fund_rr_housing", "X") == does_not_exist.value.message.replace("fund_nothing", "X")
