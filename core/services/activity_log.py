"""
In-app activity + notification feed for the Now screen.

Agent calls, watchdog crashes/retries, and Hub actions land here.
Newest first. Capped and persisted so a restart doesn't wipe the board.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from core import paths

MAX_EVENTS = 80
_FILE = Path(paths.data_path("activity", "log.json"))

_lock = threading.Lock()
_events: list[dict] = []
_loaded = False
_listeners: list = []


def _ensure_loaded() -> None:
    global _loaded, _events
    if _loaded:
        return
    _loaded = True
    try:
        if _FILE.is_file():
            data = json.loads(_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                _events = [e for e in data if isinstance(e, dict)][:MAX_EVENTS]
    except (OSError, json.JSONDecodeError):
        _events = []


def _save() -> None:
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        _FILE.write_text(json.dumps(_events[:MAX_EVENTS], indent=2), encoding="utf-8")
    except OSError:
        pass


def add(kind: str, title: str, detail: str = "", level: str = "info") -> dict:
    """kind: agent | crash | retry | hub | notify. level: info | warn | error | ok."""
    _ensure_loaded()
    event = {
        "ts": time.time(),
        "kind": kind,
        "title": title,
        "detail": detail or "",
        "level": level,
        "read": False,
    }
    with _lock:
        _events.insert(0, event)
        del _events[MAX_EVENTS:]
        _save()
        listeners = list(_listeners)
    for cb in listeners:
        try:
            cb(event)
        except Exception:
            pass
    return event


def recent(limit: int = 30) -> list[dict]:
    _ensure_loaded()
    with _lock:
        return list(_events[:limit])


def unread_count() -> int:
    _ensure_loaded()
    with _lock:
        return sum(1 for e in _events if not e.get("read"))


def mark_all_read() -> None:
    _ensure_loaded()
    with _lock:
        for event in _events:
            event["read"] = True
        _save()


def subscribe(callback) -> None:
    with _lock:
        if callback not in _listeners:
            _listeners.append(callback)
