"""Hand gestures → one-off actions (HANDOFF §10). Off by default: set GESTURES_ENABLED in config.py.

MediaPipe's Gesture Recognizer runs locally on the latest camera frame a few times a second. A gesture
fires its action only after it has been held steadily, and then not again until the hand has been
released and a cooldown has passed.

    python gestures.py --download   fetch the MediaPipe model (about 8 MB) into models/
    python gestures.py              watch the camera and print what is recognized; fires nothing
    python gestures.py --act        the same, but actions really fire

Untested against the real camera angle: try the print-only mode before enabling it in the agent.
"""

import queue
import subprocess
import sys
import threading
import time
import urllib.request

import config

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task"
MODEL_PATH = config.BASE_DIR / "models" / "gesture_recognizer.task"

# What MediaPipe's stock model can recognize. Anything else needs a retrained model.
GESTURES = ("Closed_Fist", "Open_Palm", "Pointing_Up", "Thumb_Down", "Thumb_Up", "Victory", "ILoveYou")

# macOS media keys (NX_KEYTYPE_*).
_MEDIA_KEYS = {"play_pause": 16, "next_track": 17, "previous_track": 18}


class GestureTrigger:
    """Decides when a recognized gesture counts. Pure: feed it (gesture, score, time), get a gesture back
    on the frame it fires."""

    def __init__(self, hold_s: float, cooldown_s: float, min_score: float):
        self.hold_s, self.cooldown_s, self.min_score = hold_s, cooldown_s, min_score
        self._current: str | None = None
        self._since = 0.0
        self._fired = False
        self._last_fire = -1e9

    def feed(self, gesture: str | None, score: float, now: float) -> str | None:
        if gesture in (None, "None") or score < self.min_score:
            gesture = None
        if gesture != self._current:
            self._current, self._since, self._fired = gesture, now, False
            return None
        if gesture is None or self._fired:
            return None  # one fire per hold: the hand must be released first
        if now - self._since >= self.hold_s and now - self._last_fire >= self.cooldown_s:
            self._fired, self._last_fire = True, now
            return gesture
        return None


def _media_key(key: int) -> None:
    import Quartz
    from AppKit import NSEvent

    for down in (True, False):
        event = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            14, (0, 0), 0xA00 if down else 0xB00, 0, 0, 0, 8, (key << 16) | ((0xA if down else 0xB) << 8), -1
        )
        Quartz.CGEventPost(0, event.CGEvent())


def _osascript(script: str) -> str:
    out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=3)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "osascript failed")
    return out.stdout.strip()


_mic_restore = 75


def _mic_mute() -> None:
    """Toggles the Mac's input volume, so it works in every app (Discord, Meet, Zoom)."""
    global _mic_restore
    level = int(_osascript("input volume of (get volume settings)"))
    if level > 0:
        _mic_restore = level
        _osascript("set volume input volume 0")
    else:
        _osascript(f"set volume input volume {_mic_restore}")


def _volume(step: int) -> None:
    level = int(_osascript("output volume of (get volume settings)"))
    _osascript(f"set volume output volume {max(0, min(100, level + step))}")


def _keystroke() -> None:
    """Presses the shortcut in config.GESTURE_KEYSTROKE, e.g. Discord's own Toggle Mute keybind."""
    key, modifiers = config.GESTURE_KEYSTROKE
    using = f" using {{{', '.join(m + ' down' for m in modifiers)}}}" if modifiers else ""
    _osascript(f'tell application "System Events" to keystroke "{key}"{using}')


# Every action a gesture can be mapped to in config.GESTURE_ACTIONS.
ACTIONS = {
    "play_pause": lambda: _media_key(_MEDIA_KEYS["play_pause"]),
    "next_track": lambda: _media_key(_MEDIA_KEYS["next_track"]),
    "previous_track": lambda: _media_key(_MEDIA_KEYS["previous_track"]),
    "mic_mute": _mic_mute,
    "volume_up": lambda: _volume(10),
    "volume_down": lambda: _volume(-10),
    "keystroke": _keystroke,
}


def validate() -> None:
    for gesture, action in config.GESTURE_ACTIONS.items():
        if gesture not in GESTURES:
            raise ValueError(f"GESTURE_ACTIONS: unknown gesture '{gesture}'. Choose from {', '.join(GESTURES)}")
        if action not in ACTIONS:
            raise ValueError(f"GESTURE_ACTIONS: unknown action '{action}'. Choose from {', '.join(ACTIONS)}")


def crop(frame):
    """Hands are small in a whole-desk frame. GESTURE_REGION zooms the recognizer onto one part of it."""
    if not config.GESTURE_REGION:
        return frame
    h, w = frame.shape[:2]
    x0, y0, x1, y1 = config.GESTURE_REGION
    return frame[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


class GestureWatcher:
    """Runs the recognizer on its own thread against camera.latest(). Fired gestures land in `events` as
    (utc timestamp, gesture, action, success) for the agent to log."""

    def __init__(self, cam, act: bool = True, verbose: bool = False):
        validate()
        if not MODEL_PATH.exists():
            raise FileNotFoundError(f"{MODEL_PATH} is missing. Run: python gestures.py --download")
        self._cam, self._act, self._verbose = cam, act, verbose
        self.events: queue.Queue = queue.Queue()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _run(self) -> None:
        import cv2
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        import db

        recognizer = vision.GestureRecognizer.create_from_options(
            vision.GestureRecognizerOptions(base_options=BaseOptions(model_asset_path=str(MODEL_PATH)), num_hands=2)
        )
        trigger = GestureTrigger(config.GESTURE_HOLD_S, config.GESTURE_COOLDOWN_S, config.GESTURE_MIN_SCORE)
        last_time, shown = 0.0, None
        while self._running:
            time.sleep(1 / config.GESTURE_FPS)
            frame, frame_time = self._cam.latest()
            if frame is None or frame_time == last_time:
                continue
            last_time = frame_time
            rgb = cv2.cvtColor(crop(frame), cv2.COLOR_BGR2RGB)
            result = recognizer.recognize(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
            # The most confident mapped gesture across the hands in view.
            best, score = None, 0.0
            for hand in result.gestures:
                top = hand[0]
                if top.category_name != "None" and top.score > score:
                    best, score = top.category_name, top.score
            if self._verbose and best != shown:
                shown = best
                print(f"{time.strftime('%H:%M:%S')}  sees {best or 'no gesture'}" + (f" ({score:.2f})" if best else ""))
            fired = trigger.feed(best if best in config.GESTURE_ACTIONS else None, score, time.monotonic())
            if not fired:
                continue
            action, ok = config.GESTURE_ACTIONS[fired], True
            if self._act:
                try:
                    ACTIONS[action]()
                except Exception as e:
                    ok = False
                    print(f"gesture action {action} failed: {type(e).__name__}: {e}")
            print(f"{time.strftime('%H:%M:%S')}  gesture {fired} -> {action}" + ("" if self._act else "  (not fired: print-only)"))
            self.events.put((db.utc_now(), fired, action, ok and self._act))
        recognizer.close()


def download() -> None:
    MODEL_PATH.parent.mkdir(exist_ok=True)
    print(f"downloading {MODEL_URL}")
    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
    print(f"saved {MODEL_PATH.stat().st_size / 1e6:.1f} MB to {MODEL_PATH}")


def main() -> None:
    if "--download" in sys.argv:
        return download()
    from Foundation import NSDate, NSRunLoop

    from camera import Camera, request_access

    request_access()
    cam = Camera(config.CAMERA_NAME)
    cam.start()
    watcher = GestureWatcher(cam, act="--act" in sys.argv, verbose=True)
    watcher.start()
    print(f"watching '{config.CAMERA_NAME}' for {', '.join(config.GESTURE_ACTIONS)}. Ctrl+C to stop.")
    try:
        while True:
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.5))
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop()
        cam.stop()


if __name__ == "__main__":
    main()
