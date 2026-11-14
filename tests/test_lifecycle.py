import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
import db
from lifecycle import SessionTracker


def rows(conn):
    return conn.execute("SELECT id, ended_at, end_reason FROM sessions ORDER BY id").fetchall()


def test_no_session_until_the_camera_is_live():
    conn = db.connect(":memory:")
    s = SessionTracker(conn)
    assert s.update(False, 0.0) is None
    assert rows(conn) == []
    assert s.update(True, 1.0) == "started"
    assert rows(conn) == [(1, None, None)]


def test_short_dropout_stays_in_the_session():
    conn = db.connect(":memory:")
    s = SessionTracker(conn)
    s.update(True, 0.0)
    assert s.update(False, 1.0) is None
    assert s.update(False, 1.0 + config.CAMERA_LOST_S) is None
    assert s.update(True, 2.0 + config.CAMERA_LOST_S) is None
    assert rows(conn) == [(1, None, None)]


def test_long_dropout_ends_the_session_when_the_camera_was_last_live():
    conn = db.connect(":memory:")
    s = SessionTracker(conn)
    s.update(True, 0.0)
    last_live = db.utc_now()
    s.update(False, 1.0)
    assert s.update(False, 2.0 + config.CAMERA_LOST_S) == "ended"
    (sid, ended_at, reason), = rows(conn)
    assert reason == "camera_lost" and ended_at <= last_live
    assert s.session_id is None
    # The camera coming back opens a new session.
    assert s.update(True, 500.0) == "started"
    assert [r[0] for r in rows(conn)] == [1, 2]


def test_quit_closes_the_open_session_and_is_a_no_op_without_one():
    conn = db.connect(":memory:")
    s = SessionTracker(conn)
    s.close("quit")
    assert rows(conn) == []
    s.update(True, 0.0)
    s.close("quit")
    assert rows(conn)[0][2] == "quit" and rows(conn)[0][1] is not None


def test_token_budget_levels(monkeypatch):
    from lifecycle import TokenBudget
    monkeypatch.setattr(config, "DAILY_TOKEN_BUDGET", 1000)
    b = TokenBudget(db.connect(":memory:"))
    assert b.level() == "ok"
    b.add(800)
    assert b.level() == "slow"
    b.add(None)
    b.add(200)
    assert b.level() == "over"
    monkeypatch.setattr(config, "DAILY_TOKEN_BUDGET", None)
    assert b.level() == "ok"


def test_live_mode_follows_the_engine():
    from lifecycle import LiveMode
    m = LiveMode()
    gone = {"ok": True, "nouls": {"person_present": 0.02, "tablet_gaming": 0.0, "controllers_out": 0.0, "camera_ok": 0.99},
            "probabilities": {"computer": 0.01, "gaming": 0.01, "other": 0.01, "nobody": 0.97}}
    obs = {"ts": "2026-11-14T18:00:00.000+00:00", "app": "Cursor", "domain": None, "idle_s": 300.0}
    assert m.update(obs, gone) == "away" and m.away
    m.reset()
    assert not m.away
    assert m.update({**obs, "idle_s": 1.0}, {"ok": False, "error": "x"}) == "computer"
