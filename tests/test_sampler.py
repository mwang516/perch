import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

np = pytest.importorskip("numpy")
pytest.importorskip("cv2")

import config
from sampler import Sampler

FRAME = np.zeros((360, 640, 3), np.uint8)


def triggers(sampler, times, busy=False):
    return [(t, hit[0]) for t in times if (hit := sampler.check(FRAME, t, "Cursor", 1.0, busy))]


def test_quiet_desk_only_sends_heartbeats():
    s = Sampler()
    sent = triggers(s, [i * 0.5 for i in range(121)])
    assert sent == [(0.0, "heartbeat"), (25.0, "heartbeat"), (50.0, "heartbeat")]


def test_failed_send_is_followed_by_a_fresh_frame():
    s = Sampler()
    assert triggers(s, [0.0]) == [(0.0, "heartbeat")]
    s.failed()
    sent = triggers(s, [i * 0.5 for i in range(1, 61)])
    assert sent == [(config.FAST_INTERVAL_S, "retry"), (config.FAST_INTERVAL_S + config.HEARTBEAT_S, "heartbeat")]


def test_retry_waits_while_a_request_is_in_flight():
    s = Sampler()
    triggers(s, [0.0])
    s.failed()
    assert triggers(s, [3.0], busy=True) == []
    assert triggers(s, [3.5]) == [(3.5, "retry")]
