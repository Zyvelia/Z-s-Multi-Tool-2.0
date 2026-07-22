# music_player/auto_index.py
#
# Keeps the library index automatically in sync with the music folder,
# so new/changed/removed files show up without the user ever having to
# click "Rescan Now". Two mechanisms work together:
#
#   1. Live filesystem watching (via the optional `watchdog` package).
#      When a file is created/modified/deleted/moved under the watched
#      folder, its path is queued and — after a short debounce, so a
#      big drag-and-drop of an album doesn't cause a flood of work —
#      indexed directly via Library.index_paths()/remove_paths(). No
#      directory walk needed, so this stays cheap even on a
#      750,000+ file network share.
#
#      Cue sheets (album.ape + album.cue) get the same live treatment:
#      a changed .cue is re-expanded into its per-track rows via
#      Library.index_cue_sheet(), and a newly-arrived audio file is
#      checked against any sibling .cue that already claims it before
#      falling back to indexing it as one whole-file track.
#
#   2. A periodic incremental safety-net scan (Library.scan(), which is
#      itself cheap for unchanged files). This catches anything the
#      watcher misses — which happens more than you'd like on network
#      shares/SMB mounts, drives that get disconnected and reconnected,
#      etc. — and is the *only* mechanism used if `watchdog` isn't
#      installed at all.
#
# Everything here runs on a single background thread (started in
# start(), stopped in stop()) plus, if available, watchdog's own
# observer thread. Only one sqlite connection ends up being opened for
# this module's work, since sqlite3 connections in db.py are cached
# per-thread and we deliberately avoid spinning up a new thread per
# event (e.g. threading.Timer would do exactly that).

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


DEBOUNCE_SECONDS = 3.0                 # let a burst of changes settle
DEFAULT_SAFETY_SCAN_SECONDS = 15 * 60  # fallback full incremental rescan


class _Handler(FileSystemEventHandler):
    """Translates raw watchdog events into queued path changes."""

    def __init__(self, on_changed, on_removed):
        super().__init__()
        self._on_changed = on_changed
        self._on_removed = on_removed

    @staticmethod
    def _is_relevant(path):
        low = path.lower()
        return low.endswith(musicdb.AUDIO_EXTS) or low.endswith(musicdb.CUE_EXTS)

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

    Usage:
        indexer = AutoIndexer(library)
        indexer.start(folder, status_cb=lambda text: ...)
        ...
        indexer.stop()

    status_cb(text) is called from a background thread whenever the
    human-readable status changes — hop to the GUI thread yourself
    (e.g. via widget.after(...)) before touching widgets with it.
    """

    def __init__(self, library, safety_scan_seconds=DEFAULT_SAFETY_SCAN_SECONDS):
        self.library = library
        self.safety_scan_seconds = safety_scan_seconds
        self.folder = None
        self.status_cb = None
        self.using_watchdog = False

        self._observer = None
        self._worker_thread = None
        self._stop_event = threading.Event()

        self._pending_lock = threading.Lock()
        self._pending_changed = set()
        self._pending_removed = set()
        self._last_event_time = None

    @property
    def running(self):
        return self._worker_thread is not None and self._worker_thread.is_alive()

    # ── lifecycle ────────────────────────────────────────────────

    def start(self, folder, status_cb=None):
        self.stop()
        if not folder:
            return
        self.folder = folder
        self.status_cb = status_cb
        self._stop_event.clear()
        self._pending_changed.clear()
        self._pending_removed.clear()
        self._last_event_time = None

        self.using_watchdog = False
        if HAS_WATCHDOG and os.path.isdir(folder):
            try:
                handler = _Handler(self._queue_changed, self._queue_removed)
                self._observer = Observer()
                self._observer.schedule(handler, folder, recursive=True)
                self._observer.start()
                self.using_watchdog = True
            except Exception:
                # Some network filesystems / mounts don't support native
                # change notifications — fall back to periodic scanning.
                self._observer = None
                self.using_watchdog = False

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

    # ── live events (called from the watchdog observer thread) ────

    def _queue_changed(self, path):
        with self._pending_lock:
            self._pending_changed.add(path)
            self._pending_removed.discard(path)
            self._last_event_time = time.monotonic()

    def _queue_removed(self, path):
        with self._pending_lock:
            self._pending_removed.add(path)
            self._pending_changed.discard(path)
            self._last_event_time = time.monotonic()

    # ── single background worker: debounce flush + safety scan ────

    def _worker_loop(self):
        last_safety = time.monotonic()
        # Stagger the first safety scan a bit so it doesn't collide
        # with a manual/startup scan already in flight.
        if self._stop_event.wait(5):
            return
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
            return (time.monotonic() - self._last_event_time) >= DEBOUNCE_SECONDS

    def _sibling_cue_claiming(self, audio_path):
        """
        If a .cue sheet already sitting next to `audio_path` references
        it, return that cue sheet's path. Used when a *new* audio file
        shows up after its .cue sheet was already there (so no event
        fires for the cue itself) — otherwise the file would get indexed
        as one whole-file track instead of being split by the cue.
        """
        dirpath = os.path.dirname(audio_path)
        basename_lower = os.path.basename(audio_path).lower()
        try:
            entries = os.listdir(dirpath)
        except OSError:
            return None
        for fn in entries:
            if not fn.lower().endswith(musicdb.CUE_EXTS):
                continue
            candidate = os.path.join(dirpath, fn)
            try:
                tracks = cuesheet.parse_cue(candidate)
            except Exception:
                continue
            if any(os.path.basename(t["file"]).lower() == basename_lower for t in tracks):
                return candidate
        return None

    def _flush_pending(self):
        with self._pending_lock:
            changed = list(self._pending_changed)
            removed = list(self._pending_removed)
            self._pending_changed.clear()
            self._pending_removed.clear()
        if not changed and not removed:
            return

        cue_changed = [p for p in changed if p.lower().endswith(musicdb.CUE_EXTS)]
        audio_changed = [p for p in changed if not p.lower().endswith(musicdb.CUE_EXTS)]

        try:
            if removed:
                self.library.remove_paths(removed)

            # Cue sheets that were created/edited: (re-)expand into
            # per-track rows, and drop any stale whole-file row for the
            # audio they now claim.
            claimed_this_round = set()
            for cue_path in cue_changed:
                _indexed, claimed_audio_paths = self.library.index_cue_sheet(cue_path)
                if claimed_audio_paths:
                    self.library.remove_paths(list(claimed_audio_paths))
                claimed_this_round.update(os.path.normcase(p) for p in claimed_audio_paths)

            # Audio files that were created/changed: if a sibling .cue
            # already claims this file, expand via the cue instead of
            # adding a plain whole-file row.
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
        try:
            self.library.scan(self.folder, workers=3, stop_event=self._stop_event)
            if not self._stop_event.is_set():
                self._set_status(f"Up to date — {self.library.count():,} songs in library")
        except Exception:
            pass

    def _set_status(self, text):
        if self.status_cb:
            try:
                self.status_cb(text)
            except Exception:
                pass
