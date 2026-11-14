import signal
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor

import cv2
import numpy as np
from Foundation import NSDate, NSRunLoop

import config
import db
import signals
from camera import Camera, authorized, list_cameras, request_access
from jev import Jev
from lifecycle import LiveMode, SessionTracker, TokenBudget
from sampler import Sampler


def wait(seconds: float) -> None:
    # Pumping the main run loop lets AVFoundation and NSWorkspace refresh (camera list, frontmost app).
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(seconds))


def context(obs: dict) -> str:
    app = obs["app"] + (f" ({obs['domain']})" if obs["domain"] else "") if obs["app"] else None
    return f"{time.strftime('%H:%M:%S')}  {obs['trigger']:12} score={obs['score']:5.1f}  app={app} idle={obs['idle_s']:.0f}s"


def print_result(ctx: str, r: dict, mode: str | None = None) -> None:
    if not r["ok"]:
        print(f"{ctx}  ERROR {r['error']}")
        return
    n = r["nouls"]
    print(
        f"{ctx}  [{mode or '?':8}] activity={r['activity']} ({r['confidence']:.2f})  "
        f"person={n['person_present']:.2f} tablet={n['tablet_gaming']:.2f} ctrl={n['controllers_out']:.2f} cam={n['camera_ok']:.2f}  "
        f"{r['latency_ms']:.0f}ms {r['tokens']}tok"
    )


def save_thumbnail(frame: np.ndarray, ts: str) -> str:
    config.THUMBS_DIR.mkdir(exist_ok=True)
    path = config.THUMBS_DIR / f"{ts[:23].replace(':', '-')}.jpg"
    small = cv2.resize(frame, config.THUMB_SIZE, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), small, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return str(path.relative_to(config.BASE_DIR))


class Agent:
    """The collector. `tick()` is called about twice a second, from the terminal loop below or from the
    menu bar app's timer. It must run on the main thread, whose run loop keeps AVFoundation and
    NSWorkspace fresh (camera list, frontmost app)."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        print(f"cameras visible: {list_cameras()}")
        print(f"looking for: '{config.CAMERA_NAME}'" + ("  (dry run, no Jev calls)" if dry_run else ""))
        request_access()
        self.cam = Camera(config.CAMERA_NAME)
        self.cam.start()
        self.sampler = Sampler()
        self.jev = None if dry_run else Jev()
        self.conn = None if dry_run else db.connect()
        self.sessions = SessionTracker(self.conn) if self.conn else None
        self.budget = TokenBudget(self.conn) if self.conn else None
        self.live_mode = LiveMode()
        self.budget_level = "ok"
        if self.conn:
            print(f"pruned {db.prune_thumbnails(self.conn)} old thumbnails")
        self.last_prune = time.monotonic()
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.pending: Future | None = None
        self.pending_obs: dict = {}
        self.connected: bool | None = None
        self.paused = False
        self.gestures = None
        self._start_gestures()

    def _start_gestures(self) -> None:
        if not config.GESTURES_ENABLED or self.dry_run:
            return
        try:
            from gestures import GestureWatcher

            self.gestures = GestureWatcher(self.cam)
            self.gestures.start()
            print(f"gestures on: {config.GESTURE_ACTIONS}")
        except Exception as e:
            # Gestures are an extra: a missing model or package must not stop the collector.
            self.gestures = None
            print(f"gestures off: {type(e).__name__}: {e}")

    @property
    def status(self) -> str:
        """One line for the menu bar."""
        if self.paused:
            return "Paused"
        if not authorized():
            return "Camera access not allowed"
        if not self.connected:
            return f"Waiting for {config.CAMERA_NAME}"
        mode = self.live_mode.state.mode
        return f"Tracking: {mode}" if mode else "Tracking"

    def pause(self) -> None:
        """Stops tracking and releases the camera. The session ends, so paused time is untracked."""
        if self.paused:
            return
        self.paused = True
        if self.sessions:
            self.sessions.close("paused")
        if self.gestures:
            self.gestures.stop()
            self.gestures = None
        self.cam.stop()
        self.connected = None
        print("paused")

    def resume(self) -> None:
        if not self.paused:
            return
        self.paused = False
        self.sampler = Sampler()
        self.cam = Camera(config.CAMERA_NAME)
        self.cam.start()
        self._start_gestures()
        print("resumed")

    def _finish_pending(self) -> None:
        try:
            result = self.pending.result()
        except Exception as e:
            # Anything unexpected from the Jev call is one failed observation, not a dead agent.
            result = {"ok": False, "error": f"{type(e).__name__}: {e}", "latency_ms": None}
        obs, self.pending = self.pending_obs, None
        print_result(context(obs), result, self.live_mode.update(obs, result))
        self.budget.add(result.get("tokens"))
        if self.budget.level() != self.budget_level:
            self.budget_level = self.budget.level()
            print(f"token budget: {self.budget.used:,} of {config.DAILY_TOKEN_BUDGET:,} used today, "
                  f"sampling is now '{self.budget_level}'")
        frame = obs.pop("frame")
        # The session has ended meanwhile if tracking was paused or the camera vanished mid-request.
        if self.sessions.session_id is not None:
            obs["thumb_path"] = save_thumbnail(frame, obs["ts"])
            db.add_observation(self.conn, self.sessions.session_id, obs, result)
        # One fresh frame after a failure, but no chain of retries while Jev is down.
        if not result["ok"] and obs["trigger"] != "retry":
            self.sampler.failed()

    def tick(self) -> None:
        if self.pending and self.pending.done():
            self._finish_pending()
        if self.conn and time.monotonic() - self.last_prune > config.PRUNE_INTERVAL_S:
            db.prune_thumbnails(self.conn)
            self.last_prune = time.monotonic()
        while self.gestures and not self.gestures.events.empty():
            db.add_gesture(self.conn, *self.gestures.events.get())
        if self.paused:
            return

        frame, _ = self.cam.latest()
        live = self.cam.connected and frame is not None
        if live != self.connected:
            self.connected = live
            print("camera connected" if live else f"waiting for '{config.CAMERA_NAME}'... visible: {list_cameras()}")
        if self.sessions:
            change = self.sessions.update(live, time.monotonic())
            if change == "started":
                self.live_mode.reset()
                print(f"session {self.sessions.session_id} started")
            elif change == "ended":
                print(f"session ended: camera gone for over {config.CAMERA_LOST_S} s; waiting for it to return")
        if not live:
            return

        app, idle_s = signals.frontmost_app(), signals.idle_seconds()
        hit = self.sampler.check(frame, time.monotonic(), app, idle_s, busy=self.pending is not None,
                                 away=self.live_mode.away, budget=self.budget.level() if self.budget else "ok")
        if hit is None:
            return
        trigger, score = hit
        obs = {
            "ts": db.utc_now(),
            "trigger": trigger,
            "score": score,
            "app": app,
            "domain": signals.chrome_domain() if app == config.CHROME_APP else None,
            "idle_s": idle_s,
        }
        if self.dry_run:
            print(f"{context(obs)}  (would send)")
            return
        self.pending, self.pending_obs = self.pool.submit(self.jev.ask, frame), {**obs, "frame": frame}

    def close(self, reason: str) -> None:
        """An unexpected error still closes the session (reason "error"), so only a hard kill looks like a crash."""
        if self.sessions:
            self.sessions.close(reason)
        self.pool.shutdown(wait=False, cancel_futures=True)
        if self.gestures:
            self.gestures.stop()
        self.cam.stop()


class Stop(Exception):
    pass


def _stop(signum, _frame) -> None:
    raise Stop(signal.Signals(signum).name)


def main() -> None:
    # Closing the terminal window (SIGHUP) or a kill (SIGTERM) should end the session as cleanly as Ctrl+C.
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGHUP, _stop)
    agent = Agent(dry_run="--dry-run" in sys.argv)
    end_reason = "error"
    try:
        while True:
            wait(config.TICK_S)
            agent.tick()
    except (KeyboardInterrupt, Stop) as e:
        end_reason = "quit"
        print(f"\nstopping ({type(e).__name__ if isinstance(e, KeyboardInterrupt) else e})")
    finally:
        agent.close(end_reason)


if __name__ == "__main__":
    main()
