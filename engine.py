"""Mode engine: fuses one observation (Jev answers + Mac signals) into a mode, then smooths and switches.

Pure: no I/O and no clock. `step(state, obs, params) -> (new_state, events)` can be replayed over logged
observations, which is how the thresholds get tuned (see replay.py).

An observation is a dict:
    t        seconds (epoch) the frame was sent
    ok       False when the Jev call failed
    nouls    {"person_present", "tablet_gaming", "controllers_out", "camera_ok"} -> probability (when ok)
    activity {"computer", "gaming", "other", "nobody"} -> probability (when ok)
    app      frontmost app name or None
    domain   Chrome domain or None
    idle_s   seconds since the last keyboard or mouse input
"""

import math
from dataclasses import dataclass, field

import config

MODES = ("computer", "gaming", "other", "away", "unknown")


@dataclass(frozen=True)
class Params:
    """All numbers are starting points, to be tuned by replaying real logs."""

    # Smoothing time constant. Must stay above ~1.1x the heartbeat (25 s), or one odd heartbeat frame can flip the mode.
    tau_s: float = 30.0
    switch_score: float = 0.6  # a mode needs at least this smoothed score to take over
    switch_lead: float = 0.15  # ...and must lead the current mode by this much
    min_dwell_s: float = 30.0  # ...and the current mode must have lasted this long
    recent_input_s: float = 5.0  # input this recent means he's certainly at the Mac
    active_input_s: float = 60.0  # the frontmost app is trusted only with input this recent
    away_idle_s: float = 60.0  # away needs an empty chair AND the Mac idle this long
    person_cutoff: float = 0.5
    tablet_cutoff: float = 0.5
    controllers_cutoff: float = 0.5
    camera_cutoff: float = 0.5
    reset_gap_s: float = 120.0  # a longer gap between observations resets the smoothed scores
    stale_s: float = 90.0  # this long with no usable evidence (failed Jev calls) means unknown


@dataclass(frozen=True)
class State:
    mode: str | None = None
    coding: bool = False
    since: float = 0.0
    scores: dict = field(default_factory=dict)
    last_t: float | None = None  # time of the last observation that carried evidence


@dataclass(frozen=True)
class Fused:
    scores: dict  # mode -> weight, sums to 1; empty means no evidence
    coding: bool | None  # None when the Mac signals have no opinion
    rule: str  # which rule decided, for debugging and the ablation


def is_coding(obs: dict) -> bool:
    return obs["app"] in config.CODING_APPS or (
        obs["app"] == config.CHROME_APP and obs["domain"] in config.CODING_DOMAINS
    )


def os_mode(obs: dict) -> str:
    return "gaming" if obs["app"] in config.GAME_APPS else "computer"


def camera_mode(obs: dict) -> str | None:
    """What the camera alone says, for the camera-only vs fused comparison."""
    if not obs["ok"]:
        return None
    choice = max(obs["activity"], key=obs["activity"].get)
    return "away" if choice == "nobody" else choice


def fuse(obs: dict, p: Params = Params()) -> Fused:
    if not obs["ok"]:
        # No camera answer. Recent input still says he's at the Mac; otherwise this frame is no evidence.
        if obs["idle_s"] < p.active_input_s:
            mode = os_mode(obs)
            return Fused({mode: 1.0}, is_coding(obs) if mode == "computer" else None, "os_only")
        return Fused({}, None, "jev_error")
    n = obs["nouls"]
    if n["camera_ok"] < p.camera_cutoff:
        return Fused({"unknown": 1.0}, None, "camera_bad")

    idle = obs["idle_s"]
    present = n["person_present"] >= p.person_cutoff
    # Away needs the camera; idle time only confirms it.
    if not present and idle >= p.away_idle_s:
        return Fused({"away": 1.0}, None, "away")
    # Tablet or controller gaming overrides the Mac: Chrome or Cursor may sit frontmost on an idle Mac.
    if present and n["tablet_gaming"] >= p.tablet_cutoff:
        return Fused({"gaming": 1.0}, None, "tablet")
    if present and n["controllers_out"] >= p.controllers_cutoff:
        return Fused({"gaming": 1.0}, None, "controllers")
    if idle < p.active_input_s:
        mode = os_mode(obs)
        return Fused({mode: 1.0}, is_coding(obs) if mode == "computer" else None, "os")

    # Idle Mac, someone in the chair: the camera decides. "nobody" can't mean away here, so it counts as other.
    a = obs["activity"]
    scores = {"computer": a["computer"], "gaming": a["gaming"], "other": a["other"] + a["nobody"]}
    return Fused(scores, None, "camera")


def step(state: State, obs: dict, p: Params = Params()) -> tuple[State, list[dict]]:
    t = obs["t"]
    f = fuse(obs, p)
    gap = None if state.last_t is None else t - state.last_t
    if not f.scores:
        if gap is not None and gap <= p.stale_s:
            return state, []  # a failed call is absorbed; the next good frame smooths over the whole gap
        f = Fused({"unknown": 1.0}, None, f.rule)

    if gap is None or gap < 0 or gap > p.reset_gap_s:
        scores = {m: f.scores.get(m, 0.0) for m in MODES}
    else:
        # Time-weighted EMA: exp(-gap/tau) of the old score survives, so two 10 s gaps equal one 20 s gap.
        alpha = 1 - math.exp(-gap / p.tau_s)
        scores = {m: s + alpha * (f.scores.get(m, 0.0) - s) for m, s in state.scores.items()}

    mode, since, coding = state.mode, state.since, state.coding
    if mode == "away" and obs["idle_s"] < p.recent_input_s:
        # Leaving away is instant on any input, even if this frame's Jev call failed.
        mode, since = os_mode(obs), t
        scores = {m: 1.0 if m == mode else 0.0 for m in MODES}
    else:
        top = max(MODES, key=scores.get)
        if mode is None:
            mode, since = top, t
        elif (
            top != mode
            and scores[top] >= p.switch_score
            and scores[top] - scores[mode] >= p.switch_lead
            # Coming back from away shouldn't wait out the dwell; entering away is already slowed by away_idle_s.
            and (t - since >= p.min_dwell_s or mode == "away")
        ):
            mode, since = top, t

    if mode != "computer":
        coding = False
    elif obs["idle_s"] < p.active_input_s:
        coding = is_coding(obs)
    elif state.mode != "computer":
        coding = False

    events = []
    if mode != state.mode or coding != state.coding:
        events.append({"t": t, "mode": mode, "coding": coding})
    return State(mode, coding, since, scores, t), events
