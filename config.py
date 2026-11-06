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

# EXPERIMENT: no monitor mask. The change score uses the whole frame, so screen content can trigger motion.
MOTION_THRESHOLD = 8.0
CHANGE_THUMB_SIZE = (64, 48)
