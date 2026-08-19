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
from array import array

from . import cue as cuesheet
from .db_index import BATCH_SIZE, DirCache, ScanSession, TagReaderPool
from .media_types import (
    AUDIO_EXTS,
    CUE_EXTS,
    LIBRARY_EXTS,
    MEDIA_EXTS,
    PLAYLIST_EXTS,
    is_media_path,
)

# Re-export for modules that still import from db.
__all__ = [
    "AUDIO_EXTS", "MEDIA_EXTS", "LIBRARY_EXTS", "PLAYLIST_EXTS", "CUE_EXTS",
    "Library", "is_media_path",
]

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

CREATE TABLE IF NOT EXISTS dir_index (
    dir_path    TEXT PRIMARY KEY,
    dir_mtime   REAL NOT NULL,
    file_count  INTEGER NOT NULL,
    names_sig   TEXT NOT NULL,
    content_sig TEXT NOT NULL DEFAULT '',
    scanned_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_meta (
    root_path       TEXT PRIMARY KEY,
    last_scan_at    REAL,
    last_scan_found INTEGER,
    scan_generation INTEGER NOT NULL DEFAULT 0
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


def normalize_path(path: str) -> str:
    """Canonical path key — prevents duplicate rows for E:/foo vs E:\\foo."""
    if not path:
        return path
    if "::cue" in path:
        base, _, suffix = path.partition("::cue")
        return normalize_path(base) + "::cue" + suffix
    return os.path.normcase(os.path.normpath(path))


def _read_tags(path):
    """Read title/artist/album/duration for one file. Never raises."""
    title = artist = album = None
    duration = 0.0
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(path, easy=True)
        if audio is None:
            audio = MutagenFile(path)
        if audio is not None:
            tags = getattr(audio, "tags", None)
            if tags:
                try:
                    if "title" in tags:
                        title = tags["title"][0]
                    if "artist" in tags:
                        artist = tags["artist"][0]
                    if "album" in tags:
                        album = tags["album"][0]
                except (TypeError, KeyError, IndexError):
                    pass
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
        if "scan_gen" not in existing_cols:
            conn.execute("ALTER TABLE songs ADD COLUMN scan_gen INTEGER")
        conn.commit()

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_songs_sort ON songs("
            "artist COLLATE NOCASE, album COLLATE NOCASE, title COLLATE NOCASE)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_songs_scan_gen ON songs(scan_gen)")
        conn.commit()

        dir_cols = {row["name"] for row in conn.execute("PRAGMA table_info(dir_index)")}
        if dir_cols and "content_sig" not in dir_cols:
            conn.execute("ALTER TABLE dir_index ADD COLUMN content_sig TEXT NOT NULL DEFAULT ''")
            conn.commit()

        if self.get_setting("library_paths_normalized") != "2":
            self._dedupe_paths_by_normalization()
            self.set_setting("library_paths_normalized", "2")
            conn.execute("DELETE FROM dir_index")
            conn.commit()

        try:
            conn.executescript(FTS_SCHEMA)
            self._has_fts = True
        except sqlite3.OperationalError:
            # FTS5 not available in this SQLite build — fall back to LIKE.
            self._has_fts = False
        conn.commit()

    def _dedupe_paths_by_normalization(self):
        """Merge rows that differ only by slash/case (E:/music vs E:\\music)."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT id, path, scan_gen FROM songs ORDER BY id"
        ).fetchall()
        buckets: dict[str, list] = {}
        for row in rows:
            key = normalize_path(row["path"])
            buckets.setdefault(key, []).append(row)

        removed = 0
        updated = 0
        for key, group in buckets.items():
            if len(group) == 1:
                row = group[0]
                if row["path"] != key:
                    conn.execute("UPDATE songs SET path=? WHERE id=?", (key, row["id"]))
                    updated += 1
                continue
            group.sort(key=lambda r: ((r["scan_gen"] or 0), r["id"]), reverse=True)
            keep = group[0]
            conn.execute("UPDATE songs SET path=? WHERE id=?", (key, keep["id"]))
            updated += 1
            for row in group[1:]:
                conn.execute("DELETE FROM songs WHERE id=?", (row["id"],))
                removed += 1
        if removed or updated:
            conn.commit()
            if removed:
                print(f"[Library] Removed {removed} duplicate path entries")

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

    def index_cue_sheet(self, cue_path):
        """
        Parse one .cue sheet and index each track it describes as its own
        library row (synthetic path, real audio_path + cue_start/cue_end
        window into the shared audio file). Standalone and non-destructive
        (no scan_seen bookkeeping, no deletion of unrelated rows) — safe
        to call from a full scan() *or* directly from the live auto-index
        watcher when a .cue (or its paired audio file) changes.

        Returns (indexed_paths, claimed_audio_paths):
          indexed_paths       — synthetic `songs.path` values written
          claimed_audio_paths — real, absolute paths of the audio file(s)
                                 this cue sheet successfully claimed
        """
        conn = self._conn()
        dirpath = os.path.dirname(cue_path)
        try:
            filenames_lower = {f.lower(): f for f in os.listdir(dirpath)}
        except OSError:
            return [], set()

        try:
            cue_tracks = cuesheet.parse_cue(cue_path)
        except Exception:
            cue_tracks = []
        if not cue_tracks:
            return [], set()

        by_file = {}
        for t in cue_tracks:
            by_file.setdefault(t["file"], []).append(t)

        indexed_paths = []
        claimed_audio_paths = set()

        for ref_name, tlist in by_file.items():
            real_name = filenames_lower.get(os.path.basename(ref_name).lower())
            if not real_name:
                continue  # referenced audio file isn't next to the cue sheet
            audio_path = normalize_path(os.path.join(dirpath, real_name))
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
                indexed_paths.append(synth_path)
            claimed_audio_paths.add(audio_path)

        if indexed_paths:
            conn.commit()
        return indexed_paths, claimed_audio_paths

    def invalidate_dirs_for_paths(self, paths):
        """Drop dir fingerprint cache so the next scan re-checks those folders."""
        DirCache(self._conn()).invalidate_for_paths(paths)

    def get_scan_meta(self, root: str):
        row = self._conn().execute(
            "SELECT last_scan_at, last_scan_found, scan_generation FROM scan_meta WHERE root_path=?",
            (os.path.abspath(root),),
        ).fetchone()
        return dict(row) if row else None

    def _existing_meta_for_paths(self, conn, paths):
        if not paths:
            return {}
        placeholders = ",".join("?" * len(paths))
        rows = conn.execute(
            f"SELECT path, mtime, size FROM songs WHERE path IN ({placeholders})",
            paths,
        ).fetchall()
        return {r["path"]: (r["mtime"], r["size"]) for r in rows}

    def quick_scan(self, root, progress_cb=None, stop_event=None, workers=6):
        """Fast incremental scan — skips directories whose listing hasn't changed."""
        return self._run_scan(root, progress_cb, stop_event, workers, use_dir_cache=True)

    def scan(self, root, progress_cb=None, stop_event=None, workers=6, full=False):
        """
        Index `root`. Default uses directory cache for speed; pass full=True
        to rebuild the cache and walk every folder (Rescan Now).
        """
        return self._run_scan(
            root, progress_cb, stop_event, workers, use_dir_cache=not full
        )

    def _run_scan(self, root, progress_cb, stop_event, workers, *, use_dir_cache: bool):
        conn = self._conn()
        root = normalize_path(os.path.abspath(root))
        session = ScanSession(conn, root)
        dir_cache = DirCache(conn)
        pool = TagReaderPool(workers)
        found = 0
        updated = 0
        aborted = False

        def progress(stage=None):
            if progress_cb:
                progress_cb(found, updated, stage or root)

        try:
            for dirpath, _dirnames, filenames in os.walk(root):
                if stop_event and stop_event.is_set():
                    aborted = True
                    break

                try:
                    dir_stat = os.stat(dirpath)
                    dir_mtime = dir_stat.st_mtime
                except OSError:
                    continue

                if use_dir_cache and dir_cache.is_unchanged(dirpath, dir_mtime, filenames):
                    known = dir_cache.paths_known_in_dir(dirpath)
                    if known:
                        found += len(known)
                        session.mark_seen_many(known)
                    if progress_cb and found % 2000 == 0:
                        progress(dirpath)
                    continue

                claimed = set()
                for fn in filenames:
                    if stop_event and stop_event.is_set():
                        aborted = True
                        break
                    if not fn.lower().endswith(CUE_EXTS):
                        continue
                    cue_path = os.path.join(dirpath, fn)
                    indexed_paths, claimed_audio_paths = self.index_cue_sheet(cue_path)
                    for p in indexed_paths:
                        found += 1
                        updated += 1
                        session.mark_seen(p)
                    claimed |= {os.path.basename(p).lower() for p in claimed_audio_paths}
                session.flush_seen()
                if aborted:
                    break

                dir_paths = []
                dir_entries = []
                for fn in filenames:
                    if not fn.lower().endswith(LIBRARY_EXTS):
                        continue
                    if fn.lower() in claimed:
                        continue
                    path = normalize_path(os.path.join(dirpath, fn))
                    dir_entries.append(path)
                    dir_paths.append(path)

                existing = self._existing_meta_for_paths(conn, dir_paths)

                for path in dir_entries:
                    if stop_event and stop_event.is_set():
                        aborted = True
                        break
                    try:
                        st = os.stat(path)
                    except OSError:
                        continue

                    found += 1
                    session.mark_seen(path)

                    row = existing.get(path)
                    unchanged = (
                        row is not None
                        and row[1] == st.st_size
                        and abs((row[0] or 0) - st.st_mtime) < 1.0
                    )
                    if not unchanged:
                        pool.submit(path, st.st_size, st.st_mtime)

                    if len(session.seen_batch) >= BATCH_SIZE:
                        session.flush_seen()
                    if progress_cb and found % 500 == 0:
                        progress(dirpath)

                updated += pool.pending_results(conn, scan_gen=session.generation)
                session.flush_seen()
                if aborted:
                    break

                dir_cache.save(dirpath, dir_mtime, filenames)

            updated += pool.close(conn, scan_gen=session.generation)
            session.finish(found=found, updated=updated, aborted=aborted)
        except Exception:
            pool.close(conn, scan_gen=session.generation)
            raise

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
        paths = [normalize_path(p) for p in paths if is_media_path(p)]
        if not paths:
            return 0

        conn = self._conn()
        to_read = []
        for path in paths:
            try:
                st = os.stat(path)
            except OSError:
                continue
            row = conn.execute(
                "SELECT mtime, size FROM songs WHERE path=?", (path,)
            ).fetchone()
            unchanged = (
                row is not None
                and row["size"] == st.st_size
                and abs((row["mtime"] or 0) - st.st_mtime) < 1.0
            )
            if unchanged:
                continue
            to_read.append((path, st.st_size, st.st_mtime))

        if not to_read:
            return 0

        if len(to_read) == 1:
            path, size, mtime = to_read[0]
            title, artist, album, duration = _read_tags(path)
            conn.execute(
                "INSERT INTO songs(path, title, artist, album, duration, size, mtime, audio_path) "
                "VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET "
                "title=excluded.title, artist=excluded.artist, album=excluded.album, "
                "duration=excluded.duration, size=excluded.size, mtime=excluded.mtime, "
                "audio_path=excluded.audio_path",
                (path, title, artist, album, duration, size, mtime, path),
            )
            conn.commit()
            return 1

        pool = TagReaderPool(workers=min(4, len(to_read)))
        for path, size, mtime in to_read:
            pool.submit(path, size, mtime)
        updated = pool.close(conn)
        return updated

    def remove_paths(self, paths):
        """Remove specific files by path (e.g. after a delete/move-away
        event). Returns count removed."""
        paths = [normalize_path(p) for p in paths]
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
