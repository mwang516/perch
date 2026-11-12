"""Replays logged observations through the mode engine. Modes are derived at read time, never stored,
so changing a threshold re-derives every past day."""

import json
import sqlite3
from datetime import datetime

import engine
from engine import Params, State


def to_epoch(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp()


def to_obs(row: sqlite3.Row | dict) -> dict:
    ok = row["status"] == "ok"
    answers = json.loads(row["answers"]) if ok else None
    return {
        "id": row["id"],
        "t": to_epoch(row["ts"]),
        "ok": ok,
        "nouls": answers["nouls"] if ok else None,
        "activity": answers["activity"]["probabilities"] if ok else None,
        "app": row["app"],
        "domain": row["chrome_domain"],
        "idle_s": row["idle_s"],
    }


def load(conn: sqlite3.Connection, start_iso: str | None = None, end_iso: str | None = None) -> list[dict]:
    """Sessions overlapping [start, end), each with its observations in time order."""
    conn.row_factory = sqlite3.Row
    sessions = conn.execute(
        """SELECT * FROM sessions
           WHERE (:end IS NULL OR started_at < :end)
             AND (:start IS NULL OR ended_at IS NULL OR ended_at >= :start)
           ORDER BY started_at""",
        {"start": start_iso, "end": end_iso},
    ).fetchall()
    out = []
    for s in sessions:
        rows = conn.execute("SELECT * FROM observations WHERE session_id = ? ORDER BY ts", (s["id"],)).fetchall()
        out.append({
            "id": s["id"],
            "start": to_epoch(s["started_at"]),
            "end": to_epoch(s["ended_at"]) if s["ended_at"] else None,
            "end_reason": s["end_reason"],
            "observations": [to_obs(r) for r in rows],
        })
    return out


def replay_session(session: dict, p: Params = Params(), trace: list | None = None) -> list[dict]:
    """Mode segments for one session: {session_id, mode, coding, start, end, gap}.

    A gap between observations longer than reset_gap_s (lid closed, sleep) becomes an away segment.
    A session with no clean end (crash) stops at its last observation.
    """
    segments: list[dict] = []
    sid = session["id"]

    def close(end: float) -> None:
        if segments and segments[-1]["end"] is None:
            segments[-1]["end"] = end

    def gap(start: float, end: float) -> None:
        close(start)
        segments.append({"session_id": sid, "mode": "away", "coding": False, "start": start, "end": end, "gap": True})

    state, prev_t = State(), session["start"]
    for obs in session["observations"]:
        if obs["t"] - prev_t > p.reset_gap_s:
            gap(prev_t, obs["t"])
            state = State()
        state, events = engine.step(state, obs, p)
        for e in events:
            close(e["t"])
            segments.append({"session_id": sid, "mode": e["mode"], "coding": e["coding"], "start": e["t"], "end": None, "gap": False})
        if trace is not None:
            trace.append({"id": obs["id"], "t": obs["t"], "mode": state.mode, "coding": state.coding,
                          "rule": engine.fuse(obs, p).rule, "scores": state.scores})
        prev_t = obs["t"]

    end = session["end"]
    if end is not None and end - prev_t > p.reset_gap_s:
        gap(prev_t, end)
    close(prev_t if end is None else end)
    return [s for s in segments if s["end"] > s["start"]]


def replay(sessions: list[dict], p: Params = Params()) -> list[dict]:
    return [seg for s in sessions for seg in replay_session(s, p)]


def totals(segments: list[dict], start: float | None = None, end: float | None = None) -> dict:
    """Seconds per mode within [start, end), with coding split out of computer."""
    out = {m: 0.0 for m in engine.MODES} | {"coding": 0.0}
    for s in segments:
        a = s["start"] if start is None else max(s["start"], start)
        b = s["end"] if end is None else min(s["end"], end)
        if b > a:
            out[s["mode"]] += b - a
            if s["coding"]:
                out["coding"] += b - a
    return out


def score_labels(conn: sqlite3.Connection, p: Params = Params()) -> dict:
    """Accuracy against hand labels: the fused engine vs the camera's activity answer alone."""
    conn.row_factory = sqlite3.Row
    labels = {r["observation_id"]: r["mode"] for r in conn.execute("SELECT observation_id, mode FROM labels")}
    pairs = []  # (truth, fused, camera)
    for session in load(conn):
        trace: list = []
        replay_session(session, p, trace)
        for obs, tr in zip(session["observations"], trace):
            if obs["id"] in labels:
                pairs.append((labels[obs["id"]], tr["mode"], engine.camera_mode(obs)))

    def summarize(idx: int) -> dict:
        confusion: dict = {}
        for pair in pairs:
            row = confusion.setdefault(pair[0], {})
            pred = pair[idx] or "unknown"
            row[pred] = row.get(pred, 0) + 1
        correct = sum(row.get(truth, 0) for truth, row in confusion.items())
        return {"accuracy": correct / len(pairs) if pairs else None, "confusion": confusion}

    return {"n": len(pairs), "fused": summarize(1), "camera": summarize(2)}
