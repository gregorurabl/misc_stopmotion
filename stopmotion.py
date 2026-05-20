import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
import threading
import queue
import os
import time
import json
import shutil
import subprocess
import glob

import cv2
import numpy as np
from PIL import Image, ImageTk

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# --- Style tokens ---
ONION_FALLOFF = 0.6
FONT_MONO     = "Courier New"
BG            = "#1a1a1a"
PANEL         = "#1e1e1e"
BTN_BG        = "#222222"
BTN_HVR       = "#333333"
BTN_BORDER    = "#3a3a3a"
ACCENT        = "#2ecc71"
ACCENT_HVR    = "#27ae60"
FG_DIM        = "#555555"
FG_MID        = "#888888"
FG_MAIN       = "#e0e0e0"
GROUP_BG      = "#252525"
GROUP_BORDER  = "#383838"

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
CAPTURE_ROOT = os.path.join(SCRIPT_DIR, "capture")


# ---------------------------------------------------------------------------
# Linux sysfs camera name resolution
# ---------------------------------------------------------------------------

def _resolve_cam_name_linux(opencv_index: int) -> str | None:
    """
    Map an OpenCV integer index to the real device name via sysfs.

    On Linux, /dev/videoN can contain both capture interfaces (sysfs index=0)
    and secondary interfaces such as metadata or ISP nodes (sysfs index>0).
    OpenCV's VideoCapture(N) enumerates only capture-capable devices, so
    VideoCapture(1) may correspond to /dev/video2 if /dev/video1 is a
    metadata interface.  Reading sysfs by OpenCV index directly therefore
    returns the wrong name.  We rebuild the ordered list of primary-capture
    devices (sysfs interface index == 0) and return the entry at opencv_index.
    """
    if not os.path.isdir("/sys/class/video4linux"):
        return None
    try:
        paths = sorted(
            glob.glob("/sys/class/video4linux/video*"),
            key=lambda p: int(p.rsplit("video", 1)[1]))
        devices: list[str] = []
        for path in paths:
            try:
                iface_idx = int(open(path + "/index").read().strip())
                if iface_idx != 0:
                    continue   # skip metadata / secondary interfaces
                name = open(path + "/name").read().strip()
                devices.append(name)
            except (OSError, ValueError):
                continue
        return devices[opencv_index] if opencv_index < len(devices) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Camera thread
# ---------------------------------------------------------------------------

class CameraThread(threading.Thread):
    def __init__(self, index: int, frame_queue: queue.Queue, name_cb=None):
        super().__init__(daemon=True)
        self.index   = index
        self.queue   = frame_queue
        self.name_cb = name_cb
        self._halt   = threading.Event()

    def run(self):
        # Resolve device name before opening (Linux: sysfs primary-interface map)
        cam_name = _resolve_cam_name_linux(self.index)

        # Retry loop: USB cameras need time to register after hot-plug
        cap = None
        for _ in range(8):
            if self._halt.is_set():
                return
            cap = cv2.VideoCapture(self.index)
            if cap.isOpened():
                break
            cap.release()
            cap = None
            time.sleep(0.5)

        if cap is None:
            if self.name_cb:
                self.name_cb("no device")
            return

        # Fallback to OpenCV backend string when sysfs gave nothing
        if cam_name is None:
            cam_name = cap.getBackendName()
        if self.name_cb:
            self.name_cb(cam_name)

        while not self._halt.is_set():
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.02)
                continue
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            if self.queue.full():
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    pass
            self.queue.put(frame)
        cap.release()

    def stop(self):
        self._halt.set()


# ---------------------------------------------------------------------------
# Onion-skin blending
# ---------------------------------------------------------------------------

def blend_onion(base: np.ndarray, layers: list[np.ndarray],
                opacity: float) -> np.ndarray:
    result = base.astype(np.float32)
    for i, layer in enumerate(layers):
        if layer.shape[:2] != base.shape[:2]:
            layer = np.array(
                Image.fromarray(layer).resize(
                    (base.shape[1], base.shape[0]), Image.BILINEAR))
        alpha  = opacity * (ONION_FALLOFF ** i)
        result = result * (1.0 - alpha) + layer.astype(np.float32) * alpha
    return np.clip(result, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class StopMotionApp(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=BG)
        self.resizable(True, True)

        os.makedirs(CAPTURE_ROOT, exist_ok=True)

        # Project state
        self.project_path: str | None = None
        self.project_name: str        = "Unnamed Project"
        self._update_title()

        # Playback state
        self.frames: list[np.ndarray] = []
        self.save_dir        = CAPTURE_ROOT
        self.live_mode       = True
        self.playing         = False
        self.play_index      = 0
        self._after_id       = None
        self._live_after_id  = None
        self._resize_job     = None
        self._suppress_scrub = False

        # Camera
        self.cam_queue     = queue.Queue(maxsize=2)
        self.cam_thread    = None
        self.current_frame = None

        # Letterbox geometry
        self.native_w  = 640
        self.native_h  = 360
        self.display_w = 640
        self.display_h = 360
        self._ox = 0
        self._oy = 0

        self._build_ui()
        self._bind_keys()
        self._start_camera(0)

    # -----------------------------------------------------------------------
    # Window title
    # -----------------------------------------------------------------------

    def _update_title(self):
        saved = "" if self.project_path else " •"
        self.title(f"Onion Film BETA  –  {self.project_name}{saved}")

    # -----------------------------------------------------------------------
    # Widget helpers
    # -----------------------------------------------------------------------

    def _btn(self, parent, text, cmd, width=120,
             fg=BTN_BG, hover=BTN_HVR, text_color=FG_MAIN,
             accent=False) -> ctk.CTkButton:
        return ctk.CTkButton(
            parent, text=text, command=cmd, width=width,
            fg_color=ACCENT if accent else fg,
            hover_color=ACCENT_HVR if accent else hover,
            text_color="black" if accent else text_color,
            border_width=1, border_color=BTN_BORDER,
            font=ctk.CTkFont(family=FONT_MONO, size=12),
            corner_radius=6)

    def _lbl(self, parent, text, size=11, color=FG_DIM, **kw) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent, text=text,
            font=ctk.CTkFont(family=FONT_MONO, size=size),
            text_color=color, **kw)

    def _spinbox(self, parent, var: tk.IntVar, lo: int, hi: int,
                 entry_w=44, on_change=None) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color=BTN_BG, corner_radius=6,
                         border_width=1, border_color=BTN_BORDER)
        def _dec():
            var.set(max(lo, var.get() - 1))
            if on_change:
                on_change()
        def _inc():
            var.set(min(hi, var.get() + 1))
            if on_change:
                on_change()
        ctk.CTkButton(f, text="-", width=22, height=26,
                      fg_color="transparent", hover_color=BTN_HVR,
                      font=ctk.CTkFont(size=13), text_color=FG_MAIN,
                      border_width=0, command=_dec).pack(side="left")
        ctk.CTkEntry(f, textvariable=var, width=entry_w, justify="center",
                     border_width=0, fg_color="transparent",
                     font=ctk.CTkFont(family=FONT_MONO, size=11),
                     text_color=FG_MAIN).pack(side="left")
        ctk.CTkButton(f, text="+", width=22, height=26,
                      fg_color="transparent", hover_color=BTN_HVR,
                      font=ctk.CTkFont(size=13), text_color=FG_MAIN,
                      border_width=0, command=_inc).pack(side="left")
        return f

    # -----------------------------------------------------------------------
    # UI layout
    # -----------------------------------------------------------------------

    def _build_ui(self):
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        # ---- Row 0: video canvas ----
        self.canvas = tk.Canvas(self, bg="#000", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", self._on_canvas_resize)

        # ---- Row 1: timeline ----
        tf = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        tf.grid(row=1, column=0, sticky="ew", pady=(1, 0))
        tf.columnconfigure(1, weight=1)

        self.frame_counter = self._lbl(tf, "0 / 0", color=FG_MAIN, width=72)
        self.frame_counter.grid(row=0, column=0, padx=(10, 6), pady=6)

        self.timeline_var = tk.DoubleVar(value=0)
        self.timeline = ctk.CTkSlider(
            tf, from_=0, to=1, number_of_steps=1,
            variable=self.timeline_var,
            command=self._on_timeline_scrub,
            button_color=ACCENT, button_hover_color=ACCENT_HVR,
            progress_color="#2a5a2a", fg_color="#2e2e2e", height=16)
        self.timeline.grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=6)

        # ---- Row 2: transport ----
        cf = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        cf.grid(row=2, column=0, sticky="ew", pady=(1, 0))

        self.btn_capture = self._btn(cf, "Capture  [Space]",
                                     self._capture, width=160, accent=True)
        self.btn_capture.pack(side="left", padx=(10, 6), pady=8)

        self.btn_live = self._btn(cf, "Live", self._set_live_mode, width=80)
        self.btn_live.configure(text_color=ACCENT)
        self.btn_live.pack(side="left", padx=4, pady=8)

        self.btn_play = self._btn(cf, "Play", self._toggle_play, width=80)
        self.btn_play.pack(side="left", padx=4, pady=8)

        self._btn(cf, "Export Video", self._export_video, width=120).pack(
            side="left", padx=4, pady=8)

        # ---- Row 3: project management ----
        pf = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        pf.grid(row=3, column=0, sticky="ew", pady=(1, 0))

        self._btn(pf, "New Project",  self._new_project,  width=120).pack(
            side="left", padx=(10, 4), pady=6)
        self._btn(pf, "Open Project", self._open_project, width=120).pack(
            side="left", padx=4, pady=6)
        self._btn(pf, "Save",         self._save,         width=80).pack(
            side="left", padx=4, pady=6)
        self._btn(pf, "Save As",      self._save_as,      width=90).pack(
            side="left", padx=4, pady=6)

        self.project_name_lbl = self._lbl(
            pf, self.project_name, size=12, color=FG_MID, anchor="w")
        self.project_name_lbl.pack(side="left", padx=(12, 4))

        # ---- Row 4: settings ----
        sf = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        sf.grid(row=4, column=0, sticky="ew", pady=(1, 0))

        # FPS
        self._lbl(sf, "FPS").pack(side="left", padx=(10, 4))
        self.fps_var = tk.IntVar(value=12)
        self._spinbox(sf, self.fps_var, 1, 60, entry_w=36).pack(
            side="left", padx=(0, 10))

        # Separator
        ctk.CTkFrame(sf, width=1, height=28,
                     fg_color=GROUP_BORDER).pack(side="left", padx=6)

        # Onion group
        og = ctk.CTkFrame(sf, fg_color=GROUP_BG, corner_radius=8,
                          border_width=1, border_color=GROUP_BORDER)
        og.pack(side="left", padx=6, pady=5)

        self.onion_enabled = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(
            og, text="Onion", variable=self.onion_enabled,
            font=ctk.CTkFont(family=FONT_MONO, size=12),
            text_color=FG_MAIN, checkmark_color=BG,
            fg_color=ACCENT, hover_color=ACCENT_HVR,
            border_color=BTN_BORDER, width=18, height=18
        ).pack(side="left", padx=(8, 6), pady=5)

        # Opacity slider left of layer-count spinbox
        self.opacity_var = tk.DoubleVar(value=0.5)
        ctk.CTkSlider(
            og, from_=0.0, to=1.0, variable=self.opacity_var, width=90,
            button_color=ACCENT, button_hover_color=ACCENT_HVR,
            progress_color="#2a5a2a", fg_color="#2e2e2e", height=14
        ).pack(side="left", padx=(0, 6), pady=5)

        self.onion_var = tk.IntVar(value=3)
        self._spinbox(og, self.onion_var, 0, 20, entry_w=36).pack(
            side="left", padx=(0, 8), pady=5)

        # Separator
        ctk.CTkFrame(sf, width=1, height=28,
                     fg_color=GROUP_BORDER).pack(side="left", padx=6)

        # Camera
        self._lbl(sf, "Cam").pack(side="left", padx=(0, 4))
        self.cam_index_var = tk.IntVar(value=0)
        self._spinbox(sf, self.cam_index_var, 0, 10, entry_w=30,
                      on_change=self._on_cam_change).pack(
            side="left", padx=(0, 4))
        self.cam_name_lbl = self._lbl(sf, "—", color=FG_DIM, width=160,
                                      anchor="w")
        self.cam_name_lbl.pack(side="left", padx=(2, 10))

        # Separator
        ctk.CTkFrame(sf, width=1, height=28,
                     fg_color=GROUP_BORDER).pack(side="left", padx=6)

        # Save dir
        self._btn(sf, "Save Dir", self._choose_dir, width=90).pack(
            side="left", padx=(6, 6), pady=6)
        self.dir_label = self._lbl(sf, self._short_path(self.save_dir),
                                   color=FG_DIM, anchor="w", width=220)
        self.dir_label.pack(side="left")

        # ---- Row 5: export progress ----
        ef = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0)
        ef.grid(row=5, column=0, sticky="ew", pady=(1, 0))
        ef.columnconfigure(1, weight=1)

        self._lbl(ef, "Export", color=FG_DIM).grid(
            row=0, column=0, padx=(10, 6), pady=5)

        self._export_progress_var = tk.DoubleVar(value=0.0)
        self._export_bar = ctk.CTkProgressBar(
            ef, variable=self._export_progress_var,
            progress_color=ACCENT, fg_color="#2e2e2e",
            height=10, corner_radius=4)
        self._export_bar.grid(row=0, column=1, sticky="ew",
                              padx=(0, 8), pady=5)

        self._export_pct_lbl = self._lbl(ef, "—", color=FG_DIM, width=46,
                                         anchor="e")
        self._export_pct_lbl.grid(row=0, column=2, padx=(0, 10))

        # ---- Row 6: status bar ----
        self.status_var = tk.StringVar(value="  ready")
        ctk.CTkLabel(
            self, textvariable=self.status_var,
            fg_color="#111111", corner_radius=0,
            font=ctk.CTkFont(family=FONT_MONO, size=10),
            text_color=FG_DIM, anchor="w", height=22
        ).grid(row=6, column=0, sticky="ew")

    # -----------------------------------------------------------------------
    # Keys
    # -----------------------------------------------------------------------

    def _bind_keys(self):
        self.bind("<space>", lambda e: self._capture())
        self.bind("<Left>",  lambda e: self._step_frame(-1))
        self.bind("<Right>", lambda e: self._step_frame(1))

    # -----------------------------------------------------------------------
    # Letterbox
    # -----------------------------------------------------------------------

    def _on_canvas_resize(self, event):
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(
            60, lambda w=event.width, h=event.height: self._apply_resize(w, h))

    def _apply_resize(self, avail_w: int, avail_h: int):
        self._resize_job = None
        if self.native_w == 0 or avail_w == 0 or avail_h == 0:
            return
        scale = min(avail_w / self.native_w, avail_h / self.native_h)
        self.display_w = max(1, int(self.native_w * scale))
        self.display_h = max(1, int(self.native_h * scale))
        self._ox = (avail_w - self.display_w) // 2
        self._oy = (avail_h - self.display_h) // 2
        if not self.live_mode and self.frames:
            self._show_saved_frame(int(self.timeline_var.get()))

    # -----------------------------------------------------------------------
    # Camera
    # -----------------------------------------------------------------------

    def _start_camera(self, index: int):
        if self.cam_thread and self.cam_thread.is_alive():
            self.cam_thread.stop()
            self.cam_thread.join(timeout=1.0)
        while not self.cam_queue.empty():
            try:
                self.cam_queue.get_nowait()
            except queue.Empty:
                break
        self.cam_name_lbl.configure(text="connecting…", text_color=FG_DIM)
        self.cam_thread = CameraThread(
            index, self.cam_queue,
            name_cb=lambda n: self.after(0, lambda: self.cam_name_lbl.configure(
                text=n, text_color=FG_MID)))
        self.cam_thread.start()
        self.after(350, self._calibrate_canvas)

    def _calibrate_canvas(self):
        try:
            frame = self.cam_queue.get(timeout=0.8)
            self.cam_queue.put(frame)
        except queue.Empty:
            return
        h, w = frame.shape[:2]
        scale = min(1280 / w, 720 / h, 1.0)
        self.native_w = max(1, int(w * scale))
        self.native_h = max(1, int(h * scale))
        cw = max(self.canvas.winfo_width(),  self.native_w)
        ch = max(self.canvas.winfo_height(), self.native_h)
        self._apply_resize(cw, ch)

    def _on_cam_change(self):
        self._start_camera(self.cam_index_var.get())

    # -----------------------------------------------------------------------
    # Capture
    # -----------------------------------------------------------------------

    def _capture(self):
        if self.current_frame is None:
            return
        idx      = len(self.frames)
        filename = os.path.join(self.save_dir, f"frame_{idx:04d}.png")
        Image.fromarray(self.current_frame).save(filename)
        self.frames.append(self.current_frame.copy())
        self._update_timeline()
        self._set_live_mode()
        self._update_title()
        self._set_status(f"captured frame {idx:04d}")

    # -----------------------------------------------------------------------
    # Live mode
    # -----------------------------------------------------------------------

    def _set_live_mode(self):
        self.live_mode = True
        self.playing   = False
        self.btn_live.configure(text_color=ACCENT)
        self.btn_play.configure(text="Play")
        for aid in (self._after_id, self._live_after_id):
            if aid:
                self.after_cancel(aid)
        self._after_id = self._live_after_id = None
        self._live_loop()

    def _live_loop(self):
        if not self.live_mode:
            return
        try:
            frame = self.cam_queue.get_nowait()
            self.current_frame = frame
        except queue.Empty:
            frame = self.current_frame

        if frame is not None:
            self._show(self._apply_onion_live(frame))

        self._live_after_id = self.after(16, self._live_loop)

    def _apply_onion_live(self, live: np.ndarray) -> np.ndarray:
        if not self.onion_enabled.get():
            return live
        n = self.onion_var.get()
        if n == 0 or not self.frames:
            return live
        return blend_onion(live, list(reversed(self.frames[-n:])),
                           self.opacity_var.get())

    def _apply_onion_at(self, idx: int) -> np.ndarray:
        base = self.frames[idx]
        if not self.onion_enabled.get() or idx == 0:
            return base
        n = self.onion_var.get()
        if n == 0:
            return base
        layers = list(reversed(self.frames[max(0, idx - n):idx]))
        return blend_onion(base, layers, self.opacity_var.get())

    # -----------------------------------------------------------------------
    # Scrub / timeline
    # -----------------------------------------------------------------------

    def _on_timeline_scrub(self, val):
        if self._suppress_scrub or not self.frames:
            return
        if self._live_after_id:
            self.after_cancel(self._live_after_id)
            self._live_after_id = None
        self.live_mode = False
        self.btn_live.configure(text_color=FG_DIM)
        idx = max(0, min(int(float(val)), len(self.frames) - 1))
        self._suppress_scrub = True
        self.timeline.set(idx)
        self._suppress_scrub = False
        self._show_saved_frame(idx)

    def _show_saved_frame(self, idx: int):
        if not self.frames or idx >= len(self.frames):
            return
        self._show(self._apply_onion_at(idx))
        self.frame_counter.configure(text=f"{idx + 1} / {len(self.frames)}")

    def _step_frame(self, delta: int):
        if not self.frames:
            return
        self._set_scrub_mode()
        idx = max(0, min(int(self.timeline_var.get()) + delta,
                         len(self.frames) - 1))
        self._suppress_scrub = True
        self.timeline.set(idx)
        self._suppress_scrub = False
        self._show_saved_frame(idx)

    def _set_scrub_mode(self):
        if self.live_mode:
            if self._live_after_id:
                self.after_cancel(self._live_after_id)
                self._live_after_id = None
            self.live_mode = False
            self.btn_live.configure(text_color=FG_DIM)

    # -----------------------------------------------------------------------
    # Playback
    # -----------------------------------------------------------------------

    def _toggle_play(self):
        if self.playing:
            self._stop_play()
        else:
            self._start_play()

    def _start_play(self):
        if not self.frames:
            return
        self._set_scrub_mode()
        self.playing = True
        self.btn_play.configure(text="Stop")
        self.play_index = int(self.timeline_var.get())
        self._play_tick()

    def _stop_play(self):
        self.playing = False
        self.btn_play.configure(text="Play")
        if self._after_id:
            self.after_cancel(self._after_id)
            self._after_id = None

    def _play_tick(self):
        if not self.playing or not self.frames:
            return
        self._show_saved_frame(self.play_index)
        self._suppress_scrub = True
        self.timeline.set(self.play_index)
        self._suppress_scrub = False
        self.play_index = (self.play_index + 1) % len(self.frames)
        self._after_id = self.after(
            max(1, int(1000 / self.fps_var.get())), self._play_tick)

    # -----------------------------------------------------------------------
    # Project management
    # -----------------------------------------------------------------------

    def _new_project(self):
        if self.frames and not messagebox.askyesno(
                "New Project", "Current project will be discarded. Continue?"):
            return
        i = 1
        while True:
            d = os.path.join(CAPTURE_ROOT, f"project_{i:03d}")
            if not os.path.exists(d):
                break
            i += 1
        os.makedirs(d)
        self.save_dir     = d
        self.frames.clear()
        self.project_path = None
        self.project_name = "Unnamed Project"
        self.dir_label.configure(text=self._short_path(d))
        self._reset_timeline()
        self._update_title()
        self.project_name_lbl.configure(text=self.project_name)
        self._set_status(f"new project: {os.path.basename(d)}")

    def _open_project(self):
        path = filedialog.askopenfilename(
            filetypes=[("Onion Film Project", "*.json")],
            initialdir=CAPTURE_ROOT)
        if not path:
            return
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception as e:
            self._set_status(f"load error: {e}")
            return

        save_dir = data.get("save_dir", "")
        if not os.path.isdir(save_dir):
            self._set_status("project save_dir not found on disk")
            return

        frames, i = [], 0
        while True:
            p = os.path.join(save_dir, f"frame_{i:04d}.png")
            if not os.path.exists(p):
                break
            try:
                frames.append(np.array(Image.open(p).convert("RGB")))
            except Exception:
                break
            i += 1

        self.save_dir     = save_dir
        self.frames       = frames
        self.project_path = path
        self.project_name = os.path.splitext(os.path.basename(path))[0]
        self.fps_var.set(data.get("fps", 12))
        self.onion_var.set(data.get("onion_layers", 3))
        self.opacity_var.set(data.get("opacity", 0.5))
        self.dir_label.configure(text=self._short_path(save_dir))
        self._update_timeline()
        self._update_title()
        self.project_name_lbl.configure(text=self.project_name)
        if self.frames:
            self._show_saved_frame(0)
        self._set_status(f"opened: {self.project_name}  ({len(frames)} frames)")

    def _save(self):
        if self.project_path is None:
            self._save_as()
        else:
            self._write_project(self.project_path)

    def _save_as(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("Onion Film Project", "*.json")],
            initialdir=self.save_dir,
            initialfile=f"{self.project_name}.json")
        if not path:
            return
        self.project_path = path
        self.project_name = os.path.splitext(os.path.basename(path))[0]
        self._write_project(path)
        self._update_title()
        self.project_name_lbl.configure(text=self.project_name)

    def _write_project(self, path: str):
        with open(path, "w") as f:
            json.dump({"version":      1,
                       "save_dir":     self.save_dir,
                       "fps":          self.fps_var.get(),
                       "onion_layers": self.onion_var.get(),
                       "opacity":      self.opacity_var.get(),
                       "frame_count":  len(self.frames)}, f, indent=2)
        self._set_status(f"saved: {os.path.basename(path)}")

    # -----------------------------------------------------------------------
    # Export — ProRes 422HQ via ffmpeg, progress from stderr
    # -----------------------------------------------------------------------

    def _export_video(self):
        if not self.frames:
            self._set_status("no frames to export")
            return
        if not shutil.which("ffmpeg"):
            messagebox.showerror("Export", "ffmpeg not found in PATH.")
            return
        out = filedialog.asksaveasfilename(
            defaultextension=".mov",
            filetypes=[("QuickTime Movie", "*.mov")],
            initialdir=self.save_dir,
            initialfile=f"{self.project_name}.mov")
        if not out:
            return
        threading.Thread(target=self._run_export,
                         args=(out, self.fps_var.get(), len(self.frames)),
                         daemon=True).start()

    def _run_export(self, out_path: str, fps: int, total: int):
        self.after(0, lambda: self._set_status("exporting…"))
        self.after(0, lambda: self._set_export_progress(0.0))

        cmd = ["ffmpeg", "-y",
               "-framerate", str(fps),
               "-i", os.path.join(self.save_dir, "frame_%04d.png"),
               "-c:v", "prores_ks",
               "-profile:v", "3",
               "-pix_fmt", "yuv422p10le",
               "-vendor", "apl0",
               out_path]
        try:
            proc = subprocess.Popen(
                cmd, stderr=subprocess.PIPE, text=True,
                bufsize=1, errors="replace")

            for line in proc.stderr:
                if "frame=" in line:
                    try:
                        n = int(line.split("frame=")[1].split()[0].strip())
                        pct = min(n / max(total, 1), 1.0)
                        self.after(0, lambda p=pct: self._set_export_progress(p))
                    except (ValueError, IndexError):
                        pass

            proc.wait()
            if proc.returncode == 0:
                self.after(0, lambda: self._set_export_progress(1.0))
                self.after(0, lambda: self._set_status(
                    f"exported: {os.path.basename(out_path)}"))
            else:
                self.after(0, lambda: self._set_export_progress(0.0))
                self.after(0, lambda: self._set_status("export failed"))
        except Exception as e:
            self.after(0, lambda: self._set_export_progress(0.0))
            self.after(0, lambda: self._set_status(f"export error: {e}"))

    def _set_export_progress(self, value: float):
        self._export_progress_var.set(value)
        if value <= 0.0:
            self._export_pct_lbl.configure(text="—")
        elif value >= 1.0:
            self._export_pct_lbl.configure(text="done")
        else:
            self._export_pct_lbl.configure(text=f"{int(value * 100):3d} %")

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _update_timeline(self):
        n     = len(self.frames)
        steps = max(1, n - 1)
        self._suppress_scrub = True
        self.timeline.configure(to=float(steps), number_of_steps=steps)
        self.timeline.set(n - 1)
        self._suppress_scrub = False
        self.frame_counter.configure(text=f"{n} / {n}")

    def _reset_timeline(self):
        self._suppress_scrub = True
        self.timeline.configure(to=1.0, number_of_steps=1)
        self.timeline.set(0)
        self._suppress_scrub = False
        self.frame_counter.configure(text="0 / 0")
        self.canvas.delete("all")

    def _show(self, frame: np.ndarray):
        if self.display_w == 0 or self.display_h == 0:
            return
        try:
            img   = Image.fromarray(frame).resize(
                (self.display_w, self.display_h), Image.BILINEAR)
            photo = ImageTk.PhotoImage(img)
            self.canvas.delete("all")
            self.canvas.create_image(self._ox, self._oy, anchor="nw", image=photo)
            self.canvas._photo = photo
        except Exception:
            pass

    def _choose_dir(self):
        d = filedialog.askdirectory(initialdir=self.save_dir)
        if d:
            self.save_dir = d
            self.dir_label.configure(text=self._short_path(d))

    def _set_status(self, msg: str):
        self.status_var.set(f"  {msg}")

    @staticmethod
    def _short_path(path: str, max_len: int = 40) -> str:
        return path if len(path) <= max_len else "…" + path[-(max_len - 1):]

    def _on_close(self):
        for aid in (self._live_after_id, self._after_id, self._resize_job):
            if aid:
                self.after_cancel(aid)
        if self.cam_thread:
            self.cam_thread.stop()
            self.cam_thread.join(timeout=1.0)
        self.destroy()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app = StopMotionApp()
    app.protocol("WM_DELETE_WINDOW", app._on_close)
    app.after(450, app._set_live_mode)
    app.mainloop()


if __name__ == "__main__":
    main()
