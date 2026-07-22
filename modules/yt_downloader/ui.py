import customtkinter as ctk
from tkinter import filedialog
import os
import json
import sys
import subprocess
import urllib.request
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
from .web_server import YTWebServer

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

# Music defaults to 8766, Security Vault to 8765 — kept distinct so all
# three can run at once without a port clash.
DEFAULT_REMOTE_PORT = 8767


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


# ── Main page ─────────────────────────────────────────────────────────────────

class YTDownloaderPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=BG)
        self.manager      = manager
        self.ffmpeg_dir   = _find_ffmpeg()
        self._downloading = False
        self._remote_job_ids_seen = set()

        # Shared with Music Player / Security Vault's Settings tabs — same
        # tailnet connection, same TailscaleService instance either way.
        self.tailscale = manager.container.tailscale_service
        self._phone_poll_job = None

        # Shared with the browser extension: a loopback server that lets a
        # "Send to Downloader" button on a YouTube tab queue a download
        # here. Created once and stashed on the manager (same lazy pattern
        # Music Player uses) so it survives navigating away from this page.
        self.web_server = getattr(manager, "yt_web_server", None) or YTWebServer(
            get_output_dir=lambda: self._out_entry.get().strip(),
            get_cookie_file=lambda: self._cookie_entry.get().strip(),
            get_ffmpeg_dir=lambda: self.ffmpeg_dir,
        )
        manager.yt_web_server = self.web_server
        self.web_server.on_job_update = self._on_remote_job_update

        self._build_ui()
        self._load_settings()
        threading.Thread(target=self._check_for_update, daemon=True).start()

        if self._autostart_var.get() and not self.web_server.is_running():
            self._start_remote_access()

        self._refresh_remote_status()
        self._refresh_phone_status()

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        self._build_url_row()
        self._build_options_row()
        self._build_paths_row()
        self._build_remote_row()
        self._build_phone_row()
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

        self._update_btn = _make_btn(inner, "⟳  Update yt-dlp", self._start_update,
                                     width=140)
        self._update_btn.pack(side="left", padx=(8, 0))

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

    def _build_remote_row(self):
        panel = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        panel.pack(fill="x", padx=12, pady=(0, 4))

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(10, 4))

        ctk.CTkLabel(top, text="🧩  Browser extension (\"Send to Downloader\")",
                     font=("Segoe UI", 13, "bold"), text_color=TEXT).pack(side="left")

        self._remote_status_lbl = ctk.CTkLabel(top, text="⚪ Off", text_color=MUTED)
        self._remote_status_lbl.pack(side="right")

        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0, 6))

        self._remote_start_btn = _make_btn(row, "▶ Start", self._start_remote_access,
                                           **_BTN_ACCENT, width=90)
        self._remote_start_btn.pack(side="left")

        self._remote_stop_btn = _make_btn(row, "■ Stop", self._stop_remote_access,
                                          **_BTN_DANGER, width=90)
        self._remote_stop_btn.pack(side="left", padx=(8, 0))

        ctk.CTkLabel(row, text="Local port", text_color=MUTED,
                     font=("Segoe UI", 12)).pack(side="left", padx=(20, 6))
        self._remote_port_entry = ctk.CTkEntry(
            row, width=80, fg_color=PANEL_2, text_color=TEXT, border_color=PANEL_2, corner_radius=8)
        self._remote_port_entry.pack(side="left")

        self._autostart_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            row, text="Auto-start with the app", variable=self._autostart_var,
            text_color=MUTED, font=("Segoe UI", 12), fg_color=ACCENT, hover_color="#2f7fd6",
            command=self._save_settings,
        ).pack(side="left", padx=(20, 0))

        ctk.CTkLabel(
            panel,
            text="Turn this on, then use the \"Send to Downloader\" button in the Zs Multi Tool "
                 "Companion browser extension on any YouTube tab. Downloads land in the output "
                 "folder above, using the format/quality set here. Loopback only (127.0.0.1) — "
                 "never reachable off this PC.",
            text_color=MUTED, font=("Segoe UI", 11), anchor="w", justify="left", wraplength=760,
        ).pack(fill="x", padx=10, pady=(0, 10))

    def _build_phone_row(self):
        panel = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        panel.pack(fill="x", padx=12, pady=(0, 4))

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(10, 4))

        ctk.CTkLabel(top, text="📱  Phone access (Tailscale)",
                     font=("Segoe UI", 13, "bold"), text_color=TEXT).pack(side="left")

        self._phone_status_lbl = ctk.CTkLabel(top, text="⚪ Off", text_color=MUTED)
        self._phone_status_lbl.pack(side="right")

        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(0, 6))

        self._phone_start_btn = _make_btn(row, "▶ Start Phone Access", self._start_phone_access,
                                           **_BTN_ACCENT, width=170)
        self._phone_start_btn.pack(side="left")

        self._phone_stop_btn = _make_btn(row, "■ Stop", self._stop_phone_access,
                                          **_BTN_DANGER, width=90)
        self._phone_stop_btn.pack(side="left", padx=(8, 0))

        ctk.CTkLabel(row, text="Access code (optional)", text_color=MUTED,
                     font=("Segoe UI", 12)).pack(side="left", padx=(20, 6))
        self._access_code_entry = ctk.CTkEntry(
            row, width=110, show="•", fg_color=PANEL_2, text_color=TEXT,
            border_color=PANEL_2, corner_radius=8)
        self._access_code_entry.pack(side="left")

        ctk.CTkLabel(
            panel,
            text="Exposes this same downloader to your phone over your own Tailscale "
                 "network — reachable only from devices signed into your tailnet, never "
                 "the open internet. Uses the same local port as the browser extension "
                 "above; starting this will start that server too if it isn't already on. "
                 "An access code is optional — if set, it's required to queue a download "
                 "from the mobile page (and from the browser extension, since they share "
                 "this same endpoint) but not to view download status.",
            text_color=MUTED, font=("Segoe UI", 11), anchor="w", justify="left", wraplength=760,
        ).pack(fill="x", padx=10, pady=(0, 10))

    def _current_access_code(self):
        code = self._access_code_entry.get().strip()
        self.web_server.access_code = code
        return code

    def _start_phone_access(self):
        self._current_access_code()
        self._save_settings()

        status = self.tailscale.get_status()
        if not status["installed"]:
            from tkinter import messagebox
            messagebox.showwarning("Tailscale not installed", "Install Tailscale first "
                                    "(see the Security Vault or Music Player Settings tab).")
            return
        if not status["running"]:
            from tkinter import messagebox
            if not messagebox.askyesno(
                "Not connected",
                "You're not connected to Tailscale yet. Connect now, then start phone access?",
            ):
                return
            cfg = self.tailscale.load_config()
            self.tailscale.connect(
                hostname=cfg.get("hostname") or None,
                auth_key=cfg.get("auth_key") or None,
                accept_routes=cfg.get("accept_routes", True),
            )

        self._phone_start_btn.configure(state="disabled", text="Starting…")

        def work():
            port = self._current_remote_port()
            ok, msg = (True, "already running") if self.web_server.is_running() else self.web_server.start(port)
            if ok:
                ok2, msg2 = self.tailscale.enable_app_serve("yt", port)
                if not ok2:
                    ok, msg = ok2, msg2
            self.after(0, lambda: self._after_start_phone_access(ok, msg))

        threading.Thread(target=work, daemon=True).start()

    def _after_start_phone_access(self, ok, msg):
        self._phone_start_btn.configure(state="normal", text="▶ Start Phone Access")
        if not ok:
            from tkinter import messagebox
            messagebox.showerror("Couldn't start phone access", msg)
        self._refresh_phone_status()
        self._refresh_remote_status()

    def _stop_phone_access(self):
        self.tailscale.disable_app_serve("yt")
        self._refresh_phone_status()

    def _refresh_phone_status(self):
        if self._phone_poll_job:
            try:
                self.after_cancel(self._phone_poll_job)
            except Exception:
                pass

        def work():
            status = self.tailscale.get_status()
            live = status["running"] and self.tailscale.is_app_serving("yt")
            self.after(0, lambda: self._apply_phone_status(status, live))

        threading.Thread(target=work, daemon=True).start()
        self._phone_poll_job = self.after(4000, self._refresh_phone_status)

    def _apply_phone_status(self, status, live):
        if not self.winfo_exists():
            return
        if live:
            hostname = status.get("hostname") or "this-device"
            self._phone_status_lbl.configure(
                text=f"🟢 https://{hostname}:8445/", text_color=SUCCESS
            )
        else:
            self._phone_status_lbl.configure(text="⚪ Off", text_color=MUTED)

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
                self._remote_port_entry.insert(0, str(s.get("remote_port", DEFAULT_REMOTE_PORT)))
                self._autostart_var.set(bool(s.get("auto_start_remote", False)))
                self._access_code_entry.insert(0, s.get("access_code", ""))
                self.web_server.access_code = s.get("access_code", "")
            else:
                self._set_entry(self._out_entry, os.path.expanduser("~"))
                self._remote_port_entry.insert(0, str(DEFAULT_REMOTE_PORT))
        except Exception:
            self._set_entry(self._out_entry, os.path.expanduser("~"))
            if not self._remote_port_entry.get():
                self._remote_port_entry.insert(0, str(DEFAULT_REMOTE_PORT))

    def _save_settings(self):
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump({
                    "output_dir":        self._out_entry.get(),
                    "cookie_file":       self._cookie_entry.get(),
                    "format":            self._fmt_var.get(),
                    "type":              self._type_var.get(),
                    "quality":           self._quality_var.get(),
                    "remote_port":       self._current_remote_port(),
                    "auto_start_remote": bool(self._autostart_var.get()),
                    "access_code":       self._access_code_entry.get().strip(),
                }, f, indent=2)
        except Exception:
            pass

    # ── Remote access (browser extension) ───────────────────────────────────

    def _current_remote_port(self):
        try:
            return int(self._remote_port_entry.get().strip() or DEFAULT_REMOTE_PORT)
        except ValueError:
            return DEFAULT_REMOTE_PORT

    def _start_remote_access(self):
        port = self._current_remote_port()
        self._remote_start_btn.configure(state="disabled", text="Starting…")

        def work():
            ok, msg = self.web_server.start(port)
            self.after(0, lambda: self._after_start_remote_access(ok, msg))

        threading.Thread(target=work, daemon=True).start()

    def _after_start_remote_access(self, ok, msg):
        self._remote_start_btn.configure(state="normal", text="▶ Start")
        if not ok:
            self._log_msg(f"❌ Couldn't start browser-extension server: {msg}")
        else:
            self._log_msg(f"🧩 Browser-extension server started — {msg}")
        self._save_settings()
        self._refresh_remote_status()

    def _stop_remote_access(self):
        self.web_server.stop()
        self._log_msg("🧩 Browser-extension server stopped.")
        self._refresh_remote_status()

    def _refresh_remote_status(self):
        if not self.winfo_exists():
            return
        if self.web_server.is_running():
            self._remote_status_lbl.configure(
                text=f"🟢 On — 127.0.0.1:{self.web_server.port}", text_color=SUCCESS)
            self._remote_start_btn.configure(state="disabled")
            self._remote_stop_btn.configure(state="normal")
        else:
            self._remote_status_lbl.configure(text="⚪ Off", text_color=MUTED)
            self._remote_start_btn.configure(state="normal")
            self._remote_stop_btn.configure(state="disabled")

    def _on_remote_job_update(self, job):
        """Fires (from the server's worker thread) whenever a job queued by
        the extension changes state. Mirrors it into this page's log/progress
        so downloads triggered remotely are visible here too, if open."""
        def _do():
            if not self.winfo_exists():
                return
            first_time = job["id"] not in self._remote_job_ids_seen
            if first_time and job["status"] in ("queued", "downloading"):
                self._remote_job_ids_seen.add(job["id"])
                self._log_msg(f"🧩 Extension queued: {job['url']}  ({job['format']}, {job['type']})")

            if job["status"] == "downloading":
                self._set_status(f"⬇ (extension) {job['message']}", ACCENT)
                self._set_progress(job.get("percent", 0.0))
            elif job["status"] == "done":
                self._log_msg(f"✅ (extension) Download complete: {job['url']}")
                self._set_status("✅ Done", SUCCESS)
                self._set_progress(1.0)
            elif job["status"] == "error":
                self._log_msg(f"❌ (extension) {job['url']} — {job['message']}")
                self._set_status("❌ Failed", DANGER)
        self.after(0, _do)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_entry(self, entry, value: str):
        entry.configure(state='normal')
        entry.delete(0, 'end')
        entry.insert(0, value)
        entry.configure(state='readonly')

    # ── yt-dlp updates ────────────────────────────────────────────────────────

    def _check_for_update(self):
        """Best-effort, silent-on-failure check against PyPI for a newer yt-dlp."""
        if youtube_dl is None:
            return
        try:
            current = youtube_dl.version.__version__
        except Exception:
            return
        try:
            with urllib.request.urlopen(
                "https://pypi.org/pypi/yt-dlp/json", timeout=5
            ) as resp:
                data = json.load(resp)
            latest = data.get("info", {}).get("version")
        except Exception:
            return
        if not latest:
            return
        # yt-dlp versions are dates (YYYY.MM.DD[.rev]) but aren't always
        # zero-padded consistently between sources (e.g. "2026.7.4" vs
        # "2026.07.04" are the same release) — compare numerically per
        # segment rather than as raw strings to avoid false positives.
        def _parts(v):
            out = []
            for p in v.split("."):
                try:
                    out.append(int(p))
                except ValueError:
                    out.append(p)
            return out

        if _parts(latest) != _parts(current):
            self._log_msg(f"ℹ A newer yt-dlp is available: {latest} (you have {current}). "
                          f"Click 'Update yt-dlp' to install it.")

    def _start_update(self):
        if youtube_dl is None:
            self._log_msg("❌ yt-dlp not installed. Run: pip install yt-dlp")
            return
        self._update_btn.configure(state="disabled", text="Updating…")
        threading.Thread(target=self._update_worker, daemon=True).start()

    def _update_worker(self):
        try:
            # A frozen/bundled build (PyInstaller etc.) has no pip and no
            # source install to upgrade — running pip here would either fail
            # outright or silently update an environment the app doesn't
            # actually use. Tell the user plainly instead of pretending it
            # worked.
            if getattr(sys, "frozen", False):
                self._log_msg(
                    "❌ This is a bundled build — it has no pip to update itself. "
                    "Grab the latest release build, or run the app from source "
                    "with 'pip install -U yt-dlp' in that environment."
                )
                return

            self._log_msg("Checking for pip...")
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "--version"],
                    check=True, capture_output=True, text=True,
                )
            except FileNotFoundError:
                self._log_msg(
                    "❌ Couldn't find Python/pip on PATH. Install pip, or update "
                    "manually with: pip install -U yt-dlp"
                )
                return
            except subprocess.CalledProcessError as e:
                self._log_msg(f"❌ pip isn't working: {e.stderr or e}")
                return

            self._log_msg("Updating yt-dlp...")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "yt-dlp"],
                capture_output=True, text=True,
            )
            stdout = result.stdout or ""
            for line in stdout.splitlines():
                self._log_msg(line)
            if result.returncode != 0:
                self._log_msg(f"❌ Update failed: {result.stderr.strip()}")
                return

            if "Successfully installed" in stdout:
                self._log_msg(
                    "✅ yt-dlp updated. Restart the app for it to take effect."
                )
            else:
                # "Requirement already satisfied" case — pip exits 0 having
                # done nothing, so don't claim an update happened.
                self._log_msg("✅ Already up to date — nothing to install.")
        except Exception as e:
            self._log_msg(f"❌ Update error: {e}")
        finally:
            self.after(0, lambda: self._update_btn.configure(
                state="normal", text="⟳  Update yt-dlp"))

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

            # android/ios/web_safari don't support cookies and get silently
            # skipped when a cookiefile is set, which was leaving only the
            # "tv" client in play (the one hitting 403s). Pick clients that
            # actually get used for the auth mode in play.
            if cookie:
                player_clients = ["web", "mweb", "tv"]
            else:
                player_clients = ["default", "android", "ios"]

            opts = {
                "outtmpl":         outtmpl,
                "logger":          _YTLogger(),
                "progress_hooks":  [self._progress_hook],
                "quiet":           True,
                "no_warnings":     True,
                "noplaylist":      dl_type != "playlist",
                # Sanitize titles for illegal filesystem characters instead of
                # relying on the unused _sanitize() helper.
                "windowsfilenames": True,
                # Retry harder — YouTube throttling/403s are often transient.
                "retries":          10,
                "fragment_retries": 10,
                # Don't let one bad video in a playlist kill the whole batch.
                "ignoreerrors":     dl_type == "playlist",
                "extractor_args": {
                    "youtube": {
                        "player_client": player_clients,
                    }
                },
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
            try:
                ver = youtube_dl.version.__version__
            except Exception:
                ver = "unknown"
            self._log_msg(f"yt-dlp version: {ver}")
            self._log_msg("Starting download...")

            try:
                with youtube_dl.YoutubeDL(opts) as ydl:
                    ret = ydl.download([url])
            except youtube_dl.utils.DownloadError as e:
                # YouTube is currently 403'ing the split adaptive audio/video
                # streams for some videos while the combined "progressive"
                # format (itag 18) still works. Retry once with that before
                # giving up.
                if "403" in str(e) and opts.get("format") != "18/best":
                    self._log_msg(
                        "⚠ Adaptive stream blocked (403) — retrying with a "
                        "combined format (18)…"
                    )
                    fallback_opts = dict(opts)
                    fallback_opts["format"] = "18/best"
                    with youtube_dl.YoutubeDL(fallback_opts) as ydl:
                        ret = ydl.download([url])
                else:
                    raise

            # With ignoreerrors=True (playlist mode), failures don't raise —
            # ydl.download() returns non-zero instead. Report that honestly
            # rather than always claiming success.
            if ret:
                self._log_msg("⚠ Finished, but one or more items failed — see errors above.")
                self._set_status("⚠ Finished with errors", "#f0a500")
            else:
                self._log_msg("✅ Download complete!")
                self._set_status("✅ Done", SUCCESS)
                self._set_progress(1.0)

        except Exception as e:
            import traceback
            self._log_msg(f"❌ Error: {e}")
            self._log_msg(traceback.format_exc())
            msg = str(e)
            if "403" in msg or "unavailable" in msg.lower():
                self._log_msg(
                    "💡 YouTube changes how it blocks downloaders often. "
                    "If this just started happening, run: pip install -U yt-dlp "
                    "(or 'yt-dlp -U' / '--update-to nightly' if it's a standalone exe) "
                    "and try again."
                )
            self._set_status("❌ Failed", DANGER)

        finally:
            self._downloading = False
            self.after(0, lambda: self._dl_btn.configure(state="normal", text="⬇  Download"))