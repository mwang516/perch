from pathlib import Path

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "perch.db"
THUMBS_DIR = BASE_DIR / "thumbnails"
THUMB_SIZE = (640, 360)
THUMB_RETENTION_DAYS = 7
PRUNE_INTERVAL_S = 3600

CHROME_APP = "Google Chrome"

CAMERA_NAME = "Matt Camera"
CAMERA_RETRY_S = 3
CAMERA_STALL_S = 5

TICK_S = 0.5
HEARTBEAT_S = 25
FAST_INTERVAL_S = 2.5
FAST_WINDOW_S = 30
IDLE_THRESHOLD_S = 60

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
