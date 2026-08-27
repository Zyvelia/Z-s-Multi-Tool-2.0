import customtkinter as ctk
import os
import json
import sys
import subprocess
import urllib.request
import threading
import shutil
import glob
import random
import time
import queue
import re
import unicodedata
import zipfile
import io
from difflib import SequenceMatcher

from core import paths

# ── Self-update support for frozen (PyInstaller) builds ─────────────────────
# A bundled exe has no pip, so a normal `pip install -U yt-dlp` isn't
# possible. yt-dlp is pure Python though, so instead: if a newer version has
# been unpacked into this folder (by _update_worker below), put it at the
# FRONT of sys.path so it shadows whatever version got frozen into the exe.
# Must run before the `import yt_dlp` below.
def yt_dlp_update_dir() -> str:
    return paths.data_path("yt_downloader", "yt_dlp_update")


_update_dir = yt_dlp_update_dir()
if os.path.isdir(os.path.join(_update_dir, "yt_dlp")) and _update_dir not in sys.path:
    sys.path.insert(0, _update_dir)

try:
    import yt_dlp as youtube_dl
except ImportError:
    try:
        import youtube_dl
    except ImportError:
        youtube_dl = None

try:
    import mutagen  # noqa: F401 — presence check only, submodules imported per-format below
    _HAVE_MUTAGEN = True
except ImportError:
    _HAVE_MUTAGEN = False

from core import theme
from .web_server import YTWebServer

# ── Colours (shared app theme) ───────────────────────────────────────────

class _SmoothCTkScrollableFrame(ctk.CTkScrollableFrame):
    """A CTkScrollableFrame whose mouse-wheel scrolling glides toward its
    target position instead of jumping there in one step, so a long page
    (lots of subscriptions, a big browse list, a growing log) doesn't feel
    jerky to scroll through. Only used for the main page frame — other
    scrollable areas (the subscription list, browse list) keep the stock,
    instant-jump CTkScrollableFrame behavior."""

    _SMOOTH_STEP_MS = 15        # time between animation frames
    _SMOOTH_EASE = 0.28         # fraction of remaining distance closed per frame
    _SMOOTH_PX_PER_NOTCH = 70   # target travel distance per wheel notch

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._smooth_target_px = None
        self._smooth_anim_job = None

    def _mouse_wheel_all(self, event):
        if not self._check_if_valid_scroll(event.widget):
            return
        if sys.platform.startswith("win"):
            if self._shift_pressed:
                # Horizontal scroll — not used on this page, keep stock behavior.
                super()._mouse_wheel_all(event)
                return
            notches = -event.delta / 120.0
        elif sys.platform == "darwin":
            # macOS already delivers small, granular deltas — the stock
            # handler feels smooth there without any extra animation.
            super()._mouse_wheel_all(event)
            return
        else:
            notches = -1 if event.num == 4 else 1

        self._smooth_scroll_by(notches * self._SMOOTH_PX_PER_NOTCH)

    def _smooth_scroll_by(self, delta_px):
        canvas = self._parent_canvas
        bbox = canvas.bbox("all")
        if not bbox:
            return
        total = max(1, bbox[3] - bbox[1])
        visible = canvas.winfo_height()
        max_scroll = max(0, total - visible)
        if max_scroll <= 0:
            return

        current_px = canvas.yview()[0] * total
        base = self._smooth_target_px if self._smooth_target_px is not None else current_px
        self._smooth_target_px = min(max_scroll, max(0.0, base + delta_px))

        if not self._smooth_anim_job:
            self._smooth_animate_step()

    def _smooth_animate_step(self):
        canvas = self._parent_canvas
        bbox = canvas.bbox("all")
        if not bbox or self._smooth_target_px is None:
            self._smooth_anim_job = None
            return

        total = max(1, bbox[3] - bbox[1])
        current_px = canvas.yview()[0] * total
        diff = self._smooth_target_px - current_px

        if abs(diff) < 1:
            canvas.yview_moveto(self._smooth_target_px / total)
            self._smooth_target_px = None
            self._smooth_anim_job = None
            return

        new_px = max(0.0, current_px + diff * self._SMOOTH_EASE)
        canvas.yview_moveto(new_px / total)
        self._smooth_anim_job = self.after(self._SMOOTH_STEP_MS, self._smooth_animate_step)


def _make_btn(parent, text, cmd, **ov):
    kw = theme.secondary_button_kwargs()
    kw.update(ov)
    return ctk.CTkButton(parent, text=text, command=cmd, **kw)


SETTINGS_FILE = paths.migrate_legacy_file(
    paths.data_path("yt_downloader", "downloader_settings.json"),
    "modules", "yt_downloader", "downloader_settings.json"
)

HISTORY_FILE = paths.data_path("yt_downloader", "download_history.json")


def _read_history() -> list:
    try:
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _append_history(records: list) -> None:
    """Appends completed-download records ({'id','title','filename','url',
    'output_dir','downloaded_at'}) to the history file. Later records win
    on lookup if a video is ever re-downloaded to a new path."""
    if not records:
        return
    try:
        history = _read_history()
        history.extend(records)
        history = history[-5000:]   # cap growth
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception:
        pass


def _history_by_id() -> dict:
    out = {}
    for rec in _read_history():
        vid = rec.get("id")
        if vid:
            out[vid] = rec   # later entries overwrite — most recent path wins
    return out


# Media extensions worth scanning the output folder for when checking what's
# already been downloaded.
_MEDIA_EXTS = {".mp3", ".m4a", ".mp4", ".webm", ".mkv", ".opus", ".flac", ".wav", ".aac", ".ogg"}


def _normalize_name(s: str) -> str:
    """Strips extension/accents/punctuation and lowercases, so 'Song Title
    (Official Video) [4K].mp4' and 'song title' compare sanely, and so a
    half/truncated filename can still be matched by substring."""
    s = os.path.splitext(s)[0]
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


_INVALID_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _sanitize_folder_name(name: str) -> str:
    """Cleans up a user-typed subscription folder name so it's safe to use
    as a single path segment on Windows/macOS/Linux — strips characters
    that aren't allowed in filenames, collapses whitespace, and trims
    trailing dots/spaces (Windows chokes on those)."""
    name = (name or "").strip()
    name = _INVALID_FOLDER_CHARS.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name


_YTID_TAG_KEY = "ytdlid"          # Vorbis-comment-style key used for flac/opus/ogg
_YTID_MP4_ATOM = "----:com.zyvelia.ytdl:id"   # freeform atom for m4a/mp4


def _embed_video_id_tag(filepath: str, video_id: str) -> bool:
    """Writes the YouTube video ID into the file's own tags right after
    download, so 'have I got this already' can be answered by reading the
    file itself — no separate database to lose, and it survives renames,
    moving folders, even copying to another machine. Best-effort: quietly
    returns False if mutagen isn't installed or the format isn't handled."""
    if not _HAVE_MUTAGEN or not video_id or not filepath or not os.path.exists(filepath):
        return False
    ext = os.path.splitext(filepath)[1].lower()
    try:
        if ext == ".mp3":
            from mutagen.id3 import ID3, TXXX, ID3NoHeaderError
            try:
                tags = ID3(filepath)
            except ID3NoHeaderError:
                tags = ID3()
            tags.delall(f"TXXX:{_YTID_TAG_KEY}")
            tags.add(TXXX(encoding=3, desc=_YTID_TAG_KEY, text=video_id))
            tags.save(filepath)
            return True
        elif ext in (".m4a", ".mp4"):
            from mutagen.mp4 import MP4
            tags = MP4(filepath)
            tags[_YTID_MP4_ATOM] = [video_id.encode("utf-8")]
            tags.save()
            return True
        elif ext == ".flac":
            from mutagen.flac import FLAC
            tags = FLAC(filepath)
            tags[_YTID_TAG_KEY] = video_id
            tags.save()
            return True
        elif ext == ".opus":
            from mutagen.oggopus import OggOpus
            tags = OggOpus(filepath)
            tags[_YTID_TAG_KEY] = video_id
            tags.save()
            return True
        elif ext == ".ogg":
            from mutagen.oggvorbis import OggVorbis
            tags = OggVorbis(filepath)
            tags[_YTID_TAG_KEY] = video_id
            tags.save()
            return True
    except Exception:
        return False
    return False


def _read_video_id_tag(filepath: str):
    """Reads back the ID embedded by _embed_video_id_tag, or None if
    there isn't one (unsupported format, older file, mutagen missing)."""
    if not _HAVE_MUTAGEN:
        return None
    ext = os.path.splitext(filepath)[1].lower()
    try:
        if ext == ".mp3":
            from mutagen.id3 import ID3
            tags = ID3(filepath)
            frame = tags.get(f"TXXX:{_YTID_TAG_KEY}")
            if frame and frame.text:
                return str(frame.text[0])
        elif ext in (".m4a", ".mp4"):
            from mutagen.mp4 import MP4
            tags = MP4(filepath)
            val = tags.get(_YTID_MP4_ATOM)
            if val:
                return val[0].decode("utf-8", "ignore")
        elif ext == ".flac":
            from mutagen.flac import FLAC
            tags = FLAC(filepath)
            if _YTID_TAG_KEY in tags:
                return tags[_YTID_TAG_KEY][0]
        elif ext == ".opus":
            from mutagen.oggopus import OggOpus
            tags = OggOpus(filepath)
            if _YTID_TAG_KEY in tags:
                return tags[_YTID_TAG_KEY][0]
        elif ext == ".ogg":
            from mutagen.oggvorbis import OggVorbis
            tags = OggVorbis(filepath)
            if _YTID_TAG_KEY in tags:
                return tags[_YTID_TAG_KEY][0]
    except Exception:
        return None
    return None


def _scan_output_files(output_dir: str) -> list:
    """Recursively lists media files under output_dir (covers the
    per-playlist subfolders yt-dlp creates for playlist downloads),
    returning a list of (path, normalized_name, embedded_video_id) tuples.
    embedded_video_id is None when there isn't one (mutagen missing,
    unsupported format, or the file predates tag embedding)."""
    results = []
    if not output_dir or not os.path.isdir(output_dir):
        return results
    for root, _dirs, names in os.walk(output_dir):
        for n in names:
            if os.path.splitext(n)[1].lower() in _MEDIA_EXTS:
                path = os.path.join(root, n)
                results.append((path, _normalize_name(n), _read_video_id_tag(path)))
    return results


def _build_tag_index(norm_files: list) -> dict:
    return {tid: path for path, _name, tid in norm_files if tid}


def _match_existing(video: dict, history_by_id: dict, norm_files: list, tag_index: dict = None):
    """Figures out whether `video` (a dict with 'id'/'title') has already
    been downloaded. Three passes, most to least reliable:
      1. Embedded file-tag ID match — read straight off the file itself,
         so it's correct even if history.json was lost/deleted or the
         file got moved/renamed/copied elsewhere.
      2. Exact video-ID match against download history — survives
         renamed files, but only as good as the (separate) history file.
      3. Fuzzy filename match against what's actually in the output
         folder, for files that predate tag embedding/history. Covers
         partial/half filenames via substring + similarity-ratio checks.
    Returns (path, how) — how is "tag", "history", or "filename" — or
    (None, None).
    """
    vid = video.get("id")

    if tag_index and vid and vid in tag_index:
        path = tag_index[vid]
        if path and os.path.exists(path):
            return path, "tag"

    rec = history_by_id.get(vid)
    if rec:
        path = rec.get("filename")
        if path and os.path.exists(path):
            return path, "history"

    title_norm = _normalize_name(video.get("title") or "")
    if not title_norm:
        return None, None

    best_path, best_score = None, 0.0
    for path, name_norm, _tid in norm_files:
        if not name_norm:
            continue
        if title_norm in name_norm or name_norm in title_norm:
            score = 0.95
        else:
            score = SequenceMatcher(None, title_norm, name_norm).ratio()
        if score > best_score:
            best_score, best_path = score, path

    if best_score >= 0.72:
        return best_path, "filename"
    return None, None

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
        "delay_min": 20,
        "delay_max": 45,
        "subscriptions": [],
        "watch_enabled": False,
        "watch_interval_min": 60,
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


def _set_entry_plain(entry, value: str):
    """Like _set_entry but leaves the widget editable (for entries the
    user is meant to type into, e.g. the delay-range boxes)."""
    entry.delete(0, 'end')
    entry.insert(0, value)


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
        self._warned_no_mutagen = False
        self._browse_sub_folder = ""   # subfolder tied to the current browse list, if any

        # Shared download queue — both the manual "Download" button and the
        # subscription watcher feed into this, so there's only ever one
        # yt-dlp download running at a time with the same paced delay
        # between items (whether it's a pasted list or new watcher finds).
        self._dl_queue      = queue.Queue()
        self._worker_lock   = threading.Lock()
        self._worker_active = False
        self._stop_after_current = threading.Event()

        self._watch_job = None

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
        self.bind("<Destroy>", self._on_destroy)

    def _on_destroy(self, _event=None):
        if self._watch_job:
            try:
                self.after_cancel(self._watch_job)
            except Exception:
                pass
            self._watch_job = None

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Wrapped in a scrollable frame so the page never clips/overlaps
        # itself in a smaller window — it scrolls instead.
        self._content = _SmoothCTkScrollableFrame(self, fg_color="transparent")
        self._content.pack(fill="both", expand=True)

        self._build_header()
        self._build_url_row()
        self._build_options_row()
        self._build_watch_section()
        self._build_browse_section()
        self._build_log()

    def _build_header(self):
        header = ctk.CTkFrame(self._content, fg_color=theme.PANEL, corner_radius=10)
        header.pack(fill="x", padx=10, pady=(10, 3))

        ctk.CTkLabel(header, text="▶  YouTube Downloader",
                     font=("Segoe UI", 18, "bold"), text_color=theme.TEXT
                     ).pack(side="left", padx=10, pady=8)

        self._status_lbl = ctk.CTkLabel(header, text="Idle", text_color=theme.MUTED,
                                        font=("Segoe UI", 11))
        self._status_lbl.pack(side="right", padx=10)

    def _build_url_row(self):
        panel = ctk.CTkFrame(self._content, fg_color=theme.PANEL, corner_radius=10)
        panel.pack(fill="x", padx=10, pady=(0, 3))

        inner = ctk.CTkFrame(panel, fg_color="transparent")
        inner.pack(fill="x", padx=8, pady=6)

        top_row = ctk.CTkFrame(inner, fg_color="transparent")
        top_row.pack(fill="x")

        ctk.CTkLabel(top_row, text="URLs (one per line)", text_color=theme.MUTED,
                     font=("Segoe UI", 11)).pack(side="left", padx=(0, 8))

        # Small helper label showing how many URLs are currently queued.
        self._queue_count_lbl = ctk.CTkLabel(
            top_row, text="", text_color=theme.MUTED, font=("Segoe UI", 10))
        self._queue_count_lbl.pack(side="right")

        self._url_box = ctk.CTkTextbox(
            inner, height=60, corner_radius=8, fg_color=theme.PANEL_2,
            text_color=theme.TEXT, font=("Consolas", 11), wrap="none")
        self._url_box.pack(fill="x", expand=True, pady=(3, 6))
        self._url_box.bind("<KeyRelease>", lambda e: self._update_queue_count())

        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(fill="x")

        _dl_kw = theme.primary_button_kwargs()
        _dl_kw.update(width=130, height=28)
        self._dl_btn = _make_btn(btn_row, "⬇  Download", self._start_download, **_dl_kw)
        self._dl_btn.pack(side="left")

        self._stop_btn = _make_btn(
            btn_row, "⏹ Stop After Current", self._toggle_stop_after_current,
            width=150, height=28)
        self._stop_btn.configure(state="disabled")
        self._stop_btn.pack(side="left", padx=(6, 0))

        self._update_btn = _make_btn(btn_row, "⟳  Update yt-dlp", self._start_update,
                                     width=120, height=28)
        self._update_btn.pack(side="left", padx=(6, 0))

        # ── Delay between downloads (helps avoid triggering rate limits
        # when downloading a whole list of songs back to back) ──
        delay_frame = ctk.CTkFrame(btn_row, fg_color="transparent")
        delay_frame.pack(side="right")

        ctk.CTkLabel(delay_frame, text="sec", text_color=theme.MUTED,
                     font=("Segoe UI", 10)).pack(side="right", padx=(3, 0))
        self._delay_max_entry = ctk.CTkEntry(
            delay_frame, width=40, height=26, corner_radius=8, fg_color=theme.PANEL_2,
            text_color=theme.TEXT, border_color=theme.PANEL_2, font=("Segoe UI", 11))
        self._delay_max_entry.pack(side="right")
        ctk.CTkLabel(delay_frame, text="–", text_color=theme.MUTED).pack(side="right", padx=2)
        self._delay_min_entry = ctk.CTkEntry(
            delay_frame, width=40, height=26, corner_radius=8, fg_color=theme.PANEL_2,
            text_color=theme.TEXT, border_color=theme.PANEL_2, font=("Segoe UI", 11))
        self._delay_min_entry.pack(side="right")
        ctk.CTkLabel(delay_frame, text="Delay:", text_color=theme.MUTED,
                     font=("Segoe UI", 11)).pack(side="right", padx=(0, 5))

    def _update_queue_count(self):
        urls = self._get_urls()
        if not urls:
            self._queue_count_lbl.configure(text="")
        else:
            self._queue_count_lbl.configure(text=f"{len(urls)} URL{'s' if len(urls) != 1 else ''} queued")

    def _get_urls(self):
        raw = self._url_box.get("1.0", "end")
        urls, seen = [], set()
        for line in raw.splitlines():
            u = line.strip()
            # Allow comma-separated URLs on a single line too.
            for piece in u.split(","):
                piece = piece.strip()
                if piece and piece not in seen:
                    seen.add(piece)
                    urls.append(piece)
        return urls

    def _build_options_row(self):
        panel = ctk.CTkFrame(self._content, fg_color=theme.PANEL, corner_radius=10)
        panel.pack(fill="x", padx=10, pady=(0, 3))

        inner = ctk.CTkFrame(panel, fg_color="transparent")
        inner.pack(fill="x", padx=8, pady=6)

        # ── Type ──
        ctk.CTkLabel(inner, text="Type", text_color=theme.MUTED,
                     font=("Segoe UI", 11)).pack(side="left", padx=(0, 4))

        self._type_var = ctk.StringVar(value="video")
        for label, val in [("Single Video", "video"), ("Playlist", "playlist")]:
            ctk.CTkRadioButton(
                inner, text=label, variable=self._type_var, value=val,
                text_color=theme.TEXT, fg_color=theme.ACCENT, hover_color="#2f7fd6",
                font=("Segoe UI", 11), radiobutton_width=16, radiobutton_height=16,
            ).pack(side="left", padx=4)

        # ── Format ──
        ctk.CTkLabel(inner, text="Format", text_color=theme.MUTED,
                     font=("Segoe UI", 11)).pack(side="left", padx=(14, 4))

        self._fmt_var = ctk.StringVar(value="mp3")
        for label, val in [("MP3", "mp3"), ("MP4", "mp4")]:
            ctk.CTkRadioButton(
                inner, text=label, variable=self._fmt_var, value=val,
                text_color=theme.TEXT, fg_color=theme.ACCENT, hover_color="#2f7fd6",
                font=("Segoe UI", 11), radiobutton_width=16, radiobutton_height=16,
            ).pack(side="left", padx=4)

        # ── Quality (MP3) ──
        ctk.CTkLabel(inner, text="Quality", text_color=theme.MUTED,
                     font=("Segoe UI", 11)).pack(side="left", padx=(14, 4))

        self._quality_var = ctk.StringVar(value="192")
        ctk.CTkOptionMenu(
            inner, variable=self._quality_var,
            values=["320", "256", "192", "128", "96"],
            fg_color=theme.PANEL_2, button_color=theme.ACCENT,
            button_hover_color="#2f7fd6", text_color=theme.TEXT,
            width=70, height=26, font=("Segoe UI", 11)
        ).pack(side="left")

        ctk.CTkLabel(inner, text="kbps", text_color=theme.MUTED,
                     font=("Segoe UI", 10)).pack(side="left", padx=(3, 0))

    def _build_watch_section(self):
        panel = ctk.CTkFrame(self._content, fg_color=theme.PANEL, corner_radius=10)
        panel.pack(fill="x", padx=10, pady=(0, 3))

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=8, pady=(6, 3))

        ctk.CTkLabel(top, text="🔔  Watch for new uploads",
                     font=("Segoe UI", 12, "bold"), text_color=theme.TEXT).pack(side="left")

        self._watch_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            top, text="Auto-check every", variable=self._watch_var,
            text_color=theme.MUTED, font=("Segoe UI", 11), fg_color=theme.ACCENT,
            hover_color="#2f7fd6", command=self._on_watch_toggle,
            checkbox_width=16, checkbox_height=16,
        ).pack(side="left", padx=(12, 4))

        self._watch_interval_entry = ctk.CTkEntry(
            top, width=40, height=24, corner_radius=8, fg_color=theme.PANEL_2,
            text_color=theme.TEXT, border_color=theme.PANEL_2, font=("Segoe UI", 11))
        self._watch_interval_entry.pack(side="left")
        self._watch_interval_entry.bind("<FocusOut>", lambda e: self._on_watch_interval_changed())
        ctk.CTkLabel(top, text="min", text_color=theme.MUTED,
                     font=("Segoe UI", 10)).pack(side="left", padx=(3, 0))

        _make_btn(top, "Check Now", self._check_subscriptions_now,
                  width=90, height=26).pack(side="right")

        add_row = ctk.CTkFrame(panel, fg_color="transparent")
        add_row.pack(fill="x", padx=8, pady=(0, 4))

        self._sub_url_entry = ctk.CTkEntry(
            add_row, placeholder_text="Channel 'Videos' tab or playlist URL to watch…",
            corner_radius=8, fg_color=theme.PANEL_2, text_color=theme.TEXT,
            border_color=theme.PANEL_2, height=26, font=("Segoe UI", 11))
        self._sub_url_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._sub_url_entry.bind("<Return>", lambda e: self._add_subscription())

        _make_btn(add_row, "+ Add", self._add_subscription, width=64, height=26).pack(side="left")

        self._sub_list_frame = ctk.CTkScrollableFrame(
            panel, fg_color="transparent", height=150)
        self._sub_list_frame.pack(fill="x", padx=8, pady=(0, 6))

        self._sub_empty_lbl = ctk.CTkLabel(
            self._sub_list_frame, text="Not watching anything yet.",
            text_color=theme.MUTED, font=("Segoe UI", 10))
        self._sub_empty_lbl.pack(anchor="w")

    def _build_browse_section(self):
        panel = ctk.CTkFrame(self._content, fg_color=theme.PANEL, corner_radius=10)
        panel.pack(fill="x", padx=10, pady=(0, 3))
        self._browse_panel = panel

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=8, pady=(6, 3))

        ctk.CTkLabel(top, text="🎯  Browse & pick videos",
                     font=("Segoe UI", 12, "bold"), text_color=theme.TEXT).pack(side="left")

        fetch_row = ctk.CTkFrame(panel, fg_color="transparent")
        fetch_row.pack(fill="x", padx=8, pady=(0, 4))

        self._browse_url_entry = ctk.CTkEntry(
            fetch_row, placeholder_text="Channel 'Videos' tab or playlist URL…",
            corner_radius=8, fg_color=theme.PANEL_2, text_color=theme.TEXT,
            border_color=theme.PANEL_2, height=26, font=("Segoe UI", 11))
        self._browse_url_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._browse_url_entry.bind("<Return>", lambda e: self._fetch_browse_list())

        self._browse_fetch_btn = _make_btn(
            fetch_row, "List Videos", self._fetch_browse_list, width=96, height=26)
        self._browse_fetch_btn.pack(side="left")

        action_row = ctk.CTkFrame(panel, fg_color="transparent")
        action_row.pack(fill="x", padx=8, pady=(0, 4))

        self._browse_status_lbl = ctk.CTkLabel(
            action_row, text="", text_color=theme.MUTED, font=("Segoe UI", 10))
        self._browse_status_lbl.pack(side="left")

        self._browse_hide_downloaded_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            action_row, text="Hide already-downloaded", variable=self._browse_hide_downloaded_var,
            text_color=theme.MUTED, font=("Segoe UI", 10), fg_color=theme.ACCENT,
            hover_color="#2f7fd6", checkbox_width=14, checkbox_height=14,
            command=self._rerender_browse_list,
        ).pack(side="left", padx=(10, 0))

        _dlsel_kw = theme.primary_button_kwargs()
        _dlsel_kw.update(width=130, height=26)
        _make_btn(action_row, "Download Selected", self._download_selected_browse,
                  **_dlsel_kw).pack(side="right")
        _make_btn(action_row, "None", lambda: self._set_all_browse_checks(False),
                  width=50, height=26).pack(side="right", padx=(0, 5))
        _make_btn(action_row, "All", lambda: self._set_all_browse_checks(True),
                  width=50, height=26).pack(side="right", padx=(0, 5))
        _make_btn(action_row, "🔄 Rescan", self._rescan_browse_matches,
                  width=80, height=26).pack(side="right", padx=(0, 5))

        self._browse_list_frame = ctk.CTkScrollableFrame(
            panel, fg_color=theme.PANEL_2, corner_radius=8, height=130)
        self._browse_list_frame.pack(fill="x", padx=8, pady=(0, 6))

        self._browse_videos = []   # list of {"id","url","title","var"}
        self._browse_all_videos = []   # raw fetched+matched videos, independent of hide-toggle render
        self._browse_feed_title = None
        self._browse_empty_lbl = ctk.CTkLabel(
            self._browse_list_frame, text="Paste a channel or playlist URL above and click "
            "\"List Videos\" to pick specific ones to download.",
            text_color=theme.MUTED, font=("Segoe UI", 10), wraplength=520, justify="left")
        self._browse_empty_lbl.pack(anchor="w", padx=6, pady=6)

    def _build_log(self):
        panel = ctk.CTkFrame(self._content, fg_color=theme.PANEL, corner_radius=10)
        panel.pack(fill="x", expand=False, padx=10, pady=(0, 10))

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=8, pady=(6, 3))

        ctk.CTkLabel(top, text="Download Log",
                     font=("Segoe UI", 12, "bold"), text_color=theme.TEXT).pack(side="left")

        _make_btn(top, "🗑 Clear", self._clear_log, width=64, height=24).pack(side="right")

        self._log = ctk.CTkTextbox(
            panel, fg_color=theme.PANEL_2, text_color=theme.TEXT,
            corner_radius=8, font=("Consolas", 10), height=100, state="disabled")
        self._log.pack(fill="x", expand=False, padx=8, pady=(0, 6))

        # Progress bar
        self._progress = ctk.CTkProgressBar(
            panel, progress_color=theme.ACCENT, fg_color=theme.PANEL_2, corner_radius=4)
        self._progress.set(0)
        self._progress.pack(fill="x", padx=8, pady=(0, 6))

    # ── Settings ──────────────────────────────────────────────────────────────

    def _load_settings(self):
        s = _read_all_settings()
        self._fmt_var.set(s.get("format", "mp3"))
        self._type_var.set(s.get("type", "video"))
        self._quality_var.set(s.get("quality", "192"))
        _set_entry_plain(self._delay_min_entry, str(s.get("delay_min", 20)))
        _set_entry_plain(self._delay_max_entry, str(s.get("delay_max", 45)))

        _set_entry_plain(self._watch_interval_entry, str(s.get("watch_interval_min", 60)))
        self._watch_var.set(bool(s.get("watch_enabled", False)))
        self._refresh_subscription_list()
        self._schedule_watch_check()

    def _save_settings(self):
        _write_settings({
            "format": self._fmt_var.get(),
            "type": self._type_var.get(),
            "quality": self._quality_var.get(),
            "delay_min": self._get_delay_bounds()[0],
            "delay_max": self._get_delay_bounds()[1],
        })

    def _get_delay_bounds(self):
        """Returns (min_seconds, max_seconds) for the inter-download delay,
        falling back to sane defaults and swapping/clamping if the user
        typed something odd."""
        def _num(entry, default):
            try:
                v = float(entry.get().strip())
                return max(0.0, v)
            except (ValueError, AttributeError):
                return default

        lo = _num(self._delay_min_entry, 20)
        hi = _num(self._delay_max_entry, 45)
        if hi < lo:
            lo, hi = hi, lo
        return lo, hi

    # ── Subscription watcher ─────────────────────────────────────────────────

    def _get_subscriptions(self):
        return list(_read_setting("subscriptions", []) or [])

    def _save_subscriptions(self, subs):
        _write_settings({"subscriptions": subs})

    def _get_watch_interval_min(self):
        try:
            v = float(self._watch_interval_entry.get().strip())
            return max(5.0, v)   # floor at 5 min so a typo can't hammer YouTube
        except (ValueError, AttributeError):
            return 60.0

    def _on_watch_toggle(self):
        _write_settings({"watch_enabled": bool(self._watch_var.get())})
        self._schedule_watch_check()

    def _on_watch_interval_changed(self):
        _write_settings({"watch_interval_min": self._get_watch_interval_min()})
        self._schedule_watch_check()

    def _schedule_watch_check(self):
        if self._watch_job:
            try:
                self.after_cancel(self._watch_job)
            except Exception:
                pass
            self._watch_job = None

        if not self._watch_var.get():
            return

        interval_ms = int(self._get_watch_interval_min() * 60 * 1000)
        self._watch_job = self.after(interval_ms, self._on_watch_tick)

    def _on_watch_tick(self):
        self._check_subscriptions_now(manual=False)
        self._schedule_watch_check()

    def _refresh_subscription_list(self):
        for child in self._sub_list_frame.winfo_children():
            child.destroy()

        subs = self._get_subscriptions()
        if not subs:
            self._sub_empty_lbl = ctk.CTkLabel(
                self._sub_list_frame, text="Not watching anything yet.",
                text_color=theme.MUTED, font=("Segoe UI", 10))
            self._sub_empty_lbl.pack(anchor="w")
            return

        for sub in subs:
            row = ctk.CTkFrame(self._sub_list_frame, fg_color=theme.PANEL_2, corner_radius=8)
            row.pack(fill="x", pady=(0, 3))

            label = sub.get("label") or sub["url"]
            ctk.CTkLabel(row, text=label, text_color=theme.TEXT,
                         font=("Segoe UI", 11), anchor="w").pack(
                side="left", fill="x", expand=True, padx=(8, 4), pady=4)

            _make_btn(row, "✕", lambda u=sub["url"]: self._remove_subscription(u),
                      width=26, height=22).pack(side="right", padx=(0, 6), pady=3)
            _make_btn(row, "🔍 Browse", lambda u=sub["url"]: self._browse_from_subscription(u),
                      width=76, height=22).pack(side="right", padx=(0, 4), pady=3)

            folder_entry = ctk.CTkEntry(
                row, placeholder_text="folder (optional)", width=110, height=22,
                corner_radius=6, fg_color=theme.PANEL, text_color=theme.TEXT,
                border_color=theme.PANEL, font=("Segoe UI", 10))
            folder_entry.insert(0, sub.get("folder") or "")
            folder_entry.pack(side="right", padx=(0, 4), pady=3)
            folder_entry.bind(
                "<FocusOut>", lambda e, u=sub["url"], ent=folder_entry: self._set_subscription_folder(u, ent.get()))
            folder_entry.bind(
                "<Return>", lambda e, u=sub["url"], ent=folder_entry: self._set_subscription_folder(u, ent.get()))
            ctk.CTkLabel(row, text="📁", text_color=theme.MUTED,
                         font=("Segoe UI", 11)).pack(side="right", padx=(4, 0), pady=3)

    def _set_subscription_folder(self, url, raw_folder):
        clean = _sanitize_folder_name(raw_folder)
        subs = self._get_subscriptions()
        changed = False
        for s in subs:
            if s["url"] == url and (s.get("folder") or "") != clean:
                s["folder"] = clean
                changed = True
        if changed:
            self._save_subscriptions(subs)
            if clean:
                self._log_msg(f"📁 New uploads from that watch will now go into: {clean}/")
            else:
                self._log_msg("📁 That watch will download into your normal output folder again.")

    def _add_subscription(self):
        url = self._sub_url_entry.get().strip()
        if not url:
            return
        subs = self._get_subscriptions()
        if any(s["url"] == url for s in subs):
            self._log_msg("ℹ Already watching that URL.")
            return

        subs.append({"url": url, "label": url, "folder": "", "last_ids": []})
        self._save_subscriptions(subs)
        self._sub_url_entry.delete(0, "end")
        self._refresh_subscription_list()
        self._log_msg(f"👁 Added to watch list: {url} — checking it now to set a baseline "
                      f"(existing uploads won't be downloaded, only new ones from here on).")
        self._check_subscriptions_now(manual=False)

    def _remove_subscription(self, url):
        subs = [s for s in self._get_subscriptions() if s["url"] != url]
        self._save_subscriptions(subs)
        self._refresh_subscription_list()
        self._log_msg(f"Removed from watch list: {url}")

    def _browse_from_subscription(self, url):
        """Reuses a watched channel/playlist's already-saved URL to
        populate the Browse & pick section below, instead of making the
        user copy/paste it again — then fetches its video list right
        away and scrolls it into view."""
        sub = next((s for s in self._get_subscriptions() if s["url"] == url), None)
        self._browse_sub_folder = (sub.get("folder") if sub else "") or ""
        self._browse_url_entry.delete(0, "end")
        self._browse_url_entry.insert(0, url)
        self._fetch_browse_list()
        self.after(100, self._scroll_to_browse_section)

    def _scroll_to_browse_section(self):
        try:
            canvas = self._content._parent_canvas
            bbox = canvas.bbox("all")
            if not bbox:
                return
            total_height = bbox[3] - bbox[1]
            if total_height <= 0:
                return
            target_y = self._browse_panel.winfo_y()
            frac = max(0.0, min(1.0, target_y / total_height))
            canvas.yview_moveto(frac)
        except Exception:
            pass

    def _check_subscriptions_now(self, manual=True):
        if youtube_dl is None:
            self._log_msg("❌ yt-dlp not installed. Run: pip install yt-dlp")
            return
        subs = self._get_subscriptions()
        if not subs:
            if manual:
                self._log_msg("No subscriptions to check yet — add a channel or playlist URL above.")
            return
        threading.Thread(target=self._check_subscriptions_worker, args=(subs, manual), daemon=True).start()

    def _fetch_latest_video_ids(self, url, limit=20):
        """Returns (feed_title, [{"id","url","title"}, ...]) for uploads,
        without downloading anything. limit=None fetches the whole
        channel/playlist instead of just the most recent ones — can be
        slow on very large channels since yt-dlp still has to page through
        the listing."""
        opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
        }
        if limit is not None:
            opts["playlistend"] = limit
        with youtube_dl.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

        feed_title = info.get("title") or info.get("channel") or info.get("uploader")
        entries = info.get("entries") or [info]

        # A bare channel URL (no /videos, /shorts, /streams suffix) flattens
        # into the channel's TABS (Videos / Live / Shorts) instead of actual
        # uploads — each "entry" is itself a sub-playlist whose "id" is a
        # channel/playlist id, not a real 11-char video id. If we don't catch
        # this, we build a bogus watch?v=<channel id> URL later and yt-dlp
        # correctly reports it as "unavailable". Detect that case and drill
        # into the Videos tab (falling back to the first tab) to get the
        # real video entries instead.
        video_id_re = re.compile(r"^[0-9A-Za-z_-]{11}$")

        def _looks_like_tab(e):
            vid = e.get("id") or ""
            return not video_id_re.match(vid)

        if entries and all(_looks_like_tab(e) for e in entries):
            videos_tab = next(
                (e for e in entries
                 if (e.get("title") or "").strip().lower().endswith("videos")),
                None,
            )
            tab_url = (videos_tab or entries[0]).get("url")
            if tab_url:
                with youtube_dl.YoutubeDL(opts) as ydl:
                    tab_info = ydl.extract_info(tab_url, download=False)
                feed_title = tab_info.get("title") or tab_info.get("channel") or feed_title
                entries = tab_info.get("entries") or []

        results = []
        for e in entries:
            if not e:
                continue
            vid = e.get("id")
            if vid and not video_id_re.match(vid):
                # Not a real video id (e.g. a leftover tab/playlist entry) —
                # skip it rather than building a broken watch URL.
                continue
            vurl = e.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else None)
            if vid and vurl:
                results.append({"id": vid, "url": vurl, "title": e.get("title") or vid})
        return feed_title, results

    def _check_subscriptions_worker(self, subs, manual):
        if manual:
            self._log_msg(f"🔎 Checking {len(subs)} subscription(s) for new uploads…")

        new_items = []
        changed = False

        for sub in subs:
            try:
                feed_title, videos = self._fetch_latest_video_ids(sub["url"])
            except Exception as e:
                self._log_msg(f"⚠ Couldn't check {sub.get('label') or sub['url']}: {e}")
                continue

            if feed_title and sub.get("label") == sub["url"]:
                sub["label"] = feed_title
                changed = True

            last_ids = set(sub.get("last_ids") or [])
            if not last_ids:
                # First time watching this one — set a baseline instead of
                # queuing its whole back-catalogue.
                sub["last_ids"] = [v["id"] for v in videos]
                changed = True
                continue

            fresh = [v for v in videos if v["id"] not in last_ids]
            if fresh:
                self._log_msg(
                    f"🆕 {len(fresh)} new upload(s) from {sub.get('label') or sub['url']}")
                # Tag each fresh video with the folder (if any) configured
                # for this subscription, so it lands in the right place
                # once queued below.
                folder = sub.get("folder") or ""
                for v in fresh:
                    v["_sub_folder"] = folder
                new_items.extend(fresh)

            sub["last_ids"] = list({v["id"] for v in videos} | last_ids)[-100:]
            changed = True

        if changed:
            self._save_subscriptions(subs)
            self.after(0, self._refresh_subscription_list)

        if new_items:
            base_output_dir = _read_setting("output_dir", os.path.expanduser("~")).strip()
            fmt        = self._fmt_var.get()
            quality    = self._quality_var.get()
            cookie     = _read_setting("cookie_file", "").strip()

            if not base_output_dir or not os.path.isdir(base_output_dir):
                self._log_msg("❌ Found new uploads, but the output folder isn't set/valid — "
                              "set it in this module's settings to auto-download them.")
                return

            # Belt-and-suspenders check: last_ids should already prevent
            # re-queuing, but if a file exists on disk (downloaded
            # manually, moved back in, or from before last_ids was set)
            # skip it instead of downloading a duplicate. This scans the
            # whole output tree (including subfolders), so it catches a
            # video regardless of which subfolder it's actually sitting in.
            history_by_id = _history_by_id()
            norm_files = _scan_output_files(base_output_dir)
            tag_index = _build_tag_index(norm_files)
            still_new = []
            for v in new_items:
                path, _how = _match_existing(v, history_by_id, norm_files, tag_index)
                if path:
                    self._log_msg(f"⏭ Skipping (already have it): {v['title']}")
                else:
                    still_new.append(v)
            new_items = still_new

            if not new_items:
                return

            items = []
            for v in new_items:
                folder = v.get("_sub_folder") or ""
                out_dir = os.path.join(base_output_dir, folder) if folder else base_output_dir
                try:
                    os.makedirs(out_dir, exist_ok=True)
                except Exception as e:
                    self._log_msg(f"⚠ Couldn't create folder '{folder}', using the normal "
                                  f"output folder instead: {e}")
                    out_dir = base_output_dir
                items.append({
                    "url": v["url"], "output_dir": out_dir, "fmt": fmt,
                    "dl_type": "video", "quality": quality, "cookie": cookie,
                    "label": f"New upload: {v['title']}" + (f"  → {folder}/" if folder else ""),
                })
            self._enqueue_downloads(items)
        elif manual:
            self._log_msg("✅ No new uploads since last check.")

    # ── Browse & pick ─────────────────────────────────────────────────────────

    def _fetch_browse_list(self):
        if youtube_dl is None:
            self._log_msg("❌ yt-dlp not installed. Run: pip install yt-dlp")
            return
        url = self._browse_url_entry.get().strip()
        if not url:
            self._log_msg("❌ Paste a channel or playlist URL first.")
            return

        # If this URL happens to match a watched subscription, adopt its
        # folder automatically — covers pasting the same URL by hand
        # instead of going through the "🔍 Browse" button on that
        # subscription (which sets this explicitly already).
        sub = next((s for s in self._get_subscriptions() if s["url"] == url), None)
        self._browse_sub_folder = (sub.get("folder") if sub else "") or ""

        self._browse_fetch_btn.configure(state="disabled", text="Loading…")
        self._browse_status_lbl.configure(text="Fetching full video list… this can take a bit on big channels.")
        threading.Thread(target=self._fetch_browse_list_worker, args=(url,), daemon=True).start()

    def _fetch_browse_list_worker(self, url):
        try:
            feed_title, videos = self._fetch_latest_video_ids(url, limit=None)
        except Exception as e:
            self._log_msg(f"❌ Couldn't fetch that list: {e}")
            self.after(0, lambda: self._browse_status_lbl.configure(text="Couldn't fetch that list."))
            videos, feed_title = [], None

        if videos:
            output_dir = _read_setting("output_dir", os.path.expanduser("~")).strip()
            history_by_id = _history_by_id()
            norm_files = _scan_output_files(output_dir)
            tag_index = _build_tag_index(norm_files)
            for v in videos:
                path, how = _match_existing(v, history_by_id, norm_files, tag_index)
                v["existing_path"] = path
                v["existing_how"] = how

        self.after(0, lambda: self._render_browse_list(feed_title, videos))
        self.after(0, lambda: self._browse_fetch_btn.configure(state="normal", text="List Videos"))

    def _rescan_browse_matches(self):
        """Re-checks the currently-listed videos against the output folder
        and history without re-fetching from YouTube — useful after moving
        files around or downloading some manually."""
        if not self._browse_all_videos:
            return
        threading.Thread(target=self._rescan_browse_matches_worker, daemon=True).start()

    def _rescan_browse_matches_worker(self):
        output_dir = _read_setting("output_dir", os.path.expanduser("~")).strip()
        history_by_id = _history_by_id()
        norm_files = _scan_output_files(output_dir)
        tag_index = _build_tag_index(norm_files)
        for v in self._browse_all_videos:
            path, how = _match_existing(v, history_by_id, norm_files, tag_index)
            v["existing_path"] = path
            v["existing_how"] = how
        self.after(0, self._rerender_browse_list)

    def _render_browse_list(self, feed_title, videos):
        self._browse_feed_title = feed_title
        self._browse_all_videos = videos
        self._rerender_browse_list()

    def _rerender_browse_list(self):
        for child in self._browse_list_frame.winfo_children():
            child.destroy()
        self._browse_videos = []

        videos = self._browse_all_videos
        if not videos:
            self._browse_empty_lbl = ctk.CTkLabel(
                self._browse_list_frame, text="No videos found for that URL.",
                text_color=theme.MUTED, font=("Segoe UI", 10))
            self._browse_empty_lbl.pack(anchor="w", padx=5, pady=5)
            self._browse_status_lbl.configure(text="")
            return

        hide_downloaded = self._browse_hide_downloaded_var.get()
        matched_count = sum(1 for v in videos if v.get("existing_path"))
        shown = 0

        for v in videos:
            already = bool(v.get("existing_path"))
            if already and hide_downloaded:
                continue
            shown += 1
            var = ctk.BooleanVar(value=False)
            text = v["title"]
            color = theme.TEXT
            if already:
                how = v.get("existing_how")
                badge = {
                    "tag": "✅ already have it",
                    "history": "✅ already have it (history)",
                    "filename": "≈ possibly have it (name match)",
                }.get(how, "✅ already have it")
                text = f"{text}  [{badge}]"
                color = theme.MUTED
            ctk.CTkCheckBox(
                self._browse_list_frame, text=text, variable=var,
                text_color=color, font=("Segoe UI", 11), fg_color=theme.ACCENT,
                hover_color="#2f7fd6", checkbox_width=16, checkbox_height=16,
            ).pack(anchor="w", padx=5, pady=2)
            self._browse_videos.append({**v, "var": var})

        if shown == 0 and hide_downloaded:
            self._browse_empty_lbl = ctk.CTkLabel(
                self._browse_list_frame, text="All videos in this list are already downloaded.",
                text_color=theme.MUTED, font=("Segoe UI", 10))
            self._browse_empty_lbl.pack(anchor="w", padx=5, pady=5)

        label = self._browse_feed_title or "that list"
        suffix = f" — {matched_count} already downloaded" if matched_count else ""
        folder_note = f" — downloading into: {self._browse_sub_folder}/" if self._browse_sub_folder else ""
        self._browse_status_lbl.configure(text=f"{len(videos)} video(s) from {label}{suffix}{folder_note}")

    def _set_all_browse_checks(self, selected: bool):
        for v in self._browse_videos:
            v["var"].set(selected)

    def _download_selected_browse(self):
        selected = [v for v in self._browse_videos if v["var"].get()]
        if not selected:
            self._log_msg("❌ Nothing checked — tick the videos you want first.")
            return

        # Auto-skip only high-confidence matches (embedded file tag, or a
        # history record with a file that still exists). Fuzzy filename
        # matches are informational-only in the badge because they can be
        # wrong (similar titles, remixes, etc.) — those still download, but
        # we flag them so it's obvious it's worth a second look.
        already_have = [v for v in selected if v.get("existing_how") in ("tag", "history")]
        possibly_have = [v for v in selected if v.get("existing_how") == "filename"]
        to_download = [v for v in selected if not v.get("existing_path")] + possibly_have

        if already_have:
            for v in already_have:
                self._log_msg(f"⏭ Skipping (already have it): {v['title']}")
        if possibly_have:
            for v in possibly_have:
                self._log_msg(f"⚠ Downloading anyway (only a fuzzy filename match, could be wrong): {v['title']}")

        if not to_download:
            self._log_msg("Nothing to download — every checked video is already in your library.")
            return

        output_dir = _read_setting("output_dir", os.path.expanduser("~")).strip()
        fmt        = self._fmt_var.get()
        quality    = self._quality_var.get()
        cookie     = _read_setting("cookie_file", "").strip()

        if not output_dir or not os.path.isdir(output_dir):
            self._log_msg("❌ Please select a valid output folder.")
            return
        if cookie and not os.path.exists(cookie):
            self._log_msg(f"❌ Cookie file not found: {cookie}")
            return

        if self._browse_sub_folder:
            output_dir = os.path.join(output_dir, self._browse_sub_folder)
            try:
                os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                self._log_msg(f"⚠ Couldn't create folder '{self._browse_sub_folder}', using the "
                              f"normal output folder instead: {e}")
                output_dir = _read_setting("output_dir", os.path.expanduser("~")).strip()

        delay_min, delay_max = self._get_delay_bounds()
        if len(to_download) > 1:
            self._log_msg(
                f"Queued {len(to_download)} selected video(s) — waiting "
                f"{delay_min:g}–{delay_max:g}s between each."
            )

        items = [{
            "url": v["url"], "output_dir": output_dir, "fmt": fmt,
            "dl_type": "video", "quality": quality, "cookie": cookie,
            "label": v["title"],
        } for v in to_download]
        self._enqueue_downloads(items)

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
            # source install to run pip against — but yt-dlp is pure Python,
            # so we can fetch the wheel straight from PyPI ourselves and
            # unpack it into a folder that shadows the version frozen into
            # the exe (see yt_dlp_update_dir() / sys.path setup at the top
            # of this file).
            if getattr(sys, "frozen", False):
                self._update_worker_frozen()
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
                self._log_msg("✅ yt-dlp updated.")
                self.after(0, self._schedule_restart)
            else:
                # "Requirement already satisfied" case — pip exits 0 having
                # done nothing, so don't claim an update happened.
                self._log_msg("✅ Already up to date — nothing to install.")
        except Exception as e:
            self._log_msg(f"❌ Update error: {e}")
        finally:
            self.after(0, lambda: self._update_btn.configure(
                state="normal", text="⟳  Update yt-dlp"))

    def _update_worker_frozen(self):
        """Downloads yt-dlp's wheel from PyPI and unpacks the pure-Python
        `yt_dlp` package into yt_dlp_update_dir(), which gets put at the
        front of sys.path on next launch (see top of file) — shadowing
        the version bundled into the exe. No pip, no compiler, no admin
        rights needed, since the package is pure Python."""
        self._log_msg("Looking up the latest yt-dlp release on PyPI...")
        try:
            with urllib.request.urlopen(
                "https://pypi.org/pypi/yt-dlp/json", timeout=15
            ) as resp:
                data = json.load(resp)
        except Exception as e:
            self._log_msg(f"❌ Couldn't reach PyPI: {e}")
            return

        latest = data.get("info", {}).get("version")
        if not latest:
            self._log_msg("❌ PyPI didn't return a version number.")
            return

        releases = data.get("releases", {}).get(latest, [])
        wheel = next(
            (r for r in releases
             if r.get("packagetype") == "bdist_wheel" and r.get("filename", "").endswith(".whl")),
            None,
        )
        if wheel is None:
            self._log_msg(
                f"❌ No wheel found for yt-dlp {latest} on PyPI — can't self-update "
                f"a bundled build without one. Grab the latest release build instead."
            )
            return

        url = wheel["url"]
        self._log_msg(f"Downloading yt-dlp {latest}...")
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                wheel_bytes = resp.read()
        except Exception as e:
            self._log_msg(f"❌ Download failed: {e}")
            return

        self._log_msg("Unpacking...")
        try:
            update_dir = yt_dlp_update_dir()
            staging_dir = update_dir + ".staging"
            if os.path.isdir(staging_dir):
                shutil.rmtree(staging_dir)
            os.makedirs(staging_dir, exist_ok=True)

            with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as zf:
                members = [n for n in zf.namelist() if n.startswith("yt_dlp/")]
                if not members:
                    self._log_msg("❌ That wheel didn't contain a yt_dlp/ package — aborting.")
                    shutil.rmtree(staging_dir, ignore_errors=True)
                    return
                zf.extractall(staging_dir, members=members)

            # Swap in atomically: remove the old unpacked copy (if any),
            # then rename the freshly-extracted one into place.
            os.makedirs(os.path.dirname(update_dir), exist_ok=True)
            if os.path.isdir(update_dir):
                shutil.rmtree(update_dir)
            os.rename(staging_dir, update_dir)
        except Exception as e:
            self._log_msg(f"❌ Couldn't unpack the update: {e}")
            return

        self._log_msg(f"✅ yt-dlp {latest} downloaded and ready.")
        self.after(0, self._schedule_restart)

    def _schedule_restart(self, seconds: float = 2.0):
        """Auto-restarts the app so an update takes effect immediately,
        instead of making the user close and reopen it manually. Holds
        off if a download is actively running so it doesn't get cut off
        mid-file — the user can restart by hand once it's done."""
        if self._downloading:
            self._log_msg(
                "ℹ A download is still in progress, so I won't auto-restart — "
                "restart the app manually once it finishes for the update to "
                "take effect."
            )
            return
        self._log_msg(f"🔄 Restarting in {seconds:g}s to load the update...")
        self.after(int(seconds * 1000), self._restart_app)

    def _restart_app(self):
        """Relaunches the app as a fresh process and exits this one.
        Works for both a frozen exe and a `python -m ...` source run,
        since sys.executable + sys.argv[1:] covers either case."""
        try:
            args = [sys.executable] + sys.argv[1:]
            subprocess.Popen(args, close_fds=True)
        except Exception as e:
            self._log_msg(
                f"❌ Couldn't auto-restart: {e}. Please close and reopen the app manually."
            )
            return
        os._exit(0)

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

        urls       = self._get_urls()
        output_dir = _read_setting("output_dir", os.path.expanduser("~")).strip()
        fmt        = self._fmt_var.get()
        dl_type    = self._type_var.get()
        quality    = self._quality_var.get()
        cookie     = _read_setting("cookie_file", "").strip()
        delay_min, delay_max = self._get_delay_bounds()

        if not urls:
            self._log_msg("❌ Please enter at least one URL (one per line).")
            return
        if not output_dir or not os.path.isdir(output_dir):
            self._log_msg("❌ Please select a valid output folder.")
            return
        if cookie and not os.path.exists(cookie):
            self._log_msg(f"❌ Cookie file not found: {cookie}")
            return

        self._save_settings()

        if len(urls) > 1:
            self._log_msg(
                f"Queued {len(urls)} URLs — waiting {delay_min:g}–{delay_max:g}s "
                f"between each so downloads don't get flagged for hammering "
                f"YouTube back to back."
            )

        items = [{
            "url": u, "output_dir": output_dir, "fmt": fmt,
            "dl_type": dl_type, "quality": quality, "cookie": cookie,
        } for u in urls]
        self._enqueue_downloads(items)

    def _toggle_stop_after_current(self):
        if self._stop_after_current.is_set():
            self._stop_after_current.clear()
            self._stop_btn.configure(text="⏹ Stop After Current")
            self._log_msg("Stop request cancelled — queue will keep going.")
        else:
            self._stop_after_current.set()
            self._stop_btn.configure(text="✖ Cancel Stop")
            self._log_msg("⏹ Will stop once the current video finishes downloading.")

    def _enqueue_downloads(self, items):
        """Adds items (dicts with url/output_dir/fmt/dl_type/quality/cookie,
        and an optional 'label' for the log) to the shared download queue.
        Safe to call while a download is already running — new items just
        join the back of the line — so the manual queue and the
        subscription watcher never fire yt-dlp at the same time."""
        if not items:
            return
        for it in items:
            self._dl_queue.put(it)

        with self._worker_lock:
            already_running = self._worker_active
            self._worker_active = True

        if not already_running:
            self._downloading = True
            self.after(0, lambda: self._dl_btn.configure(state="disabled", text="Downloading…"))
            self.after(0, lambda: self._stop_btn.configure(state="normal"))
            self._set_progress(0)
            threading.Thread(target=self._queue_worker, daemon=True).start()

    def _queue_worker(self):
        first = True
        try:
            while True:
                try:
                    item = self._dl_queue.get_nowait()
                except queue.Empty:
                    break

                if not first:
                    delay_min, delay_max = self._get_delay_bounds()
                    self._wait_with_log(random.uniform(delay_min, delay_max))
                first = False

                remaining = self._dl_queue.qsize()
                label = item.get("label") or item["url"]
                self._log_msg(f"— {label}" + (f"  ({remaining} more queued)" if remaining else ""))
                self._set_status(
                    f"⬇ Downloading…" + (f" ({remaining} more queued)" if remaining else ""),
                    theme.ACCENT)

                self._download_one(
                    item["url"], item["output_dir"], item["fmt"],
                    item["dl_type"], item["quality"], item["cookie"])

                if self._stop_after_current.is_set():
                    self._stop_after_current.clear()
                    self.after(0, lambda: self._stop_btn.configure(text="⏹ Stop After Current"))
                    remaining = self._dl_queue.qsize()
                    if remaining:
                        self._log_msg(
                            f"⏹ Stopped after that download — {remaining} item(s) still "
                            f"queued for next time you click Download.")
                    else:
                        self._log_msg("⏹ Stopped after that download.")
                    break
        finally:
            with self._worker_lock:
                self._worker_active = False
            self._downloading = False
            self.after(0, lambda: self._dl_btn.configure(state="normal", text="⬇  Download"))
            self.after(0, lambda: self._stop_btn.configure(state="disabled", text="⏹ Stop After Current"))

    def _wait_with_log(self, seconds: float):
        """Sleeps for `seconds`, updating the status label every second so
        it always shows the real remaining time (picked from the Delay
        settings) instead of a number that's frozen from the start."""
        self._log_msg(f"⏳ Waiting ~{seconds:.0f}s before the next download…")
        end = time.monotonic() + seconds
        last_shown = None
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            secs_left = max(1, round(remaining))
            if secs_left != last_shown:
                self._set_status(f"⏳ Waiting {secs_left}s…", theme.MUTED)
                last_shown = secs_left
            time.sleep(min(0.2, remaining))

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

    def _postprocessor_hook(self, d):
        """Fires as yt-dlp's postprocessors (mp3 extraction, mp4 muxing,
        file-move) complete. We only care about the final "finished" event
        that carries the actual on-disk filepath, so history records the
        real output file rather than a pre-conversion temp name."""
        if d.get("status") != "finished":
            return
        info = d.get("info_dict") or {}
        filepath = info.get("filepath")
        if not filepath:
            return
        if filepath in self._current_finished_paths:
            return
        self._current_finished_paths.add(filepath)
        self._current_finished.append({
            "id": info.get("id"),
            "title": info.get("title") or os.path.splitext(os.path.basename(filepath))[0],
            "filename": filepath,
        })

    def _download_one(self, url, output_dir, fmt, dl_type, quality, cookie):
        """Downloads a single URL. Errors are logged and swallowed so one
        bad link in a multi-URL queue doesn't stop the rest from running."""

        log_fn = self._log_msg

        self._current_finished = []
        self._current_finished_paths = set()

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
                "postprocessor_hooks": [self._postprocessor_hook],
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

            # Record whatever actually finished (even a partially-failed
            # playlist run) so future scans/browse checks know about it.
            if self._current_finished:
                # Embed the video ID straight into each file's own tags —
                # the most durable way to recognize it later, since it
                # travels with the file itself (survives renames, moves,
                # even copying to another machine) instead of depending
                # on history.json still being around.
                if not _HAVE_MUTAGEN and not self._warned_no_mutagen:
                    self._warned_no_mutagen = True
                    self._log_msg(
                        "💡 Install 'mutagen' (pip install mutagen) so downloaded "
                        "files get tagged with their video ID — makes duplicate "
                        "detection reliable even if history.json is lost or files "
                        "get moved/renamed."
                    )
                for item in self._current_finished:
                    _embed_video_id_tag(item.get("filename"), item.get("id"))

                now = time.time()
                _append_history([{
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "filename": item.get("filename"),
                    "url": url,
                    "output_dir": output_dir,
                    "downloaded_at": now,
                } for item in self._current_finished])

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