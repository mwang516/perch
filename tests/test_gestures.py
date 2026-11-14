import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
import gestures
from gestures import GestureTrigger


def fires(trigger, frames):
    return [(t, g) for t, name, score in frames if (g := trigger.feed(name, score, t))]


def test_a_held_gesture_fires_once():
    t = GestureTrigger(hold_s=0.5, cooldown_s=2.0, min_score=0.6)
    frames = [(i * 0.125, "Victory", 0.9) for i in range(40)]
    assert fires(t, frames) == [(0.5, "Victory")]


def test_a_brief_flash_does_not_fire():
    t = GestureTrigger(0.5, 2.0, 0.6)
    assert fires(t, [(0.0, "Victory", 0.9), (0.125, "Victory", 0.9), (0.25, None, 0.0), (0.375, "Victory", 0.9)]) == []


def test_low_confidence_is_ignored():
    t = GestureTrigger(0.5, 2.0, 0.6)
    assert fires(t, [(i * 0.125, "Victory", 0.4) for i in range(20)]) == []


def test_refires_only_after_release_and_cooldown():
    t = GestureTrigger(0.5, 2.0, 0.6)
    hold = lambda start: [(start + i * 0.125, "Victory", 0.9) for i in range(8)]
    # Released and shown again 1 s later: still inside the cooldown.
    assert fires(t, hold(0.0) + [(1.0, None, 0.0)] + hold(1.125)) == [(0.5, "Victory")]
    # Shown again after the cooldown.
    assert fires(t, [(3.0, None, 0.0)] + hold(3.125)) == [(3.625, "Victory")]


def test_config_mapping_is_valid(monkeypatch):
    gestures.validate()
    monkeypatch.setattr(config, "GESTURE_ACTIONS", {"Wave": "play_pause"})
    with pytest.raises(ValueError):
        gestures.validate()
    monkeypatch.setattr(config, "GESTURE_ACTIONS", {"Victory": "launch_rocket"})
    with pytest.raises(ValueError):
        gestures.validate()
