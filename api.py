"""Read-only API for the dashboard. Modes are derived per request by replaying observations through the
engine, so any engine threshold can be overridden with a query parameter (e.g. ?tau_s=45).

    uvicorn api:app --port 8765

Reads perch.db, or fake.db when there is no real data yet. Set PERCH_DB to point somewhere else.
"""

import os
import sqlite3
import statistics
from dataclasses import fields
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

import config
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
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
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
