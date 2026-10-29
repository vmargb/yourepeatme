import sqlite3
from datetime import datetime

import pytest

import db


@pytest.fixture
def c():
    return db.connect(":memory:")


def setup(c):
    pid = db.save_problem(c, dict(title="t", reference_code="x"))
    return pid, db.create_session(c, 25, [pid])


def test_unique_item_per_session(c):
    pid, sid = setup(c)
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("INSERT INTO session_items(session_id,problem_id,position) VALUES(?,?,1)", (sid, pid))


def test_complete_review_updates_schedule(c):
    pid, sid = setup(c)
    db.complete_review(c, sid, pid, "independent", "code", "n")
    p = db.list_problems(c)[0]
    r = c.execute("SELECT * FROM reviews").fetchone()
    assert p["stage"] == 0 and r["outcome"] == "independent" and r["attempt_code"] == "code"
    delta = datetime.fromisoformat(p["next_review_at"]) - datetime.fromisoformat(r["completed_at"])
    assert delta.days == 1


def test_double_submit_rejected(c):
    pid, sid = setup(c)
    db.complete_review(c, sid, pid, "partial")
    with pytest.raises(ValueError):
        db.complete_review(c, sid, pid, "independent")
    assert c.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 1


def test_archive_keeps_history(c):
    pid, sid = setup(c)
    db.complete_review(c, sid, pid, "independent")
    db.set_active(c, pid, False)
    assert c.execute("SELECT COUNT(*) FROM reviews").fetchone()[0] == 1


def test_export_import_roundtrip(c):
    pid, sid = setup(c)
    db.complete_review(c, sid, pid, "needed_help")
    data = db.export_data(c)
    c2 = db.connect(":memory:")
    db.import_data(c2, data)
    assert db.export_data(c2) == data
