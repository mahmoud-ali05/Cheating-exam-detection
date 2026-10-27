"""Optional Firebase sync: Firestore (alert records) + Storage (screenshots).

Enabled automatically when `firebase_key.json` exists and `firebase-admin` is installed.
If anything is missing the app simply keeps using the local SQLite database.
"""
from __future__ import annotations

from . import config as C


class FirebaseSync:
    def __init__(self):
        self.enabled = False
        if not C.FIREBASE_CREDENTIALS.exists():
            return
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore, storage
            if not firebase_admin._apps:
                firebase_admin.initialize_app(
                    credentials.Certificate(str(C.FIREBASE_CREDENTIALS)),
                    {"storageBucket": C.FIREBASE_BUCKET})
            self.fs = firestore.client()
            self.bucket = storage.bucket()
            self.enabled = True
        except Exception as exc:  # noqa: BLE001
            print(f"[Firebase] disabled: {exc}")

    def upload(self, rec):
        """Upload screenshot + record. Returns the public screenshot URL (or None)."""
        if not self.enabled:
            return None
        try:
            local = C.BASE_DIR / rec["screenshot_path"]
            blob = self.bucket.blob(f"screenshots/{local.name}")
            blob.upload_from_filename(str(local))
            blob.make_public()
            self.fs.collection("cheating_alerts").add({
                "created_at": rec["created_at"],
                "student_id": rec["student_id"],
                "behavior": rec["behavior"],
                "confidence": rec["confidence"],
                "video_name": rec["video_name"],
                "screenshot_url": blob.public_url,
            })
            return blob.public_url
        except Exception as exc:  # noqa: BLE001
            print(f"[Firebase] upload failed: {exc}")
            return None
