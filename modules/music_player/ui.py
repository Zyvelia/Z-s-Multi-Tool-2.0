import os
import random
import threading

import customtkinter as ctk
from tkinter import filedialog

from .player import VLCMusicEngine, State
from . import db as musicdb
from . import auto_index
from . import playlist as playlistfile
from .web_server import MusicWebServer
from .remote_access_tab import RemoteAccessTab
from core import theme

try:
    import tkinterdnd2
    from tkinterdnd2 import DND_FILES, COPY
    HAS_DND = True
except ImportError:
    tkinterdnd2 = None
    DND_FILES = COPY = None
    HAS_DND = False

BG      = theme.BG
PANEL   = theme.PANEL
PANEL_2 = theme.PANEL_2
ACCENT  = theme.ACCENT
DANGER  = theme.DANGER
TEXT    = theme.TEXT
MUTED   = theme.MUTED

_BTN = dict(fg_color=PANEL_2, hover_color=ACCENT, text_color=TEXT,
            height=34, corner_radius=8)
_BTN_ACCENT = dict(fg_color=ACCENT, hover_color=theme.ACCENT_DIM, text_color="white",
                   height=34, corner_radius=8)

PAGE_SIZE   = 100     # rows rendered at once — fine even with 750,000+ songs total
SCAN_WORKERS = 6      # concurrent tag-reader threads (network share = I/O bound, so
                       # a handful of threads in flight speeds this up a lot)


def _make_btn(parent, text, cmd, **overrides):
    kw = {**_BTN, **overrides}
    return ctk.CTkButton(parent, text=text, command=cmd, **kw)


def _fmt_row(meta, fallback_path):
    if meta:
        title = meta.get("title") or os.path.basename(meta.get("path") or fallback_path)
        artist = meta.get("artist")
        return f"{artist} - {title}" if artist else title
    return os.path.basename(fallback_path or "?")


def _fmt_count(n):
    return f"{n:,}"


class MusicPage(ctk.CTkFrame):

    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=BG)

        self.manager = manager
        self.engine = getattr(manager, "music_engine", None) or VLCMusicEngine()
        manager.music_engine = self.engine

        # Shared SQLite library index — lives on local disk, not the
        # network share, so browsing/searching/shuffling stay instant
        # even with 750,000+ songs indexed.
        self.db = getattr(manager, "music_db", None) or musicdb.Library()
        manager.music_db = self.db

        # Remote-access web server (phone streaming) — lazily created and
        # stashed on the manager, same pattern as engine/db above, so it
        # (and any in-progress remote session) survives re-opening this page.
        self.web_server = getattr(manager, "music_web_server", None) or MusicWebServer(library=self.db, engine=self.engine)
        manager.music_web_server = self.web_server
        # Always refresh — if the server object was reused from a prior
        # page-open, its .engine reference should still point at the live
        # engine so /api/control and /api/now-playing (used by the browser
        # extension) stay in sync.
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

        # Browse/search state
        self._result_ids = self.db.all_ids()
        self._page = 0
        self._search_seq = 0
        self._search_after_id = None
        self.row_widgets = []

        self._build_ui()
        self._sync_initial_state()
        self._render_page()
        self._start_loop()
        self._maybe_autoscan()
        self._setup_drag_drop()

    # ── Build ─────────────────────────────────────────────────

    def _build_ui(self):
        self._build_header()

        self.tabview = ctk.CTkTabview(
            self,
            fg_color=BG,
            segmented_button_fg_color=PANEL,
            segmented_button_selected_color=ACCENT,
            segmented_button_selected_hover_color=ACCENT,
        )
        self.tabview.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        library_tab = self.tabview.add("🎵 Library")
        settings_tab = self.tabview.add("⚙ Settings")

        # Everything below builds into `self._tab_body` (not `self`) so the
        # existing pack()-based layout works unchanged inside its tab.
        self._tab_body = library_tab

        self._build_library_controls()
        self._build_browse_panel()
        self._build_now_playing()
        self._build_controls()

        settings_tab.grid_rowconfigure(0, weight=1)
        settings_tab.grid_columnconfigure(0, weight=1)
        RemoteAccessTab(settings_tab, self.manager).grid(row=0, column=0, sticky="nsew")

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=10)
        header.pack(fill="x", padx=12, pady=(12, 4))

        ctk.CTkLabel(
            header, text="🎵  Music Player",
            font=("Segoe UI", 22, "bold"), text_color=TEXT
        ).pack(side="left", padx=14, pady=10)

        self.status = ctk.CTkLabel(header, text="Idle", text_color=MUTED)
        self.status.pack(side="right", padx=14)

    def _build_library_controls(self):
        panel = ctk.CTkFrame(self._tab_body, fg_color=PANEL, corner_radius=10)
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
            command=self._on_toggle_autoindex, text_color=TEXT,
            fg_color=ACCENT, hover_color=ACCENT,
        ).pack(side="left", padx=(0, 6))

        self.folder_label = ctk.CTkLabel(
            row, text=self._folder_display(), text_color=MUTED, anchor="w")
        self.folder_label.pack(side="left", fill="x", expand=True, padx=(6, 0))

        self.scan_status = ctk.CTkLabel(
            panel, text="", text_color=MUTED, anchor="w",
            font=("Segoe UI", 11))
        self.scan_status.pack(fill="x", padx=14, pady=(0, 10))

    def _build_browse_panel(self):
        panel = ctk.CTkFrame(self._tab_body, fg_color=PANEL, corner_radius=10)
        panel.pack(fill="both", expand=True, padx=12, pady=6)
        self.library_panel = panel

        top = ctk.CTkFrame(panel, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 4))

        ctk.CTkLabel(top, text="Library",
                     font=("Segoe UI", 15, "bold"), text_color=TEXT).pack(side="left")

        self.results_count = ctk.CTkLabel(top, text="0 songs", text_color=MUTED)
        self.results_count.pack(side="right")

        big_row = ctk.CTkFrame(panel, fg_color="transparent")
        big_row.pack(fill="x", padx=10, pady=(0, 6))

        _make_btn(big_row, "🔀  Shuffle All ▶", self.shuffle_all,
                  **_BTN_ACCENT, width=170).pack(side="left", padx=(0, 6))
        _make_btn(big_row, "▶  Play All (in order)", self.play_all,
                  width=170).pack(side="left", padx=(0, 6))
        _make_btn(big_row, "＋  Add Files (quick queue)", self.load_files,
                  width=190).pack(side="left")

        if HAS_DND:
            ctk.CTkLabel(
                big_row, text="…or drag files/a folder anywhere on this page",
                text_color=MUTED, font=("Segoe UI", 11)
            ).pack(side="left", padx=(10, 0))

        self.search_entry = ctk.CTkEntry(
            panel, placeholder_text="Search title / artist / album…", corner_radius=8)
        self.search_entry.pack(fill="x", padx=10, pady=(0, 6))
        self.search_entry.bind("<KeyRelease>", self._on_search_key)

        self.song_buttons_frame = ctk.CTkScrollableFrame(
            panel, fg_color=PANEL_2, corner_radius=8)
        self.song_buttons_frame.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        pager = ctk.CTkFrame(panel, fg_color="transparent")
        pager.pack(fill="x", padx=10, pady=(0, 10))

        self.prev_page_btn = _make_btn(pager, "◀ Prev", self.prev_page, width=90)
        self.prev_page_btn.pack(side="left")

        self.page_label = ctk.CTkLabel(pager, text="Page 1 / 1", text_color=MUTED)
        self.page_label.pack(side="left", expand=True)

        self.next_page_btn = _make_btn(pager, "Next ▶", self.next_page, width=90)
        self.next_page_btn.pack(side="right")

    def _build_now_playing(self):
        card = ctk.CTkFrame(self._tab_body, fg_color=PANEL, corner_radius=10)
        card.pack(fill="x", padx=12, pady=6)

        ctk.CTkLabel(card, text="Now Playing",
                     font=("Segoe UI", 12, "bold"), text_color=MUTED
                     ).pack(anchor="w", padx=14, pady=(10, 0))

        self.current_song_label = ctk.CTkLabel(
            card, text="Nothing playing", text_color=TEXT,
            font=("Segoe UI", 13), anchor="w")
        self.current_song_label.pack(fill="x", padx=14, pady=(2, 0))

        self.time_label = ctk.CTkLabel(card, text="00:00 / 00:00", text_color=MUTED)
        self.time_label.pack(anchor="w", padx=14, pady=(2, 4))

        self.progress = ctk.CTkProgressBar(
            card, progress_color=ACCENT, fg_color=PANEL_2, corner_radius=4)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=14, pady=(0, 12))

    def _build_controls(self):
        outer = ctk.CTkFrame(self._tab_body, fg_color=PANEL, corner_radius=10)
        outer.pack(fill="x", padx=12, pady=(4, 12))

        transport = ctk.CTkFrame(outer, fg_color="transparent")
        transport.pack(pady=(10, 4))

        for col, (text, cmd) in enumerate([
            ("⏮", self.prev), ("▶", self.play),
            ("⏸", self.pause), ("⏭", self.next),
        ]):
            _make_btn(transport, text, cmd, width=56).grid(
                row=0, column=col, padx=4)

        mode_row = ctk.CTkFrame(outer, fg_color="transparent")
        mode_row.pack(pady=(0, 4))

        self.shuffle_btn = _make_btn(mode_row, "🔀  Shuffle", self.toggle_shuffle, width=130)
        self.shuffle_btn.grid(row=0, column=0, padx=6)

        self.repeat_btn = _make_btn(mode_row, "🔁  Repeat", self.toggle_repeat, width=130)
        self.repeat_btn.grid(row=0, column=1, padx=6)

        vol_row = ctk.CTkFrame(outer, fg_color="transparent")
        vol_row.pack(fill="x", padx=14, pady=(4, 12))

        ctk.CTkLabel(vol_row, text="Vol", text_color=MUTED,
                     font=("Segoe UI", 11)).pack(side="left", padx=(0, 8))

        self.volume = ctk.CTkSlider(
            vol_row, from_=0, to=1, progress_color=ACCENT,
            command=self.set_volume, corner_radius=4)
        self.volume.pack(side="left", fill="x", expand=True)

    # ── Initial State Sync ────────────────────────────────────

    def _sync_initial_state(self):
        vol = getattr(self.engine, "volume", 0.5)
        self.volume.set(vol)
        self.engine.set_volume(vol)

        if self.engine.shuffle:
            self.shuffle_btn.configure(text="🔀  Shuffle", fg_color=ACCENT)

        mode = self.engine.repeat_mode
        if mode == "all":
            self.repeat_btn.configure(text="🔁  Repeat All", fg_color=ACCENT)
        elif mode == "one":
            self.repeat_btn.configure(text="🔂  Repeat One", fg_color="#2ecc71")

        self.results_count.configure(text=f"{_fmt_count(len(self._result_ids))} songs")
        self._update_playback_ui_state()

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

        current = max(0, self.engine.get_time())
        total   = max(0, self.engine.get_length())

        if total > 0:
            self.progress.set(current / total)
            self.time_label.configure(
                text=f"{int(current//60):02d}:{int(current%60):02d} / "
                     f"{int(total//60):02d}:{int(total%60):02d}")
        else:
            self.progress.set(0)
            self.time_label.configure(text="00:00 / 00:00")

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
        self._sync_autoindexer(folder)

    def rescan_now(self):
        folder = self.db.get_setting("music_folder")
        if not folder:
            self.status.configure(text="Set a music folder first")
            return
        if self.scan_state["scanning"]:
            self.status.configure(text="Already scanning…")
            return
        self._begin_scan(folder)

    def _maybe_autoscan(self):
        folder = self.db.get_setting("music_folder")
        if not getattr(self.manager, "_music_autoscanned", False):
            self.manager._music_autoscanned = True
            if folder:
                self._begin_scan(folder)
        # Start (or resume) the background auto-indexer regardless of
        # whether we just kicked off a startup scan — if the page is
        # being reopened, the indexer is likely already running and
        # this is a no-op via _sync_autoindexer's running-folder check.
        self._sync_autoindexer(folder)

    def _sync_autoindexer(self, folder):
        """Start/stop the background auto-indexer to match the current
        folder and the "Auto-index new files" checkbox state."""
        want_running = bool(folder) and self.autoindex_var.get()
        already_running = self.auto_indexer.running and self.auto_indexer.folder == folder
        if want_running and not already_running:
            self.auto_indexer.start(folder, status_cb=self._on_autoindex_status)
        elif not want_running and self.auto_indexer.running:
            self.auto_indexer.stop()
            self.autoindex_status["text"] = ""

    def _on_toggle_autoindex(self):
        enabled = self.autoindex_var.get()
        self.db.set_setting("auto_index_enabled", "1" if enabled else "0")
        self._sync_autoindexer(self.db.get_setting("music_folder"))

    def _on_autoindex_status(self, text):
        # Called from a background thread — just stash it; the GUI
        # thread picks it up next time _poll_scan_state runs.
        self.autoindex_status["text"] = text

    def _begin_scan(self, folder):
        state = self.scan_state
        state["scanning"] = True
        state["found"] = 0
        state["updated"] = 0
        state["stage"] = "starting"
        state["stop_event"] = threading.Event()

        def progress_cb(found, updated, stage):
            state["found"] = found
            state["updated"] = updated
            state["stage"] = stage

        def worker():
            try:
                self.db.scan(folder, progress_cb=progress_cb,
                             stop_event=state["stop_event"], workers=SCAN_WORKERS)
            finally:
                state["scanning"] = False

        threading.Thread(target=worker, daemon=True).start()

    def _poll_scan_state(self):
        state = self.scan_state
        if state["scanning"]:
            self.scan_status.configure(
                text=f"Scanning… {_fmt_count(state['found'])} files seen, "
                     f"{_fmt_count(state['updated'])} indexed/updated")
        elif self._last_seen_stage != state["stage"] and state["stage"] in ("done", "aborted"):
            self.scan_status.configure(
                text=f"Scan {state['stage']} — {_fmt_count(self.db.count())} songs in library")
            self._last_seen_stage = state["stage"]
            # Refresh whatever's currently being browsed/searched now that
            # the index may have changed.
            self._run_search(immediate=True)
        elif self.autoindex_status["text"]:
            # Nothing from the manual scanner to report — show the
            # background auto-indexer's status instead.
            text = self.autoindex_status["text"]
            self.scan_status.configure(text=text)
            if text != self._last_seen_autoindex_text:
                self._last_seen_autoindex_text = text
                if text.startswith("Auto-indexed"):
                    # The index just changed — refresh whatever's
                    # currently being browsed/searched.
                    self._run_search(immediate=True)

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
        audio_patterns = " ".join(f"*{ext}" for ext in musicdb.AUDIO_EXTS)
        playlist_patterns = " ".join(f"*{ext}" for ext in musicdb.PLAYLIST_EXTS)
        files = filedialog.askopenfilenames(
            filetypes=[
                ("Audio + Playlist Files", f"{audio_patterns} {playlist_patterns}"),
                ("Audio Files", audio_patterns),
                ("Playlist Files", playlist_patterns),
                ("All Files", "*.*"),
            ])
        if files:
            resolved, playlist_notes = self._expand_playlist_selection(files)
            if not resolved:
                msg = "; ".join(playlist_notes) if playlist_notes else "No playable tracks found in that selection"
                self.status.configure(text=msg)
                return
            self.engine.load(resolved)
            self.engine.play()
            n = len(resolved)
            msg = f"{n} file{'s' if n != 1 else ''} loaded"
            if playlist_notes:
                msg += " — " + "; ".join(playlist_notes)
            self.status.configure(text=msg)
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
        dropped_files = [
            p for p in paths
            if os.path.isfile(p) and p.lower().endswith(musicdb.AUDIO_EXTS + musicdb.PLAYLIST_EXTS)
        ]
        audio_files, playlist_notes = self._expand_playlist_selection(dropped_files)

        if audio_files:
            self.engine.load(audio_files)
            self.engine.play()
            n = len(audio_files)
            msg = f"{n} file{'s' if n != 1 else ''} added from drag & drop"
            if playlist_notes:
                msg += " — " + "; ".join(playlist_notes)
            self.status.configure(text=msg)
            self._update_playback_ui_state()
        elif dirs:
            folder = dirs[0]
            self.db.set_setting("music_folder", folder)
            self.folder_label.configure(text=folder)
            self.status.configure(text=f"Indexing dropped folder: {folder}")
            self.rescan_now()
            self._sync_autoindexer(folder)
        elif playlist_notes:
            # A playlist file was dropped but every entry inside it
            # failed to resolve — tell the user why instead of the
            # generic "no supported files" message below.
            self.status.configure(text="; ".join(playlist_notes))
        else:
            self.status.configure(text="No supported audio files in that drop")

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
        self.results_count.configure(text=f"{_fmt_count(len(ids))} songs")
        self._render_page()

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
        for w in self.song_buttons_frame.winfo_children():
            w.destroy()
        self.row_widgets = []

        start = self._page * PAGE_SIZE
        end = min(start + PAGE_SIZE, len(self._result_ids))
        page_ids = list(self._result_ids[start:end])
        metas = self.db.get_songs(page_ids)

        for offset, sid in enumerate(page_ids):
            global_index = start + offset
            meta = metas.get(sid)
            text = f"{global_index + 1}.  {_fmt_row(meta, None)}"

            row = ctk.CTkFrame(self.song_buttons_frame, fg_color=PANEL, corner_radius=6)
            row.pack(fill="x", padx=4, pady=2)

            btn = ctk.CTkButton(
                row, text=text,
                fg_color=PANEL, hover_color=ACCENT, text_color=TEXT,
                anchor="w", height=30, corner_radius=6,
                command=lambda gi=global_index: self.play_result(gi))
            btn.pack(side="left", fill="x", expand=True)

            self.row_widgets.append((global_index, btn))

        total_pages = self._total_pages()
        self.page_label.configure(text=f"Page {self._page + 1} / {total_pages}")
        self.prev_page_btn.configure(state="normal" if self._page > 0 else "disabled")
        self.next_page_btn.configure(
            state="normal" if self._page + 1 < total_pages else "disabled")

        self._highlight_active()

    # ── Playback ─────────────────────────────────────────────

    def play_result(self, global_index):
        self.engine.load_ids(self.db, self._result_ids, start_index=global_index)
        self.engine.play()
        self._update_playback_ui_state()

    def shuffle_all(self):
        ids = self.db.all_ids()
        if not len(ids):
            self.status.configure(text="Library is empty — set a music folder first")
            return
        start = random.randrange(len(ids))
        self.engine.load_ids(self.db, ids, start_index=start)
        self.engine.shuffle = True
        self.shuffle_btn.configure(fg_color=ACCENT)
        self.engine.play()
        self._update_playback_ui_state()

    def play_all(self):
        ids = self.db.all_ids()
        if not len(ids):
            self.status.configure(text="Library is empty — set a music folder first")
            return
        self.engine.load_ids(self.db, ids, start_index=0)
        self.engine.play()
        self._update_playback_ui_state()

    def play(self):
        self.engine.play()
        self._update_playback_ui_state()

    def pause(self):
        self.engine.pause()
        self._update_playback_ui_state()

    def next(self):
        self.engine.next()
        self._update_playback_ui_state()

    def prev(self):
        self.engine.prev()
        self._update_playback_ui_state()

    def set_volume(self, value):
        self.engine.set_volume(value)

    # ── Shuffle / Repeat ──────────────────────────────────────

    def toggle_shuffle(self):
        self.engine.shuffle = not self.engine.shuffle
        self.shuffle_btn.configure(fg_color=ACCENT if self.engine.shuffle else PANEL_2)

    def toggle_repeat(self):
        modes = ["off", "all", "one"]
        next_mode = modes[(modes.index(self.engine.repeat_mode) + 1) % len(modes)]
        self.engine.repeat_mode = next_mode

        if next_mode == "off":
            self.repeat_btn.configure(text="🔁  Repeat", fg_color=PANEL_2)
        elif next_mode == "all":
            self.repeat_btn.configure(text="🔁  Repeat All", fg_color=ACCENT)
        else:
            self.repeat_btn.configure(text="🔂  Repeat One", fg_color="#2ecc71")

    # ── Highlight ─────────────────────────────────────────────

    def _highlight_active(self):
        for global_index, btn in self.row_widgets:
            if global_index == self.active_index and self._current_queue_is(self._result_ids):
                btn.configure(fg_color=ACCENT, text_color="white")
            else:
                btn.configure(fg_color=PANEL, text_color=TEXT)

    def _current_queue_is(self, ids):
        # Only highlight a browse row as "active" when the engine's queue is
        # actually this same result set (not, say, an ad-hoc "Add Files" list).
        playlist = self.engine.playlist
        return getattr(playlist, "ids", None) is ids

    # ── NEW: Unified UI Playback State Updater ────────────────

    def _update_playback_ui_state(self):
        current_engine_index = self.engine.index
        is_playing = self.engine.is_playing()
        engine_state = self.engine.get_state()

        if current_engine_index != self.active_index:
            self.active_index = current_engine_index
            self._highlight_active()
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

        if is_playing:
            self.status.configure(text=f"Playing ▶ Track {self.active_index + 1}")
            if not self._discord_rpc_active:
                self.update_discord_song(force_update=True)
        elif engine_state == State.Paused:
            self.status.configure(text="Paused ⏸")
            if self._discord_rpc_active:
                self.update_discord_song(force_clear=True)
        elif (current_engine_index == -1 and not self.engine.playlist) or \
             (current_engine_index == -1 and self.engine.playlist and engine_state == State.Stopped):
            self.status.configure(text="Idle" if not self.engine.playlist else "Stopped")
            if self._discord_rpc_active:
                self.update_discord_song(force_clear=True)
        elif engine_state == State.Ended:
            self.status.configure(text="Finished")
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
