"""Sessions: a session is the agent running AND the camera delivering frames (HANDOFF §11)."""

import sqlite3
from datetime import datetime, timezone

import config
import db
import engine
import replay


class SessionTracker:
    """Opens a session when the camera goes live and ends it once the camera has been gone too long.

    A short dropout (phone unlocked, Mac waking up) stays inside the session. A long one ends the session
    at the moment the camera was last live, so the time without a camera is untracked rather than away.
    `now` is monotonic, which doesn't advance while the Mac sleeps: only awake time without a camera counts.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self.session_id: int | None = None
        self._last_live: str | None = None  # UTC time the camera was last live
        self._lost_since: float | None = None

    def update(self, live: bool, now: float) -> str | None:
        """Call every tick. Returns "started" or "ended" when the session changes."""
        if live:
            self._last_live, self._lost_since = db.utc_now(), None
            if self.session_id is None:
                self.session_id = db.start_session(self._conn)
                return "started"
        elif self.session_id is not None:
            if self._lost_since is None:
                self._lost_since = now
            elif now - self._lost_since > config.CAMERA_LOST_S:
                self._end("camera_lost")
                return "ended"
        return None

    def close(self, reason: str) -> None:
        """The agent is stopping. If the camera is gone right now, the session ended when it was last live."""
        if self.session_id is not None:
            self._end(reason)

    def _end(self, reason: str) -> None:
        at = self._last_live if self._lost_since is not None else None
        db.end_session(self._conn, self.session_id, reason, at)
        self.session_id, self._lost_since = None, None


class LiveMode:
    """The engine run live, only to pace the sampler and label the console line. Nothing it decides is
    stored: modes are always re-derived from the logged observations at read time."""

    def __init__(self):
        self.state = engine.State()

    def reset(self) -> None:
        self.state = engine.State()

    def update(self, obs: dict, result: dict) -> str | None:
        self.state, _ = engine.step(self.state, {
            "t": replay.to_epoch(obs["ts"]),
            "ok": result["ok"],
            "nouls": result.get("nouls"),
            "activity": result.get("probabilities"),
            "app": obs["app"],
            "domain": obs["domain"],
            "idle_s": obs["idle_s"],
        })
        return self.state.mode

    @property
    def away(self) -> bool:
        return self.state.mode == "away"


class TokenBudget:
    """Counts today's Jev input tokens (local day) against the daily cap."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._day = None
        self.used = 0
        self._roll()

    def _roll(self) -> None:
        now = datetime.now().astimezone()
        if now.date() != self._day:
            self._day = now.date()
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
            self.used = db.tokens_since(self._conn, midnight.isoformat(timespec="milliseconds"))

    def add(self, tokens: int | None) -> None:
        self._roll()
        self.used += tokens or 0

    def level(self) -> str:
        self._roll()
        if not config.DAILY_TOKEN_BUDGET:
            return "ok"
        if self.used >= config.DAILY_TOKEN_BUDGET:
            return "over"
        return "slow" if self.used >= config.DAILY_TOKEN_BUDGET * config.BUDGET_SLOW_AT else "ok"
