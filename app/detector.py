"""Student tracking + cheating detection.

Pipeline per frame:
  1. YOLO-pose + ByteTrack  -> stable student IDs, boxes, face keypoints
  2. YOLO detect            -> phones / books
  3. Rules                  -> phone or book near a student, or head turned sideways
  4. Draw                   -> green box = normal, red box = cheating
"""
from __future__ import annotations

import math

import cv2
from ultralytics import YOLO

from . import config as C

GREEN = (0, 200, 0)     # BGR
RED = (0, 0, 255)
FONT = cv2.FONT_HERSHEY_SIMPLEX


class StudentState:
    def __init__(self):
        self.since = {}          # behavior -> time it started
        self.last_hit = {}       # behavior -> last time seen
        self.conf = {}           # behavior -> last confidence
        self.last_alert = {}     # behavior -> time of last alert
        self.flag_until = -1e9
        self.flag_label = ""


def head_turn(kp):
    """Return (ratio, confidence) of horizontal head turn from COCO keypoints, or None."""
    nose, l_eye, r_eye = kp[0], kp[1], kp[2]
    if min(nose[2], l_eye[2], r_eye[2]) < 0.5:
        return None
    eye_dist = abs(l_eye[0] - r_eye[0])
    if eye_dist < 4:
        return None
    ratio = (nose[0] - (l_eye[0] + r_eye[0]) / 2) / eye_dist
    kp_conf = float((nose[2] + l_eye[2] + r_eye[2]) / 3)
    return float(ratio), kp_conf


class CheatingDetector:
    def __init__(self):
        self.det_model = YOLO(C.DETECT_MODEL)
        self.pose_model = YOLO(C.POSE_MODEL)
        self.state: dict[int, StudentState] = {}
        self._last_draw = []

    @property
    def n_students(self):
        return len(self._last_draw)

    def reset(self):
        """Call before each new video so track IDs start fresh."""
        self.state.clear()
        self._last_draw = []
        self.pose_model.predictor = None     # forces a fresh tracker on next call

    # ------------------------------------------------------------------ inference
    def _infer(self, frame):
        pose = self.pose_model.track(
            frame, persist=True, tracker=C.TRACKER, classes=[0],
            conf=C.PERSON_CONF, imgsz=C.IMGSZ, verbose=False)[0]
        objs = self.det_model.predict(
            frame, classes=list(C.OBJECT_CLASSES), conf=C.OBJECT_CONF,
            imgsz=C.IMGSZ, verbose=False)[0]

        students = {}
        boxes = pose.boxes
        if boxes is not None and boxes.id is not None:
            ids = boxes.id.int().cpu().tolist()
            xyxy = boxes.xyxy.cpu().numpy()
            kps = (pose.keypoints.data.cpu().numpy()
                   if pose.keypoints is not None else [None] * len(ids))
            for tid, box, kp in zip(ids, xyxy, kps):
                students[tid] = (box, kp)

        current = {tid: {} for tid in students}

        # phones / books -> nearest student whose (expanded) box contains them
        for b in objs.boxes:
            label = C.OBJECT_CLASSES[int(b.cls[0])]
            conf = float(b.conf[0])
            x1, y1, x2, y2 = b.xyxy[0].tolist()
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            best, best_d = None, 1e18
            for tid, (box, _) in students.items():
                bx1, by1, bx2, by2 = box
                mx, my = (bx2 - bx1) * C.BOX_MARGIN, (by2 - by1) * C.BOX_MARGIN
                if bx1 - mx <= cx <= bx2 + mx and by1 - my <= cy <= by2 + my:
                    d = math.hypot(cx - (bx1 + bx2) / 2, cy - (by1 + by2) / 2)
                    if d < best_d:
                        best, best_d = tid, d
            if best is not None:
                current[best][label] = max(current[best].get(label, 0.0), conf)

        # head turned sideways
        for tid, (_, kp) in students.items():
            if kp is None or len(kp) < 3:
                continue
            res = head_turn(kp)
            if res and abs(res[0]) >= C.HEAD_TURN_RATIO:
                ratio, kp_conf = res
                score = kp_conf * min(1.0, abs(ratio) / (C.HEAD_TURN_RATIO * 1.5))
                current[tid]["Looking sideways"] = score
        return students, current

    # ------------------------------------------------------------------ rules
    def process(self, frame, t):
        """Analyse one frame at video time `t` (seconds).

        Returns (annotated_frame, new_alerts). Each alert is a dict with
        student_id, behavior, confidence, video_time and the annotated frame.
        """
        students, current = self._infer(frame)
        alerts, draws = [], []

        for tid, (box, _) in students.items():
            st = self.state.setdefault(tid, StudentState())
            cur = current.get(tid, {})

            for name in C.MIN_DURATION:
                if name in cur:
                    st.since.setdefault(name, t)
                    st.last_hit[name] = t
                    st.conf[name] = cur[name]
                elif name in st.since and t - st.last_hit[name] > C.GRACE_SECONDS:
                    del st.since[name]

            confirmed = [n for n, s in st.since.items() if t - s >= C.MIN_DURATION[n]]
            if confirmed:
                st.flag_until = t + C.RED_HOLD_SECONDS
                st.flag_label = max(confirmed, key=lambda n: st.conf[n])
                for n in confirmed:
                    if t - st.last_alert.get(n, -1e9) >= C.COOLDOWN_SECONDS:
                        st.last_alert[n] = t
                        alerts.append({"student_id": tid, "behavior": n,
                                       "confidence": float(st.conf[n]), "video_time": t})

            if t < st.flag_until:
                label = f"ID {tid} | {st.flag_label} {st.conf.get(st.flag_label, 0):.0%}"
                draws.append((box, RED, label))
            else:
                draws.append((box, GREEN, f"ID {tid}"))

        self._last_draw = draws
        self.redraw(frame, t)
        if alerts:
            snap = frame.copy()
            for a in alerts:
                a["frame"] = snap
        return frame, alerts

    # ------------------------------------------------------------------ drawing
    def redraw(self, frame, t):
        """Draw the most recent boxes on `frame` (used for skipped frames too)."""
        for box, color, label in self._last_draw:
            x1, y1, x2, y2 = (int(v) for v in box)
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 3 if color == RED else 2)
            (tw, th), _ = cv2.getTextSize(label, FONT, 0.55, 1)
            y0 = max(y1 - th - 8, 0)
            cv2.rectangle(frame, (x1, y0), (x1 + tw + 6, y0 + th + 8), color, -1)
            cv2.putText(frame, label, (x1 + 3, y0 + th + 2), FONT, 0.55,
                        (255, 255, 255), 1, cv2.LINE_AA)

        n_red = sum(1 for _, c, _ in self._last_draw if c == RED)
        hud = f"{int(t // 60):02d}:{int(t % 60):02d} | Students: {len(self._last_draw)} | Cheating: {n_red}"
        cv2.rectangle(frame, (0, 0), (cv2.getTextSize(hud, FONT, 0.6, 2)[0][0] + 14, 28), (0, 0, 0), -1)
        cv2.putText(frame, hud, (7, 20), FONT, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
        return frame
