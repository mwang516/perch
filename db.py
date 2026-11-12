import json
import sqlite3
from datetime import datetime, timedelta, timezone

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    end_reason TEXT
);
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    ts TEXT NOT NULL,
    trigger TEXT NOT NULL,
    change_score REAL,
    status TEXT NOT NULL,
    error TEXT,
    latency_ms REAL,
    input_tokens INTEGER,
    model TEXT,
    answers TEXT,
    app TEXT,
    chrome_domain TEXT,
    idle_s REAL,
    thumb_path TEXT
);
CREATE TABLE IF NOT EXISTS labels (
    observation_id INTEGER PRIMARY KEY REFERENCES observations(id),
    mode TEXT NOT NULL,
    labeled_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def connect(path=None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.executescript(SCHEMA)
    return conn


def start_session(conn: sqlite3.Connection) -> int:
    cur = conn.execute("INSERT INTO sessions (started_at) VALUES (?)", (utc_now(),))
    conn.commit()
    return cur.lastrowid


def end_session(conn: sqlite3.Connection, session_id: int, reason: str) -> None:
    conn.execute("UPDATE sessions SET ended_at = ?, end_reason = ? WHERE id = ?", (utc_now(), reason, session_id))
    conn.commit()


def add_observation(conn: sqlite3.Connection, session_id: int, obs: dict, result: dict, commit: bool = True) -> int:
    answers = None
    if result["ok"]:
        answers = json.dumps({
            "nouls": result["nouls"],
            "activity": {
                "choice": result["activity"],
                "confidence": result["confidence"],
                "probabilities": result["probabilities"],
            },
        })
    cur = conn.execute(
        """INSERT INTO observations (session_id, ts, trigger, change_score, status, error, latency_ms,
               input_tokens, model, answers, app, chrome_domain, idle_s, thumb_path)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            session_id, obs["ts"], obs["trigger"], obs["score"], "ok" if result["ok"] else "error",
            result.get("error"), result["latency_ms"], result.get("tokens"), result.get("model"), answers,
            obs["app"], obs["domain"], obs["idle_s"], obs["thumb_path"],
        ),
    )
    if commit:
        conn.commit()
    return cur.lastrowid


def prune_thumbnails(conn: sqlite3.Connection) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=config.THUMB_RETENTION_DAYS)).isoformat(timespec="milliseconds")
    rows = conn.execute(
        """SELECT id, thumb_path FROM observations
           WHERE thumb_path IS NOT NULL AND ts < ? AND id NOT IN (SELECT observation_id FROM labels)""",
        (cutoff,),
    ).fetchall()
    for obs_id, thumb_path in rows:
        (config.BASE_DIR / thumb_path).unlink(missing_ok=True)
        conn.execute("UPDATE observations SET thumb_path = NULL WHERE id = ?", (obs_id,))
    conn.commit()
    return len(rows)
