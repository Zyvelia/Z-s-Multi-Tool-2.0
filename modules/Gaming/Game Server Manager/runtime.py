"""
Shared live-process map for Game Server Manager.

The desktop UI and the in-app agent must start/stop the same
ServerProcess instance for a given server id, or they will fight.
"""

from __future__ import annotations

import threading
from .core.process import ServerProcess

_lock = threading.Lock()
_processes: dict[str, ServerProcess] = {}
_expected_stops: set[str] = set()


def mark_expected_stop(server_id: str) -> None:
    if server_id:
        with _lock:
            _expected_stops.add(server_id)


def consume_expected_stop(server_id: str) -> bool:
    with _lock:
        if server_id in _expected_stops:
            _expected_stops.discard(server_id)
            return True
    return False


def get_process(server_id: str) -> ServerProcess:
    if not server_id:
        return ServerProcess()
    with _lock:
        proc = _processes.get(server_id)
        if proc is None:
            proc = ServerProcess()
            _processes[server_id] = proc
        return proc


def discard_process(server_id: str) -> None:
    with _lock:
        _processes.pop(server_id, None)


def is_running(server_id: str) -> bool:
    with _lock:
        proc = _processes.get(server_id)
    return bool(proc and proc.running)


def snapshot(server_id: str) -> dict:
    with _lock:
        proc = _processes.get(server_id)
    if proc is None:
        return {"running": False, "ready": False, "players": []}
    return {
        "running": bool(proc.running),
        "ready": bool(proc.ready),
        "players": sorted(proc.players),
        "started_at": proc.started_at,
    }
