import math

import cv2
import numpy as np

import config


def _thumb(frame: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, config.CHANGE_THUMB_SIZE, interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(small, (5, 5), 0).astype(np.int16)


class Sampler:
    def __init__(self):
        self._last_thumb: np.ndarray | None = None
        self._last_send = -math.inf
        self._fast_until = -math.inf
        self._last_app: str | None = None
        self._was_idle = False
        self._retry = False
        self._app_pending = False

    def failed(self) -> None:
        """The last send got no answer: send the newest frame soon instead of waiting for the heartbeat."""
        self._retry = True

    def check(self, frame: np.ndarray, now: float, app: str | None, idle_s: float, busy: bool,
              away: bool = False, budget: str = "ok") -> tuple[str, float] | None:
        """`budget` is "ok", "slow" (near the daily token cap) or "over" (past it: heartbeats only)."""
        thumb = _thumb(frame)
        score = float(np.abs(thumb - self._last_thumb).mean()) if self._last_thumb is not None else 0.0

        if self._last_app is not None and app != self._last_app:
            self._app_pending = True
        self._last_app = app
        idle = idle_s >= config.IDLE_THRESHOLD_S
        idle_crossed = idle and not self._was_idle
        self._was_idle = idle

        slow = config.BUDGET_SLOW_FACTOR if budget == "slow" else 1
        fast_s = config.FAST_INTERVAL_S * slow
        heartbeat_s = (config.AWAY_HEARTBEAT_S if away else config.HEARTBEAT_S) * slow
        since = now - self._last_send
        if budget == "over":
            trigger = "heartbeat" if since >= config.OVER_BUDGET_HEARTBEAT_S else None
        elif self._app_pending and since >= config.APP_CHANGE_MIN_S * slow:
            trigger = "app_change"
        elif idle_crossed:
            trigger = "idle_crossed"
        elif self._retry and since >= fast_s:
            trigger = "retry"
        elif score > config.MOTION_THRESHOLD and since >= fast_s:
            trigger = "motion"
        elif now < self._fast_until and since >= fast_s:
            trigger = "fast"
        elif since >= heartbeat_s:
            trigger = "heartbeat"
        else:
            trigger = None
        if trigger is None or busy:
            return None
        if trigger == "motion":
            self._fast_until = now + config.FAST_WINDOW_S
        self._last_thumb, self._last_send, self._retry, self._app_pending = thumb, now, False, False
        return trigger, score
