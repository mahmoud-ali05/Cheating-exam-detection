"""Central configuration - tweak thresholds here, no other file needs editing."""
from pathlib import Path

# ---------- paths ----------
BASE_DIR = Path(__file__).resolve().parent.parent
ALERTS_DIR = BASE_DIR / "alerts"
SCREENSHOT_DIR = ALERTS_DIR / "screenshots"      # alerts/screenshots
DB_PATH = ALERTS_DIR / "alerts.db"
ASSETS_DIR = BASE_DIR / "assets"

# ---------- models ----------
DETECT_MODEL = "yolo11n.pt"          # objects (phone, book). Also try yolov8n.pt / yolo11s.pt
POSE_MODEL = "yolo11n-pose.pt"       # people + keypoints (used for tracking and head-turn)
TRACKER = "bytetrack.yaml"           # or "botsort.yaml"
IMGSZ = 640
PROCESS_EVERY = 2                    # run AI on every Nth frame (others reuse last boxes)
PERSON_CONF = 0.35
OBJECT_CONF = 0.35

# COCO class id -> behavior label
OBJECT_CLASSES = {67: "Phone detected", 73: "Book/notes detected"}
BOX_MARGIN = 0.15                    # object centre may be this far outside a student's box

# ---------- cheating rules ----------
HEAD_TURN_RATIO = 0.55               # nose offset / eye distance. Lower = more sensitive
MIN_DURATION = {                     # seconds a behavior must persist before it counts
    "Phone detected": 0.5,
    "Book/notes detected": 1.0,
    "Looking sideways": 2.5,
}
GRACE_SECONDS = 0.6                  # tolerate brief detection drop-outs
COOLDOWN_SECONDS = 15.0              # min gap between alerts for same student + behavior
RED_HOLD_SECONDS = 2.0               # keep the box red this long after last detection

# ---------- optional Firebase ----------
FIREBASE_CREDENTIALS = BASE_DIR / "firebase_key.json"   # service-account key
FIREBASE_BUCKET = "your-project-id.appspot.com"
