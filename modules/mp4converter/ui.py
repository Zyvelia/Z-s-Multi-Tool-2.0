# modules/mp4_to_gif/ui.py

import os
import threading
import subprocess
import sys

import customtkinter as ctk
from tkinter import filedialog, messagebox

from core import theme
from core import paths
from . import converter

# Drag-and-drop is optional — falls back to Browse-only if the package
# isn't installed (`pip install tkinterdnd2`). CTk's root isn't a
# TkinterDnD.Tk subclass, but TkinterDnD._require(window) retrofits tkdnd
# onto an existing Tk interpreter without needing to change core/app.py.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND_IMPORTED = True
except ImportError:
    _DND_IMPORTED = False

SETTINGS_FILE = paths.data_path("mp4_to_gif", "settings.json")

VIDEO_TYPES = [
    ("Video files", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"),
    ("All files", "*.*"),
]


def _load_settings() -> dict:
    import json
    defaults = {
        "fps": 15, "width": 480, "loop": True, "dither": "bayer", "last_dir": "", "output_dir": "",
        "fit_box": False, "max_height": 320,
        "compress": False, "target_size_mb": 10,
    }
    try:
        if os.path.isfile(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                defaults.update(json.load(f))
    except Exception as e:
        print(f"[mp4_to_gif] settings load failed: {e}")
    return defaults


def _save_settings(data: dict):
    import json
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[mp4_to_gif] settings save failed: {e}")


def _fmt_time(seconds: float) -> str:
    if seconds is None:
        return "0:00"
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


class Mp4ToGifPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=theme.BG)
        self.manager = manager
        self.settings = _load_settings()

        self.input_path = None
        self.duration = None          # probed source duration, seconds
        self.cancel_event = None
        self.converting = False
        self.last_output_path = None
        self.output_dir = self.settings.get("output_dir") or ""
        self._dnd_active = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        self._build_header()
        self._build_dropzone()
        self._build_options()
        self._build_output_panel()
        self._build_progress()

        self._try_enable_dnd()

        if not converter.find_ffmpeg():
            self._warn_no_ffmpeg()

    # =====================================================
    # HEADER
    # =====================================================

    def _build_header(self):
        header = ctk.CTkFrame(self, **theme.panel_style())
        header.grid(row=0, column=0, sticky="ew", padx=theme.PAD_LG, pady=(theme.PAD_LG, theme.PAD))
        header.grid_columnconfigure(0, weight=1)

        box = ctk.CTkFrame(header, fg_color="transparent")
        box.grid(row=0, column=0, sticky="w", padx=theme.PAD_LG, pady=theme.PAD)

        ctk.CTkLabel(
            box, text="🎞  MP4 to GIF", font=theme.font(22, "bold"), text_color=theme.TEXT
        ).pack(anchor="w")

        ctk.CTkLabel(
            box, text="Pick a video, adjust the settings, convert.",
            font=theme.font(12), text_color=theme.MUTED
        ).pack(anchor="w")

        ctk.CTkButton(
            header, text="←  Back", width=100, height=34,
            command=lambda: self.manager.show_page("catalog"),
            **theme.secondary_button_style()
        ).grid(row=0, column=1, padx=theme.PAD_LG)

    # =====================================================
    # FILE PICKER / DROPZONE
    # =====================================================

    def _build_dropzone(self):
        zone = ctk.CTkFrame(self, **theme.panel_style(), border_width=1, border_color=theme.BORDER)
        zone.grid(row=1, column=0, sticky="ew", padx=theme.PAD_LG, pady=(0, theme.PAD))
        zone.grid_columnconfigure(0, weight=1)
        self.dropzone = zone

        self.file_label = ctk.CTkLabel(
            zone, text="No file selected", font=theme.font(14),
            text_color=theme.MUTED, anchor="w"
        )
        self.file_label.grid(row=0, column=0, sticky="ew", padx=theme.PAD_LG, pady=(theme.PAD_LG, 4))

        self.file_meta_label = ctk.CTkLabel(
            zone, text="", font=theme.font(11), text_color=theme.FAINT, anchor="w"
        )
        self.file_meta_label.grid(row=1, column=0, sticky="ew", padx=theme.PAD_LG, pady=(0, 4))

        # Filled in by _try_enable_dnd() only if tkinterdnd2 is actually
        # available and initializes successfully — stays blank otherwise
        # so we never claim a feature that silently doesn't work.
        self.dnd_hint_label = ctk.CTkLabel(
            zone, text="", font=theme.font(10), text_color=theme.FAINT, anchor="w"
        )
        self.dnd_hint_label.grid(row=2, column=0, sticky="ew", padx=theme.PAD_LG, pady=(0, theme.PAD_LG))

        ctk.CTkButton(
            zone, text="Browse for video…", height=36, width=180,
            command=self.browse_file, **theme.primary_button_style()
        ).grid(row=0, column=1, rowspan=3, padx=theme.PAD_LG, pady=theme.PAD)

    def browse_file(self):
        start_dir = self.settings.get("last_dir") or None
        path = filedialog.askopenfilename(title="Select a video", filetypes=VIDEO_TYPES, initialdir=start_dir)
        if path:
            self._set_input(path)

    def _set_input(self, path):
        self.input_path = path
        self.settings["last_dir"] = os.path.dirname(path)
        _save_settings(self.settings)

        self.file_label.configure(text=os.path.basename(path), text_color=theme.TEXT)
        self.file_meta_label.configure(text="Reading video info…")
        self.status_label.configure(text="")
        self.last_output_path = None
        self.open_output_btn.configure(state="disabled")

        threading.Thread(target=self._probe_worker, args=(path,), daemon=True).start()

    def _probe_worker(self, path):
        info = converter.probe(path)
        self.after(0, lambda: self._on_probed(info))

    def _on_probed(self, info):
        self.duration = info.get("duration")
        w, h = info.get("width"), info.get("height")

        parts = []
        if self.duration:
            parts.append(f"{_fmt_time(self.duration)} long")
        if w and h:
            parts.append(f"{w}×{h} source")
        self.file_meta_label.configure(text="  •  ".join(parts) or "Duration/resolution unavailable")

        if self.duration:
            self.trim_end_slider.configure(from_=0, to=self.duration)
            self.trim_start_slider.configure(from_=0, to=self.duration)
            self.trim_start_slider.set(0)
            self.trim_end_slider.set(self.duration)
            self._update_trim_labels()

    # =====================================================
    # OPTIONS
    # =====================================================

    def _build_options(self):
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=2, column=0, sticky="nsew", padx=theme.PAD_LG, pady=(0, theme.PAD))
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=1)
        row.grid_rowconfigure(0, weight=1)

        self._build_quality_panel(row)
        self._build_trim_panel(row)

    def _build_quality_panel(self, parent):
        panel = ctk.CTkScrollableFrame(parent, height=260, **theme.panel_style())
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, theme.PAD // 2))
        panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            panel, text="QUALITY", font=theme.font(11, "bold"), text_color=theme.FAINT, anchor="w"
        ).grid(row=0, column=0, sticky="ew", padx=theme.PAD, pady=(theme.PAD, 6))

        # ---- FPS ----
        fps_row = ctk.CTkFrame(panel, fg_color="transparent")
        fps_row.grid(row=1, column=0, sticky="ew", padx=theme.PAD)
        fps_row.grid_columnconfigure(0, weight=1)

        self.fps_value_label = ctk.CTkLabel(fps_row, text="", font=theme.font(11), text_color=theme.TEXT)
        self.fps_value_label.grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(fps_row, text="Frame rate", font=theme.font(11), text_color=theme.MUTED).grid(row=0, column=0, sticky="w")

        self.fps_slider = ctk.CTkSlider(
            panel, from_=5, to=30, number_of_steps=25, height=14, command=self._on_fps_change
        )
        self.fps_slider.set(self.settings.get("fps", 15))
        self.fps_slider.grid(row=2, column=0, sticky="ew", padx=theme.PAD, pady=(3, 6))
        self._on_fps_change(self.fps_slider.get())

        # ---- Width ----
        width_row = ctk.CTkFrame(panel, fg_color="transparent")
        width_row.grid(row=3, column=0, sticky="ew", padx=theme.PAD)
        width_row.grid_columnconfigure(0, weight=1)

        self.width_value_label = ctk.CTkLabel(width_row, text="", font=theme.font(11), text_color=theme.TEXT)
        self.width_value_label.grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(width_row, text="Output width", font=theme.font(11), text_color=theme.MUTED).grid(row=0, column=0, sticky="w")

        self.width_slider = ctk.CTkSlider(
            panel, from_=120, to=1080, number_of_steps=96, height=14, command=self._on_width_change
        )
        self.width_slider.set(self.settings.get("width", 480))
        self.width_slider.grid(row=4, column=0, sticky="ew", padx=theme.PAD, pady=(3, 6))
        self._on_width_change(self.width_slider.get())

        # ---- Loop / dither ----
        opt_row = ctk.CTkFrame(panel, fg_color="transparent")
        opt_row.grid(row=5, column=0, sticky="ew", padx=theme.PAD, pady=(0, 8))

        self.loop_var = ctk.BooleanVar(value=self.settings.get("loop", True))
        ctk.CTkCheckBox(
            opt_row, text="Loop forever", variable=self.loop_var,
            font=theme.font(11), text_color=theme.TEXT, checkbox_width=16, checkbox_height=16,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER
        ).pack(side="left")

        ctk.CTkLabel(opt_row, text="  Smaller width and lower FPS = smaller file size.",
                     font=theme.font(9), text_color=theme.FAINT).pack(side="left", padx=(8, 0))

        self._build_compress_controls(panel)

    def _build_compress_controls(self, panel):
        """
        Two independent extras layered onto the basic width/fps controls:
          - "Fit inside a box" — constrains output to width x max-height
            (e.g. 320x320) instead of a fixed width with auto height.
          - "Compress to a target size" — after converting, if the GIF
            is over the limit, automatically retries at lower quality
            (see converter.convert_within_size) until it fits or the
            attempt budget runs out.
        Both are opt-in checkboxes so the simple case (just move the
        sliders) still behaves exactly as before.
        """
        sep = ctk.CTkFrame(panel, height=1, fg_color=theme.BORDER)
        sep.grid(row=6, column=0, sticky="ew", padx=theme.PAD, pady=(0, 8))

        # ---- Fit inside a box (max height) ----
        box_row = ctk.CTkFrame(panel, fg_color="transparent")
        box_row.grid(row=7, column=0, sticky="ew", padx=theme.PAD)
        box_row.grid_columnconfigure(1, weight=1)

        self.fit_box_var = ctk.BooleanVar(value=self.settings.get("fit_box", False))
        ctk.CTkCheckBox(
            box_row, text="Fit inside a box (max height)", variable=self.fit_box_var,
            font=theme.font(11), text_color=theme.TEXT, checkbox_width=16, checkbox_height=16,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self._on_fit_box_toggle,
        ).grid(row=0, column=0, sticky="w")

        self.max_height_entry = ctk.CTkEntry(box_row, width=52, height=22, font=theme.font(11))
        self.max_height_entry.insert(0, str(self.settings.get("max_height", 320)))
        self.max_height_entry.grid(row=0, column=2, sticky="e")
        ctk.CTkLabel(box_row, text="max height px", font=theme.font(10), text_color=theme.MUTED).grid(
            row=0, column=1, sticky="e", padx=(0, 6)
        )

        ctk.CTkLabel(
            box_row,
            text="Output width above becomes the box's max width too — e.g. 320 + 320 keeps everything within 320×320.",
            font=theme.font(9), text_color=theme.FAINT, wraplength=280, justify="left"
        ).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(2, 8))

        # ---- Compress to a target size ----
        size_row = ctk.CTkFrame(panel, fg_color="transparent")
        size_row.grid(row=8, column=0, sticky="ew", padx=theme.PAD, pady=(0, theme.PAD))
        size_row.grid_columnconfigure(1, weight=1)

        self.compress_var = ctk.BooleanVar(value=self.settings.get("compress", False))
        ctk.CTkCheckBox(
            size_row, text="Compress to under", variable=self.compress_var,
            font=theme.font(11), text_color=theme.TEXT, checkbox_width=16, checkbox_height=16,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            command=self._on_compress_toggle,
        ).grid(row=0, column=0, sticky="w")

        self.target_size_entry = ctk.CTkEntry(size_row, width=52, height=22, font=theme.font(11))
        self.target_size_entry.insert(0, str(self.settings.get("target_size_mb", 10)))
        self.target_size_entry.grid(row=0, column=2, sticky="e")
        ctk.CTkLabel(size_row, text="MB", font=theme.font(10), text_color=theme.MUTED).grid(
            row=0, column=1, sticky="e", padx=(0, 6)
        )

        ctk.CTkLabel(
            size_row,
            text="Automatically lowers width/fps/colors and re-converts until it fits, up to a few tries.",
            font=theme.font(9), text_color=theme.FAINT, wraplength=280, justify="left"
        ).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(2, 0))

        self._on_fit_box_toggle()
        self._on_compress_toggle()

    def _on_fit_box_toggle(self):
        state = "normal" if self.fit_box_var.get() else "disabled"
        self.max_height_entry.configure(state=state)

    def _on_compress_toggle(self):
        state = "normal" if self.compress_var.get() else "disabled"
        self.target_size_entry.configure(state=state)

    def _on_fps_change(self, value):
        self.fps_value_label.configure(text=f"{int(value)} fps")

    def _on_width_change(self, value):
        self.width_value_label.configure(text=f"{int(value)} px")

    def _build_trim_panel(self, parent):
        panel = ctk.CTkScrollableFrame(parent, height=260, **theme.panel_style())
        panel.grid(row=0, column=1, sticky="nsew", padx=(theme.PAD // 2, 0))
        panel.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            panel, text="TRIM (OPTIONAL)", font=theme.font(11, "bold"), text_color=theme.FAINT, anchor="w"
        ).grid(row=0, column=0, sticky="ew", padx=theme.PAD, pady=(theme.PAD, 6))

        start_row = ctk.CTkFrame(panel, fg_color="transparent")
        start_row.grid(row=1, column=0, sticky="ew", padx=theme.PAD)
        start_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(start_row, text="Start", font=theme.font(11), text_color=theme.MUTED).grid(row=0, column=0, sticky="w")
        self.trim_start_label = ctk.CTkLabel(start_row, text="0:00", font=theme.font(11), text_color=theme.TEXT)
        self.trim_start_label.grid(row=0, column=1, sticky="e")

        self.trim_start_slider = ctk.CTkSlider(
            panel, from_=0, to=1, number_of_steps=200, height=14, command=lambda v: self._update_trim_labels()
        )
        self.trim_start_slider.set(0)
        self.trim_start_slider.grid(row=2, column=0, sticky="ew", padx=theme.PAD, pady=(3, 6))

        end_row = ctk.CTkFrame(panel, fg_color="transparent")
        end_row.grid(row=3, column=0, sticky="ew", padx=theme.PAD)
        end_row.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(end_row, text="End", font=theme.font(11), text_color=theme.MUTED).grid(row=0, column=0, sticky="w")
        self.trim_end_label = ctk.CTkLabel(end_row, text="0:00", font=theme.font(11), text_color=theme.TEXT)
        self.trim_end_label.grid(row=0, column=1, sticky="e")

        self.trim_end_slider = ctk.CTkSlider(
            panel, from_=0, to=1, number_of_steps=200, height=14, command=lambda v: self._update_trim_labels()
        )
        self.trim_end_slider.set(1)
        self.trim_end_slider.grid(row=4, column=0, sticky="ew", padx=theme.PAD, pady=(3, 6))

        ctk.CTkLabel(
            panel, text="Select a video to enable trimming — full length converts by default.",
            font=theme.font(9), text_color=theme.FAINT, wraplength=280, justify="left"
        ).grid(row=5, column=0, sticky="ew", padx=theme.PAD, pady=(0, theme.PAD))

    def _update_trim_labels(self):
        start = self.trim_start_slider.get()
        end = self.trim_end_slider.get()
        # keep start strictly before end
        if end <= start and self.duration:
            end = min(start + 0.5, self.duration)
            self.trim_end_slider.set(end)
        self.trim_start_label.configure(text=_fmt_time(start))
        self.trim_end_label.configure(text=_fmt_time(end))

    # =====================================================
    # OUTPUT FOLDER
    # =====================================================

    def _build_output_panel(self):
        panel = ctk.CTkFrame(self, **theme.panel_style())
        panel.grid(row=3, column=0, sticky="ew", padx=theme.PAD_LG, pady=(0, theme.PAD))
        panel.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            panel, text="OUTPUT FOLDER", font=theme.font(11, "bold"), text_color=theme.FAINT, anchor="w"
        ).grid(row=0, column=0, columnspan=3, sticky="ew", padx=theme.PAD_LG, pady=(theme.PAD_LG, 4))

        self.output_dir_label = ctk.CTkLabel(
            panel, text="", font=theme.font(12), text_color=theme.TEXT, anchor="w"
        )
        self.output_dir_label.grid(row=1, column=0, columnspan=2, sticky="ew", padx=theme.PAD_LG, pady=(0, theme.PAD_LG))

        ctk.CTkButton(
            panel, text="Browse…", width=100, height=32,
            command=self.browse_output_folder, **theme.secondary_button_style()
        ).grid(row=1, column=2, padx=(0, theme.PAD // 2), pady=(0, theme.PAD_LG))

        ctk.CTkButton(
            panel, text="Use source folder", width=140, height=32,
            command=self.clear_output_folder, **theme.secondary_button_style()
        ).grid(row=1, column=3, padx=(0, theme.PAD_LG), pady=(0, theme.PAD_LG))

        self._refresh_output_dir_label()

    def _refresh_output_dir_label(self):
        if self.output_dir:
            self.output_dir_label.configure(text=self.output_dir, text_color=theme.TEXT)
        else:
            self.output_dir_label.configure(
                text="(same folder as the source video)", text_color=theme.MUTED
            )

    def browse_output_folder(self):
        start_dir = self.output_dir or self.settings.get("last_dir") or None
        chosen = filedialog.askdirectory(title="Choose output folder", initialdir=start_dir)
        if chosen:
            self.output_dir = chosen
            self.settings["output_dir"] = chosen
            _save_settings(self.settings)
            self._refresh_output_dir_label()

    def clear_output_folder(self):
        self.output_dir = ""
        self.settings["output_dir"] = ""
        _save_settings(self.settings)
        self._refresh_output_dir_label()

    @staticmethod
    def _unique_path(path: str) -> str:
        """Avoids silently overwriting an existing GIF — appends (1), (2)… """
        if not os.path.exists(path):
            return path
        base, ext = os.path.splitext(path)
        n = 1
        while os.path.exists(f"{base} ({n}){ext}"):
            n += 1
        return f"{base} ({n}){ext}"

    # =====================================================
    # DRAG AND DROP
    # =====================================================

    def _try_enable_dnd(self):
        if not _DND_IMPORTED:
            return
        try:
            root = self.winfo_toplevel()
            TkinterDnD._require(root)
            self.dropzone.drop_target_register(DND_FILES)
            self.dropzone.dnd_bind("<<Drop>>", self._on_drop)
            self._dnd_active = True
            self.dnd_hint_label.configure(text="…or drag & drop a video file here")
        except Exception as e:
            print(f"[mp4_to_gif] drag-and-drop unavailable: {e}")

    def _on_drop(self, event):
        paths = self._parse_dnd_paths(event.data)
        if paths:
            self._set_input(paths[0])

    @staticmethod
    def _parse_dnd_paths(data: str):
        """tkinterdnd2 wraps paths containing spaces in {curly braces}
        and separates multiple paths with spaces — this splits that
        format properly instead of a naive .split(' ')."""
        paths, buf, in_brace = [], "", False
        for ch in data:
            if ch == "{":
                in_brace = True
                buf = ""
            elif ch == "}":
                in_brace = False
                paths.append(buf)
                buf = ""
            elif ch == " " and not in_brace:
                if buf:
                    paths.append(buf)
                    buf = ""
            else:
                buf += ch
        if buf:
            paths.append(buf)
        return paths

    # =====================================================
    # PROGRESS / ACTIONS
    # =====================================================

    def _build_progress(self):
        panel = ctk.CTkFrame(self, **theme.panel_style())
        panel.grid(row=4, column=0, sticky="ew", padx=theme.PAD_LG, pady=(0, theme.PAD_LG))
        panel.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(
            panel, text="", font=theme.font(12), text_color=theme.MUTED, anchor="w"
        )
        self.status_label.grid(row=0, column=0, sticky="ew", padx=theme.PAD_LG, pady=(theme.PAD_LG, 4))

        self.progress_bar = ctk.CTkProgressBar(panel, progress_color=theme.ACCENT)
        self.progress_bar.set(0)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=theme.PAD_LG, pady=(0, theme.PAD_LG))

        btn_row = ctk.CTkFrame(panel, fg_color="transparent")
        btn_row.grid(row=0, column=1, rowspan=2, padx=theme.PAD_LG)

        self.convert_btn = ctk.CTkButton(
            btn_row, text="Convert to GIF", height=38, width=160,
            command=self.start_conversion, **theme.primary_button_style()
        )
        self.convert_btn.pack(side="left", padx=(0, 8))

        self.cancel_btn = ctk.CTkButton(
            btn_row, text="Cancel", height=38, width=90, state="disabled",
            command=self.cancel_conversion, **theme.danger_button_style()
        )
        self.cancel_btn.pack(side="left", padx=(0, 8))

        self.open_output_btn = ctk.CTkButton(
            btn_row, text="Show in folder", height=38, width=130, state="disabled",
            command=self.open_output_folder, **theme.secondary_button_style()
        )
        self.open_output_btn.pack(side="left")

    def _warn_no_ffmpeg(self):
        self.status_label.configure(
            text="⚠ ffmpeg not found — add ffmpeg.exe to a 'bin' folder next to the app, or install it on PATH.",
            text_color=theme.ERROR,
        )
        self.convert_btn.configure(state="disabled")

    # =====================================================
    # CONVERSION
    # =====================================================

    def start_conversion(self):
        if self.converting:
            return

        if not self.input_path:
            messagebox.showwarning("No video selected", "Pick a video file first.")
            return

        fps = int(self.fps_slider.get())
        width = int(self.width_slider.get())
        loop = self.loop_var.get()

        fit_box = self.fit_box_var.get()
        max_height = None
        if fit_box:
            try:
                max_height = max(16, int(float(self.max_height_entry.get())))
            except ValueError:
                messagebox.showwarning("Invalid max height", "Max height must be a number, e.g. 320.")
                return

        compress = self.compress_var.get()
        target_size_mb = None
        if compress:
            try:
                target_size_mb = float(self.target_size_entry.get())
                if target_size_mb <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showwarning("Invalid target size", "Target size must be a number of MB, e.g. 10.")
                return

        start = end = None
        if self.duration:
            start = self.trim_start_slider.get()
            end = self.trim_end_slider.get()
            # trim only if the user actually narrowed the range
            if start <= 0.01 and end >= self.duration - 0.01:
                start = end = None

        out_dir = self.output_dir or os.path.dirname(self.input_path)
        try:
            os.makedirs(out_dir, exist_ok=True)
        except Exception as e:
            messagebox.showerror("Can't use that folder", str(e))
            return

        default_name = os.path.splitext(os.path.basename(self.input_path))[0] + ".gif"
        output_path = self._unique_path(os.path.join(out_dir, default_name))

        self.settings.update({
            "fps": fps, "width": width, "loop": loop,
            "fit_box": fit_box, "max_height": max_height or self.settings.get("max_height", 320),
            "compress": compress, "target_size_mb": target_size_mb or self.settings.get("target_size_mb", 10),
        })
        _save_settings(self.settings)

        self.converting = True
        self.cancel_event = threading.Event()
        self.convert_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.open_output_btn.configure(state="disabled")
        self.progress_bar.set(0)
        self.status_label.configure(text="Converting…  (building palette)", text_color=theme.MUTED)

        threading.Thread(
            target=self._convert_worker,
            args=(self.input_path, output_path, fps, width, max_height, target_size_mb, start, end, loop),
            daemon=True,
        ).start()

    def _convert_worker(self, input_path, output_path, fps, width, max_height, target_size_mb, start, end, loop):
        def on_progress(frac):
            self.after(0, lambda: self._on_progress(frac))

        def on_attempt(attempt, attempt_fps, attempt_width, attempt_colors):
            self.after(0, lambda: self._on_attempt(attempt, attempt_fps, attempt_width, attempt_colors))

        try:
            if target_size_mb:
                _, size, attempts, met_target = converter.convert_within_size(
                    input_path, output_path,
                    max_size_mb=target_size_mb,
                    fps=fps, width=width, max_height=max_height,
                    start=start, end=end, loop=loop,
                    on_progress=on_progress, on_attempt=on_attempt, cancel_event=self.cancel_event,
                )
                self.after(0, lambda: self._on_done(output_path, attempts=attempts, met_target=met_target,
                                                      target_size_mb=target_size_mb))
            else:
                converter.convert(
                    input_path, output_path,
                    fps=fps, width=width, max_height=max_height, start=start, end=end, loop=loop,
                    on_progress=on_progress, cancel_event=self.cancel_event,
                )
                self.after(0, lambda: self._on_done(output_path))

        except converter.ConversionCancelled:
            self.after(0, self._on_cancelled)

        except converter.ConversionError as e:
            self.after(0, lambda: self._on_error(str(e)))

        except Exception as e:
            self.after(0, lambda: self._on_error(str(e)))

    def _on_progress(self, frac):
        self.progress_bar.set(frac)
        stage = "building palette" if frac < 0.45 else "encoding gif"
        prefix = getattr(self, "_attempt_prefix", "Converting…")
        self.status_label.configure(text=f"{prefix}  ({stage}, {int(frac * 100)}%)")

    def _on_attempt(self, attempt, fps, width, colors):
        suffix = "" if attempt == 1 else f", attempt {attempt}"
        self._attempt_prefix = f"Compressing…  ({width}px, {fps}fps{suffix})"
        self.status_label.configure(text=self._attempt_prefix)

    def _on_done(self, output_path, attempts=None, met_target=None, target_size_mb=None):
        self.converting = False
        self.last_output_path = output_path
        self.convert_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.open_output_btn.configure(state="normal")
        self.progress_bar.set(1)
        self._attempt_prefix = "Converting…"

        size_mb = os.path.getsize(output_path) / (1024 * 1024) if os.path.isfile(output_path) else 0

        if attempts is not None:
            if met_target:
                extra = "" if attempts == 1 else f" after {attempts} attempts"
                self.status_label.configure(
                    text=f"✓ Done — {os.path.basename(output_path)} ({size_mb:.1f} MB, under {target_size_mb:g} MB{extra})",
                    text_color=theme.SUCCESS,
                )
            else:
                self.status_label.configure(
                    text=(f"⚠ Done, but couldn't get under {target_size_mb:g} MB — smallest result was "
                          f"{os.path.basename(output_path)} ({size_mb:.1f} MB) after {attempts} attempts. "
                          f"Try a shorter trim or a smaller box."),
                    text_color=theme.MUTED,
                )
            return

        self.status_label.configure(
            text=f"✓ Done — saved {os.path.basename(output_path)} ({size_mb:.1f} MB)",
            text_color=theme.SUCCESS,
        )

    def _on_cancelled(self):
        self.converting = False
        self.convert_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.progress_bar.set(0)
        self.status_label.configure(text="Cancelled.", text_color=theme.MUTED)

    def _on_error(self, message):
        self.converting = False
        self.convert_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        self.progress_bar.set(0)
        self.status_label.configure(text="✗ Conversion failed — see below.", text_color=theme.ERROR)
        messagebox.showerror("Conversion failed", message[-1500:])

    def cancel_conversion(self):
        if self.cancel_event:
            self.cancel_event.set()
        self.cancel_btn.configure(state="disabled")
        self.status_label.configure(text="Cancelling…", text_color=theme.MUTED)

    def open_output_folder(self):
        if not self.last_output_path:
            return
        folder = os.path.dirname(self.last_output_path)
        try:
            if sys.platform == "win32":
                subprocess.run(["explorer", "/select,", self.last_output_path])
            elif sys.platform == "darwin":
                subprocess.run(["open", folder])
            else:
                subprocess.run(["xdg-open", folder])
        except Exception as e:
            print(f"[mp4_to_gif] open folder failed: {e}")
