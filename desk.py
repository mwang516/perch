import time

from Foundation import NSDate, NSRunLoop

import config
from camera import Camera, list_cameras


def main() -> None:
    print(f"cameras visible: {list_cameras()}")
    print(f"looking for: '{config.CAMERA_NAME}'")
    cam = Camera(config.CAMERA_NAME)
    cam.start()
    try:
        while True:
            # Pumping the main run loop lets AVFoundation refresh its device list.
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(config.STATUS_INTERVAL_S))
            frame, frame_time = cam.latest()
            if not cam.connected or frame is None:
                print(f"waiting for '{config.CAMERA_NAME}'... visible: {list_cameras()}")
                continue
            h, w = frame.shape[:2]
            age = time.monotonic() - frame_time
            print(f"connected  {w}x{h}  latest frame {age:.1f}s old  brightness {frame.mean():.0f}")
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        cam.stop()


if __name__ == "__main__":
    main()
