import customtkinter as ctk
from tkinter import filedialog
import os
import re
import json
import threading

try:
    import yt_dlp as youtube_dl
except ImportError:
    try:
        import youtube_dl
    except ImportError:
        youtube_dl = None

from core import theme
from core import paths

# ── Colours (shared app theme) ───────────────────────────────────────────
BG      = theme.BG
PANEL   = theme.PANEL
PANEL_2 = theme.PANEL_2
ACCENT  = theme.ACCENT
DANGER  = theme.DANGER
SUCCESS = theme.SUCCESS
TEXT    = theme.TEXT
MUTED   = theme.MUTED

_BTN        = dict(fg_color=PANEL_2, hover_color=ACCENT,    text_color=TEXT,    height=34, corner_radius=8)
_BTN_ACCENT = dict(fg_color=ACCENT,  hover_color=theme.ACCENT_DIM, text_color="white", height=34, corner_radius=8)
_BTN_DANGER = dict(fg_color=DANGER,  hover_color=theme.DANGER_HOVER, text_color="white", height=34, corner_radius=8)

SETTINGS_FILE = paths.migrate_legacy_file(
    paths.data_path("yt_downloader", "downloader_settings.json"),
    "modules", "yt_downloader", "downloader_settings.json"
)


def _make_btn(parent, text, cmd, **ov):
    return ctk.CTkButton(parent, text=text, command=cmd, **{**_BTN, **ov})


def _find_ffmpeg() -> str:
    """Find ffmpeg — checks local bin folder then falls back to system PATH."""
    import shutil
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "bin"),
        os.path.join(os.path.dirname(here), "bin"),
    ]
    for d in candidates:
        if os.path.isfile(os.path.join(d, "ffmpeg.exe")):
            return d
    # Fall back to system PATH — just return None so yt-dlp finds it itself
    if shutil.which("ffmpeg"):
        return None   # yt-dlp will find it via PATH when ffmpeg_location is None
    return None       # still let yt-dlp try


def _sanitize(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()


# ── Main page ─────────────────────────────────────────────────────────────────

class YTDownloaderPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=BG)
        self.manager      = manager
        self.ffmpeg_dir   = _find_ffmpeg()
        self._downloading = False

        self._build_ui()
        self._load_settings()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        self._build_url_row()
        self._build_options_row()
        self._build_paths_row()
        self._build_log()

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        header.pack(fill="x", padx=12, pady=(12, 4))

        ctk.CTkLabel(header, text="▶  YouTube Downloader",
                     font=("Segoe UI", 22, "bold"), text_color=TEXT
                     ).pack(side="left", padx=14, pady=10)

        self._status_lbl = ctk.CTkLabel(header, text="Idle", text_color=MUTED)
        self._status_lbl.pack(side="right", padx=14)

    def _build_url_row(self):
        panel = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        panel.pack(fill="x", padx=12, pady=(0, 4))

        inner = ctk.CTkFrame(panel, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(inner, text="URL", text_color=MUTED,
                     font=("Segoe UI", 12)).pack(side="left", padx=(0, 8))

        self._url_entry = ctk.CTkEntry(
            inner, placeholder_text="Paste YouTube video or playlist URL…",
            corner_radius=8, fg_color=PANEL_2, text_color=TEXT,
            border_color=PANEL_2)
        self._url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self._dl_btn = _make_btn(inner, "⬇  Download", self._start_download,
                                 **_BTN_ACCENT, width=130)
        self._dl_btn.pack(side="left")

    def _build_options_row(self):
        panel = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        panel.pack(fill="x", padx=12, pady=(0, 4))

        inner = ctk.CTkFrame(panel, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=10)

        # ── Type ──
        ctk.CTkLabel(inner, text="Type", text_color=MUTED,
                     font=("Segoe UI", 12)).pack(side="left", padx=(0, 6))

        self._type_var = ctk.StringVar(value="video")
        for label, val in [("Single Video", "video"), ("Playlist", "playlist")]:
            ctk.CTkRadioButton(
                inner, text=label, variable=self._type_var, value=val,
                text_color=TEXT, fg_color=ACCENT, hover_color="#2f7fd6"
            ).pack(side="left", padx=6)

        # ── Format ──
        ctk.CTkLabel(inner, text="Format", text_color=MUTED,
                     font=("Segoe UI", 12)).pack(side="left", padx=(20, 6))

        self._fmt_var = ctk.StringVar(value="mp3")
        for label, val in [("MP3", "mp3"), ("MP4", "mp4")]:
            ctk.CTkRadioButton(
                inner, text=label, variable=self._fmt_var, value=val,
                text_color=TEXT, fg_color=ACCENT, hover_color="#2f7fd6"
            ).pack(side="left", padx=6)

        # ── Quality (MP3) ──
        ctk.CTkLabel(inner, text="Quality", text_color=MUTED,
                     font=("Segoe UI", 12)).pack(side="left", padx=(20, 6))

        self._quality_var = ctk.StringVar(value="192")
        ctk.CTkOptionMenu(
            inner, variable=self._quality_var,
            values=["320", "256", "192", "128", "96"],
            fg_color=PANEL_2, button_color=ACCENT,
            button_hover_color="#2f7fd6", text_color=TEXT,
            width=80
        ).pack(side="left")

        ctk.CTkLabel(inner, text="kbps", text_color=MUTED,
                     font=("Segoe UI", 11)).pack(side="left", padx=(4, 0))

    def _build_paths_row(self):
        panel = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        panel.pack(fill="x", padx=12, pady=(0, 4))

        inner = ctk.CTkFrame(panel, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=10)

        # ── Output dir ──
        out_col = ctk.CTkFrame(inner, fg_color="transparent")
        out_col.pack(side="left", fill="x", expand=True, padx=(0, 12))

        ctk.CTkLabel(out_col, text="📁  Output Folder", text_color=MUTED,
                     font=("Segoe UI", 11)).pack(anchor="w", pady=(0, 4))

        out_row = ctk.CTkFrame(out_col, fg_color="transparent")
        out_row.pack(fill="x")

        self._out_entry = ctk.CTkEntry(
            out_row, fg_color=PANEL_2, text_color=TEXT,
            border_color=PANEL_2, corner_radius=8, state="readonly")
        self._out_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        _make_btn(out_row, "Browse", self._browse_output, width=80).pack(side="left")

        # ── Cookie file ──
        cookie_col = ctk.CTkFrame(inner, fg_color="transparent")
        cookie_col.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(cookie_col, text="🍪  Cookie File (optional)", text_color=MUTED,
                     font=("Segoe UI", 11)).pack(anchor="w", pady=(0, 4))

        cookie_row = ctk.CTkFrame(cookie_col, fg_color="transparent")
        cookie_row.pack(fill="x")

        self._cookie_entry = ctk.CTkEntry(
            cookie_row, fg_color=PANEL_2, text_color=TEXT,
            border_color=PANEL_2, corner_radius=8, state="readonly")
        self._cookie_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        _make_btn(cookie_row, "Browse", self._browse_cookie, width=80).pack(side="left")
        _make_btn(cookie_row, "✕", self._clear_cookie, width=36).pack(side="left", padx=(4, 0))

    def _build_log(self):
        panel = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        panel.pack(fill="x", expand=False, padx=12, pady=(0, 12))

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 4))

        ctk.CTkLabel(top, text="Download Log",
                     font=("Segoe UI", 13, "bold"), text_color=TEXT).pack(side="left")

        _make_btn(top, "🗑 Clear", self._clear_log, width=80).pack(side="right")

        self._log = ctk.CTkTextbox(
            panel, fg_color=PANEL_2, text_color=TEXT,
            corner_radius=8, font=("Consolas", 11), height=140, state="disabled")
        self._log.pack(fill="x", expand=False, padx=10, pady=(0, 10))

        # Progress bar
        self._progress = ctk.CTkProgressBar(
            panel, progress_color=ACCENT, fg_color=PANEL_2, corner_radius=4)
        self._progress.set(0)
        self._progress.pack(fill="x", padx=10, pady=(0, 10))

    # ── Settings ──────────────────────────────────────────────────────────────

    def _load_settings(self):
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE) as f:
                    s = json.load(f)
                self._set_entry(self._out_entry, s.get("output_dir", os.path.expanduser("~")))
                self._set_entry(self._cookie_entry, s.get("cookie_file", ""))
                self._fmt_var.set(s.get("format", "mp3"))
                self._type_var.set(s.get("type", "video"))
                self._quality_var.set(s.get("quality", "192"))
            else:
                self._set_entry(self._out_entry, os.path.expanduser("~"))
        except Exception:
            self._set_entry(self._out_entry, os.path.expanduser("~"))

    def _save_settings(self):
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump({
                    "output_dir":  self._out_entry.get(),
                    "cookie_file": self._cookie_entry.get(),
                    "format":      self._fmt_var.get(),
                    "type":        self._type_var.get(),
                    "quality":     self._quality_var.get(),
                }, f, indent=2)
        except Exception:
            pass

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_entry(self, entry, value: str):
        entry.configure(state='normal')
        entry.delete(0, 'end')
        entry.insert(0, value)
        entry.configure(state='readonly')

    # ── File pickers ──────────────────────────────────────────────────────────

    def _browse_output(self):
        d = filedialog.askdirectory(initialdir=self._out_entry.get() or os.path.expanduser("~"))
        if d:
            self._set_entry(self._out_entry, d)
            self._save_settings()

    def _browse_cookie(self):
        f = filedialog.askopenfilename(
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if f:
            self._set_entry(self._cookie_entry, f)
            self._save_settings()

    def _clear_cookie(self):
        self._set_entry(self._cookie_entry, "")
        self._save_settings()

    # ── Logging ───────────────────────────────────────────────────────────────

    def _log_msg(self, msg: str):
        def _do():
            self._log.configure(state="normal")
            self._log.insert("end", msg + "\n")
            self._log.see("end")
            self._log.configure(state="disabled")
        self.after(0, _do)

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _set_status(self, text: str, color: str = MUTED):
        self.after(0, lambda: self._status_lbl.configure(text=text, text_color=color))

    def _set_progress(self, val: float):
        self.after(0, lambda: self._progress.set(max(0.0, min(1.0, val))))

    # ── Download ──────────────────────────────────────────────────────────────

    def _start_download(self):
        if youtube_dl is None:
            self._log_msg("❌ yt-dlp not installed. Run: pip install yt-dlp")
            return
        if self._downloading:
            return

        url        = self._url_entry.get().strip()
        output_dir = self._out_entry.get().strip()
        fmt        = self._fmt_var.get()
        dl_type    = self._type_var.get()
        quality    = self._quality_var.get()
        cookie     = self._cookie_entry.get().strip()

        if not url:
            self._log_msg("❌ Please enter a URL.")
            return
        if not output_dir or not os.path.isdir(output_dir):
            self._log_msg("❌ Please select a valid output folder.")
            return
        if cookie and not os.path.exists(cookie):
            self._log_msg(f"❌ Cookie file not found: {cookie}")
            return

        self._downloading = True
        self._dl_btn.configure(state="disabled", text="Downloading…")
        self._set_progress(0)
        self._save_settings()

        threading.Thread(
            target=self._download_worker,
            args=(url, output_dir, fmt, dl_type, quality, cookie),
            daemon=True
        ).start()

    def _progress_hook(self, d):
        if d["status"] == "downloading":
            # Parse percent
            pct_str = d.get("_percent_str", "").replace("\x1b[0K", "").strip()
            try:
                pct = float(pct_str.replace("%", "")) / 100
                self._set_progress(pct)
            except Exception:
                pass
            speed = d.get("_speed_str", "").replace("\x1b[0K", "").strip()
            eta   = d.get("_eta_str",   "").replace("\x1b[0K", "").strip()
            self._set_status(f"⬇ {pct_str}  {speed}  ETA {eta}", ACCENT)

        elif d["status"] == "finished":
            self._set_status("⚙ Post-processing…", "#f0a500")
            self._set_progress(1.0)

    def _download_worker(self, url, output_dir, fmt, dl_type, quality, cookie):

        log_fn = self._log_msg

        class _YTLogger:
            def debug(self, msg):
                if not msg.startswith("[debug]"):
                    log_fn(msg)
            def info(self, msg):
                log_fn(msg)
            def warning(self, msg):
                log_fn(f"⚠ {msg}")
            def error(self, msg):
                log_fn(f"❌ {msg}")

        try:
            if dl_type == "playlist":
                outtmpl = os.path.join(output_dir, "%(playlist)s", "%(title)s.%(ext)s")
            else:
                outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")

            opts = {
                "outtmpl":        outtmpl,
                "logger":         _YTLogger(),
                "progress_hooks": [self._progress_hook],
                "quiet":          True,
                "no_warnings":    True,
                "noplaylist":     dl_type != "playlist",
            }

            if self.ffmpeg_dir:
                opts["ffmpeg_location"] = self.ffmpeg_dir

            if cookie:
                opts["cookiefile"] = os.path.abspath(cookie)

            if fmt == "mp3":
                opts["format"] = "bestaudio/best"
                opts["postprocessors"] = [{
                    "key":              "FFmpegExtractAudio",
                    "preferredcodec":   "mp3",
                    "preferredquality": quality,
                }]
            else:
                opts["format"] = "bestvideo+bestaudio/best"
                opts["merge_output_format"] = "mp4"

            if cookie:
                self._log_msg(f"Using cookie file: {cookie}")
            self._log_msg("Starting download...")

            with youtube_dl.YoutubeDL(opts) as ydl:
                ydl.download([url])

            self._log_msg("✅ Download complete!")
            self._set_status("✅ Done", SUCCESS)
            self._set_progress(1.0)

        except Exception as e:
            import traceback
            self._log_msg(f"❌ Error: {e}")
            self._log_msg(traceback.format_exc())
            self._set_status("❌ Failed", DANGER)

        finally:
            self._downloading = False
            self.after(0, lambda: self._dl_btn.configure(state="normal", text="⬇  Download"))