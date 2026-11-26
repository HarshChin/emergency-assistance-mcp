"""Schema constraints, the seed/reset command and the transaction helper."""

import sqlite3

import pytest

from assistance import db as database
from assistance import seed


def dump(path):
    """Every row of every table, as plain tuples."""
    conn = sqlite3.connect(path)
    try:
        tables = ["nonprofits", "staff", "participants", "funds", "requests"]
        return {t: conn.execute(f"SELECT * FROM {t} ORDER BY id").fetchall() for t in tables}
    finally:
        conn.close()


@pytest.mark.req("FR-12")
def test_seed_has_two_nonprofits_each_with_every_role_participants_and_funds(db):
    with database.reading() as conn:
        for nonprofit in ("np_cb", "np_rr"):
            roles = {r["role"] for r in conn.execute("SELECT role FROM staff WHERE nonprofit_id = ?", (nonprofit,))}
            assert roles == {"case_worker", "program_manager", "finance"}
            assert conn.execute("SELECT COUNT(*) FROM participants WHERE nonprofit_id = ?", (nonprofit,)).fetchone()[0] >= 2
            assert conn.execute("SELECT COUNT(*) FROM funds WHERE nonprofit_id = ?", (nonprofit,)).fetchone()[0] >= 2
        assert conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0] == 0


@pytest.mark.req("FR-12")
def test_reset_restores_the_seed_state_and_is_repeatable(db):
    seeded = dump(db)
    with database.transaction() as conn:
        conn.execute("UPDATE funds SET committed_cents = 500 WHERE id = 'fund_cb_rent'")
    assert dump(db) != seeded

    seed.reset(db)
    assert dump(db) == seeded
    seed.reset(db)
    assert dump(db) == seeded


@pytest.mark.req("FR-12")
def test_seed_command_refuses_an_existing_database_without_reset(db, capsys):
    with database.transaction() as conn:
        conn.execute("UPDATE funds SET committed_cents = 500 WHERE id = 'fund_cb_rent'")
    changed = dump(db)

    assert seed.main([]) == 1
    assert "--reset" in capsys.readouterr().err
    assert dump(db) == changed  # nothing was touched

    assert seed.main(["--reset"]) == 0
    assert dump(db) != changed


@pytest.mark.req("FR-12")
def test_opening_a_missing_database_fails_and_does_not_create_it(tmp_path, monkeypatch):
    missing = tmp_path / "nowhere.db"
    monkeypatch.setenv("ASSISTANCE_DB_PATH", str(missing))
    with pytest.raises(FileNotFoundError):
        database.connect()
    assert not missing.exists()


@pytest.mark.req("FR-11")
def test_committed_data_is_visible_to_a_new_connection(db):
    with database.transaction() as conn:
        conn.execute("UPDATE funds SET committed_cents = 500 WHERE id = 'fund_cb_rent'")
    with database.reading() as conn:
        row = conn.execute("SELECT committed_cents FROM funds WHERE id = 'fund_cb_rent'").fetchone()
    assert row["committed_cents"] == 500


@pytest.mark.req("BR-08")
@pytest.mark.parametrize(
    "bad_update",
    [
        "UPDATE funds SET committed_cents = allocation_cents + 1",  # committed more than the fund has
        "UPDATE funds SET committed_cents = 600000, paid_cents = 600000 WHERE id = 'fund_cb_rent'",  # together too much
        "UPDATE funds SET committed_cents = -1",
        "UPDATE funds SET paid_cents = -1",
    ],
)
def test_the_database_itself_refuses_an_overspent_or_negative_fund(db, bad_update):
    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as conn:
            conn.execute(bad_update)


@pytest.mark.req("BR-10")
@pytest.mark.parametrize("not_whole_cents", [300.5, "abc"])
def test_the_database_refuses_money_that_is_not_a_whole_number_of_cents(db, not_whole_cents):
    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as conn:
            conn.execute("UPDATE funds SET committed_cents = ? WHERE id = 'fund_cb_rent'", (not_whole_cents,))


@pytest.mark.req("BR-12")
def test_a_failed_transaction_leaves_nothing_behind(db):
    before = dump(db)
    with pytest.raises(RuntimeError):
        with database.transaction() as conn:
            conn.execute("UPDATE funds SET committed_cents = 500 WHERE id = 'fund_cb_rent'")
            raise RuntimeError("something went wrong half way")
    assert dump(db) == before
