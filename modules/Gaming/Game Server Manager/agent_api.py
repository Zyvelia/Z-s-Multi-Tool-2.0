"""GUI-free helpers the in-app agent uses for Game Server Manager."""

from __future__ import annotations

from pathlib import Path

from . import runtime
from .adapters import get_adapter
from .core.settings import load_servers
from .server_files import create_backup_zip


def load_servers_safe() -> list[dict]:
    rows = []
    for srv in load_servers():
        snap = runtime.snapshot(srv.get("id", ""))
        rows.append({
            "id": srv.get("id"),
            "name": srv.get("name"),
            "game_type": srv.get("game_type"),
            "server_dir": srv.get("server_dir"),
            "running": snap["running"],
            "ready": snap.get("ready", False),
            "players": snap["players"],
        })
    return rows


def find_server(query: str) -> tuple[dict | None, str | None]:
    q = (query or "").strip().lower()
    servers = load_servers()
    if not servers:
        return None, "No game servers saved yet. Add one in Game Server Manager first."
    if not q:
        return None, "Say which server (name, id, or game)."

    for srv in servers:
        if str(srv.get("id", "")).lower() == q or str(srv.get("name", "")).lower() == q:
            return srv, None

    matches = [
        srv for srv in servers
        if q in str(srv.get("name", "")).lower()
        or q in str(srv.get("game_type", "")).lower()
        or q in str(srv.get("id", "")).lower()
    ]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        names = ", ".join(str(s.get("name") or s.get("id")) for s in matches)
        return None, f"Multiple matches: {names}. Be more specific."
    return None, f"No server matching {query!r}."


def status_payload(srv: dict) -> dict:
    snap = runtime.snapshot(srv.get("id", ""))
    return {
        "id": srv.get("id"),
        "name": srv.get("name"),
        "game_type": srv.get("game_type"),
        "server_dir": srv.get("server_dir"),
        "running": snap["running"],
        "ready": snap.get("ready", False),
        "players": snap["players"],
        "started_at": snap.get("started_at"),
    }


def start_server(srv: dict) -> dict:
    adapter = get_adapter(srv.get("game_type", ""))
    if adapter is None:
        return {"ok": False, "error": f"Unknown game type: {srv.get('game_type')}"}
    proc = runtime.get_process(srv["id"])
    if proc.running:
        return {"ok": True, "already_running": True, "name": srv.get("name")}
    try:
        from core.services.resource_governor import allow_start
        ok, reason = allow_start("game_server", srv.get("name") or "server")
        if not ok:
            return {"ok": False, "error": reason, "name": srv.get("name")}
    except Exception:
        pass
    root = Path(srv.get("server_dir") or "")
    if not root.is_dir():
        return {"ok": False, "error": f"Server folder is missing: {root}"}
    error = proc.start(root, dict(srv.get("config") or {}), adapter)
    if error:
        return {"ok": False, "error": error, "name": srv.get("name")}
    return {"ok": True, "started": True, "name": srv.get("name"), "game_type": srv.get("game_type")}


def stop_server(srv: dict) -> dict:
    proc = runtime.get_process(srv["id"])
    if not proc.running:
        return {"ok": True, "already_stopped": True, "name": srv.get("name")}
    runtime.mark_expected_stop(srv["id"])
    proc.stop(graceful=True)
    return {"ok": True, "stopped": True, "name": srv.get("name")}


def wait_until_ready(srv: dict, timeout_seconds: float = 180) -> dict:
    """Block until the process logs ready, the game port accepts a TCP
    connect, the process dies, or timeout. Does not start the server."""
    import time

    timeout = max(5.0, min(float(timeout_seconds or 180), 600.0))
    deadline = time.time() + timeout
    adapter = get_adapter(srv.get("game_type", ""))
    port = _listen_port(srv, adapter)
    proto = adapter.port_protocol() if adapter else "TCP"

    while time.time() < deadline:
        snap = runtime.snapshot(srv.get("id", ""))
        if snap.get("ready"):
            return {"ok": True, "ready": True, "how": "log", "name": srv.get("name"), "port": port}
        if not snap.get("running"):
            return {"ok": False, "ready": False, "error": "Server process is not running.", "name": srv.get("name")}
        if port and proto.upper() == "TCP" and _tcp_open(port):
            return {"ok": True, "ready": True, "how": "tcp", "name": srv.get("name"), "port": port}
        time.sleep(1.0)

    return {
        "ok": False,
        "ready": False,
        "error": f"Timed out after {int(timeout)}s waiting for {srv.get('name')}.",
        "name": srv.get("name"),
        "port": port,
    }


def _listen_port(srv: dict, adapter) -> int | None:
    cfg = srv.get("config") or {}
    for key in ("port", "query_port", "game_port"):
        raw = str(cfg.get(key) or "").strip()
        if raw.isdigit():
            return int(raw)
    if adapter is None:
        return None
    try:
        return int(adapter.default_port())
    except (TypeError, ValueError):
        return None


def _tcp_open(port: int) -> bool:
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.4)
    try:
        sock.connect(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def send_console(srv: dict, command: str) -> dict:
    command = (command or "").strip()
    if not command:
        return {"ok": False, "error": "command required"}
    proc = runtime.get_process(srv["id"])
    if not proc.running:
        return {"ok": False, "error": "Server is not running."}
    if not proc.send(command):
        return {"ok": False, "error": "Could not write to the console."}
    return {"ok": True, "sent": command, "name": srv.get("name")}


def backup_server(srv: dict) -> dict:
    root = Path(srv.get("server_dir") or "")
    keep = int((srv.get("config") or {}).get("backup_keep_count", 5) or 5)
    try:
        zip_path = create_backup_zip(root, str(srv.get("name") or "server"), keep=keep)
    except OSError as e:
        return {"ok": False, "error": str(e), "name": srv.get("name")}
    return {"ok": True, "backup": zip_path.name, "path": str(zip_path), "name": srv.get("name")}
