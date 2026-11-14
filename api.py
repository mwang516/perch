"""API for the dashboard. Modes are derived per request by replaying observations through the engine, so
any engine threshold can be overridden with a query parameter (e.g. ?tau_s=45). The only thing it writes
is hand labels.

    uvicorn api:app --port 8765

Reads perch.db, or fake.db when there is no real data yet. Set PERCH_DB to point somewhere else.
Serves the built dashboard from dashboard/dist when it exists (`npm --prefix dashboard run build`).
Localhost only: thumbnails are raw frames and must never be exposed remotely.
"""

import os
import random
import sqlite3
import statistics
from dataclasses import fields
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import db
import engine
import replay
from engine import Params

USD_PER_INPUT_TOKEN = 0.042 / 1_000_000

app = FastAPI(title="Perch")


def db_path() -> Path:
    if os.environ.get("PERCH_DB"):
        return Path(os.environ["PERCH_DB"])
    return config.DB_PATH if config.DB_PATH.exists() else config.FAKE_DB_PATH


def connect() -> sqlite3.Connection:
    path = db_path()
    if not path.exists():
        raise HTTPException(503, f"No database at {path.name}. Run the agent, or `python fake.py` for synthetic data.")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def connect_rw() -> sqlite3.Connection:
    """For labels only. Also brings an older database up to the current schema."""
    path = db_path()
    if not path.exists():
        raise HTTPException(503, f"No database at {path.name}.")
    conn = db.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def params_from(request: Request) -> Params:
    overrides = {}
    for f in fields(Params):
        if f.name in request.query_params:
            try:
                overrides[f.name] = float(request.query_params[f.name])
            except ValueError:
                raise HTTPException(400, f"{f.name} must be a number")
    return Params(**overrides)


def utc_iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds")


def day_window(day: date) -> tuple[float, float]:
    """Local midnight to the next local midnight, as epoch seconds."""
    start = datetime.combine(day, time.min).astimezone()
    end = datetime.combine(day + timedelta(days=1), time.min).astimezone()
    return start.timestamp(), end.timestamp()


def session_end(s: dict) -> float:
    if s["end"] is not None:
        return s["end"]
    return s["observations"][-1]["t"] if s["observations"] else s["start"]


def clip(items: list[dict], start: float, end: float) -> list[dict]:
    out = []
    for item in items:
        a, b = max(item["start"], start), min(item["end"], end)
        if b > a:
            out.append({**item, "start": a, "end": b})
    return out


def summarize(segments: list[dict], start: float, end: float) -> dict:
    totals = replay.totals(segments, start, end)
    tracked = sum(totals[m] for m in engine.MODES)
    return {**totals, "tracked": tracked, "at_desk": tracked - totals["away"] - totals["unknown"]}


@app.get("/api/meta")
def meta() -> dict:
    path = db_path()
    return {"db": path.name, "synthetic": path.name == config.FAKE_DB_PATH.name,
            "params": {f.name: f.default for f in fields(Params)}}


@app.get("/api/day")
def day(request: Request, date: date | None = None) -> dict:
    """One local day: sessions, mode segments, totals and sampler stats."""
    day_ = date or datetime.now().date()
    start, end = day_window(day_)
    end = min(end, max(start, datetime.now().timestamp()))
    p = params_from(request)
    conn = connect()
    try:
        sessions = [s for s in replay.load(conn, utc_iso(start), utc_iso(end)) if session_end(s) > start]
        rows = conn.execute(
            "SELECT status, latency_ms, input_tokens, trigger FROM observations WHERE ts >= ? AND ts < ?",
            (utc_iso(start), utc_iso(end)),
        ).fetchall()
    finally:
        conn.close()

    segments = clip(replay.replay(sessions, p), start, end)
    spans = clip([{"id": s["id"], "start": s["start"], "end": session_end(s), "crashed": s["end"] is None} for s in sessions], start, end)
    ok = [r for r in rows if r["status"] == "ok"]
    tokens = sum(r["input_tokens"] or 0 for r in ok)
    triggers: dict = {}
    for r in rows:
        triggers[r["trigger"]] = triggers.get(r["trigger"], 0) + 1
    return {
        "date": day_.isoformat(),
        "start": start,
        "end": end,
        "sessions": spans,
        "segments": segments,
        "totals": summarize(segments, start, end),
        "stats": {
            "observations": len(rows),
            "failed": len(rows) - len(ok),
            "median_latency_ms": statistics.median(r["latency_ms"] for r in ok) if ok else None,
            "input_tokens": tokens,
            "cost_usd": tokens * USD_PER_INPUT_TOKEN,
            "triggers": triggers,
        },
    }


@app.get("/api/days")
def days(request: Request, n: int = 7, until: date | None = None) -> list[dict]:
    """Totals for the n local days ending at `until` (default today), oldest first."""
    if not 1 <= n <= 90:
        raise HTTPException(400, "n must be between 1 and 90")
    last = until or datetime.now().date()
    wanted = [last - timedelta(days=i) for i in range(n - 1, -1, -1)]
    p = params_from(request)
    conn = connect()
    try:
        sessions = replay.load(conn, utc_iso(day_window(wanted[0])[0]), utc_iso(day_window(last)[1]))
    finally:
        conn.close()
    segments = replay.replay(sessions, p)
    return [{"date": d.isoformat(), "totals": summarize(segments, *day_window(d))} for d in wanted]


# ---- Live view ----

@app.get("/api/live")
def live(request: Request, n: int = 40) -> dict:
    """The newest session's latest observations with what the engine made of each one, newest first."""
    if not 1 <= n <= 500:
        raise HTTPException(400, "n must be between 1 and 500")
    p = params_from(request)
    conn = connect()
    try:
        last = conn.execute("SELECT id FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
        if not last:
            return {"session": None, "observations": [], "now": datetime.now().timestamp()}
        session = next(s for s in replay.load(conn) if s["id"] == last["id"])
        rows = conn.execute(
            """SELECT id, trigger, change_score, status, error, latency_ms, input_tokens, answers, thumb_path
               FROM observations WHERE session_id = ? ORDER BY ts""", (last["id"],)
        ).fetchall()
    finally:
        conn.close()
    trace: list = []
    replay.replay_session(session, p, trace)
    out = []
    for row, obs, tr in list(zip(rows, session["observations"], trace))[-n:]:
        out.append({
            "id": row["id"], "t": obs["t"], "trigger": row["trigger"], "change_score": row["change_score"],
            "ok": obs["ok"], "error": row["error"], "latency_ms": row["latency_ms"],
            "app": obs["app"], "domain": obs["domain"], "idle_s": obs["idle_s"],
            "nouls": obs["nouls"], "activity": obs["activity"], "has_thumb": row["thumb_path"] is not None,
            "mode": tr["mode"], "coding": tr["coding"], "rule": tr["rule"],
        })
    out.reverse()
    return {
        "session": {"id": session["id"], "start": session["start"], "end": session["end"],
                    "end_reason": session["end_reason"], "observations": len(rows)},
        "observations": out,
        "now": datetime.now().timestamp(),
    }


# ---- Labeling ----

UNLABELED = """FROM observations o LEFT JOIN labels l ON l.observation_id = o.id
               WHERE l.observation_id IS NULL AND o.thumb_path IS NOT NULL"""


class LabelIn(BaseModel):
    observation_id: int
    mode: str
    sampled: str | None = None


def label_item(row: sqlite3.Row) -> dict:
    # Deliberately no Jev answers or app name: labels must come from the picture alone.
    return {"id": row["id"], "t": replay.to_epoch(row["ts"])}


@app.get("/api/label/next")
def label_next(strategy: str = "random") -> dict:
    """One unlabeled frame. "random" is unbiased; "balanced" picks evenly across what the camera answered,
    so rare activities get labeled sooner (those labels are marked and can be left out of headline accuracy)."""
    if strategy not in ("random", "balanced"):
        raise HTTPException(400, "strategy must be random or balanced")
    conn = connect_rw()
    try:
        remaining = conn.execute(f"SELECT COUNT(*) {UNLABELED}").fetchone()[0]
        where = ""
        args: tuple = ()
        if strategy == "balanced" and remaining:
            kind = "COALESCE(json_extract(o.answers, '$.activity.choice'), 'error')"
            kinds = [r[0] for r in conn.execute(f"SELECT DISTINCT {kind} {UNLABELED}")]
            where, args = f" AND {kind} = ?", (random.choice(kinds),)
        row = conn.execute(f"SELECT o.id, o.ts {UNLABELED}{where} ORDER BY RANDOM() LIMIT 1", args).fetchone()
    finally:
        conn.close()
    return {"item": label_item(row) if row else None, "remaining": remaining, "sampled": strategy}


@app.get("/api/label/summary")
def label_summary() -> dict:
    conn = connect_rw()
    try:
        counts = {r[0]: r[1] for r in conn.execute("SELECT mode, COUNT(*) FROM labels GROUP BY mode")}
        remaining = conn.execute(f"SELECT COUNT(*) {UNLABELED}").fetchone()[0]
    finally:
        conn.close()
    return {"counts": counts, "labeled": sum(counts.values()), "remaining": remaining}


@app.post("/api/label")
def label_set(body: LabelIn) -> dict:
    if body.mode not in db.LABEL_MODES:
        raise HTTPException(400, f"mode must be one of {', '.join(db.LABEL_MODES)}")
    conn = connect_rw()
    try:
        if not conn.execute("SELECT 1 FROM observations WHERE id = ?", (body.observation_id,)).fetchone():
            raise HTTPException(404, "No such observation")
        db.set_label(conn, body.observation_id, body.mode, body.sampled)
    finally:
        conn.close()
    return {"ok": True}


@app.delete("/api/label/{observation_id}")
def label_delete(observation_id: int) -> dict:
    """Undo: removes the label and hands the frame back so it can be labeled again."""
    conn = connect_rw()
    try:
        db.delete_label(conn, observation_id)
        row = conn.execute("SELECT id, ts FROM observations WHERE id = ?", (observation_id,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(404, "No such observation")
    return {"item": label_item(row)}


@app.get("/api/thumb/{observation_id}")
def thumb(observation_id: int) -> FileResponse:
    conn = connect()
    try:
        row = conn.execute("SELECT thumb_path FROM observations WHERE id = ?", (observation_id,)).fetchone()
    finally:
        conn.close()
    if not row or not row["thumb_path"]:
        raise HTTPException(404, "No thumbnail")
    path = (config.BASE_DIR / row["thumb_path"]).resolve()
    if not path.is_relative_to(config.THUMBS_DIR.resolve()) or not path.is_file():
        raise HTTPException(404, "No thumbnail")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


# ---- Accuracy and stats ----

@app.get("/api/accuracy")
def accuracy(request: Request, sampled: str | None = None) -> dict:
    """Fused engine vs camera alone against the hand labels, plus calibration of Jev's probabilities."""
    conn = connect_rw()
    try:
        return replay.score_labels(conn, params_from(request), sampled)
    finally:
        conn.close()


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, round(q * (len(values) - 1)))]


@app.get("/api/stats")
def stats(n: int = 14, until: date | None = None) -> dict:
    """Sampler, latency and cost numbers for the n local days ending at `until` (default today)."""
    if not 1 <= n <= 90:
        raise HTTPException(400, "n must be between 1 and 90")
    last = until or datetime.now().date()
    wanted = [last - timedelta(days=i) for i in range(n - 1, -1, -1)]
    start, end = day_window(wanted[0])[0], day_window(last)[1]
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT ts, status, error, latency_ms, input_tokens, trigger FROM observations WHERE ts >= ? AND ts < ?",
            (utc_iso(start), utc_iso(end)),
        ).fetchall()
        sessions = replay.load(conn, utc_iso(start), utc_iso(end))
    finally:
        conn.close()

    spans = [(s["start"], session_end(s)) for s in sessions]
    times = [replay.to_epoch(r["ts"]) for r in rows]
    days_out = []
    for d in wanted:
        a, b = day_window(d)
        day_rows = [r for r, t in zip(rows, times) if a <= t < b]
        tokens = sum(r["input_tokens"] or 0 for r in day_rows)
        running = sum(max(0.0, min(e, b) - max(s, a)) for s, e in spans)
        days_out.append({
            "date": d.isoformat(),
            "observations": len(day_rows),
            "failed": sum(r["status"] != "ok" for r in day_rows),
            "input_tokens": tokens,
            "cost_usd": tokens * USD_PER_INPUT_TOKEN,
            "running_s": running,
            "per_hour": len(day_rows) / (running / 3600) if running >= 60 else None,
        })
    ok = [r for r in rows if r["status"] == "ok"]
    latencies = [r["latency_ms"] for r in ok if r["latency_ms"] is not None]
    triggers: dict = {}
    errors: dict = {}
    for r in rows:
        triggers[r["trigger"]] = triggers.get(r["trigger"], 0) + 1
        if r["status"] != "ok":
            kind = (r["error"] or "unknown").split(":")[0]
            errors[kind] = errors.get(kind, 0) + 1
    tokens = sum(r["input_tokens"] or 0 for r in ok)
    return {
        "days": days_out,
        "observations": len(rows),
        "failed": len(rows) - len(ok),
        "latency_ms": {q: percentile(latencies, v) for q, v in (("p50", 0.5), ("p90", 0.9), ("p99", 0.99))},
        "tokens_per_call": tokens / len(ok) if ok else None,
        "cost_usd": tokens * USD_PER_INPUT_TOKEN,
        "triggers": triggers,
        "errors": errors,
    }


# The built dashboard, when present. Mounted last so /api routes win.
DIST = config.BASE_DIR / "dashboard" / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="dashboard")
