import os
from pathlib import Path

BASE_DIR = Path(__file__).parent
# PERCH_DB points the agent and the API at another database (tests, experiments).
DB_PATH = Path(os.environ.get("PERCH_DB") or BASE_DIR / "perch.db")
THUMBS_DIR = BASE_DIR / "thumbnails"
THUMB_SIZE = (640, 360)
# Long enough to build the labeling UI and label frames; labeled thumbnails are kept regardless.
THUMB_RETENTION_DAYS = 30
PRUNE_INTERVAL_S = 3600

CHROME_APP = "Google Chrome"

# The spare iPhone, named "Perch" so the main phone ("Matt Camera") is never opened by mistake.
CAMERA_NAME = "Perch Camera"
CAMERA_RETRY_S = 3
CAMERA_STALL_S = 5
# The camera gone for longer than this (awake time) ends the session; shorter dropouts stay inside it.
CAMERA_LOST_S = 120

TICK_S = 0.5
HEARTBEAT_S = 25
FAST_INTERVAL_S = 2.5
FAST_WINDOW_S = 30
IDLE_THRESHOLD_S = 60
# Flipping between apps would otherwise send a frame per switch (13 of the first 22 real observations).
# A switch inside this window still gets its frame, once the window has passed.
APP_CHANGE_MIN_S = 2.5
# While the live mode is away, an empty desk needs fewer heartbeats. Motion still triggers at full speed.
AWAY_HEARTBEAT_S = 45

# Daily cap on Jev input tokens (local day). 48M tokens is about $2 at $0.042 per million.
# Past BUDGET_SLOW_AT of the cap the sampler slows down; past the cap it sends heartbeats only.
DAILY_TOKEN_BUDGET = 48_000_000
BUDGET_SLOW_AT = 0.8
BUDGET_SLOW_FACTOR = 3  # fast interval and heartbeat are multiplied by this when slowing
OVER_BUDGET_HEARTBEAT_S = 120

# A normal answer takes ~150 ms. A hung request blocks every other send, so give up early.
JEV_TIMEOUT_S = 3

# EXPERIMENT: no monitor mask. The change score uses the whole frame, so screen content can trigger motion.
MOTION_THRESHOLD = 8.0
CHANGE_THUMB_SIZE = (64, 48)

# Synthetic data for building the engine and dashboard before real logs exist (see fake.py).
FAKE_DB_PATH = BASE_DIR / "fake.db"

# App → meaning map for the mode engine. Trusted only while the Mac has recent input.
GAME_APPS = {"osu!", "VMware Fusion"}
CODING_APPS = {"Cursor", "Terminal", "iTerm2"}
CODING_DOMAINS = {"leetcode.com", "github.com"}

# Where the menu bar app serves the dashboard (the built copy in dashboard/dist).
DASHBOARD_PORT = 8765
