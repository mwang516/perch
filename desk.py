import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor

from Foundation import NSDate, NSRunLoop

import config
import signals
from camera import Camera, list_cameras
from jev import Jev
from sampler import Sampler


def wait(seconds: float) -> None:
    # Pumping the main run loop lets AVFoundation and NSWorkspace refresh (camera list, frontmost app).
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(seconds))


def context(trigger: str, score: float, app: str | None, idle_s: float) -> str:
    return f"{time.strftime('%H:%M:%S')}  {trigger:12} score={score:5.1f}  app={app} idle={idle_s:.0f}s"


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


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    print(f"cameras visible: {list_cameras()}")
    print(f"looking for: '{config.CAMERA_NAME}'" + ("  (dry run, no Jev calls)" if dry_run else ""))
    cam = Camera(config.CAMERA_NAME)
    cam.start()
    sampler = Sampler()
    jev = None if dry_run else Jev()
    pool = ThreadPoolExecutor(max_workers=1)
    pending: Future | None = None
    pending_ctx = ""
    connected: bool | None = None
    try:
        while True:
            wait(config.TICK_S)
            if pending and pending.done():
                print_result(pending_ctx, pending.result())
                pending = None

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
            ctx = context(*hit, app, idle_s)
            if dry_run:
                print(f"{ctx}  (would send)")
                continue
            pending, pending_ctx = pool.submit(jev.ask, frame), ctx
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        cam.stop()


if __name__ == "__main__":
    main()
