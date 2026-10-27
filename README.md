# Cheating Tracking and Alert System

Desktop AI system that tracks students in an exam video, detects cheating behavior,
turns the suspect's bounding box **red** (normal students stay **green**), saves a
screenshot, stores the incident in a database and pops up an alert.

## Setup
```bash
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
# Linux only, if Tkinter is missing:  sudo apt install python3-tk
python main.py
```
The first run downloads `yolo11n.pt` and `yolo11n-pose.pt` automatically (internet needed once).

## Usage
1. Click **Upload Video** and pick an exam video (mp4/avi/mov/mkv).
2. Watch live tracking. Pause / Stop at any time.
3. On cheating: box turns red, screenshot saved to `alerts/screenshots/`, row added to the
   database, toast notification shown ("Cheating Alert Detected / Behavior / Time / Screenshot saved successfully.").
4. **Alert History** lists every past event (date/time, student, behavior, confidence, screenshot path).
   Double-click a row or press **View Screenshot** to open the saved image.

## Architecture
| File | Role |
|---|---|
| `main.py` | entry point |
| `app/config.py` | all thresholds, model names, paths |
| `app/detector.py` | YOLO-pose + ByteTrack tracking, YOLO object detection, cheating rules, drawing |
| `app/database.py` | SQLite alert history (`alerts/alerts.db`) |
| `app/firebase_sync.py` | optional Firestore + Storage sync |
| `app/notifier.py` | optional native OS notification (plyer) |
| `app/gui.py` | Tkinter app: upload, video player, alert history, toast, screenshot viewer, app icon |

## Detected behaviors
| Behavior | How |
|---|---|
| Phone detected | COCO "cell phone" inside/near a tracked student's box for >= 0.5 s |
| Book/notes detected | COCO "book" near a student for >= 1 s |
| Looking sideways | head turn from pose keypoints (nose vs. eyes) sustained >= 2.5 s |

Alerts are debounced: behaviors must persist (`MIN_DURATION`), short drop-outs are tolerated
(`GRACE_SECONDS`) and the same student + behavior alerts at most once per `COOLDOWN_SECONDS`.
Tune everything in `app/config.py` (e.g. lower `HEAD_TURN_RATIO` for more sensitivity,
use `yolo11s.pt` for accuracy, `botsort.yaml` for BoT-SORT, `PROCESS_EVERY = 1` for max accuracy).

Notes: head-turn works best when students face the camera (front/angled view). Open-book exams:
remove class 73 from `OBJECT_CLASSES`.

## Optional: Firebase (Firestore + Storage)
1. Create a Firebase project, enable Firestore and Storage.
2. Download a service-account key, save as `firebase_key.json` in the project root.
3. Set `FIREBASE_BUCKET` in `app/config.py`, then `pip install firebase-admin`.

Alerts are then also written to the `cheating_alerts` collection and screenshots uploaded to
Storage; the public URL is saved in the local database. Without the key the app uses SQLite only.

## Optional extras (already included)
Screenshot viewer, custom app icon (auto-generated to `assets/icon.png` / `icon.ico`; replace with your own file if you like).
