import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor

import cv2
import numpy as np
from Foundation import NSDate, NSRunLoop

import config
import db
import signals
from camera import Camera, list_cameras
from jev import Jev
from sampler import Sampler


def wait(seconds: float) -> None:
    # Pumping the main run loop lets AVFoundation and NSWorkspace refresh (camera list, frontmost app).
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(seconds))


def context(obs: dict) -> str:
    app = obs["app"] + (f" ({obs['domain']})" if obs["domain"] else "") if obs["app"] else None
    return f"{time.strftime('%H:%M:%S')}  {obs['trigger']:12} score={obs['score']:5.1f}  app={app} idle={obs['idle_s']:.0f}s"


def print_result(ctx: str, r: dict) -> None:
    if not r["ok"]:
        print(f"{ctx}  ERROR {r['error']}")
        return
    n = r["nouls"]
    print(
        f"{ctx}  activity={r['activity']} ({r['confidence']:.2f})  "
        f"person={n['person_present']:.2f} tablet={n['tablet_gaming']:.2f} ctrl={n['controllers_out']:.2f} cam={n['camera_ok']:.2f}  "
        f"{r['latency_ms']:.0f}ms {r['tokens']}tok"
    )


def save_thumbnail(frame: np.ndarray, ts: str) -> str:
    config.THUMBS_DIR.mkdir(exist_ok=True)
    path = config.THUMBS_DIR / f"{ts[:23].replace(':', '-')}.jpg"
    small = cv2.resize(frame, config.THUMB_SIZE, interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(path), small, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return str(path.relative_to(config.BASE_DIR))


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    print(f"cameras visible: {list_cameras()}")
    print(f"looking for: '{config.CAMERA_NAME}'" + ("  (dry run, no Jev calls)" if dry_run else ""))
    cam = Camera(config.CAMERA_NAME)
    cam.start()
    sampler = Sampler()
    jev = None if dry_run else Jev()
    conn = None if dry_run else db.connect()
    session_id = None
    if conn:
        session_id = db.start_session(conn)
        print(f"session {session_id}, pruned {db.prune_thumbnails(conn)} old thumbnails")
    last_prune = time.monotonic()
    pool = ThreadPoolExecutor(max_workers=1)
    pending: Future | None = None
    pending_obs: dict = {}
    connected: bool | None = None
    try:
        while True:
            wait(config.TICK_S)
            if pending and pending.done():
                result = pending.result()
                print_result(context(pending_obs), result)
                pending_obs["thumb_path"] = save_thumbnail(pending_obs.pop("frame"), pending_obs["ts"])
                db.add_observation(conn, session_id, pending_obs, result)
                # One fresh frame after a failure, but no chain of retries while Jev is down.
                if not result["ok"] and pending_obs["trigger"] != "retry":
                    sampler.failed()
                pending = None
            if conn and time.monotonic() - last_prune > config.PRUNE_INTERVAL_S:
                db.prune_thumbnails(conn)
                last_prune = time.monotonic()

            frame, _ = cam.latest()
            live = cam.connected and frame is not None
            if live != connected:
                connected = live
                print("camera connected" if live else f"waiting for '{config.CAMERA_NAME}'... visible: {list_cameras()}")
            if not live:
                continue

            app, idle_s = signals.frontmost_app(), signals.idle_seconds()
            hit = sampler.check(frame, time.monotonic(), app, idle_s, busy=pending is not None)
            if hit is None:
                continue
            trigger, score = hit
            obs = {
                "ts": db.utc_now(),
                "trigger": trigger,
                "score": score,
                "app": app,
                "domain": signals.chrome_domain() if app == config.CHROME_APP else None,
                "idle_s": idle_s,
            }
            if dry_run:
                print(f"{context(obs)}  (would send)")
                continue
            pending, pending_obs = pool.submit(jev.ask, frame), {**obs, "frame": frame}
    except KeyboardInterrupt:
        if conn:
            db.end_session(conn, session_id, "quit")
        print("\nstopping")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        cam.stop()


if __name__ == "__main__":
    main()
