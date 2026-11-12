import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import engine
import fake
import replay
from engine import Params, State

P = Params()


def obs(t, *, app="Cursor", domain=None, idle=1.0, person=0.97, tablet=0.03, controllers=0.03, camera=0.97,
        activity="computer", ok=True):
    probs = {m: 0.02 for m in ("computer", "gaming", "other", "nobody")} | {activity: 0.94}
    return {
        "id": int(t), "t": float(t), "ok": ok, "app": app, "domain": domain, "idle_s": idle,
        "nouls": {"person_present": person, "tablet_gaming": tablet, "controllers_out": controllers, "camera_ok": camera} if ok else None,
        "activity": probs if ok else None,
    }


def run(observations, state=State()):
    events = []
    for o in observations:
        state, ev = engine.step(state, o, P)
        events += ev
    return state, events


# --- fusion rules ---

def test_recent_input_uses_the_app():
    assert engine.fuse(obs(0, app="Cursor")).scores == {"computer": 1.0}
    assert engine.fuse(obs(0, app="Cursor")).coding is True
    assert engine.fuse(obs(0, app="Discord")).coding is False
    assert engine.fuse(obs(0, app="osu!")).scores == {"gaming": 1.0}


def test_coding_domains_only_count_in_chrome():
    assert engine.fuse(obs(0, app="Google Chrome", domain="github.com")).coding is True
    assert engine.fuse(obs(0, app="Google Chrome", domain="youtube.com")).coding is False


def test_tablet_gaming_overrides_a_frontmost_app():
    f = engine.fuse(obs(0, app="Cursor", idle=5, tablet=0.9))
    assert f.scores == {"gaming": 1.0} and f.rule == "tablet"


def test_away_needs_empty_chair_and_idle_mac():
    assert engine.fuse(obs(0, person=0.02, idle=120, activity="nobody")).scores == {"away": 1.0}
    assert "away" not in engine.fuse(obs(0, person=0.02, idle=20, activity="nobody")).scores
    assert "away" not in engine.fuse(obs(0, person=0.97, idle=600, activity="nobody")).scores


def test_idle_mac_with_person_defers_to_camera():
    f = engine.fuse(obs(0, app="Cursor", idle=300, activity="other"))
    assert f.rule == "camera" and max(f.scores, key=f.scores.get) == "other"


def test_bad_camera_is_unknown():
    assert engine.fuse(obs(0, camera=0.1)).scores == {"unknown": 1.0}


def test_failed_call_falls_back_to_recent_input():
    assert engine.fuse(obs(0, ok=False, idle=3)).scores == {"computer": 1.0}
    assert engine.fuse(obs(0, ok=False, idle=300)).scores == {}


# --- smoothing and switching ---

def test_smoothing_is_consistent_under_irregular_polling():
    start, _ = run([obs(0)])
    two, _ = run([obs(10, idle=300, activity="other"), obs(20, idle=300, activity="other")], start)
    one, _ = run([obs(20, idle=300, activity="other")], start)
    assert abs(two.scores["other"] - one.scores["other"]) < 1e-9


def test_single_odd_heartbeat_frame_is_absorbed():
    frames = [obs(t) for t in range(0, 200, 25)]
    frames[4] = obs(100, idle=300, activity="other")
    state, events = run(frames)
    assert state.mode == "computer" and len(events) == 1


def test_sustained_change_switches():
    frames = [obs(t) for t in range(0, 100, 25)] + [obs(t, idle=300, tablet=0.9, activity="gaming") for t in range(100, 250, 25)]
    state, events = run(frames)
    assert state.mode == "gaming" and [e["mode"] for e in events] == ["computer", "gaming"]


def test_bending_down_is_not_away():
    frames = [obs(t) for t in range(0, 100, 25)]
    frames += [obs(t, person=0.02, idle=t - 98, activity="nobody") for t in (100, 102.5, 105, 107.5, 110, 112.5)]
    frames += [obs(t) for t in range(115, 200, 25)]
    _, events = run(frames)
    assert [e["mode"] for e in events] == ["computer"]


def away_state():
    frames = [obs(0)] + [obs(t, person=0.02, idle=t, activity="nobody") for t in range(25, 300, 25)]
    state, _ = run(frames)
    assert state.mode == "away"
    return state


def test_keypress_leaves_away_instantly():
    state, events = run([obs(301, idle=0.5)], away_state())
    assert state.mode == "computer" and events[0]["t"] == 301


def test_keypress_leaves_away_even_when_jev_fails():
    state, _ = run([obs(301, idle=0.5, ok=False)], away_state())
    assert state.mode == "computer"


def test_camera_alone_leaves_away_for_ipad():
    frames = [obs(t, idle=t, tablet=0.9, activity="gaming") for t in (300, 302.5, 305, 307.5, 310, 320, 330, 340, 350)]
    state, _ = run(frames, away_state())
    assert state.mode == "gaming"


def test_failed_calls_are_absorbed_then_become_unknown():
    start, _ = run([obs(0, idle=300, activity="other"), obs(25, idle=300, activity="other")])
    state, events = run([obs(50, idle=300, ok=False)], start)
    assert state == start and not events
    state, _ = run([obs(t, idle=300, ok=False) for t in range(50, 300, 25)], start)
    assert state.mode == "unknown"


def test_coding_tag_follows_the_app():
    frames = [obs(0, app="Cursor"), obs(25, app="Discord"), obs(50, app="Terminal")]
    _, events = run(frames)
    assert [(e["mode"], e["coding"]) for e in events] == [("computer", True), ("computer", False), ("computer", True)]


# --- replay ---

def session(observations, start=0.0, end=None):
    return {"id": 1, "start": start, "end": end, "end_reason": "quit" if end else None, "observations": observations}


def test_gap_inside_a_session_is_away():
    frames = [obs(t) for t in range(0, 100, 25)] + [obs(t) for t in range(3000, 3100, 25)]
    segs = replay.replay_session(session(frames, end=3100.0))
    assert [(s["mode"], s["gap"]) for s in segs] == [("computer", False), ("away", True), ("computer", False)]
    assert segs[1]["start"] == 75 and segs[1]["end"] == 3000
    assert all(a["end"] == b["start"] for a, b in zip(segs, segs[1:]))


def test_crashed_session_stops_at_last_observation():
    segs = replay.replay_session(session([obs(t) for t in range(0, 100, 25)]))
    assert segs[-1]["end"] == 75


def test_totals_clip_to_the_window():
    segs = replay.replay_session(session([obs(t) for t in range(0, 101, 25)], end=100.0))
    assert replay.totals(segs, 50, 80)["computer"] == 30
    assert replay.totals(segs)["coding"] == 100


def test_fake_week_end_to_end(tmp_path):
    path = tmp_path / "fake.db"
    assert fake.generate(days=3, seed=7, path=path) > 1000
    conn = sqlite3.connect(path)
    result = replay.score_labels(conn)
    # The fused engine should beat the camera alone (osu! looks like computer use to the camera).
    assert result["fused"]["accuracy"] > 0.93
    assert result["fused"]["accuracy"] > result["camera"]["accuracy"]
    segs = replay.replay(replay.load(conn))
    assert all(s["end"] > s["start"] for s in segs)
    conn.close()
