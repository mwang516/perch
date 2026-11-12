"""Writes synthetic days into fake.db using the real schema, so the engine and dashboard can be built
before real logs exist. Every observation gets a ground-truth label.

    python fake.py [--days 7] [--seed 1]

The numbers here (noise, error rate, how often things happen) are guesses. Nothing tuned against this
data says anything about real accuracy.
"""

import argparse
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import config
import db

CHROME = config.CHROME_APP
TICK_S = config.TICK_S


@dataclass(frozen=True)
class Act:
    truth: str | None  # ground-truth mode; None keeps the previous one (a brief bend out of frame)
    activity: str  # what Jev's activity question should answer
    minutes: tuple[float, float]
    apps: tuple = ()  # (app, chrome domain) choices; empty keeps whatever was frontmost
    switches_per_min: float = 0.0
    input_every_s: float | None = None  # mean pause between inputs; None means the Mac isn't touched
    motion_per_min: float = 0.5
    person: bool = True
    tablet: bool = False
    controllers: bool = False


ACTS = {
    "coding": Act("computer", "computer", (20, 90), (("Cursor", None), ("Cursor", None), ("Cursor", None), ("Terminal", None),
              (CHROME, "github.com"), (CHROME, "leetcode.com"), (CHROME, "stackoverflow.com")), 1.5, 4),
    "browsing": Act("computer", "computer", (5, 30), ((CHROME, "youtube.com"), (CHROME, "reddit.com"), ("Discord", None),
                ("Claude", None), (CHROME, "mail.google.com")), 1.0, 12, 1.0),
    # Watching a video: person present, Mac idle for minutes, and the screen keeps tripping motion (no monitor mask).
    "video": Act("computer", "computer", (10, 40), ((CHROME, "youtube.com"),), 0.05, 240, 3.0),
    # iPad rhythm game: the Mac sits idle with whatever was frontmost.
    "ipad": Act("gaming", "gaming", (15, 45), motion_per_min=4.0, tablet=True),
    "osu": Act("gaming", "computer", (10, 30), (("osu!", None),), 0.0, 1, 2.0),
    "controller": Act("gaming", "gaming", (10, 30), (("VMware Fusion", None),), 0.0, 2, 2.0, controllers=True),
    "other": Act("other", "other", (3, 15), motion_per_min=1.0),
    "away": Act("away", "nobody", (2, 25), motion_per_min=0.1, person=False),
    "bend": Act(None, "nobody", (0.15, 0.35), motion_per_min=0.0, person=False),
}
WEIGHTS = {"coding": 5, "browsing": 3, "video": 2, "ipad": 2, "osu": 1, "controller": 1, "other": 1.5, "away": 3}


def clip(x: float) -> float:
    return min(0.999, max(0.001, x))


def jev_answers(act: Act, rng: random.Random) -> dict:
    def noul(yes: bool, hi: float = 0.96, lo: float = 0.03) -> float:
        if rng.random() < 0.02:  # a confidently wrong frame
            yes = not yes
        return clip(rng.gauss(hi if yes else lo, 0.04))

    tablet = noul(act.tablet, hi=0.88)
    if act.tablet and rng.random() < 0.15:  # iPad partly hidden by his body
        tablet = rng.uniform(0.3, 0.7)

    labels = ["computer", "gaming", "other", "nobody"]
    main, mass = act.activity, clip(rng.gauss(0.9, 0.07))
    if rng.random() < 0.03:
        main, mass = rng.choice([x for x in labels if x != act.activity]), rng.uniform(0.45, 0.7)
    rest = [rng.random() for _ in range(3)]
    others = iter((1 - mass) * r / sum(rest) for r in rest)
    probs = {x: mass if x == main else next(others) for x in labels}
    choice = max(probs, key=probs.get)
    return {
        "nouls": {
            "person_present": noul(act.person),
            "tablet_gaming": tablet,
            "controllers_out": noul(act.controllers),
            "camera_ok": 0.1 if rng.random() < 0.002 else clip(rng.gauss(0.97, 0.02)),
        },
        "activity": choice,
        "confidence": probs[choice],
        "probabilities": probs,
    }


def jev_result(act: Act, rng: random.Random) -> dict:
    if rng.random() < 0.03:  # the ~3% connection errors seen in the accuracy test
        return {"ok": False, "error": "APIConnectionError: [SSL: UNEXPECTED_EOF_WHILE_READING]", "latency_ms": rng.uniform(300, 3000)}
    return {"ok": True, "latency_ms": rng.lognormvariate(math.log(150), 0.25), "tokens": 4400 + rng.randint(-15, 15),
            "model": "jev-1.14.0", **jev_answers(act, rng)}


def plan_session(rng: random.Random, minutes: float) -> list[tuple[Act, float]]:
    """A list of (activity, seconds) filling roughly `minutes`."""
    plan, left, prev = [], minutes * 60, None
    while left > 0:
        name = rng.choices(list(WEIGHTS), list(WEIGHTS.values()))[0]
        if name == prev:
            continue
        prev, act = name, ACTS[name]
        seconds = min(left, rng.uniform(*act.minutes) * 60)
        if act.truth == "computer" and seconds > 600 and rng.random() < 0.4:
            # Bending down to grab something mid-task must not count as away.
            cut = rng.uniform(0.3, 0.7) * seconds
            plan += [(act, cut), (ACTS["bend"], rng.uniform(*ACTS["bend"].minutes) * 60), (act, seconds - cut)]
        else:
            plan.append((act, seconds))
        left -= seconds
    return plan


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds")


def run_session(conn, rng: random.Random, start: float, plan: list[tuple[Act, float]],
                sleep: tuple[float, float] | None, crash: bool) -> int:
    """Simulates the sampler tick by tick. `sleep` is (offset, seconds) with the lid closed: no observations."""
    session_id = conn.execute("INSERT INTO sessions (started_at) VALUES (?)", (iso(start),)).lastrowid
    t, count = start, 0
    app, domain = "Cursor", None
    last_input, was_idle = t, False
    last_send, fast_until = -math.inf, -math.inf
    truth = "computer"

    for act, seconds in plan:
        truth = act.truth or truth
        end = t + seconds
        motion = True  # the scene changes when the activity does
        if act.apps and (app, domain) not in act.apps:
            app, domain, app_changed = *rng.choice(act.apps), True
        else:
            app_changed = False
        while t < end:
            if sleep and start + sleep[0] <= t < start + sleep[0] + sleep[1]:
                t = start + sleep[0] + sleep[1]
                last_send, fast_until, last_input, was_idle = -math.inf, -math.inf, t - 5, False
                continue
            if act.input_every_s and rng.random() < TICK_S / act.input_every_s:
                last_input = t
            if act.apps and rng.random() < act.switches_per_min * TICK_S / 60:
                new = rng.choice(act.apps)
                app_changed = app_changed or new[0] != app
                app, domain = new
            motion = motion or rng.random() < act.motion_per_min * TICK_S / 60
            idle_s = t - last_input
            idle = idle_s >= config.IDLE_THRESHOLD_S
            since = t - last_send

            # Same order as Sampler.check.
            trigger = None
            if app_changed:
                trigger = "app_change"
            elif idle and not was_idle:
                trigger = "idle_crossed"
            elif motion and since >= config.FAST_INTERVAL_S:
                trigger = "motion"
            elif t < fast_until and since >= config.FAST_INTERVAL_S:
                trigger = "fast"
            elif since >= config.HEARTBEAT_S:
                trigger = "heartbeat"
            was_idle, app_changed = idle, False

            if trigger:
                score = rng.uniform(9, 35) if trigger == "motion" else rng.uniform(0.5, 7)
                if trigger == "motion":
                    fast_until, motion = t + config.FAST_WINDOW_S, False
                last_send = t
                obs = {"ts": iso(t), "trigger": trigger, "score": score, "app": app,
                       "domain": domain if app == CHROME else None, "idle_s": idle_s, "thumb_path": None}
                obs_id = db.add_observation(conn, session_id, obs, jev_result(act, rng), commit=False)
                conn.execute("INSERT INTO labels (observation_id, mode, labeled_at) VALUES (?, ?, ?)", (obs_id, truth, iso(t)))
                count += 1
            t += TICK_S

    if not crash:
        conn.execute("UPDATE sessions SET ended_at = ?, end_reason = 'quit' WHERE id = ?", (iso(t), session_id))
    conn.commit()
    return count


def generate(days: int, seed: int, path=config.FAKE_DB_PATH, now: datetime | None = None) -> int:
    rng = random.Random(seed)
    path.unlink(missing_ok=True)
    conn = db.connect(path)
    now = now or datetime.now().astimezone()
    total = 0
    for back in range(days - 1, -1, -1):
        day = (now - timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)
        # A morning-to-afternoon session most days, an evening one most days.
        blocks = []
        if rng.random() < 0.85:
            blocks.append((rng.uniform(9, 11), rng.uniform(150, 330)))
        if rng.random() < 0.8:
            blocks.append((rng.uniform(18.5, 20.5), rng.uniform(90, 210)))
        for hour, minutes in blocks:
            start = day + timedelta(hours=hour)
            if start >= now:
                continue
            minutes = min(minutes, (now - start).total_seconds() / 60 - 1)
            if minutes < 10:
                continue
            sleep = (rng.uniform(0.3, 0.6) * minutes * 60, rng.uniform(20, 50) * 60) if rng.random() < 0.3 else None
            if sleep and start.timestamp() + minutes * 60 + sleep[1] > now.timestamp():
                sleep = None
            total += run_session(conn, rng, start.timestamp(), plan_session(rng, minutes), sleep, crash=rng.random() < 0.1)
    conn.close()
    return total


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    print(f"wrote {generate(args.days, args.seed)} observations to {config.FAKE_DB_PATH.name}")
