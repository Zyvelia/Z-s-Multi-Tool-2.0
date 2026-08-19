# music_player/auto_index.py
#
# Keeps the library index in sync with the music folder.
#
#   1. Live filesystem watching (watchdog) — indexes only changed paths.
#   2. Periodic quick_scan() — walks the tree but skips unchanged
#      directories via the dir_index cache in db_index.py.

from __future__ import annotations

import os
import threading
import time

from . import db as musicdb
from . import cue as cuesheet

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    Observer = None
    FileSystemEventHandler = object
    HAS_WATCHDOG = False


DEBOUNCE_SECONDS = 2.0
DEFAULT_SAFETY_SCAN_SECONDS = 20 * 60
WATCHDOG_SAFETY_SCAN_SECONDS = 90 * 60
SCAN_WORKERS = 6


class _Handler(FileSystemEventHandler):
    """Translates raw watchdog events into queued path changes."""

    def __init__(self, on_changed, on_removed):
        super().__init__()
        self._on_changed = on_changed
        self._on_removed = on_removed

    @staticmethod
    def _is_relevant(path):
        low = path.lower()
        return low.endswith(musicdb.LIBRARY_EXTS) or low.endswith(musicdb.CUE_EXTS)

    def on_created(self, event):
        if not event.is_directory and self._is_relevant(event.src_path):
            self._on_changed(event.src_path)

    def on_modified(self, event):
        if not event.is_directory and self._is_relevant(event.src_path):
            self._on_changed(event.src_path)

    def on_moved(self, event):
        if event.is_directory:
            return
        if self._is_relevant(event.src_path):
            self._on_removed(event.src_path)
        if self._is_relevant(event.dest_path):
            self._on_changed(event.dest_path)

    def on_deleted(self, event):
        if not event.is_directory and self._is_relevant(event.src_path):
            self._on_removed(event.src_path)


class AutoIndexer:
    """
    Keeps `library` automatically in sync with a folder.

    status_cb(text) is invoked from a background thread.
    scan_busy_cb() should return True while a manual/full scan is running.
    """

    def __init__(self, library, safety_scan_seconds=DEFAULT_SAFETY_SCAN_SECONDS):
        self.library = library
        self.safety_scan_seconds = safety_scan_seconds
        self.folder = None
        self.status_cb = None
        self.scan_busy_cb = None
        self.using_watchdog = False
        self._library_fresh = False

        self._observer = None
        self._worker_thread = None
        self._stop_event = threading.Event()

        self._pending_lock = threading.Lock()
        self._pending_changed: set[str] = set()
        self._pending_removed: set[str] = set()
        self._last_event_time = None

        # Per-directory cue lookup cache — avoids re-parsing .cue on every file event.
        self._cue_dir_cache: dict[str, dict[str, str]] = {}

    @property
    def running(self):
        return self._worker_thread is not None and self._worker_thread.is_alive()

    def start(self, folder, status_cb=None, scan_busy_cb=None, library_fresh=False):
        self.stop()
        if not folder:
            return
        self.folder = os.path.normcase(os.path.normpath(folder)) if folder else None
        self.status_cb = status_cb
        self.scan_busy_cb = scan_busy_cb
        self._library_fresh = library_fresh
        self._stop_event.clear()
        self._pending_changed.clear()
        self._pending_removed.clear()
        self._last_event_time = None
        self._cue_dir_cache.clear()

        self.using_watchdog = False
        if HAS_WATCHDOG and os.path.isdir(self.folder):
            try:
                handler = _Handler(self._queue_changed, self._queue_removed)
                self._observer = Observer()
                self._observer.schedule(handler, self.folder, recursive=True)
                self._observer.start()
                self.using_watchdog = True
            except Exception:
                self._observer = None
                self.using_watchdog = False

        self.safety_scan_seconds = (
            WATCHDOG_SAFETY_SCAN_SECONDS if self.using_watchdog
            else DEFAULT_SAFETY_SCAN_SECONDS
        )

        self._set_status(
            "Watching for changes…" if self.using_watchdog
            else "Auto-indexing (periodic scan)…")

        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker_thread.start()

    def stop(self):
        self._stop_event.set()
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=2)
            except Exception:
                pass
            self._observer = None
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=2)
            self._worker_thread = None

    def _queue_changed(self, path):
        from .db import normalize_path
        path = normalize_path(path)
        with self._pending_lock:
            self._pending_changed.add(path)
            self._pending_removed.discard(path)
            self._last_event_time = time.monotonic()

    def _queue_removed(self, path):
        from .db import normalize_path
        path = normalize_path(path)
        with self._pending_lock:
            self._pending_removed.add(path)
            self._pending_changed.discard(path)
            self._last_event_time = time.monotonic()

    def _worker_loop(self):
        if self.using_watchdog:
            # Watch-only — file events drive indexing; no folder walks on start.
            while not self._stop_event.is_set():
                if self._debounce_due():
                    self._flush_pending()
                if self._stop_event.wait(0.5):
                    return
            return

        # No watchdog: periodic quick_scan as a fallback.
        initial_wait = 30 * 60 if self._library_fresh else 10
        if self._stop_event.wait(initial_wait):
            return
        last_safety = time.monotonic()
        while not self._stop_event.is_set():
            if self._debounce_due():
                self._flush_pending()

            if time.monotonic() - last_safety >= self.safety_scan_seconds:
                self._run_safety_scan()
                last_safety = time.monotonic()

            if self._stop_event.wait(0.5):
                return

    def _debounce_due(self):
        with self._pending_lock:
            if not self._pending_changed and not self._pending_removed:
                return False
            return (time.monotonic() - (self._last_event_time or 0)) >= DEBOUNCE_SECONDS

    def _cue_map_for_dir(self, dirpath: str) -> dict[str, str]:
        cached = self._cue_dir_cache.get(dirpath)
        if cached is not None:
            return cached
        mapping: dict[str, str] = {}
        try:
            entries = os.listdir(dirpath)
        except OSError:
            self._cue_dir_cache[dirpath] = mapping
            return mapping
        for fn in entries:
            if not fn.lower().endswith(musicdb.CUE_EXTS):
                continue
            candidate = os.path.join(dirpath, fn)
            try:
                tracks = cuesheet.parse_cue(candidate)
            except Exception:
                continue
            for t in tracks:
                base = os.path.basename(t["file"]).lower()
                mapping[base] = candidate
        self._cue_dir_cache[dirpath] = mapping
        return mapping

    def _invalidate_cue_cache(self, paths):
        for p in paths:
            self._cue_dir_cache.pop(os.path.dirname(os.path.abspath(p)), None)

    def _sibling_cue_claiming(self, audio_path: str) -> str | None:
        dirpath = os.path.dirname(os.path.abspath(audio_path))
        base = os.path.basename(audio_path).lower()
        return self._cue_map_for_dir(dirpath).get(base)

    def _flush_pending(self):
        with self._pending_lock:
            changed = list(self._pending_changed)
            removed = list(self._pending_removed)
            self._pending_changed.clear()
            self._pending_removed.clear()
        if not changed and not removed:
            return

        touched = changed + removed
        self.library.invalidate_dirs_for_paths(touched)
        self._invalidate_cue_cache(touched)

        cue_changed = [p for p in changed if p.lower().endswith(musicdb.CUE_EXTS)]
        audio_changed = [
            p for p in changed
            if musicdb.is_media_path(p) and not p.lower().endswith(musicdb.CUE_EXTS)
        ]

        try:
            if removed:
                self.library.remove_paths(removed)

            claimed_this_round: set[str] = set()
            for cue_path in cue_changed:
                _indexed, claimed_audio_paths = self.library.index_cue_sheet(cue_path)
                if claimed_audio_paths:
                    self.library.remove_paths(list(claimed_audio_paths))
                claimed_this_round.update(os.path.normcase(p) for p in claimed_audio_paths)

            plain_audio = []
            for path in audio_changed:
                if os.path.normcase(path) in claimed_this_round:
                    continue
                sibling_cue = self._sibling_cue_claiming(path)
                if sibling_cue:
                    self.library.index_cue_sheet(sibling_cue)
                else:
                    plain_audio.append(path)

            if plain_audio:
                self.library.index_paths(plain_audio)
        except Exception:
            return

        n = len(changed) + len(removed)
        self._set_status(
            f"Auto-indexed {n} change{'s' if n != 1 else ''} — "
            f"{self.library.count():,} songs in library")

    def _run_safety_scan(self):
        if not self.folder:
            return
        if self.scan_busy_cb:
            try:
                if self.scan_busy_cb():
                    return
            except Exception:
                pass
        try:
            self.library.quick_scan(
                self.folder, workers=SCAN_WORKERS, stop_event=self._stop_event)
            if not self._stop_event.is_set():
                self.library.set_setting("music_last_scan_folder", self.folder)
                self.library.set_setting("music_last_scan_at", str(time.time()))
                self._set_status(f"Up to date — {self.library.count():,} songs in library")
        except Exception:
            pass

    def _set_status(self, text):
        if self.status_cb:
            try:
                self.status_cb(text)
            except Exception:
                pass
