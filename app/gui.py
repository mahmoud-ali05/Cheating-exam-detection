"""Tkinter desktop application."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import cv2
from PIL import Image, ImageDraw, ImageTk

from . import config as C
from .database import AlertDatabase
from .firebase_sync import FirebaseSync
from .notifier import system_notify


# ---------------------------------------------------------------- helpers
def make_icon() -> Image.Image:
    """Draw the app icon (a green box and a red box on blue) and save it to assets/."""
    img = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, 248, 248), radius=48, fill=(13, 110, 190))
    d.rectangle((40, 70, 140, 200), outline=(60, 220, 90), width=12)
    d.rectangle((110, 50, 220, 190), outline=(235, 50, 50), width=12)
    d.ellipse((150, 80, 180, 110), fill=(255, 255, 255))
    d.rectangle((140, 120, 190, 180), fill=(255, 255, 255))
    try:
        C.ASSETS_DIR.mkdir(exist_ok=True)
        img.save(C.ASSETS_DIR / "icon.png")
        img.save(C.ASSETS_DIR / "icon.ico", sizes=[(256, 256), (64, 64), (32, 32)])
    except Exception:
        pass
    return img


def open_path(path):
    path = str(path)
    if sys.platform.startswith("win"):
        os.startfile(path)  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class Toast(tk.Toplevel):
    """Pop-up desktop alert shown at the bottom-right of the screen."""
    active: list = []

    def __init__(self, master, rec, duration=5000):
        super().__init__(master)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        outer = tk.Frame(self, bg="#c62828", padx=2, pady=2)
        outer.pack()
        box = tk.Frame(outer, bg="white", padx=14, pady=10)
        box.pack()
        tk.Label(box, text="Cheating Alert Detected", bg="white", fg="#c62828",
                 font=("Segoe UI", 12, "bold")).pack(anchor="w")
        time_str = datetime.now().strftime("%I:%M %p").lstrip("0")
        for line in (f"Behavior: {rec['behavior']}", f"Student ID: {rec['student_id']}",
                     f"Time: {time_str}", "Screenshot saved successfully."):
            tk.Label(box, text=line, bg="white", font=("Segoe UI", 10)).pack(anchor="w")
        self.update_idletasks()
        w, h = self.winfo_reqwidth(), self.winfo_reqheight()
        x = self.winfo_screenwidth() - w - 20
        y = max(self.winfo_screenheight() - 70 - (len(Toast.active) + 1) * (h + 10), 10)
        self.geometry(f"+{x}+{y}")
        Toast.active.append(self)
        self.after(duration, self._close)

    def _close(self):
        if self in Toast.active:
            Toast.active.remove(self)
        self.destroy()


class ScreenshotViewer(tk.Toplevel):
    def __init__(self, master, path, rec, icon=None):
        super().__init__(master)
        self.title(f"Alert #{rec['id']} - {rec['behavior']}")
        if icon:
            self.iconphoto(False, icon)
        img = Image.open(path)
        img.thumbnail((int(self.winfo_screenwidth() * 0.75), int(self.winfo_screenheight() * 0.75)))
        self._photo = ImageTk.PhotoImage(img)
        info = (f"{rec['created_at']}   |   Student {rec['student_id']}   |   {rec['behavior']}"
                f"   |   Confidence {rec['confidence']:.0%}")
        ttk.Label(self, text=info, padding=8).pack()
        tk.Label(self, image=self._photo).pack(padx=8)
        row = ttk.Frame(self, padding=8)
        row.pack()
        ttk.Button(row, text="Open Folder", command=lambda: open_path(os.path.dirname(path))).pack(side="left", padx=4)
        ttk.Button(row, text="Close", command=self.destroy).pack(side="left", padx=4)


# ---------------------------------------------------------------- main app
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Cheating Tracking and Alert System")
        self.geometry("1360x780")
        self.minsize(1100, 650)
        C.SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

        self.db = AlertDatabase(C.DB_PATH)
        self.firebase = FirebaseSync()
        self.detector = None
        self.q: queue.Queue = queue.Queue(maxsize=6)
        self.stop_event = threading.Event()
        self.run_event = threading.Event()
        self.run_event.set()
        self.worker = None
        self.display_size = (800, 500)
        self.session_alerts = 0
        self._photo = None

        icon = make_icon()
        self._icon = ImageTk.PhotoImage(icon)
        self.iconphoto(True, self._icon)
        if sys.platform.startswith("win"):
            try:
                self.iconbitmap(str(C.ASSETS_DIR / "icon.ico"))
            except Exception:
                pass

        self._build_ui()
        self._load_history()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(30, self._poll)

    # ------------------------------------------------------------ UI
    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Treeview", rowheight=26)
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

        self.status = tk.StringVar(value="Ready - upload an exam video to start.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w",
                  padding=4).pack(side="bottom", fill="x")

        bar = ttk.Frame(self, padding=8)
        bar.pack(fill="x")
        self.btn_upload = ttk.Button(bar, text="Upload Video", style="Accent.TButton", command=self.upload_video)
        self.btn_pause = ttk.Button(bar, text="Pause", command=self.toggle_pause, state="disabled")
        self.btn_stop = ttk.Button(bar, text="Stop", command=self.stop_video, state="disabled")
        for b in (self.btn_upload, self.btn_pause, self.btn_stop):
            b.pack(side="left", padx=3)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Button(bar, text="View Screenshot", command=self.view_screenshot).pack(side="left", padx=3)
        ttk.Button(bar, text="Open Screenshots Folder",
                   command=lambda: open_path(C.SCREENSHOT_DIR)).pack(side="left", padx=3)
        ttk.Button(bar, text="Refresh History", command=self._load_history).pack(side="left", padx=3)
        ttk.Button(bar, text="Clear History", command=self.clear_history).pack(side="left", padx=3)

        body = ttk.Frame(self, padding=(8, 0, 8, 8))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        left = ttk.LabelFrame(body, text="Exam Video")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.canvas = tk.Canvas(left, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self.placeholder = self.canvas.create_text(
            0, 0, text="Upload an exam video to begin", fill="#999", font=("Segoe UI", 16))
        self.canvas_img = self.canvas.create_image(0, 0, anchor="center")
        self.progress = ttk.Progressbar(left, mode="determinate")
        self.progress.pack(fill="x", padx=4, pady=4)

        right = ttk.Frame(body)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        stats = ttk.LabelFrame(right, text="Live Status", padding=8)
        stats.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.var_video = tk.StringVar(value="Video: -")
        self.var_students = tk.StringVar(value="Students tracked: 0")
        self.var_session = tk.StringVar(value="Alerts this session: 0")
        for v in (self.var_video, self.var_students, self.var_session):
            ttk.Label(stats, textvariable=v).pack(anchor="w")

        hist = ttk.LabelFrame(right, text="Alert History (double-click to open screenshot)", padding=4)
        hist.grid(row=1, column=0, sticky="nsew")
        hist.rowconfigure(0, weight=1)
        hist.columnconfigure(0, weight=1)
        cols = ("id", "time", "student", "behavior", "conf", "shot")
        self.tree = ttk.Treeview(hist, columns=cols, show="headings", selectmode="browse")
        for col, text, w in (("id", "#", 40), ("time", "Date / Time", 135), ("student", "Student", 60),
                             ("behavior", "Behavior", 130), ("conf", "Confidence", 75),
                             ("shot", "Screenshot path", 230)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w, anchor="w", stretch=(col == "shot"))
        ys = ttk.Scrollbar(hist, orient="vertical", command=self.tree.yview)
        xs = ttk.Scrollbar(hist, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<Double-1>", lambda e: self.view_screenshot())

    def _on_canvas_resize(self, e):
        self.display_size = (max(e.width, 50), max(e.height, 50))
        self.canvas.coords(self.placeholder, e.width // 2, e.height // 2)
        self.canvas.coords(self.canvas_img, e.width // 2, e.height // 2)

    # ------------------------------------------------------------ history
    @staticmethod
    def _row_values(r):
        return (r["id"], r["created_at"], r["student_id"], r["behavior"],
                f"{(r['confidence'] or 0):.0%}", r["screenshot_path"] or r.get("firebase_url") or "")

    def _load_history(self):
        self.tree.delete(*self.tree.get_children())
        for r in self.db.all_alerts():
            self.tree.insert("", "end", iid=str(r["id"]), values=self._row_values(r))

    def clear_history(self):
        if messagebox.askyesno("Clear history", "Delete all alert records from the database?\n"
                                                "(Screenshot files stay on disk.)"):
            self.db.clear()
            self._load_history()

    def _selected_alert(self):
        sel = self.tree.selection()
        return self.db.get_alert(int(sel[0])) if sel else None

    def view_screenshot(self):
        rec = self._selected_alert()
        if not rec:
            messagebox.showinfo("View Screenshot", "Select an alert in the history list first.")
            return
        path = C.BASE_DIR / (rec["screenshot_path"] or "")
        if rec["screenshot_path"] and path.exists():
            ScreenshotViewer(self, str(path), rec, self._icon)
        elif rec.get("firebase_url"):
            webbrowser.open(rec["firebase_url"])
        else:
            messagebox.showwarning("Missing file", f"Screenshot not found:\n{path}")

    # ------------------------------------------------------------ video control
    def upload_video(self):
        path = filedialog.askopenfilename(
            title="Select exam video",
            filetypes=[("Video files", "*.mp4 *.avi *.mov *.mkv *.wmv *.m4v"), ("All files", "*.*")])
        if not path:
            return
        self._stop_worker()
        self.session_alerts = 0
        self.var_session.set("Alerts this session: 0")
        self.var_video.set(f"Video: {os.path.basename(path)}")
        self.canvas.itemconfig(self.placeholder, text="")
        self.stop_event = threading.Event()
        self.run_event.set()
        self.btn_pause.config(text="Pause")
        self._set_running(True)
        self.worker = threading.Thread(target=self._worker, args=(path, self.stop_event), daemon=True)
        self.worker.start()

    def toggle_pause(self):
        if self.run_event.is_set():
            self.run_event.clear()
            self.btn_pause.config(text="Resume")
            self.status.set("Paused")
        else:
            self.run_event.set()
            self.btn_pause.config(text="Pause")
            self.status.set("Processing...")

    def stop_video(self):
        self._stop_worker()
        self._set_running(False)
        self.status.set("Stopped.")

    def _stop_worker(self):
        self.stop_event.set()
        self.run_event.set()
        if self.worker and self.worker.is_alive():
            self.worker.join(timeout=10)
        self.worker = None
        while not self.q.empty():
            try:
                self.q.get_nowait()
            except queue.Empty:
                break

    def _set_running(self, running):
        self.btn_pause.config(state="normal" if running else "disabled")
        self.btn_stop.config(state="normal" if running else "disabled")

    # ------------------------------------------------------------ worker thread
    def _put(self, msg, stop):
        while not stop.is_set():
            try:
                self.q.put(msg, timeout=0.2)
                return
            except queue.Full:
                pass

    def _worker(self, path, stop):
        name = os.path.basename(path)
        cap = None
        try:
            if self.detector is None:
                self._put(("status", "Loading AI models (first run downloads the weights)..."), stop)
                from .detector import CheatingDetector     # heavy import kept off the GUI thread
                self.detector = CheatingDetector()
            self.detector.reset()

            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                self._put(("error", f"Could not open video:\n{path}"), stop)
                return
            fps = cap.get(cv2.CAP_PROP_FPS)
            fps = fps if fps and fps > 1 else 25.0
            total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            self._put(("status", f"Processing {name} ..."), stop)

            idx, dt = 0, 1.0 / fps
            next_t = time.perf_counter()
            while not stop.is_set():
                if not self.run_event.is_set():
                    self.run_event.wait()
                    next_t = time.perf_counter()
                if stop.is_set():
                    break
                ok, frame = cap.read()
                if not ok:
                    break
                t = idx / fps
                if idx % C.PROCESS_EVERY == 0:
                    frame, alerts = self.detector.process(frame, t)
                    for a in alerts:
                        self._handle_alert(a, name, stop)
                else:
                    self.detector.redraw(frame, t)

                h, w = frame.shape[:2]
                dw, dh = self.display_size
                s = min(dw / w, dh / h)
                small = cv2.resize(frame, (max(1, int(w * s)), max(1, int(h * s))))
                rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
                prog = (idx / total * 100) if total else 0
                self._put(("frame", rgb, prog, self.detector.n_students), stop)
                idx += 1

                next_t += dt                      # keep playback near real time
                delay = next_t - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                else:
                    next_t = time.perf_counter()  # processing is slower than real time
            self._put(("done", "Finished" if not stop.is_set() else "Stopped"), stop)
        except Exception:  # noqa: BLE001
            self._put(("error", traceback.format_exc(limit=4)), stop)
        finally:
            if cap is not None:
                cap.release()

    def _handle_alert(self, a, video_name, stop):
        now = datetime.now()
        slug = a["behavior"].lower().replace("/", "_").replace(" ", "_")
        fname = f"alert_{now:%Y%m%d_%H%M%S}_student{a['student_id']}_{slug}.jpg"
        path = C.SCREENSHOT_DIR / fname
        cv2.imwrite(str(path), a["frame"])
        rel = path.relative_to(C.BASE_DIR).as_posix()
        alert_id, created = self.db.add_alert(video_name, a["video_time"], a["student_id"],
                                              a["behavior"], a["confidence"], rel)
        rec = {"id": alert_id, "created_at": created, "video_name": video_name,
               "video_time": a["video_time"], "student_id": a["student_id"],
               "behavior": a["behavior"], "confidence": a["confidence"],
               "screenshot_path": rel, "firebase_url": None}
        if self.firebase.enabled:
            threading.Thread(target=self._sync, args=(rec,), daemon=True).start()
        self._put(("alert", rec), stop)

    def _sync(self, rec):
        url = self.firebase.upload(rec)
        if url:
            self.db.set_firebase_url(rec["id"], url)

    # ------------------------------------------------------------ GUI-thread queue pump
    def _poll(self):
        latest = None
        try:
            for _ in range(12):
                kind, *data = self.q.get_nowait()
                if kind == "frame":
                    latest = data
                elif kind == "alert":
                    self._on_alert(data[0])
                elif kind == "status":
                    self.status.set(data[0])
                elif kind == "done":
                    self.status.set(f"{data[0]}. Alerts this session: {self.session_alerts}")
                    self._set_running(False)
                elif kind == "error":
                    self._set_running(False)
                    self.status.set("Error")
                    messagebox.showerror("Error", data[0])
        except queue.Empty:
            pass
        if latest:
            rgb, prog, n = latest
            self._photo = ImageTk.PhotoImage(Image.fromarray(rgb))
            self.canvas.itemconfig(self.canvas_img, image=self._photo)
            self.progress["value"] = prog
            self.var_students.set(f"Students tracked: {n}")
        self.after(25, self._poll)

    def _on_alert(self, rec):
        self.session_alerts += 1
        self.var_session.set(f"Alerts this session: {self.session_alerts}")
        self.tree.insert("", 0, iid=str(rec["id"]), values=self._row_values(rec))
        self.status.set(f"Cheating alert: {rec['behavior']} (student {rec['student_id']})")
        self.bell()
        Toast(self, rec)
        system_notify("Cheating Alert Detected",
                      f"Behavior: {rec['behavior']}\nStudent ID: {rec['student_id']}\n"
                      "Screenshot saved successfully.")

    def _on_close(self):
        self.stop_event.set()
        self.run_event.set()
        self.destroy()
