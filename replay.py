"""Replays logged observations through the mode engine. Modes are derived at read time, never stored,
so changing a threshold re-derives every past day."""

import json
import math
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


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """95% Wilson score interval for k successes in n trials."""
    if n == 0:
        return None
    phat = k / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def reliability(points: list[tuple[float, bool]], bins: int = 10) -> dict:
    """Calibration of (stated probability, was it true) pairs: per-bin rates and the expected calibration error."""
    out, ece = [], 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        inside = [(prob, hit) for prob, hit in points if lo <= prob < hi or (b == bins - 1 and prob == 1.0)]
        if not inside:
            continue
        mean_p = sum(prob for prob, _ in inside) / len(inside)
        rate = sum(hit for _, hit in inside) / len(inside)
        ece += len(inside) / len(points) * abs(mean_p - rate)
        out.append({"lo": lo, "hi": hi, "n": len(inside), "mean_p": mean_p, "rate": rate})
    return {"n": len(points), "ece": ece if points else None, "bins": out}


def score_labels(conn: sqlite3.Connection, p: Params = Params(), sampled: str | None = None) -> dict:
    """Accuracy against hand labels: the fused engine vs the camera's activity answer alone.

    `sampled` keeps only labels picked that way ("random" gives an unbiased headline number).
    Labels marked "skip" (frame too unclear to judge) are left out.
    """
    conn.row_factory = sqlite3.Row
    labels = {
        r["observation_id"]: r["mode"]
        for r in conn.execute("SELECT observation_id, mode, sampled FROM labels")
        if r["mode"] != "skip" and (sampled is None or r["sampled"] == sampled)
    }
    pairs = []  # (truth, fused, camera)
    activity_points, person_points = [], []
    for session in load(conn):
        trace: list = []
        replay_session(session, p, trace)
        for obs, tr in zip(session["observations"], trace):
            if obs["id"] not in labels:
                continue
            truth = labels[obs["id"]]
            pairs.append((truth, tr["mode"], engine.camera_mode(obs)))
            if obs["ok"]:
                activity_points.append((max(obs["activity"].values()), engine.camera_mode(obs) == truth))
                person_points.append((obs["nouls"]["person_present"], truth != "away"))

    def summarize(idx: int) -> dict:
        confusion: dict = {}
        for pair in pairs:
            row = confusion.setdefault(pair[0], {})
            pred = pair[idx] or "unknown"
            row[pred] = row.get(pred, 0) + 1
        correct = sum(row.get(truth, 0) for truth, row in confusion.items())
        per_mode = {}
        for mode in engine.MODES:
            support = sum(confusion.get(mode, {}).values())
            predicted = sum(row.get(mode, 0) for row in confusion.values())
            hit = confusion.get(mode, {}).get(mode, 0)
            if support or predicted:
                per_mode[mode] = {
                    "support": support,
                    "predicted": predicted,
                    "recall": hit / support if support else None,
                    "precision": hit / predicted if predicted else None,
                }
        return {
            "accuracy": correct / len(pairs) if pairs else None,
            "interval": wilson(correct, len(pairs)),
            "confusion": confusion,
            "per_mode": per_mode,
        }

    return {
        "n": len(pairs),
        "fused": summarize(1),
        "camera": summarize(2),
        "calibration": {"activity": reliability(activity_points), "person_present": reliability(person_points)},
    }
