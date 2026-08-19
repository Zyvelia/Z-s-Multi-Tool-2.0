# music_player/db_index.py
#
# Fast indexing helpers used by db.Library — directory fingerprint cache,
# scan-generation orphan cleanup, and a shared mutagen worker pool.

from __future__ import annotations

import hashlib
import os
import queue
import threading
import time

BATCH_SIZE = 500


def dir_content_sig(dirpath: str, filenames) -> str:
    """Fingerprint audio/cue files by name + size + mtime (no tag reads)."""
    from . import db as musicdb
    parts = []
    for fn in sorted(filenames):
        if not fn.lower().endswith(musicdb.LIBRARY_EXTS + musicdb.CUE_EXTS):
            continue
        path = os.path.join(dirpath, fn)
        try:
            st = os.stat(path)
            parts.append(f"{fn.lower()}:{st.st_size}:{int(st.st_mtime)}")
        except OSError:
            parts.append(f"{fn.lower()}:missing")
    if not parts:
        return ""
    return hashlib.md5("|".join(parts).encode("utf-8", "ignore")).hexdigest()


def dir_names_sig(filenames) -> tuple[int, str]:
    """Legacy helper — count + filename-only sig."""
    from . import db as musicdb
    relevant = sorted(
        fn.lower() for fn in filenames
        if fn.lower().endswith(musicdb.LIBRARY_EXTS + musicdb.CUE_EXTS)
    )
    if not relevant:
        return 0, ""
    digest = hashlib.md5("\0".join(relevant).encode("utf-8", "ignore")).hexdigest()
    return len(relevant), digest


def path_prefix_like(dirpath: str) -> str:
    """LIKE prefix for all song paths under a directory (Windows-safe)."""
    from .db import normalize_path
    prefix = normalize_path(dirpath).rstrip(os.sep) + os.sep
    return prefix.replace("\\", "\\\\") + "%"


class TagReaderPool:
    """Background mutagen readers — keeps the network/filesystem busy in parallel."""

    def __init__(self, workers: int = 6):
        self._work_q: queue.Queue = queue.Queue(maxsize=4000)
        self._result_q: queue.Queue = queue.Queue()
        self._sentinel = object()
        self._threads = [
            threading.Thread(target=self._worker, daemon=True)
            for _ in range(max(1, workers))
        ]
        for t in self._threads:
            t.start()

    def _worker(self):
        from .db import _read_tags
        while True:
            item = self._work_q.get()
            if item is self._sentinel:
                self._work_q.task_done()
                return
            path, size, mtime = item
            title, artist, album, duration = _read_tags(path)
            self._result_q.put((title, artist, album, duration, size, mtime, path))
            self._work_q.task_done()

    def submit(self, path: str, size: int, mtime: float):
        self._work_q.put((path, size, mtime))

    def pending_results(self, conn, *, scan_gen: int | None, force: bool = False) -> int:
        batch = []
        while True:
            try:
                batch.append(self._result_q.get_nowait())
            except queue.Empty:
                break
            if not force and len(batch) >= BATCH_SIZE:
                break
        if not batch:
            return 0
        if scan_gen is not None:
            conn.executemany(
                "INSERT INTO songs(path, title, artist, album, duration, size, mtime, "
                "audio_path, scan_gen) VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET "
                "title=excluded.title, artist=excluded.artist, album=excluded.album, "
                "duration=excluded.duration, size=excluded.size, mtime=excluded.mtime, "
                "audio_path=excluded.audio_path, scan_gen=excluded.scan_gen",
                [(p, t, ar, al, d, s, m, p, scan_gen) for (t, ar, al, d, s, m, p) in batch],
            )
        else:
            conn.executemany(
                "INSERT INTO songs(path, title, artist, album, duration, size, mtime, audio_path) "
                "VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(path) DO UPDATE SET "
                "title=excluded.title, artist=excluded.artist, album=excluded.album, "
                "duration=excluded.duration, size=excluded.size, mtime=excluded.mtime, "
                "audio_path=excluded.audio_path",
                [(p, t, ar, al, d, s, m, p) for (t, ar, al, d, s, m, p) in batch],
            )
        conn.commit()
        return len(batch)

    def close(self, conn, *, scan_gen: int | None = None) -> int:
        for _ in self._threads:
            self._work_q.put(self._sentinel)
        for t in self._threads:
            t.join()
        return self.pending_results(conn, scan_gen=scan_gen, force=True)


class DirCache:
    """Skip unchanged directories during incremental scans."""

    def __init__(self, conn):
        self._conn = conn

    def get(self, dirpath: str):
        return self._conn.execute(
            "SELECT dir_mtime, file_count, names_sig, content_sig FROM dir_index WHERE dir_path=?",
            (dirpath,),
        ).fetchone()

    def is_unchanged(self, dirpath: str, dir_mtime: float, filenames) -> bool:
        row = self.get(dirpath)
        if row is None:
            return False
        count, _names = dir_names_sig(filenames)
        content_sig = dir_content_sig(dirpath, filenames)
        stored_sig = row["content_sig"] if "content_sig" in row.keys() else ""
        if stored_sig:
            return stored_sig == content_sig
        # Legacy rows without content_sig — fall back to name + mtime check.
        return (
            row["file_count"] == count
            and row["names_sig"] == _names
            and abs((row["dir_mtime"] or 0) - dir_mtime) < 1.0
        )

    def save(self, dirpath: str, dir_mtime: float, filenames):
        count, names = dir_names_sig(filenames)
        content_sig = dir_content_sig(dirpath, filenames)
        now = time.time()
        self._conn.execute(
            "INSERT INTO dir_index(dir_path, dir_mtime, file_count, names_sig, content_sig, scanned_at) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(dir_path) DO UPDATE SET "
            "dir_mtime=excluded.dir_mtime, file_count=excluded.file_count, "
            "names_sig=excluded.names_sig, content_sig=excluded.content_sig, "
            "scanned_at=excluded.scanned_at",
            (dirpath, dir_mtime, count, names, content_sig, now),
        )

    def invalidate(self, dirpath: str):
        self._conn.execute("DELETE FROM dir_index WHERE dir_path=?", (dirpath,))

    def invalidate_for_paths(self, paths):
        from .db import normalize_path
        dirs = {normalize_path(os.path.dirname(p)) for p in paths if p}
        if not dirs:
            return
        self._conn.executemany(
            "DELETE FROM dir_index WHERE dir_path=?", [(d,) for d in dirs]
        )
        self._conn.commit()

    def paths_known_in_dir(self, dirpath: str) -> list[str]:
        like = path_prefix_like(dirpath)
        rows = self._conn.execute(
            "SELECT path FROM songs WHERE path LIKE ? ESCAPE '\\'", (like,)
        ).fetchall()
        return [r["path"] for r in rows]


class ScanSession:
    """Tracks one scan pass — generation-based orphan cleanup."""

    def __init__(self, conn, root: str):
        from .db import normalize_path
        self.conn = conn
        self.root = normalize_path(root)
        self.root_like = path_prefix_like(self.root)
        row = conn.execute(
            "SELECT scan_generation FROM scan_meta WHERE root_path=?", (self.root,)
        ).fetchone()
        self.generation = (row["scan_generation"] if row else 0) + 1
        self.seen_batch: list[str] = []

    def flush_seen(self, force: bool = False):
        if self.seen_batch and (force or len(self.seen_batch) >= BATCH_SIZE):
            self.conn.executemany(
                "UPDATE songs SET scan_gen=? WHERE path=?",
                [(self.generation, p) for p in self.seen_batch],
            )
            self.seen_batch.clear()

    def mark_seen(self, path: str):
        self.seen_batch.append(path)

    def mark_seen_many(self, paths: list[str]):
        if not paths:
            return
        self.conn.executemany(
            "UPDATE songs SET scan_gen=? WHERE path=?",
            [(self.generation, p) for p in paths],
        )

    def finish(self, *, found: int, updated: int, aborted: bool):
        self.flush_seen(force=True)
        if aborted:
            self.conn.commit()
            return
        self.conn.execute(
            "DELETE FROM songs WHERE (scan_gen IS NULL OR scan_gen != ?) "
            "AND path LIKE ? ESCAPE '\\'",
            (self.generation, self.root_like),
        )
        self.conn.execute(
            "INSERT INTO scan_meta(root_path, last_scan_at, last_scan_found, scan_generation) "
            "VALUES (?,?,?,?) "
            "ON CONFLICT(root_path) DO UPDATE SET "
            "last_scan_at=excluded.last_scan_at, "
            "last_scan_found=excluded.last_scan_found, "
            "scan_generation=excluded.scan_generation",
            (self.root, time.time(), found, self.generation),
        )
        self.conn.commit()
