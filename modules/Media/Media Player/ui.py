import os
import random
import threading
import time
from array import array

import customtkinter as ctk
from tkinter import filedialog

from .player import VLCMusicEngine, State
from . import db as musicdb
from .media_types import file_dialog_media_types, is_media_path, is_playlist_path
from . import auto_index
from . import playlist as playlistfile
from .web_server import MusicWebServer
from .remote_access_tab import RemoteAccessTab
from core import theme
from ._buttons import (
    cool_button_kwargs, make_btn as _make_btn, cool_accent, cool_accent_hover,
    highlight_action_kwargs, selected_track_kwargs, highlight_fill_hover, highlight_border,
    play_button_kwargs, seek_bar_kwargs,
)

# Video Player gets folded in here as an extra tab (see _build_ui) rather
# than living as its own top-level page/package — it's a self-contained
# ctk.CTkFrame with the same (parent, manager) constructor this page uses,
# and it keeps its own separate VLCMediaEngine (manager.media_engine), so
# there's no conflict with this page's own music engine.
from .video_player import VideoPlayerPage

try:
    import tkinterdnd2
    from tkinterdnd2 import DND_FILES, COPY
    HAS_DND = True
except ImportError:
    tkinterdnd2 = None
    DND_FILES = COPY = None
    HAS_DND = False


def normalize_folder(folder: str) -> str:
    return musicdb.normalize_path(folder) if folder else ""


def _styled_entry(parent, **overrides):
    kw = dict(
        fg_color=theme.PANEL_2,
        border_color=theme.BORDER,
        border_width=1,
        text_color=theme.TEXT,
        placeholder_text_color=theme.FAINT,
        corner_radius=8,
        height=36,
    )
    kw.update(overrides)
    return ctk.CTkEntry(parent, **kw)


PAGE_SIZE   = 100     # rows rendered at once — fine even with 750,000+ songs total
SCAN_WORKERS = 6      # concurrent tag-reader threads (network share = I/O bound, so
                       # a handful of threads in flight speeds this up a lot)
STARTUP_SCAN_MAX_AGE = 6 * 3600   # skip redundant full scan if indexed within 6 h
AUTOINDEX_START_DELAY_MS = 3_000  # brief pause after UI/library settle — watch-only, no scan
_RENDER_CHUNK = 20    # song rows built per UI frame — keeps open/page-turn responsive


def _fmt_row(meta, fallback_path):
    if meta:
        title = meta.get("title") or os.path.basename(meta.get("path") or fallback_path)
        artist = meta.get("artist")
        return f"{artist} - {title}" if artist else title
    return os.path.basename(fallback_path or "?")


def _fmt_count(n):
    return f"{n:,}"


def _fmt_time(seconds):
    s = int(max(0, seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


class MusicPage(ctk.CTkFrame):

    MODULE_SETTINGS_TITLE = "Remote access"

    @staticmethod
    def build_module_settings(parent, manager):
        return RemoteAccessTab(parent, manager)

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=theme.BG)

        self.manager = manager
        self._engine_ready = False
        self.engine = getattr(manager, "music_engine", None)
        if self.engine is not None:
            self._engine_ready = True
        manager.music_engine = self.engine

        # Shared SQLite library index — lives on local disk, not the
        # network share, so browsing/searching/shuffling stay instant
        # even with 750,000+ songs indexed.
        self.db = getattr(manager, "music_db", None) or musicdb.Library()
        manager.music_db = self.db

        # Remote-access web server — engine wired once VLC finishes loading.
        self.web_server = getattr(manager, "music_web_server", None)
        if self.web_server is None:
            self.web_server = MusicWebServer(library=self.db, engine=self.engine)
            manager.music_web_server = self.web_server
        elif self.engine is not None:
            self.web_server.engine = self.engine

        # Scan progress is stored on the manager (not on this widget) so
        # a background scan keeps going and stays trackable even if the
        # user closes and reopens the Music Player page mid-scan.
        self.scan_state = getattr(manager, "music_scan_state", None)
        if self.scan_state is None:
            self.scan_state = {"scanning": False, "found": 0, "updated": 0,
                                "stage": "idle", "stop_event": threading.Event()}
            manager.music_scan_state = self.scan_state
        self._last_seen_stage = self.scan_state["stage"]
        self._last_seen_autoindex_text = None
        self._was_scanning = bool(self.scan_state.get("scanning"))
        self._status_override = None
        self._status_override_until = 0.0

        # Background auto-indexer (filesystem watcher + periodic safety
        # scan) — lives on the manager so it keeps running even if the
        # user closes and reopens the Music Player page.
        self.auto_indexer = getattr(manager, "music_auto_indexer", None)
        if self.auto_indexer is None:
            self.auto_indexer = auto_index.AutoIndexer(self.db)
            manager.music_auto_indexer = self.auto_indexer
        self.autoindex_status = getattr(manager, "music_autoindex_status", None)
        if self.autoindex_status is None:
            self.autoindex_status = {"text": ""}
            manager.music_autoindex_status = self.autoindex_status

        self.active_index = -1
        self._loop_running = False
        self._discord_rpc_active = False

        # Browse/search state — ids load in a background thread so open stays snappy.
        self._result_ids = array("q")
        self._library_loading = False
        self._pending_playback = None  # (callback, needs_library)
        self._library_load_seq = 0
        self._render_job = None
        self._page = 0
        self._search_seq = 0
        self._search_after_id = None
        self.row_widgets = []
        self._seek_dragging = False
        self._seek_programmatic = False
        self._seek_track_length = 0.0
        self._last_followed_index = -1
        self._last_highlighted_index = -1

        self._build_ui()
        self._sync_initial_state()
        self.results_count.configure(text="Loading library…")
        self._start_loop()
        self.after(0, self._kickoff_async_init)

    # ── Build ─────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()

        self.tabview = ctk.CTkTabview(
            self,
            fg_color=theme.BG,
            segmented_button_fg_color=theme.PANEL,
            segmented_button_selected_color=theme.ACCENT,
            segmented_button_selected_hover_color=theme.ACCENT_HOVER,
            segmented_button_unselected_color=theme.PANEL_2,
            segmented_button_unselected_hover_color=theme.PANEL_HOVER,
            text_color=theme.MUTED,
            text_color_disabled=theme.FAINT,
            command=self._on_tab_changed,
        )
        self.tabview.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        library_tab = self.tabview.add("🎵 Library")
        video_player_tab = self.tabview.add("🎬 Video Player")

        # Everything below builds into `self._tab_body` (not `self`) so the
        # existing pack()-based layout works unchanged inside its tab.
        self._tab_body = library_tab

        self._build_library_controls()

        # Bottom-anchored (side="bottom"), built bottom-most-first so the
        # visual top-to-bottom order stays "now playing" above the
        # transport controls, with the controls panel flush against the
        # window's bottom edge no matter how short the window gets — it
        # used to be packed after the expanding browse panel and could
        # get pushed past the visible area on a small window.
        self._build_controls()
        self._build_now_playing()

        # Flexible middle - takes whatever space is left, shrinks first.
        self._build_browse_panel()

        # Video Player isn't built until this tab is actually opened the
        # first time (see _on_tab_changed) — no point spinning up a second
        # VLC player + its 300ms update loop for people who never touch
        # video playback. This page (like every page in this app, see
        # core/page_manager.py) is only ever constructed once and then
        # shown/hidden for the rest of the session, so a plain instance
        # attribute is enough here — no need to also cache it on manager.
        self._video_player_tab = video_player_tab
        self._video_player_page = None

    def _on_tab_changed(self):
        if self.tabview.get() != "🎬 Video Player":
            return
        if self._video_player_page is not None:
            return
        self._video_player_page = VideoPlayerPage(self._video_player_tab, self.manager)
        self._video_player_page.pack(fill="both", expand=True)

    def _build_header(self):
        header = ctk.CTkFrame(
            self, fg_color=theme.PANEL, corner_radius=10,
            border_width=1, border_color=theme.BORDER,
        )
        header.pack(fill="x", padx=12, pady=(12, 4))

        ctk.CTkLabel(
            header, text="🎵  Music Player",
            font=("Segoe UI", 22, "bold"), text_color=theme.TEXT,
        ).pack(side="left", padx=14, pady=10)

    def _kickoff_async_init(self):
        """Yield one frame, then start heavy work off the UI thread."""
        self.after(0, self._refresh_status)
        if not self._engine_ready:
            threading.Thread(target=self._init_engine_worker, daemon=True).start()
        self._begin_library_load()
        self.after(500, self._on_module_ready)
        self.after(250, self._setup_drag_drop)

    def _init_engine_worker(self):
        try:
            engine = VLCMusicEngine()
        except Exception as exc:
            print(f"[MusicPlayer] VLC init failed: {exc}")
            engine = None

        def apply():
            if not self.winfo_exists():
                return
            if engine is None:
                self._flash_status("Audio engine failed to start")
                return
            self.engine = engine
            self.manager.music_engine = engine
            self.web_server.engine = engine
            self._engine_ready = True
            self.volume.set(engine.volume)
            engine.set_volume(engine.volume)
            self._update_playback_ui_state()
            self._flush_pending_playback()
            self._refresh_status()

        self.after(0, apply)

    def _can_playback_now(self, needs_library: bool) -> bool:
        if not self._engine_ready or self.engine is None:
            return False
        if needs_library and self._library_loading:
            return False
        return True

    def _queue_playback(self, callback, *, needs_library: bool = True):
        """Defer playback until VLC + (optionally) library ids are ready."""
        if self._can_playback_now(needs_library):
            callback()
            return
        self._pending_playback = (callback, needs_library)
        if not self._engine_ready or self.engine is None:
            self._flash_status("Starting audio engine…")
        elif needs_library and self._library_loading:
            self._flash_status("Loading library…")

    def _flush_pending_playback(self):
        if not self._pending_playback or not self.winfo_exists():
            return
        callback, needs_library = self._pending_playback
        if not self._can_playback_now(needs_library):
            return
        self._pending_playback = None
        callback()

    def _ensure_engine(self) -> bool:
        if self._engine_ready and self.engine is not None:
            return True
        self._flash_status("Starting audio engine…")
        return False

    def _begin_library_load(self):
        self._library_loading = True
        self._refresh_status()
        self._library_load_seq += 1
        seq = self._library_load_seq
        cached = getattr(self.manager, "music_library_ids", None)
        if cached is not None:
            self.after(0, lambda s=seq, c=cached: self._apply_library_load(s, c, len(c)))
            return
        threading.Thread(target=self._load_library_worker, args=(seq,), daemon=True).start()

    def _load_library_worker(self, seq: int):
        try:
            count = self.db.count()
            ids = self.db.all_ids()
        except Exception as exc:
            print(f"[MusicPlayer] library load failed: {exc}")
            count, ids = 0, array("q")

        def apply():
            if seq != self._library_load_seq or not self.winfo_exists():
                return
            self.manager.music_library_ids = ids
            self._apply_library_load(seq, ids, count)

        self.after(0, apply)

    def _apply_library_load(self, seq: int, ids, count: int):
        if seq != self._library_load_seq or not self.winfo_exists():
            return
        self._result_ids = ids
        self._library_loading = False
        self._page = 0
        self.results_count.configure(text=f"{_fmt_count(count)} songs")
        self._render_page()
        self._flush_pending_playback()
        self._refresh_status()
        self.after(100, lambda: self._ensure_active_track_visible(force=True))
        self._schedule_autoindex_start()

    def _invalidate_library_cache(self):
        self.manager.music_library_ids = None
        self._begin_library_load()

    def _flash_status(self, text: str, *, duration_ms: int = 5000):
        """Show a short-lived message; persistent state resumes via _refresh_status."""
        self._status_override = text
        self._status_override_until = time.monotonic() + (duration_ms / 1000.0)
        if hasattr(self, "scan_status"):
            self.scan_status.configure(text=text)

    def _refresh_status(self):
        """Update the status bar from current load / engine / scan / auto-index state."""
        if not hasattr(self, "scan_status"):
            return
        if self._status_override and time.monotonic() < self._status_override_until:
            return
        self._status_override = None

        state = self.scan_state
        if state.get("scanning"):
            self._was_scanning = True
            self.scan_status.configure(
                text=f"Scanning… {_fmt_count(state['found'])} files seen, "
                     f"{_fmt_count(state['updated'])} indexed")
            return

        if self._was_scanning and not state.get("scanning"):
            self._was_scanning = False
            if state.get("stage") == "done":
                self.scan_status.configure(
                    text=f"Scan complete — {_fmt_count(self.db.count())} songs in library")
                return
            if state.get("stage") == "aborted":
                self.scan_status.configure(text="Scan cancelled")
                return

        count = len(self._result_ids) if len(self._result_ids) else self.db.count()
        folder = self.db.get_setting("music_folder")
        if not folder and not state.get("scanning"):
            self.scan_status.configure(text="Set a music folder to get started")
            return

        parts: list[str] = []

        if self._library_loading:
            parts.append(f"Loading library ({_fmt_count(count)} in database)…")
        elif self._render_job is not None:
            parts.append(f"Building song list ({_fmt_count(count)} songs)…")
        elif count <= 0:
            parts.append("Library empty — use Rescan Now to index your folder")
        else:
            parts.append(f"Ready — {_fmt_count(count)} songs")

        if not self._engine_ready:
            parts.append("starting audio engine…")
        elif self.engine is None:
            parts.append("audio engine unavailable")

        ai_text = (self.autoindex_status.get("text") or "").strip()
        if ai_text.startswith("Auto-indexed"):
            self.scan_status.configure(text=ai_text)
            return
        if self.auto_indexer.running and ai_text:
            parts.append(ai_text)

        self.scan_status.configure(text=" · ".join(parts))

    def _build_library_controls(self):
        panel = ctk.CTkFrame(
            self._tab_body, fg_color=theme.PANEL, corner_radius=10,
            border_width=1, border_color=theme.BORDER,
        )
        panel.pack(fill="x", padx=12, pady=6)

        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=(10, 4))
        self.folder_row = row

        _make_btn(row, "📁  Set Music Folder", self.pick_folder,
                  width=170).pack(side="left", padx=(0, 6))
        _make_btn(row, "🔄  Rescan Now", self.rescan_now,
                  width=130).pack(side="left", padx=(0, 6))

        self.autoindex_var = ctk.BooleanVar(
            value=self.db.get_setting("auto_index_enabled", "1") == "1")
        ctk.CTkCheckBox(
            row, text="Auto-index new files", variable=self.autoindex_var,
            command=self._on_toggle_autoindex, text_color=theme.TEXT,
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
            border_color=theme.BORDER,
        ).pack(side="left", padx=(0, 6))

        self.folder_label = ctk.CTkLabel(
            row, text=self._folder_display(), text_color=theme.TEXT,
            font=("Segoe UI", 11), anchor="w",
        )
        self.folder_label.pack(side="left", fill="x", expand=True, padx=(6, 0))

        self.scan_status = ctk.CTkLabel(
            panel, text="", text_color=theme.MUTED, anchor="w",
            font=("Segoe UI", 11))
        self.scan_status.pack(fill="x", padx=14, pady=(0, 10))

    def _build_browse_panel(self):
        panel = ctk.CTkFrame(
            self._tab_body, fg_color=theme.PANEL, corner_radius=10,
            border_width=1, border_color=theme.BORDER,
        )
        panel.pack(side="top", fill="both", expand=True, padx=12, pady=6)
        self.library_panel = panel

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 4))

        ctk.CTkLabel(top, text="Library",
                     font=("Segoe UI", 16, "bold"), text_color=theme.TEXT).pack(side="left")

        self.results_count = ctk.CTkLabel(
            top, text="0 songs", text_color=theme.TEXT, font=("Segoe UI", 12, "bold"),
        )
        self.results_count.pack(side="right")

        big_row = ctk.CTkFrame(panel, fg_color="transparent")
        big_row.pack(fill="x", padx=10, pady=(0, 6))

        _make_btn(big_row, "🔀  Shuffle All", self.shuffle_all,
                  **highlight_action_kwargs(), width=170).pack(side="left", padx=(0, 6))
        _make_btn(big_row, "Play All (in order)", self.play_all,
                  width=170).pack(side="left", padx=(0, 6))
        _make_btn(big_row, "＋  Add Files (quick queue)", self.load_files,
                  width=190).pack(side="left")

        if HAS_DND:
            ctk.CTkLabel(
                big_row, text="…or drag files/a folder anywhere on this page",
                text_color=theme.MUTED, font=("Segoe UI", 11),
            ).pack(side="left", padx=(10, 0))

        self.search_entry = _styled_entry(
            panel, placeholder_text="Search title / artist / album…",
        )
        self.search_entry.pack(fill="x", padx=10, pady=(0, 6))
        self.search_entry.bind("<KeyRelease>", self._on_search_key)

        self.song_buttons_frame = ctk.CTkScrollableFrame(
            panel, fg_color=theme.BG, corner_radius=8,
            border_width=1, border_color=theme.BORDER,
            scrollbar_button_color=theme.PANEL_2,
            scrollbar_button_hover_color=theme.PANEL_HOVER,
        )
        self.song_buttons_frame.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        pager = ctk.CTkFrame(panel, fg_color="transparent")
        pager.pack(fill="x", padx=10, pady=(0, 10))

        self.prev_page_btn = _make_btn(pager, "◀ Prev", self.prev_page, width=90)
        self.prev_page_btn.pack(side="left")

        self.page_label = ctk.CTkLabel(
            pager, text="Page 1 / 1", text_color=theme.TEXT, font=("Segoe UI", 12),
        )
        self.page_label.pack(side="left", expand=True)

        self.next_page_btn = _make_btn(pager, "Next ▶", self.next_page, width=90)
        self.next_page_btn.pack(side="right")

    def _build_now_playing(self):
        card = ctk.CTkFrame(
            self._tab_body, fg_color=theme.PANEL_2, corner_radius=10,
            border_width=1, border_color=theme.ACCENT_DIM,
        )
        card.pack(side="bottom", fill="x", padx=12, pady=6)

        ctk.CTkLabel(
            card, text="Now Playing",
            font=("Segoe UI", 11, "bold"), text_color=theme.ACCENT,
        ).pack(anchor="w", padx=14, pady=(10, 0))

        self.current_song_label = ctk.CTkLabel(
            card, text="Nothing playing", text_color=theme.TEXT,
            font=("Segoe UI", 16, "bold"), anchor="w",
        )
        self.current_song_label.pack(fill="x", padx=14, pady=(4, 8))

        seek_row = ctk.CTkFrame(card, fg_color="transparent")
        seek_row.pack(fill="x", padx=14, pady=(0, 12))
        seek_row.grid_columnconfigure(1, weight=1)

        self.seek_current_label = ctk.CTkLabel(
            seek_row, text="00:00", text_color=theme.ACCENT,
            font=("Consolas", 12, "bold"), width=44,
        )
        self.seek_current_label.grid(row=0, column=0, padx=(0, 10))

        self.seek_slider = ctk.CTkSlider(
            seek_row,
            from_=0,
            to=1,
            number_of_steps=1000,
            height=18,
            command=self._on_seek_slide,
            **seek_bar_kwargs(),
        )
        self.seek_slider.set(0)
        self.seek_slider.grid(row=0, column=1, sticky="ew")
        self.seek_slider.bind("<ButtonRelease-1>", self._on_seek_release)
        self.seek_slider.bind("<Button-1>", self._on_seek_press)

        self.seek_total_label = ctk.CTkLabel(
            seek_row, text="00:00", text_color=theme.FAINT,
            font=("Consolas", 12), width=44,
        )
        self.seek_total_label.grid(row=0, column=2, padx=(10, 0))

    def _build_controls(self):
        outer = ctk.CTkFrame(
            self._tab_body, fg_color=theme.PANEL, corner_radius=10,
            border_width=1, border_color=theme.BORDER,
        )
        outer.pack(side="bottom", fill="x", padx=12, pady=(4, 12))

        transport = ctk.CTkFrame(outer, fg_color="transparent")
        transport.pack(pady=(10, 4))

        transport_btns = [
            ("⏮", self.prev, False),
            ("▶", self.toggle_play_pause, True),
            ("⏭", self.next, False),
        ]
        for col, (text, cmd, is_play) in enumerate(transport_btns):
            if is_play:
                self.play_pause_btn = ctk.CTkButton(
                    transport, text=text, command=cmd, **play_button_kwargs())
                self.play_pause_btn.grid(row=0, column=col, padx=4)
            else:
                btn = _make_btn(transport, text, cmd, width=56, height=44)
                btn.grid(row=0, column=col, padx=4)

        mode_row = ctk.CTkFrame(outer, fg_color="transparent")
        mode_row.pack(pady=(0, 4))

        self.repeat_btn = _make_btn(mode_row, "🔁  Repeat", self.toggle_repeat, width=130)
        self.repeat_btn.pack()

        vol_row = ctk.CTkFrame(outer, fg_color="transparent")
        vol_row.pack(fill="x", padx=14, pady=(4, 12))

        ctk.CTkLabel(
            vol_row, text="Volume", text_color=theme.TEXT,
            font=("Segoe UI", 12, "bold"),
        ).pack(side="left", padx=(0, 10))

        self.volume = ctk.CTkSlider(
            vol_row, from_=0, to=1, progress_color=cool_accent(),
            button_color=cool_accent(), button_hover_color=cool_accent_hover(),
            fg_color=theme.BORDER, command=self.set_volume, corner_radius=4,
            height=16,
        )
        self.volume.pack(side="left", fill="x", expand=True)

    def _set_seek_display(self, current: float, total: float):
        self._seek_track_length = max(0.0, total)
        self.seek_current_label.configure(text=_fmt_time(current))
        self.seek_total_label.configure(text=_fmt_time(total))

    def _on_seek_press(self, _event=None):
        self._seek_dragging = True

    def _on_seek_slide(self, value):
        if self._seek_programmatic:
            return
        self._seek_dragging = True
        total = self._seek_track_length
        if total <= 0 and self._engine_ready and self.engine is not None:
            total = max(0.0, self.engine.get_length())
            self._seek_track_length = total
        if total > 0:
            self.seek_current_label.configure(text=_fmt_time(float(value) * total))

    def _on_seek_release(self, _event=None):
        if not self._engine_ready or self.engine is None:
            self._seek_dragging = False
            return
        total = max(0.0, self.engine.get_length())
        if total > 0:
            pos = float(self.seek_slider.get()) * total
            self.engine.seek(pos)
            self._set_seek_display(pos, total)
        self._seek_dragging = False

    # ── Initial State Sync ────────────────────────────────────

    def _sync_initial_state(self):
        if self._engine_ready and self.engine is not None:
            vol = getattr(self.engine, "volume", 0.5)
            self.volume.set(vol)
            self.engine.set_volume(vol)

            mode = self.engine.repeat_mode
            if mode == "all":
                self.repeat_btn.configure(text="🔁  Repeat All", fg_color=theme.ACCENT, text_color="#0b0d10")
            elif mode == "one":
                self.repeat_btn.configure(text="🔂  Repeat One", fg_color=theme.SUCCESS, text_color="#0b0d10")

        self._update_playback_ui_state()
        self.after(200, lambda: self._ensure_active_track_visible(force=True))

    def _folder_display(self):
        folder = self.db.get_setting("music_folder")
        return folder if folder else "No music folder set yet"

    # ── Loop ─────────────────────────────────────────────────

    def _start_loop(self):
        if not self._loop_running:
            self._loop_running = True
            self.after(300, self._update_loop)

    def _update_loop(self):
        if not self._loop_running:
            return

        if self._engine_ready and self.engine is not None:
            current = max(0, self.engine.get_time())
            total   = max(0, self.engine.get_length())

            if total > 0:
                if not self._seek_dragging:
                    self._seek_programmatic = True
                    self.seek_slider.set(current / total)
                    self._seek_programmatic = False
                    self._set_seek_display(current, total)
            else:
                if not self._seek_dragging:
                    self._seek_programmatic = True
                    self.seek_slider.set(0)
                    self._seek_programmatic = False
                    self._set_seek_display(0, 0)

        self._update_playback_ui_state()
        self._poll_scan_state()

        self.after(300, self._update_loop)

    # ── Library folder / scanning ───────────────────────────────

    def pick_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        self.db.set_setting("music_folder", folder)
        self.folder_label.configure(text=folder)
        self.rescan_now()
        self._sync_autoindexer(folder, force=True)

    def rescan_now(self):
        folder = self.db.get_setting("music_folder")
        if not folder:
            self._flash_status("Set a music folder first")
            return
        if self.scan_state["scanning"]:
            self._flash_status("Already scanning…")
            return
        self._begin_scan(folder)

    def _schedule_autoindex_start(self):
        """Start background file watch shortly after the library UI is ready."""
        pending = getattr(self.manager, "_music_autoindex_pending_id", None)
        if pending is not None:
            try:
                self.after_cancel(pending)
            except Exception:
                pass
            self.manager._music_autoindex_pending_id = None

        folder = self.db.get_setting("music_folder")
        if not folder or not self.autoindex_var.get():
            return
        if self._library_loading:
            return
        if self.auto_indexer.running and normalize_folder(folder) == normalize_folder(self.auto_indexer.folder):
            if not self.autoindex_status.get("text"):
                self.autoindex_status["text"] = "Watching for changes…"
            return

        def _start():
            self.manager._music_autoindex_pending_id = None
            self._sync_autoindexer(self.db.get_setting("music_folder"))

        self.manager._music_autoindex_pending_id = self.after(AUTOINDEX_START_DELAY_MS, _start)

    def _on_module_ready(self):
        """Kick off background file watch once the page shell is up."""
        if self.auto_indexer.running and not self.autoindex_status.get("text"):
            self.autoindex_status["text"] = "Watching for changes…"
        self._schedule_autoindex_start()
        self._refresh_status()

    def _should_skip_startup_scan(self, folder: str) -> bool:
        """Avoid a full folder walk on every app open when the index is fresh."""
        if self.db.count() <= 0:
            return False
        if normalize_folder(self.db.get_setting("music_last_scan_folder") or "") != normalize_folder(folder):
            return False
        try:
            last_at = float(self.db.get_setting("music_last_scan_at") or 0)
        except (TypeError, ValueError):
            return False
        return (time.time() - last_at) <= STARTUP_SCAN_MAX_AGE

    def _sync_autoindexer(self, folder, *, force: bool = False):
        """Start/stop the background auto-indexer to match folder + checkbox."""
        want_running = bool(folder) and self.autoindex_var.get()
        already_running = (
            self.auto_indexer.running
            and normalize_folder(folder) == normalize_folder(self.auto_indexer.folder)
        )
        if want_running and (force or not already_running):
            self.auto_indexer.start(
                folder,
                status_cb=self._on_autoindex_status,
                scan_busy_cb=lambda: self.scan_state.get("scanning", False),
                library_fresh=self._should_skip_startup_scan(folder) if folder else False,
            )
        elif not want_running and self.auto_indexer.running:
            self.auto_indexer.stop()
            self.autoindex_status["text"] = ""
        self._refresh_status()

    def _on_toggle_autoindex(self):
        enabled = self.autoindex_var.get()
        self.db.set_setting("auto_index_enabled", "1" if enabled else "0")
        self._sync_autoindexer(self.db.get_setting("music_folder"), force=True)

    def _on_autoindex_status(self, text):
        # Called from a background thread — stash it; the GUI thread refreshes.
        self.autoindex_status["text"] = text

    def _begin_scan(self, folder):
        state = self.scan_state
        state["scanning"] = True
        state["found"] = 0
        state["updated"] = 0
        state["stage"] = "starting"
        state["stop_event"] = threading.Event()
        self._last_seen_stage = "starting"
        self._was_scanning = True
        self._refresh_status()

        def progress_cb(found, updated, stage):
            state["found"] = found
            state["updated"] = updated
            state["stage"] = stage
            if stage == "done":
                self.db.set_setting("music_last_scan_folder", folder)
                self.db.set_setting("music_last_scan_at", str(time.time()))

        def worker():
            try:
                self.db.scan(
                    folder, progress_cb=progress_cb,
                    stop_event=state["stop_event"], workers=SCAN_WORKERS, full=True)
            finally:
                state["scanning"] = False

        threading.Thread(target=worker, daemon=True).start()

    def _poll_scan_state(self):
        state = self.scan_state
        if not state["scanning"] and self._last_seen_stage != state["stage"] and state["stage"] in ("done", "aborted"):
            self._last_seen_stage = state["stage"]
            self.manager.music_library_ids = None
            self._begin_library_load()

        ai_text = self.autoindex_status.get("text", "")
        if ai_text and ai_text != self._last_seen_autoindex_text:
            self._last_seen_autoindex_text = ai_text
            if ai_text.startswith("Auto-indexed"):
                self.manager.music_library_ids = None
                self._begin_library_load()

        self._refresh_status()

    # ── Add Files (small ad-hoc queue, bypasses the library index) ──

    def _expand_playlist_selection(self, paths):
        """
        Given a mix of selected/dropped paths, expand any playlist files
        (.m3u/.m3u8/.pls/.xspf) into the audio tracks they reference, and
        pass ordinary audio files through unchanged.

        Returns (resolved, playlist_notes):
          - resolved: flat, ordered list of playable paths.
          - playlist_notes: one status string per playlist file that was
            expanded, e.g. "list.m3u: 12/12 tracks found" or
            "list.m3u: 0/8 tracks found — check the paths inside it",
            so a playlist that resolves to nothing doesn't just look
            like the drop/selection was silently ignored.
        """
        out = []
        playlist_notes = []
        for p in paths:
            if p.lower().endswith(musicdb.PLAYLIST_EXTS):
                resolved, total = playlistfile.parse_playlist_report(p)
                out.extend(resolved)
                name = os.path.basename(p)
                if total == 0:
                    playlist_notes.append(f"{name}: no tracks listed (empty or unreadable)")
                elif not resolved:
                    playlist_notes.append(
                        f"{name}: 0/{total} tracks found — the paths inside it "
                        f"don't match any files on this machine")
                else:
                    playlist_notes.append(f"{name}: {len(resolved)}/{total} tracks found")
            else:
                out.append(p)
        return out, playlist_notes

    def load_files(self):
        files = filedialog.askopenfilenames(filetypes=file_dialog_media_types())
        if files:
            resolved, playlist_notes = self._expand_playlist_selection(files)
            # All Files picker may include odd extensions — VLC/ffmpeg will try them.
            resolved = [
                p for p in resolved
                if is_media_path(p) or os.path.isfile(p)
            ]
            if not resolved:
                msg = "; ".join(playlist_notes) if playlist_notes else "No playable tracks found in that selection"
                self._flash_status(msg)
                return
            if not self._ensure_engine():
                return
            self.engine.load(resolved)
            self.engine.play()
            n = len(resolved)
            msg = f"{n} file{'s' if n != 1 else ''} loaded"
            if playlist_notes:
                msg += " — " + "; ".join(playlist_notes)
            self._flash_status(msg)
            self._update_playback_ui_state()

    # ── Drag and drop ────────────────────────────────────────────
    #
    # Dropping audio file(s) anywhere on the page queues/plays them,
    # same as "Add Files". Dropping a folder (with no loose audio files
    # alongside it) sets it as the music library folder and scans it,
    # same as "Set Music Folder". Requires the optional `tkinterdnd2`
    # package — if it's missing, or tkdnd fails to load on this
    # platform, drag-and-drop is silently unavailable and everything
    # else still works via the buttons/dialogs as before.

    def _setup_drag_drop(self):
        if not HAS_DND:
            return

        ready = getattr(self.manager, "_music_dnd_ready", None)
        if ready is None:
            try:
                tkinterdnd2.TkinterDnD.require(self.winfo_toplevel())
                ready = True
            except Exception:
                ready = False
            self.manager._music_dnd_ready = ready
        if not ready:
            return

        # Register the page itself plus the main visible container frames
        # — dropping directly on top of a button/entry still works via
        # the dialogs, this just covers the surrounding background areas.
        targets = [self, self.library_panel, self.folder_row, self.song_buttons_frame]
        for widget in targets:
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

    def _on_drop(self, event):
        try:
            paths = self.tk.splitlist(event.data)
        except Exception:
            paths = [event.data]

        dirs = [p for p in paths if os.path.isdir(p)]
        dropped_files = [p for p in paths if os.path.isfile(p)]
        audio_files, playlist_notes = self._expand_playlist_selection(dropped_files)
        media_files = [p for p in audio_files if is_media_path(p)]
        if media_files:
            audio_files = media_files
        elif audio_files:
            audio_files = [p for p in audio_files if not is_playlist_path(p)]

        if audio_files:
            if not self._ensure_engine():
                return
            self.engine.load(audio_files)
            self.engine.play()
            n = len(audio_files)
            msg = f"{n} file{'s' if n != 1 else ''} added from drag & drop"
            if playlist_notes:
                msg += " — " + "; ".join(playlist_notes)
            self._flash_status(msg)
            self._update_playback_ui_state()
        elif dirs:
            folder = dirs[0]
            self.db.set_setting("music_folder", folder)
            self.folder_label.configure(text=folder)
            self._flash_status(f"Indexing dropped folder: {folder}")
            self.rescan_now()
            self._sync_autoindexer(folder, force=True)
        elif playlist_notes:
            # A playlist file was dropped but every entry inside it
            # failed to resolve — tell the user why instead of the
            # generic "no supported files" message below.
            self._flash_status("; ".join(playlist_notes))
        else:
            self._flash_status("No supported audio files in that drop")

        return COPY

    # ── Browse / Search / Paging ─────────────────────────────────

    def _on_search_key(self, event=None):
        if self._search_after_id:
            self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(350, self._run_search)

    def _run_search(self, immediate=False):
        query = self.search_entry.get() if hasattr(self, "search_entry") else ""
        self._search_seq += 1
        seq = self._search_seq

        def worker():
            ids = self.db.search_ids(query)
            self.after(0, lambda: self._apply_search_results(seq, ids))

        if immediate:
            worker()
        else:
            threading.Thread(target=worker, daemon=True).start()

    def _apply_search_results(self, seq, ids):
        if seq != self._search_seq:
            return  # a newer search superseded this one
        self._result_ids = ids
        self._page = 0
        self._last_followed_index = -1
        self.results_count.configure(text=f"{_fmt_count(len(ids))} songs")
        self._render_page()
        self.after(100, lambda: self._ensure_active_track_visible(force=True))

    def _total_pages(self):
        return max(1, (len(self._result_ids) + PAGE_SIZE - 1) // PAGE_SIZE)

    def prev_page(self):
        if self._page > 0:
            self._page -= 1
            self._render_page()

    def next_page(self):
        if self._page + 1 < self._total_pages():
            self._page += 1
            self._render_page()

    def _render_page(self):
        if self._render_job is not None:
            try:
                self.after_cancel(self._render_job)
            except Exception:
                pass
            self._render_job = None

        for w in self.song_buttons_frame.winfo_children():
            w.destroy()
        self.row_widgets = []
        self._last_highlighted_index = -1

        start = self._page * PAGE_SIZE
        end = min(start + PAGE_SIZE, len(self._result_ids))
        self._render_page_start = start
        self._render_page_ids = list(self._result_ids[start:end])
        self._render_page_metas = self.db.get_songs(self._render_page_ids)
        self._render_chunk_idx = 0
        self._render_chunk_batch()

    def _render_chunk_batch(self):
        if not self.winfo_exists():
            return

        page_ids = self._render_page_ids
        metas = self._render_page_metas
        page_start = self._render_page_start
        chunk_end = min(self._render_chunk_idx + _RENDER_CHUNK, len(page_ids))

        for offset in range(self._render_chunk_idx, chunk_end):
            sid = page_ids[offset]
            global_index = page_start + offset
            meta = metas.get(sid)
            text = f"{global_index + 1}.  {_fmt_row(meta, None)}"

            row = ctk.CTkFrame(
                self.song_buttons_frame, fg_color=theme.PANEL_2,
                corner_radius=6, border_width=1, border_color=theme.BORDER,
            )
            row.pack(fill="x", padx=4, pady=2)

            btn = ctk.CTkButton(
                row, text=text,
                fg_color="transparent",
                hover_color=theme.PANEL_HOVER,
                text_color=theme.TEXT,
                font=("Segoe UI", 13),
                anchor="w", height=34, corner_radius=6,
                command=lambda gi=global_index: self.play_result(gi),
            )
            btn.pack(side="left", fill="x", expand=True, padx=2, pady=1)
            self.row_widgets.append((global_index, btn))
            if (
                self._engine_ready
                and self.engine is not None
                and global_index == self.engine.index
                and self._current_queue_is(self._result_ids)
            ):
                btn.configure(**selected_track_kwargs())
                row.configure(border_color=highlight_border())
                self.active_index = global_index
                self._last_highlighted_index = global_index

        self._render_chunk_idx = chunk_end
        if chunk_end < len(page_ids):
            self._render_job = self.after(1, self._render_chunk_batch)
            return

        self._render_job = None
        total_pages = self._total_pages()
        self.page_label.configure(text=f"Page {self._page + 1} / {total_pages}")
        self.prev_page_btn.configure(state="normal" if self._page > 0 else "disabled")
        self.next_page_btn.configure(
            state="normal" if self._page + 1 < total_pages else "disabled")
        self._highlight_active(force=True)
        self._refresh_status()
        page_start = self._render_page_start
        page_end = page_start + len(page_ids)
        if (
            self._engine_ready
            and self.engine is not None
            and page_start <= self.engine.index < page_end
            and self._current_queue_is(self._result_ids)
        ):
            self.active_index = self.engine.index
            self._last_followed_index = self.engine.index
            self.after_idle(self._scroll_active_row_into_view)

    # ── Playback ─────────────────────────────────────────────

    def play_result(self, global_index):
        def _play():
            if not self._ensure_engine():
                return
            self.engine.load_ids(self.db, self._result_ids, start_index=global_index)
            self.engine.shuffle = False
            self.engine.play()
            self._update_playback_ui_state()

        self._queue_playback(_play)

    def shuffle_all(self):
        def _shuffle():
            if not self._ensure_engine():
                return
            ids = self._result_ids
            if not len(ids):
                self._flash_status("Library is empty — set a music folder first")
                return
            start = random.randrange(len(ids))
            self.engine.load_ids(self.db, ids, start_index=start)
            self.engine.shuffle = True
            self.engine.play()
            self._update_playback_ui_state()

        self._queue_playback(_shuffle)

    def play_all(self):
        def _play():
            if not self._ensure_engine():
                return
            ids = self._result_ids
            if not len(ids):
                self._flash_status("Library is empty — set a music folder first")
                return
            self.engine.load_ids(self.db, ids, start_index=0)
            self.engine.shuffle = False
            self.engine.play()
            self._update_playback_ui_state()

        self._queue_playback(_play)

    def toggle_play_pause(self):
        if not self._ensure_engine():
            return
        if self.engine.is_playing():
            self.engine.pause()
        else:
            self.engine.play()
        self._update_playback_ui_state()

    def play(self):
        if not self._ensure_engine():
            return
        self.engine.play()
        self._update_playback_ui_state()

    def pause(self):
        if not self._ensure_engine():
            return
        self.engine.pause()
        self._update_playback_ui_state()

    def next(self):
        if not self._ensure_engine():
            return
        self.engine.next()
        self._update_playback_ui_state()

    def prev(self):
        if not self._ensure_engine():
            return
        self.engine.prev()
        self._update_playback_ui_state()

    def set_volume(self, value):
        if self.engine is not None:
            self.engine.set_volume(value)

    # ── Repeat ────────────────────────────────────────────────

    def toggle_repeat(self):
        if not self._ensure_engine():
            return
        modes = ["off", "all", "one"]
        next_mode = modes[(modes.index(self.engine.repeat_mode) + 1) % len(modes)]
        self.engine.repeat_mode = next_mode

        if next_mode == "off":
            self.repeat_btn.configure(**cool_button_kwargs(width=130, text="🔁  Repeat"))
        elif next_mode == "all":
            self.repeat_btn.configure(
                text="🔁  Repeat All", fg_color=theme.ACCENT,
                hover_color=theme.ACCENT_HOVER, text_color="#0b0d10",
                border_color=theme.ACCENT,
            )
        else:
            self.repeat_btn.configure(
                text="🔂  Repeat One", fg_color=theme.SUCCESS,
                hover_color=theme.SUCCESS, text_color="#0b0d10",
                border_color=theme.SUCCESS,
            )

    # ── Highlight ─────────────────────────────────────────────

    def _ensure_active_track_visible(self, *, force=False):
        """Jump to the library page showing the currently playing track."""
        if not self._engine_ready or self.engine is None:
            return
        idx = self.engine.index
        if idx < 0 or not len(self._result_ids):
            return
        if not self._current_queue_is(self._result_ids):
            return
        if idx >= len(self._result_ids):
            return

        self.active_index = idx
        if not force and idx == self._last_followed_index:
            return

        self._last_followed_index = idx
        target_page = idx // PAGE_SIZE
        if target_page != self._page:
            self._page = target_page
            self._render_page()
            return

        self._highlight_active(force=True)
        self._scroll_active_row_into_view()

    def _scroll_active_row_into_view(self):
        """Scroll the song list so the active row is visible."""
        target_row = None
        for global_index, btn in self.row_widgets:
            if global_index == self.active_index:
                target_row = btn.master
                break
        if target_row is None:
            return

        canvas = getattr(self.song_buttons_frame, "_parent_canvas", None)
        inner = getattr(self.song_buttons_frame, "_scrollable_frame", None)
        if canvas is None or inner is None:
            return

        def _scroll():
            try:
                inner.update_idletasks()
                target_row.update_idletasks()
                inner_h = max(1, inner.winfo_height())
                view_h = max(1, canvas.winfo_height())
                if inner_h <= view_h:
                    return
                y = target_row.winfo_y()
                h = max(1, target_row.winfo_height())
                visible_top, visible_bottom = canvas.yview()
                top_frac = y / inner_h
                bottom_frac = (y + h) / inner_h
                if top_frac >= visible_top and bottom_frac <= visible_bottom:
                    return
                window = view_h / inner_h
                # Keep the active row anchored near the top — centering can
                # push it back out of view on short lists or after resize.
                pad = 8
                new_top = max(0.0, min(1.0 - window, (y - pad) / inner_h))
                canvas.yview_moveto(new_top)
            except Exception:
                pass

        self.after_idle(_scroll)

    def _highlight_active(self, *, force=False):
        if not force and self._last_highlighted_index == self.active_index:
            return
        if not self._current_queue_is(self._result_ids):
            self._last_highlighted_index = -1
            return

        self._last_highlighted_index = self.active_index
        active_kw = selected_track_kwargs()
        inactive_kw = dict(
            fg_color="transparent",
            hover_color=theme.PANEL_HOVER,
            text_color=theme.TEXT,
            font=("Segoe UI", 13),
        )
        for global_index, btn in self.row_widgets:
            if global_index == self.active_index:
                btn.configure(**active_kw)
                btn.master.configure(border_color=highlight_border())
            else:
                btn.configure(**inactive_kw)
                btn.master.configure(border_color=theme.BORDER)

    def _current_queue_is(self, ids):
        if not self.engine:
            return False
        # Only highlight a browse row as "active" when the engine's queue is
        # actually this same result set (not, say, an ad-hoc "Add Files" list).
        playlist = self.engine.playlist
        return getattr(playlist, "ids", None) is ids

    # ── NEW: Unified UI Playback State Updater ────────────────

    def _update_playback_ui_state(self):
        if not self._engine_ready or self.engine is None:
            if hasattr(self, "play_pause_btn"):
                self.play_pause_btn.configure(text="▶")
            return

        current_engine_index = self.engine.index
        is_playing = self.engine.is_playing()
        engine_state = self.engine.get_state()

        if current_engine_index != self.active_index:
            self.active_index = current_engine_index
            self._ensure_active_track_visible()
            self.update_discord_song(force_update=True)

        if self.engine.playlist and 0 <= self.active_index < len(self.engine.playlist):
            meta = self.engine.get_current_meta()
            if meta:
                self.current_song_label.configure(text=_fmt_row(meta, None))
            else:
                self.current_song_label.configure(
                    text=os.path.basename(self.engine.playlist[self.active_index]))
        else:
            self.current_song_label.configure(text="Nothing playing")

        if hasattr(self, "play_pause_btn"):
            self.play_pause_btn.configure(text="⏸" if is_playing else "▶")

        if is_playing:
            if not self._discord_rpc_active:
                self.update_discord_song(force_update=True)
        elif engine_state == State.Paused:
            if self._discord_rpc_active:
                self.update_discord_song(force_clear=True)
        elif (current_engine_index == -1 and not self.engine.playlist) or \
             (current_engine_index == -1 and self.engine.playlist and engine_state == State.Stopped):
            if self._discord_rpc_active:
                self.update_discord_song(force_clear=True)
        elif engine_state == State.Ended:
            if self._discord_rpc_active:
                self.update_discord_song(force_clear=True)

    # ──────────────────────────────────────────────────────────

    def update_discord_song(self, force_clear=False, force_update=False):
        try:
            discord_service = self.manager.container.discord_service

            if force_clear:
                if self._discord_rpc_active:
                    discord_service.clear()
                    self._discord_rpc_active = False
                return

            if not self._engine_ready or self.engine is None:
                return

            if self.engine.index < 0 or not self.engine.is_playing():
                if self._discord_rpc_active:
                    discord_service.clear()
                    self._discord_rpc_active = False
                return

            meta = self.engine.get_current_meta()
            song = _fmt_row(meta, self.engine.playlist[self.engine.index]) if meta \
                else os.path.basename(self.engine.playlist[self.engine.index])

            if force_update or not self._discord_rpc_active or \
               (self._discord_rpc_active and discord_service.last_details != "🎵 Listening to Music") or \
               (self._discord_rpc_active and discord_service.last_state != song):
                discord_service.update("🎵 Listening to Music", song)
                self._discord_rpc_active = True

        except Exception as e:
            print(f"Error updating Discord RPC: {e}")
            if self._discord_rpc_active:
                try:
                    discord_service.clear()
                except Exception:
                    pass
                self._discord_rpc_active = False