"""
Local library index for the MangaDex module.

NOTE: this assumes `core.paths` exposes a way to get an AppData folder for a
module, same as the rest of the app (Media Player, Security Vault, etc. all
route through it). The exact helper name varies by app version, so this
tries a couple of common shapes and falls back to a local `%APPDATA%` path
if none of them exist -- swap `_resolve_data_dir()` for whatever your
`core/paths.py` actually calls it if this guesses wrong.
"""
import os
import sqlite3
import threading


def _resolve_data_dir() -> str:
    try:
        from core import paths as core_paths
        for attr in ("get_module_data_dir", "get_data_dir", "module_dir"):
            fn = getattr(core_paths, attr, None)
            if callable(fn):
                try:
                    return fn("MangaDex Reader")
                except TypeError:
                    return fn()
        for attr in ("DATA_DIR", "APP_DATA_DIR"):
            base = getattr(core_paths, attr, None)
            if base:
                return os.path.join(base, "MangaDex Reader")
    except ImportError:
        pass
    # Fallback: keep the module self-contained if core.paths isn't wired up yet.
    base = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "ZsMultiTool", "MangaDex Reader")
    return base


DATA_DIR = _resolve_data_dir()
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "library.db")
THUMB_CACHE_DIR = os.path.join(DATA_DIR, "cover_cache")
DOWNLOADS_ROOT = os.path.join(DATA_DIR, "Downloads")

_lock = threading.Lock()


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            chapter_id TEXT PRIMARY KEY,
            manga_id TEXT NOT NULL,
            manga_title TEXT NOT NULL,
            chapter_label TEXT NOT NULL,
            language TEXT,
            format TEXT,
            path TEXT NOT NULL,
            downloaded_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            manga_id TEXT PRIMARY KEY,
            manga_title TEXT NOT NULL,
            chapter_id TEXT,
            chapter_label TEXT,
            page_index INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    return conn


class Library:
    def __init__(self):
        self.conn = _connect()

    def record_download(self, manga_id, manga_title, chapter, fmt, path):
        with _lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO downloads "
                "(chapter_id, manga_id, manga_title, chapter_label, language, format, path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (chapter["id"], manga_id, manga_title, chapter.get("chapter") or "?",
                 chapter.get("language"), fmt, path),
            )
            self.conn.commit()

    def is_downloaded(self, chapter_id) -> bool:
        cur = self.conn.execute("SELECT 1 FROM downloads WHERE chapter_id = ?", (chapter_id,))
        return cur.fetchone() is not None

    def list_downloads(self):
        cur = self.conn.execute(
            "SELECT manga_id, chapter_id, manga_title, chapter_label, language, format, path, downloaded_at "
            "FROM downloads ORDER BY downloaded_at DESC"
        )
        return cur.fetchall()

    def save_progress(self, manga_id, manga_title, chapter_id, chapter_label, page_index):
        with _lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO progress "
                "(manga_id, manga_title, chapter_id, chapter_label, page_index, updated_at) "
                "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (manga_id, manga_title, chapter_id, chapter_label, page_index),
            )
            self.conn.commit()

    def get_progress(self, manga_id):
        cur = self.conn.execute(
            "SELECT chapter_id, chapter_label, page_index FROM progress WHERE manga_id = ?",
            (manga_id,),
        )
        return cur.fetchone()

    def recent_progress(self, limit=10):
        cur = self.conn.execute(
            "SELECT manga_id, manga_title, chapter_label, page_index, updated_at "
            "FROM progress ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        return cur.fetchall()
