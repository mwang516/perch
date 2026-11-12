import time
from pathlib import Path

import config
import cv2
import numpy as np
from dotenv import load_dotenv
from PIL import Image as PILImage
from typesafe_sdk import (
    Image,
    RetryPolicy,
    TypeSafeAPIConnectionError,
    TypeSafeAPITimeoutError,
    TypeSafeClient,
    TypeSafeError,
)

from questions import HEADERS, MODEL, NOULS, QUESTIONS, prep


class Jev:
    def __init__(self):
        load_dotenv(Path(__file__).parent / ".env")
        self._client = TypeSafeClient(retry=RetryPolicy(max_retries=0), timeout=config.JEV_TIMEOUT_S)

    def ask(self, frame: np.ndarray) -> dict:
        data = prep(PILImage.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))
        start = time.perf_counter()
        for attempt in (1, 2):
            try:
                result = self._client.system_one(
                    state={"desk": Image(data)}, questions=QUESTIONS, model=MODEL, extra_headers=HEADERS
                )
                break
            except TypeSafeError as e:
                error = f"{type(e).__name__}: {e}"
                # A dropped connection fails fast, so one instant retry still answers about a fresh frame.
                # Timeouts and rate limits don't: by then the frame is stale, so they fail the observation.
                dropped = isinstance(e, TypeSafeAPIConnectionError) and not isinstance(e, TypeSafeAPITimeoutError)
                if dropped and attempt == 1:
                    print(f"  retrying after {error}")
                    continue
                return {"ok": False, "error": error, "latency_ms": (time.perf_counter() - start) * 1000}
        activity = result.choices["activity"]
        return {
            "ok": True,
            "latency_ms": (time.perf_counter() - start) * 1000,
            "tokens": result.usage.input_tokens,
            "model": result.model,
            "activity": activity.choice,
            "confidence": activity.confidence,
            "probabilities": dict(activity.probabilities),
            "nouls": {q: result.nouls[q].noul for q in NOULS},
        }
