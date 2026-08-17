"""
Clipboard Manager — core logic.

ClipboardStore holds the history in a SQLite database (indexed, appends
are cheap regardless of history size — unlike the earlier JSON version,
which rewrote the entire file on every single copy). `ClipboardMonitor`
polls the system clipboard on a Tk `.after()` loop and feeds new content
into the store.

Important: the monitor must be scheduled against a widget that outlives
the module's own frame (i.e. `manager.container`, the root App instance —
per the shared convention), not `self` inside the module frame. If it's
scheduled on the frame, history capture stops the moment the user
navigates to a different page, which defeats the point of a clipboard
manager. See ui.py for how this is wired up.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

try:
    # Project convention: user-data lives under %APPDATA%\ZsMultiTool\
    # via core/paths.py. Adjust this import if your helper is named
    # differently — falling back below keeps this module usable standalone.
    from core.paths import get_data_dir  # type: ignore
except ImportError:  # pragma: no cover - fallback for standalone use/testing
    def get_data_dir() -> Path:
        import os
        base = Path(os.environ.get("APPDATA", Path.home())) / "ZsMultiTool"
        base.mkdir(parents=True, exist_ok=True)
        return base

HISTORY_DB_FILENAME = "clipboard_history.db"
SETTINGS_FILENAME = "clipboard_settings.json"
MAX_ITEMS_DEFAULT = 200
POLL_INTERVAL_DEFAULT_MS = 600
MAX_PREVIEW_CHARS = 4000  # trim absurdly large clipboard captures (e.g. whole files)

MIN_MAX_ITEMS = 10
MAX_MAX_ITEMS = 2000
UNLIMITED = -1  # sentinel for "no cap" on max_items
POLL_INTERVAL_CHOICES_MS = (250, 500, 1000, 2000)


def _clamp_max_items(value: int) -> int:
    if value == UNLIMITED:
        return UNLIMITED
    return max(MIN_MAX_ITEMS, min(MAX_MAX_ITEMS, value))


@dataclass
class ClipboardSettings:
    max_items: int = MAX_ITEMS_DEFAULT
    poll_interval_ms: int = POLL_INTERVAL_DEFAULT_MS
    capture_enabled: bool = True
    path: Path = field(default=None, repr=False, compare=False)  # type: ignore[assignment]

    @staticmethod
    def load(path: Path | None = None) -> "ClipboardSettings":
        path = path or (get_data_dir() / SETTINGS_FILENAME)
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                return ClipboardSettings(
                    max_items=_clamp_max_items(raw.get("max_items", MAX_ITEMS_DEFAULT)),
                    poll_interval_ms=raw.get("poll_interval_ms", POLL_INTERVAL_DEFAULT_MS),
                    capture_enabled=raw.get("capture_enabled", True),
                    path=path,
                )
            except (json.JSONDecodeError, OSError):
                pass
        return ClipboardSettings(path=path)

    def save(self) -> None:
        path = self.path or (get_data_dir() / SETTINGS_FILENAME)
        try:
            path.write_text(
                json.dumps({
                    "max_items": self.max_items,
                    "poll_interval_ms": self.poll_interval_ms,
                    "capture_enabled": self.capture_enabled,
                }, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass


@dataclass
class ClipboardEntry:
    id: str
    text: str
    timestamp: float
    pinned: bool = False

    @staticmethod
    def _from_row(row: sqlite3.Row) -> "ClipboardEntry":
        return ClipboardEntry(
            id=row["id"], text=row["text"], timestamp=row["timestamp"],
            pinned=bool(row["pinned"]),
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id        TEXT PRIMARY KEY,
    text      TEXT NOT NULL,
    timestamp REAL NOT NULL,
    pinned    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_entries_timestamp ON entries (timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_entries_pinned ON entries (pinned);
"""


class ClipboardStore:
    """SQLite-backed history. Ordered newest-first by timestamp."""

    def __init__(self, max_items: int = MAX_ITEMS_DEFAULT, path: Path | None = None):
        self.max_items = max_items
        self.path = path or (get_data_dir() / HISTORY_DB_FILENAME)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------- mutation

    def add(self, text: str) -> ClipboardEntry | None:
        """Add a new clipboard capture. Returns None if it's a no-op
        (empty, or identical to the most recent entry)."""
        if not text or not text.strip():
            return None
        if len(text) > MAX_PREVIEW_CHARS:
            text = text[:MAX_PREVIEW_CHARS] + "\n… (truncated)"

        row = self._conn.execute(
            "SELECT text FROM entries ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if row is not None and row["text"] == text:
            return None  # same as most recent — don't spam duplicates

        entry = ClipboardEntry(id=str(uuid.uuid4()), text=text, timestamp=time.time())
        self._conn.execute(
            "INSERT INTO entries (id, text, timestamp, pinned) VALUES (?, ?, ?, 0)",
            (entry.id, entry.text, entry.timestamp),
        )
        self._conn.commit()
        self._trim()
        return entry

    def toggle_pin(self, entry_id: str) -> None:
        self._conn.execute(
            "UPDATE entries SET pinned = 1 - pinned WHERE id = ?", (entry_id,)
        )
        self._conn.commit()

    def delete(self, entry_id: str) -> None:
        self._conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        self._conn.commit()

    def clear_unpinned(self) -> None:
        self._conn.execute("DELETE FROM entries WHERE pinned = 0")
        self._conn.commit()

    def clear_all(self) -> None:
        self._conn.execute("DELETE FROM entries")
        self._conn.commit()

    def set_max_items(self, max_items: int) -> None:
        self.max_items = _clamp_max_items(max_items)
        self._trim()

    def _trim(self) -> None:
        if self.max_items == UNLIMITED:
            return  # no cap — keep everything

        pinned_count = self._conn.execute(
            "SELECT COUNT(*) FROM entries WHERE pinned = 1"
        ).fetchone()[0]
        budget = max(self.max_items - pinned_count, 0)

        unpinned_count = self._conn.execute(
            "SELECT COUNT(*) FROM entries WHERE pinned = 0"
        ).fetchone()[0]
        excess = unpinned_count - budget
        if excess > 0:
            self._conn.execute(
                """
                DELETE FROM entries WHERE id IN (
                    SELECT id FROM entries WHERE pinned = 0
                    ORDER BY timestamp ASC LIMIT ?
                )
                """,
                (excess,),
            )
            self._conn.commit()

    # ---------------------------------------------------------------- query

    def search(self, query: str) -> list[ClipboardEntry]:
        if not query:
            rows = self._conn.execute(
                "SELECT * FROM entries ORDER BY timestamp DESC"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM entries WHERE text LIKE ? ESCAPE '\\' ORDER BY timestamp DESC",
                (f"%{_escape_like(query)}%",),
            ).fetchall()
        return [ClipboardEntry._from_row(r) for r in rows]


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ClipboardMonitor:
    """Polls the system clipboard via a Tk widget's `.after()` loop.

    Schedule this against the root/container widget, not a module frame,
    so it keeps running when the user navigates to a different page.
    """

    def __init__(self, root_widget, store: ClipboardStore, on_change=None, interval_ms: int = 600):
        self.root_widget = root_widget
        self.store = store
        self.on_change = on_change
        self.interval_ms = interval_ms
        self._last_seen: str | None = None
        self._running = False
        self._after_id = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        # Seed with current clipboard so we don't immediately re-capture
        # whatever was already on it as a "new" entry.
        self._last_seen = self._read_clipboard()
        self._schedule()

    def stop(self) -> None:
        self._running = False
        if self._after_id is not None:
            try:
                self.root_widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None

    def is_running(self) -> bool:
        return self._running

    def set_interval(self, interval_ms: int) -> None:
        self.interval_ms = interval_ms

    def _schedule(self) -> None:
        if not self._running:
            return
        self._after_id = self.root_widget.after(self.interval_ms, self._tick)

    def _read_clipboard(self) -> str | None:
        try:
            return self.root_widget.clipboard_get()
        except Exception:
            # Empty clipboard or non-text content (e.g. an image) raises here.
            return None

    def _tick(self) -> None:
        current = self._read_clipboard()
        if current is not None and current != self._last_seen:
            self._last_seen = current
            entry = self.store.add(current)
            if entry is not None and self.on_change is not None:
                self.on_change(entry)
        self._schedule()
