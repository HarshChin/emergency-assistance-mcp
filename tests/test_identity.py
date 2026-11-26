"""Caller identity comes from the environment and is resolved by the server (PRD SEC-01 to SEC-03)."""

import pytest

from assistance.errors import UNAUTHENTICATED, AppError
from assistance.identity import Caller, resolve_caller


@pytest.mark.req("SEC-01")
@pytest.mark.parametrize(
    "staff_id, role, nonprofit_id",
    [
        ("staff_cb_cw1", "case_worker", "np_cb"),
        ("staff_cb_pm1", "program_manager", "np_cb"),
        ("staff_cb_fin1", "finance", "np_cb"),
        ("staff_rr_pm1", "program_manager", "np_rr"),
    ],
)
def test_staff_id_from_the_environment_is_resolved_to_role_and_nonprofit(db, monkeypatch, staff_id, role, nonprofit_id):
    monkeypatch.setenv("ASSISTANCE_STAFF_ID", staff_id)
    assert resolve_caller() == Caller(staff_id=staff_id, role=role, nonprofit_id=nonprofit_id)


@pytest.mark.req("SEC-02")
@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_identity_is_refused(db, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("ASSISTANCE_STAFF_ID", raising=False)
    else:
        monkeypatch.setenv("ASSISTANCE_STAFF_ID", value)
    with pytest.raises(AppError) as error:
        resolve_caller()
    assert error.value.code == UNAUTHENTICATED


@pytest.mark.req("SEC-03")
@pytest.mark.parametrize("value", ["staff_nobody", "STAFF_CB_PM1", "np_cb", "' OR 1=1 --"])
def test_unknown_identity_is_refused(db, monkeypatch, value):
    monkeypatch.setenv("ASSISTANCE_STAFF_ID", value)
    with pytest.raises(AppError) as error:
        resolve_caller()
    assert error.value.code == UNAUTHENTICATED


@pytest.mark.req("SEC-07")
def test_a_caller_cannot_be_modified_after_it_is_resolved(db, monkeypatch):
    monkeypatch.setenv("ASSISTANCE_STAFF_ID", "staff_cb_cw1")
    caller = resolve_caller()
    with pytest.raises(AttributeError):
        caller.role = "program_manager"
