"""In-process live AI client — key stays in memory, never on disk."""

from __future__ import annotations

import threading

_lock = threading.Lock()
_client = None
_source = "hosted"


def set_live(client, source: str) -> None:
    global _client, _source
    with _lock:
        _client = client
        _source = "local" if source == "local" else "hosted"


def live_client():
    with _lock:
        return _client


def live_source() -> str:
    with _lock:
        return _source
