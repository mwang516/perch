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

    def failed(self) -> None:
        """The last send got no answer: send the newest frame soon instead of waiting for the heartbeat."""
        self._retry = True

    def check(self, frame: np.ndarray, now: float, app: str | None, idle_s: float, busy: bool) -> tuple[str, float] | None:
        thumb = _thumb(frame)
        score = float(np.abs(thumb - self._last_thumb).mean()) if self._last_thumb is not None else 0.0

        app_changed = self._last_app is not None and app != self._last_app
        self._last_app = app
        idle = idle_s >= config.IDLE_THRESHOLD_S
        idle_crossed = idle and not self._was_idle
        self._was_idle = idle

        since = now - self._last_send
        if app_changed:
            trigger = "app_change"
        elif idle_crossed:
            trigger = "idle_crossed"
        elif self._retry and since >= config.FAST_INTERVAL_S:
            trigger = "retry"
        elif score > config.MOTION_THRESHOLD and since >= config.FAST_INTERVAL_S:
            trigger = "motion"
        elif now < self._fast_until and since >= config.FAST_INTERVAL_S:
            trigger = "fast"
        elif since >= config.HEARTBEAT_S:
            trigger = "heartbeat"
        else:
            return None

        if busy:
            return None
        if trigger == "motion":
            self._fast_until = now + config.FAST_WINDOW_S
        self._last_thumb, self._last_send, self._retry = thumb, now, False
        return trigger, score
