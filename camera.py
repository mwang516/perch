import threading
import time

import AVFoundation as AV
import cv2
import numpy as np

import config


def _normalize(name: str) -> str:
    return " ".join(name.split())


def list_cameras() -> list[str]:
    # Same list and order OpenCV's AVFoundation backend indexes into: video + muxed devices, sorted by uniqueID.
    devices = list(AV.AVCaptureDevice.devicesWithMediaType_(AV.AVMediaTypeVideo)) + list(
        AV.AVCaptureDevice.devicesWithMediaType_(AV.AVMediaTypeMuxed)
    )
    devices.sort(key=lambda d: d.uniqueID())
    return [_normalize(d.localizedName()) for d in devices]


def find_index(name: str) -> int | None:
    names = list_cameras()
    target = _normalize(name)
    return names.index(target) if target in names else None


class Camera:
    def __init__(self, name: str):
        self.name = name
        self.connected = False
        self._lock = threading.Lock()
        self._frame: np.ndarray | None = None
        self._frame_time = 0.0
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=config.CAMERA_STALL_S + 1)

    def latest(self) -> tuple[np.ndarray | None, float]:
        with self._lock:
            return self._frame, self._frame_time

    def _run(self) -> None:
        while self._running:
            index = find_index(self.name)
            if index is None:
                time.sleep(config.CAMERA_RETRY_S)
                continue
            cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
            if not cap.isOpened():
                cap.release()
                time.sleep(config.CAMERA_RETRY_S)
                continue

            last_read = time.monotonic()
            while self._running:
                ok, frame = cap.read()
                now = time.monotonic()
                if not ok:
                    if now - last_read > config.CAMERA_STALL_S:
                        break
                    time.sleep(0.05)
                    continue
                last_read = now
                # Continuity Camera keeps sending the same frame while paused (phone unlocked).
                if self._frame is None or not np.array_equal(frame, self._frame):
                    with self._lock:
                        self._frame, self._frame_time = frame, now
                self.connected = now - self._frame_time <= config.CAMERA_STALL_S
            cap.release()
            self.connected = False
