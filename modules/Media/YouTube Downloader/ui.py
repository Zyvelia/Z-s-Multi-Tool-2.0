import customtkinter as ctk
import os
import json
import sys
import subprocess
import urllib.request
import threading
import shutil
import glob

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

def _make_btn(parent, text, cmd, **ov):
    kw = theme.secondary_button_kwargs()
    kw.update(ov)
    return ctk.CTkButton(parent, text=text, command=cmd, **kw)


SETTINGS_FILE = paths.migrate_legacy_file(
    paths.data_path("yt_downloader", "downloader_settings.json"),
    "modules", "yt_downloader", "downloader_settings.json"
)

# yt-dlp's browser-cookie extractor only officially recognizes:
# brave, chrome, chromium, edge, firefox, opera, safari, vivaldi, whale.
# Opera GX isn't in that list, but it's Chromium under the hood, so we
# extract it as "chrome" pointed at GX's own profile folder instead.
_COOKIE_BROWSERS = {
    "opera_gx": None,   # handled specially — see _resolve_cookie_browser()
    "chrome": "chrome",
    "edge": "edge",
    "firefox": "firefox",
    "brave": "brave",
    "opera": "opera",
    "vivaldi": "vivaldi",
}


def _opera_gx_profile_dir():
    """Best-effort default profile path for Opera GX per OS. Returns None
    if it can't find a plausible location."""
    if sys.platform.startswith("win"):
        base = os.path.join(os.environ.get("APPDATA", ""), "Opera Software", "Opera GX Stable")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support/com.operasoftware.OperaGX")
    else:
        base = os.path.expanduser("~/.config/opera-gx")  # unofficial Linux builds
    profile = os.path.join(base, "Default")
    if os.path.isdir(profile):
        return profile
    return base if os.path.isdir(base) else None


def _resolve_cookie_browser(browser_key):
    """Returns (browser_name, profile_path_or_None) for extract_cookies_from_browser."""
    if browser_key == "opera_gx":
        profile = _opera_gx_profile_dir()
        if profile is None:
            raise FileNotFoundError(
                "Couldn't find Opera GX's profile folder in the usual location. "
                "If it's installed somewhere custom, use Browse to pick an "
                "existing cookies.txt exported another way instead."
            )
        return "chrome", profile
    return _COOKIE_BROWSERS.get(browser_key, browser_key), None

# Music defaults to 8766, Security Vault to 8765 — kept distinct so all
# three can run at once without a port clash.
DEFAULT_REMOTE_PORT = 8767


def _read_setting(key, default=""):
    """Reads a single value straight from downloader_settings.json,
    independent of any Tkinter widget's live state. Used by the
    (long-lived) YTWebServer instance instead of reaching into a page's
    Entry widgets, since those get destroyed and recreated whenever the
    YouTube Downloader tab is rebuilt, while the web server itself is
    reused across rebuilds — reading a destroyed widget silently returns
    "" and produces a false "no valid output folder" error even when the
    setting is saved correctly on disk."""
    return _read_all_settings().get(key, default)


def _read_all_settings():
    defaults = {
        "output_dir": os.path.expanduser("~"),
        "cookie_file": "",
        "format": "mp3",
        "type": "video",
        "quality": "192",
        "remote_port": DEFAULT_REMOTE_PORT,
        "auto_start_remote": False,
        "access_code": "",
    }
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                defaults.update(json.load(f))
    except Exception:
        pass
    return defaults


def _write_settings(updates: dict) -> None:
    data = _read_all_settings()
    data.update(updates)
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def log_to_yt_page(manager, msg: str) -> None:
    if manager is None:
        return
    current = getattr(manager, "current", None)
    if current is None:
        return
    inner = getattr(current, "_inner", current)
    if inner.__class__.__name__ == "YTDownloaderPage":
        inner._log_msg(msg)


def maybe_autostart_remote(manager) -> None:
    s = _read_all_settings()
    if not s.get("auto_start_remote"):
        return
    web_server = getattr(manager, "yt_web_server", None)
    if web_server is None or web_server.is_running():
        return
    port = s.get("remote_port", DEFAULT_REMOTE_PORT)
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = DEFAULT_REMOTE_PORT

    def work():
        web_server.start(port)

    threading.Thread(target=work, daemon=True).start()


def _set_entry(entry, value: str):
    entry.configure(state='normal')
    entry.delete(0, 'end')
    entry.insert(0, value)
    entry.configure(state='readonly')


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


def _find_deno() -> str | None:
    """
    Find the deno executable, needed by yt-dlp to solve YouTube's "n"
    signature challenge. Checked in order:
      1. PATH (covers both user- and system-PATH installs; also covers
         scoop, since its shims live on PATH).
      2. The official installer's default install location
         (%USERPROFILE%\\.deno\\bin\\deno.exe).
      3. The WinGet package folder. WinGet nests it under a
         hash-suffixed directory that can change on reinstall/update,
         so this is globbed rather than hardcoded.
    Returns None (and lets yt-dlp try PATH resolution itself) if
    nothing is found.
    """
    found = shutil.which("deno")
    if found:
        return found

    userprofile = os.environ.get("USERPROFILE", os.path.expanduser("~"))
    direct = os.path.join(userprofile, ".deno", "bin", "deno.exe")
    if os.path.isfile(direct):
        return direct

    localappdata = os.environ.get(
        "LOCALAPPDATA", os.path.join(userprofile, "AppData", "Local")
    )
    winget_glob = os.path.join(
        localappdata,
        "Microsoft", "WinGet", "Packages",
        "DenoLand.Deno_Microsoft.Winget.Source_*",
        "deno.exe",
    )
    matches = glob.glob(winget_glob)
    if matches:
        return matches[0]

    return None


# ── Main page ─────────────────────────────────────────────────────────────────

class YTDownloaderPage(ctk.CTkFrame):

    MODULE_SETTINGS_TITLE = "Paths & access"

    @staticmethod
    def build_module_settings(parent, manager):
        from .settings_panel import YTDownloaderSettingsPanel
        return YTDownloaderSettingsPanel(parent, manager)

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=theme.BG)
        self.manager      = manager
        self.ffmpeg_dir   = _find_ffmpeg()
        self._downloading = False
        self._remote_job_ids_seen = set()

        self.web_server = getattr(manager, "yt_web_server", None) or YTWebServer(
            get_output_dir=lambda: _read_setting("output_dir", os.path.expanduser("~")),
            get_cookie_file=lambda: _read_setting("cookie_file", ""),
            get_ffmpeg_dir=lambda: self.ffmpeg_dir,
        )
        manager.yt_web_server = self.web_server
        self.web_server.on_job_update = self._on_remote_job_update
        self.web_server.access_code = _read_setting("access_code", "")

        self._build_ui()
        self._load_settings()
        threading.Thread(target=self._check_for_update, daemon=True).start()
        maybe_autostart_remote(manager)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()
        self._build_url_row()
        self._build_options_row()
        self._build_log()

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        header.pack(fill="x", padx=12, pady=(12, 4))

        ctk.CTkLabel(header, text="▶  YouTube Downloader",
                     font=("Segoe UI", 22, "bold"), text_color=theme.TEXT
                     ).pack(side="left", padx=14, pady=10)

        self._status_lbl = ctk.CTkLabel(header, text="Idle", text_color=theme.MUTED)
        self._status_lbl.pack(side="right", padx=14)

    def _build_url_row(self):
        panel = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        panel.pack(fill="x", padx=12, pady=(0, 4))

        inner = ctk.CTkFrame(panel, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=10)

        ctk.CTkLabel(inner, text="URL", text_color=theme.MUTED,
                     font=("Segoe UI", 12)).pack(side="left", padx=(0, 8))

        self._url_entry = ctk.CTkEntry(
            inner, placeholder_text="Paste YouTube video or playlist URL…",
            corner_radius=8, fg_color=theme.PANEL_2, text_color=theme.TEXT,
            border_color=theme.PANEL_2)
        self._url_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self._dl_btn = _make_btn(inner, "⬇  Download", self._start_download,
                                 **theme.primary_button_kwargs(), width=130)
        self._dl_btn.pack(side="left")

        self._update_btn = _make_btn(inner, "⟳  Update yt-dlp", self._start_update,
                                     width=140)
        self._update_btn.pack(side="left", padx=(8, 0))

    def _build_options_row(self):
        panel = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        panel.pack(fill="x", padx=12, pady=(0, 4))

        inner = ctk.CTkFrame(panel, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=10)

        # ── Type ──
        ctk.CTkLabel(inner, text="Type", text_color=theme.MUTED,
                     font=("Segoe UI", 12)).pack(side="left", padx=(0, 6))

        self._type_var = ctk.StringVar(value="video")
        for label, val in [("Single Video", "video"), ("Playlist", "playlist")]:
            ctk.CTkRadioButton(
                inner, text=label, variable=self._type_var, value=val,
                text_color=theme.TEXT, fg_color=theme.ACCENT, hover_color="#2f7fd6"
            ).pack(side="left", padx=6)

        # ── Format ──
        ctk.CTkLabel(inner, text="Format", text_color=theme.MUTED,
                     font=("Segoe UI", 12)).pack(side="left", padx=(20, 6))

        self._fmt_var = ctk.StringVar(value="mp3")
        for label, val in [("MP3", "mp3"), ("MP4", "mp4")]:
            ctk.CTkRadioButton(
                inner, text=label, variable=self._fmt_var, value=val,
                text_color=theme.TEXT, fg_color=theme.ACCENT, hover_color="#2f7fd6"
            ).pack(side="left", padx=6)

        # ── Quality (MP3) ──
        ctk.CTkLabel(inner, text="Quality", text_color=theme.MUTED,
                     font=("Segoe UI", 12)).pack(side="left", padx=(20, 6))

        self._quality_var = ctk.StringVar(value="192")
        ctk.CTkOptionMenu(
            inner, variable=self._quality_var,
            values=["320", "256", "192", "128", "96"],
            fg_color=theme.PANEL_2, button_color=theme.ACCENT,
            button_hover_color="#2f7fd6", text_color=theme.TEXT,
            width=80
        ).pack(side="left")

        ctk.CTkLabel(inner, text="kbps", text_color=theme.MUTED,
                     font=("Segoe UI", 11)).pack(side="left", padx=(4, 0))

    def _build_log(self):
        panel = ctk.CTkFrame(self, fg_color=theme.PANEL, corner_radius=10)
        panel.pack(fill="x", expand=False, padx=12, pady=(0, 12))

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 4))

        ctk.CTkLabel(top, text="Download Log",
                     font=("Segoe UI", 13, "bold"), text_color=theme.TEXT).pack(side="left")

        _make_btn(top, "🗑 Clear", self._clear_log, width=80).pack(side="right")

        self._log = ctk.CTkTextbox(
            panel, fg_color=theme.PANEL_2, text_color=theme.TEXT,
            corner_radius=8, font=("Consolas", 11), height=140, state="disabled")
        self._log.pack(fill="x", expand=False, padx=10, pady=(0, 10))

        # Progress bar
        self._progress = ctk.CTkProgressBar(
            panel, progress_color=theme.ACCENT, fg_color=theme.PANEL_2, corner_radius=4)
        self._progress.set(0)
        self._progress.pack(fill="x", padx=10, pady=(0, 10))

    # ── Settings ──────────────────────────────────────────────────────────────

    def _load_settings(self):
        s = _read_all_settings()
        self._fmt_var.set(s.get("format", "mp3"))
        self._type_var.set(s.get("type", "video"))
        self._quality_var.set(s.get("quality", "192"))

    def _save_settings(self):
        _write_settings({
            "format": self._fmt_var.get(),
            "type": self._type_var.get(),
            "quality": self._quality_var.get(),
        })

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
                self._set_status(f"⬇ (extension) {job['message']}", theme.ACCENT)
                self._set_progress(job.get("percent", 0.0))
            elif job["status"] == "done":
                self._log_msg(f"✅ (extension) Download complete: {job['url']}")
                self._set_status("✅ Done", theme.SUCCESS)
                self._set_progress(1.0)
            elif job["status"] == "error":
                self._log_msg(f"❌ (extension) {job['url']} — {job['message']}")
                self._set_status("❌ Failed", theme.DANGER)
        self.after(0, _do)

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

    def _set_status(self, text: str, color: str = theme.MUTED):
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
        output_dir = _read_setting("output_dir", os.path.expanduser("~")).strip()
        fmt        = self._fmt_var.get()
        dl_type    = self._type_var.get()
        quality    = self._quality_var.get()
        cookie     = _read_setting("cookie_file", "").strip()

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
            self._set_status(f"⬇ {pct_str}  {speed}  ETA {eta}", theme.ACCENT)

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
            # "tv" client in play. "tv" used to be kept around to dodge an
            # older 403 issue, but YouTube is now running an experiment
            # that serves DRM-only formats on the tv (TVHTML5) client for
            # some accounts — yt-dlp raises "This video is DRM protected"
            # even though the video itself is fine. See
            # https://github.com/yt-dlp/yt-dlp/issues/12563. Dropping "tv"
            # avoids it; "web" + "mweb" both support cookies.
            if cookie:
                player_clients = ["web", "mweb"]
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
                "remote_components": ["ejs:github"],
            }

            if self.ffmpeg_dir:
                opts["ffmpeg_location"] = self.ffmpeg_dir

            if cookie:
                opts["cookiefile"] = os.path.abspath(cookie)

            deno_path = _find_deno()
            opts["js_runtimes"] = {"deno": {"path": deno_path}} if deno_path else {"deno": {}}

            if fmt == "mp3":
                opts["format"] = "bestaudio*/bestaudio/best"
                opts["postprocessors"] = [{
                    "key":              "FFmpegExtractAudio",
                    "preferredcodec":   "mp3",
                    "preferredquality": quality,
                }]
            else:
                # The "*" variants include formats where yt-dlp couldn't
                # resolve codec info (common with the android/ios player
                # clients) — without it, "bestvideo" alone can filter out
                # every available format and raise "Requested format is
                # not available" on some videos.
                opts["format"] = "bestvideo*+bestaudio/bestvideo+bestaudio/best"
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
                if (("403" in str(e) or "Requested format is not available" in str(e))
                        and opts.get("format") != "18/best"):
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
                self._set_status("✅ Done", theme.SUCCESS)
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
            self._set_status("❌ Failed", theme.DANGER)

        finally:
            self._downloading = False
            self.after(0, lambda: self._dl_btn.configure(state="normal", text="⬇  Download"))