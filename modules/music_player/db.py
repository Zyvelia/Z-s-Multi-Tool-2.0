# music_player/db.py
#
# SQLite-backed music library. Designed for VERY large collections
# (750,000+ files) living on a network share:
#
#   - The index itself (paths, tags, durations) lives in a small local
#     SQLite file, so search/browse/shuffle
#     are instant
#   - Scanning is INCREMENTAL: a file is only re-read (via mutagen) if
#     its size/mtime changed since the last scan. Unchanged files are
#     skipped with a single indexed point-lookup, so re-scans after the
#     first one are fast.
#   - Tag reading (the slow, network-latency-bound part) is done by a
#     small pool of worker threads so many files can be "in flight"
#     over the network at once, instead of one-at-a-time.
#   - Nothing ever holds the full list of 750k+ file paths/tags in
#     memory at once — only small pages/queues.
#
# This module has no GUI or audio dependencies; it's safe to import
# and unit-test on its own.

import os
import sqlite3
import threading
import queue
from array import array

from . import cue as cuesheet

AUDIO_EXTS = (
    ".mp3", ".flac", ".wav", ".ogg", ".oga", ".m4a", ".aac",
    ".wma", ".opus", ".aiff", ".aif", ".ape", ".wv",
)

CUE_EXTS = (".cue",)

SCHEMA = """
CREATE TABLE IF NOT EXISTS songs (
    id       INTEGER PRIMARY KEY,
    path     TEXT UNIQUE NOT NULL,
    title    TEXT,
    artist   TEXT,
    album    TEXT,
    duration REAL,
    size     INTEGER,
    mtime    REAL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# FTS5 (full text search) is created separately so we can fall back
# gracefully if the local SQLite build doesn't have FTS5 compiled in.
FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS songs_fts USING fts5(
    title, artist, album, path,
    content='songs', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS songs_ai AFTER INSERT ON songs BEGIN
    INSERT INTO songs_fts(rowid, title, artist, album, path)
    VALUES (new.id, new.title, new.artist, new.album, new.path);
END;

CREATE TRIGGER IF NOT EXISTS songs_ad AFTER DELETE ON songs BEGIN
    INSERT INTO songs_fts(songs_fts, rowid, title, artist, album, path)
    VALUES ('delete', old.id, old.title, old.artist, old.album, old.path);
END;

CREATE TRIGGER IF NOT EXISTS songs_au AFTER UPDATE ON songs BEGIN
    INSERT INTO songs_fts(songs_fts, rowid, title, artist, album, path)
    VALUES ('delete', old.id, old.title, old.artist, old.album, old.path);
    INSERT INTO songs_fts(rowid, title, artist, album, path)
    VALUES (new.id, new.title, new.artist, new.album, new.path);
END;
"""


def default_db_path():
    """Local (non-network) location for the library index file."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    d = os.path.join(base, "MusicPlayerApp")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "library.db")


def _read_tags(path):
    """Read title/artist/album/duration for one file. Never raises."""
    title = artist = album = None
    duration = 0.0
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(path, easy=True)
        if audio is not None:
            if audio.tags:
                if "title" in audio.tags:
                    title = audio.tags["title"][0]
                if "artist" in audio.tags:
                    artist = audio.tags["artist"][0]
                if "album" in audio.tags:
                    album = audio.tags["album"][0]
            if audio.info is not None:
                duration = float(getattr(audio.info, "length", 0) or 0)
    except Exception:
        pass
    if not title:
        title = os.path.splitext(os.path.basename(path))[0]
    return title, artist, album, duration


def _read_duration(path):
    """Read just the total duration (seconds) of a file. Never raises."""
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(path)
        if audio and audio.info:
            return float(getattr(audio.info, "length", 0) or 0)
    except Exception:
        pass
    return 0.0


class Library:
    """
    Thread-safe-ish handle to the SQLite library. Each thread that touches
    it gets its own connection (WAL mode lets one writer + many readers
    coexist), keyed off thread-local storage.
    """

    def __init__(self, db_path=None):
        self.db_path = db_path or default_db_path()
        self._local = threading.local()
        self._has_fts = False
        self._init_schema()

    # ── connection handling ─────────────────────────────────────

    def _conn(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=30000")
            self._local.conn = conn
        return conn

    def _init_schema(self):
        conn = self._conn()
        conn.executescript(SCHEMA)

        # Migrate older DBs: cue-sheet tracks need to point at the real
        # underlying audio file (audio_path) separately from their own
        # synthetic, per-track `path` key, plus the segment they cover.
        existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(songs)")}
        for col, decl in (("audio_path", "TEXT"), ("cue_start", "REAL"), ("cue_end", "REAL")):
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE songs ADD COLUMN {col} {decl}")
        conn.commit()

        try:
            conn.executescript(FTS_SCHEMA)
            self._has_fts = True
        except sqlite3.OperationalError:
            # FTS5 not available in this SQLite build — fall back to LIKE.
            self._has_fts = False
        conn.commit()

    # ── settings (music folder path, etc.) ──────────────────────

    def get_setting(self, key, default=None):
        row = self._conn().execute(
            "SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key, value):
        conn = self._conn()
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value))
        conn.commit()

    # ── scanning ─────────────────────────────────────────────────

    def scan(self, root, progress_cb=None, stop_event=None, workers=6):
        """
        Incrementally index `root`. Only new/changed files get their tags
        re-read; unchanged files are skipped after a cheap stat+lookup.
        After a full (non-aborted) scan, DB entries for files no longer
        present on disk are removed.

        progress_cb(found, updated, current_dir_or_"done") is called
        periodically from THIS thread — callers updating a GUI must hop
        back to the GUI thread themselves (e.g. via widget.after(...)).

        Returns (found, updated).
        """
        conn = self._conn()
        conn.execute("DROP TABLE IF EXISTS temp.scan_seen")
        conn.execute("CREATE TEMP TABLE scan_seen(path TEXT PRIMARY KEY)")
        conn.commit()

        work_q = queue.Queue(maxsize=4000)
        result_q = queue.Queue()
        SENTINEL = object()

        def tag_worker():
            while True:
                item = work_q.get()
                if item is SENTINEL:
                    work_q.task_done()
                    return
                path, size, mtime = item
                title, artist, album, duration = _read_tags(path)
                result_q.put((title, artist, album, duration, size, mtime, path))
                work_q.task_done()

        threads = [threading.Thread(target=tag_worker, daemon=True)
                   for _ in range(max(1, workers))]
        for t in threads:
            t.start()

        found = 0
        updated = 0
        aborted = False

        def drain(force=False):
            nonlocal updated
            batch = []
            while True:
                try:
                    batch.append(result_q.get_nowait())
                except queue.Empty:
                    break
                if not force and len(batch) >= 500:
                    break
            if batch:
                conn.executemany(
                    "INSERT INTO songs(path, title, artist, album, duration, size, mtime, audio_path) "
                    "VALUES (?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(path) DO UPDATE SET "
                    "title=excluded.title, artist=excluded.artist, album=excluded.album, "
                    "duration=excluded.duration, size=excluded.size, mtime=excluded.mtime, "
                    "audio_path=excluded.audio_path",
                    [(p, t, ar, al, d, s, m, p) for (t, ar, al, d, s, m, p) in batch]
                )
                conn.commit()
                updated += len(batch)

        def _index_cue_sheet(cue_path, dirpath, filenames_lower):
            """
            Parse one .cue sheet and index each track it describes as its
            own library row (synthetic path, real audio_path + cue_start/
            cue_end window). Returns the set of lowercased audio-file
            basenames it successfully claimed (so the plain-file scan
            below skips them).
            """
            nonlocal found, updated
            claimed_here = set()
            try:
                cue_tracks = cuesheet.parse_cue(cue_path)
            except Exception:
                cue_tracks = []
            if not cue_tracks:
                return claimed_here

            by_file = {}
            for t in cue_tracks:
                by_file.setdefault(t["file"], []).append(t)

            for ref_name, tlist in by_file.items():
                real_name = filenames_lower.get(os.path.basename(ref_name).lower())
                if not real_name:
                    continue  # referenced audio file isn't next to the cue sheet
                audio_path = os.path.join(dirpath, real_name)
                try:
                    st = os.stat(audio_path)
                except OSError:
                    continue

                file_duration = _read_duration(audio_path) or None
                for t, start, end in cuesheet.windows_for_file_tracks(tlist, file_duration):
                    synth_path = f"{audio_path}::cue{t['track']:02d}"
                    title = t.get("title") or f"Track {t['track']:02d}"
                    artist = t.get("performer")
                    album = t.get("album")
                    duration = (end - start) if end is not None else 0.0

                    found += 1
                    conn.execute(
                        "INSERT OR IGNORE INTO scan_seen(path) VALUES (?)", (synth_path,))
                    conn.execute(
                        "INSERT INTO songs(path, title, artist, album, duration, size, mtime, "
                        "audio_path, cue_start, cue_end) VALUES (?,?,?,?,?,?,?,?,?,?) "
                        "ON CONFLICT(path) DO UPDATE SET "
                        "title=excluded.title, artist=excluded.artist, album=excluded.album, "
                        "duration=excluded.duration, size=excluded.size, mtime=excluded.mtime, "
                        "audio_path=excluded.audio_path, cue_start=excluded.cue_start, "
                        "cue_end=excluded.cue_end",
                        (synth_path, title, artist, album, duration, st.st_size, st.st_mtime,
                         audio_path, start, end))
                    updated += 1
                claimed_here.add(real_name.lower())

            if claimed_here:
                conn.commit()
            return claimed_here

        try:
            for dirpath, dirnames, filenames in os.walk(root):
                if stop_event and stop_event.is_set():
                    aborted = True
                    break

                # ── cue sheets first: they "claim" the audio file(s) they
                # reference, so those files are indexed per-track instead
                # of as one single track below.
                claimed = set()
                filenames_lower = {f.lower(): f for f in filenames}
                for fn in filenames:
                    if stop_event and stop_event.is_set():
                        aborted = True
                        break
                    if not fn.lower().endswith(CUE_EXTS):
                        continue
                    cue_path = os.path.join(dirpath, fn)
                    claimed |= _index_cue_sheet(cue_path, dirpath, filenames_lower)
                if aborted:
                    break

                for fn in filenames:
                    if stop_event and stop_event.is_set():
                        aborted = True
                        break
                    if not fn.lower().endswith(AUDIO_EXTS):
                        continue
                    if fn.lower() in claimed:
                        continue  # already indexed per-track via its .cue sheet
                    path = os.path.join(dirpath, fn)
                    try:
                        st = os.stat(path)
                    except OSError:
                        continue

                    found += 1
                    conn.execute(
                        "INSERT OR IGNORE INTO scan_seen(path) VALUES (?)", (path,))

                    row = conn.execute(
                        "SELECT mtime, size FROM songs WHERE path=?", (path,)
                    ).fetchone()
                    unchanged = (
                        row is not None
                        and row["size"] == st.st_size
                        and abs((row["mtime"] or 0) - st.st_mtime) < 1.0
                    )
                    if not unchanged:
                        work_q.put((path, st.st_size, st.st_mtime))

                    if progress_cb and found % 250 == 0:
                        progress_cb(found, updated, dirpath)
                    drain()
                drain()
                if aborted:
                    break

            for _ in threads:
                work_q.put(SENTINEL)
            for t in threads:
                t.join()
            drain(force=True)

            if not aborted:
                conn.execute(
                    "DELETE FROM songs WHERE path NOT IN (SELECT path FROM scan_seen)")
                conn.commit()
        finally:
            conn.execute("DROP TABLE IF EXISTS scan_seen")
            conn.commit()

        if progress_cb:
            progress_cb(found, updated, "aborted" if aborted else "done")
        return found, updated

    # ── targeted (non-walk) updates ─────────────────────────────
    #
    # Used by the filesystem watcher in auto_index.py: when we already
    # know exactly which paths changed, there's no need to os.walk the
    # whole (possibly 750,000+ file) tree just to index a couple of new
    # songs.

    def index_paths(self, paths):
        """Add/update specific files by path. Returns count indexed."""
        conn = self._conn()
        updated = 0
        for path in paths:
            if not path.lower().endswith(AUDIO_EXTS):
                continue
            try:
                st = os.stat(path)
            except OSError:
                continue
            title, artist, album, duration = _read_tags(path)
            conn.execute(
                "INSERT INTO songs(path, title, artist, album, duration, size, mtime, audio_path) "
                "VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET "
                "title=excluded.title, artist=excluded.artist, album=excluded.album, "
                "duration=excluded.duration, size=excluded.size, mtime=excluded.mtime, "
                "audio_path=excluded.audio_path",
                (path, title, artist, album, duration, st.st_size, st.st_mtime, path))
            updated += 1
        if updated:
            conn.commit()
        return updated

    def remove_paths(self, paths):
        """Remove specific files by path (e.g. after a delete/move-away
        event). Returns count removed."""
        paths = list(paths)
        if not paths:
            return 0
        conn = self._conn()
        conn.executemany("DELETE FROM songs WHERE path=?", [(p,) for p in paths])
        conn.commit()
        return len(paths)

    # ── queries ──────────────────────────────────────────────────

    def count(self):
        return self._conn().execute("SELECT COUNT(*) FROM songs").fetchone()[0]

    def all_ids(self):
        """All song ids, ordered by artist/album/title. Cheap: ~6MB per 750k songs."""
        rows = self._conn().execute(
            "SELECT id FROM songs ORDER BY artist COLLATE NOCASE, album COLLATE NOCASE, "
            "title COLLATE NOCASE").fetchall()
        return array('q', (r["id"] for r in rows))

    def search_ids(self, query, limit=200000):
        query = (query or "").strip()
        conn = self._conn()
        if not query:
            return self.all_ids()

        if self._has_fts:
            terms = [t.replace('"', '') for t in query.split() if t]
            match = " ".join(f'"{t}"*' for t in terms) if terms else None
            if match:
                try:
                    rows = conn.execute(
                        "SELECT songs.id FROM songs_fts "
                        "JOIN songs ON songs.id = songs_fts.rowid "
                        "WHERE songs_fts MATCH ? "
                        "ORDER BY songs.artist COLLATE NOCASE, songs.album COLLATE NOCASE, "
                        "songs.title COLLATE NOCASE LIMIT ?",
                        (match, limit)
                    ).fetchall()
                    return array('q', (r["id"] for r in rows))
                except sqlite3.OperationalError:
                    pass  # fall through to LIKE

        like = f"%{query}%"
        rows = conn.execute(
            "SELECT id FROM songs WHERE title LIKE ? OR artist LIKE ? OR album LIKE ? "
            "OR path LIKE ? ORDER BY artist COLLATE NOCASE, album COLLATE NOCASE, "
            "title COLLATE NOCASE LIMIT ?",
            (like, like, like, like, limit)
        ).fetchall()
        return array('q', (r["id"] for r in rows))

    def get_path(self, song_id):
        """
        Returns the real, playable file path. For cue-sheet tracks this is
        the underlying whole-album file (their `path` column is a synthetic
        per-track key, not an openable file). Falls back to `path` itself
        for rows written before the audio_path column existed.
        """
        row = self._conn().execute(
            "SELECT path, audio_path FROM songs WHERE id=?", (song_id,)).fetchone()
        if not row:
            return None
        return row["audio_path"] or row["path"]

    def get_song(self, song_id):
        row = self._conn().execute(
            "SELECT id, path, title, artist, album, duration, "
            "audio_path, cue_start, cue_end FROM songs WHERE id=?",
            (song_id,)).fetchone()
        return dict(row) if row else None

    def get_songs(self, ids):
        """Batch metadata lookup for a small slice of ids (e.g. one page)."""
        ids = list(ids)
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        rows = self._conn().execute(
            f"SELECT id, path, title, artist, album, duration, "
            f"audio_path, cue_start, cue_end FROM songs "
            f"WHERE id IN ({placeholders})", ids
        ).fetchall()
        return {r["id"]: dict(r) for r in rows}
