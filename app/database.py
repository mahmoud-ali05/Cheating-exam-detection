"""SQLite storage for cheating alerts (thread-safe)."""
import sqlite3
import threading
from datetime import datetime


class AlertDatabase:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    video_name TEXT,
                    video_time REAL,
                    student_id INTEGER,
                    behavior TEXT NOT NULL,
                    confidence REAL,
                    screenshot_path TEXT,
                    firebase_url TEXT
                )""")
            self.conn.commit()

    def add_alert(self, video_name, video_time, student_id, behavior, confidence, screenshot_path):
        created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO alerts (created_at, video_name, video_time, student_id, behavior,"
                " confidence, screenshot_path) VALUES (?,?,?,?,?,?,?)",
                (created, video_name, video_time, student_id, behavior, confidence, screenshot_path))
            self.conn.commit()
            return cur.lastrowid, created

    def set_firebase_url(self, alert_id, url):
        with self.lock:
            self.conn.execute("UPDATE alerts SET firebase_url=? WHERE id=?", (url, alert_id))
            self.conn.commit()

    def get_alert(self, alert_id):
        with self.lock:
            row = self.conn.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
        return dict(row) if row else None

    def all_alerts(self):
        with self.lock:
            rows = self.conn.execute("SELECT * FROM alerts ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]

    def clear(self):
        with self.lock:
            self.conn.execute("DELETE FROM alerts")
            self.conn.commit()

    def close(self):
        with self.lock:
            self.conn.close()
