"""
RAM/CPU budgets so VLC, Ollama, and dedicated servers do not stack blindly.

This does not kill processes. It reports hogs and can block a new game-server
start when the machine is already over the configured ceiling.
"""

from __future__ import annotations

import json
from pathlib import Path

from core import paths

_FILE = Path(paths.data_path("governor", "settings.json"))

DEFAULTS = {
    "enabled": True,
    "max_ram_percent": 85,
    "max_cpu_percent": 90,
    "block_server_starts": True,
}


def load() -> dict:
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            out = dict(DEFAULTS)
            out.update({k: data[k] for k in DEFAULTS if k in data})
            return out
    except (OSError, json.JSONDecodeError):
        pass
    return dict(DEFAULTS)


def save(data: dict) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    merged = dict(DEFAULTS)
    merged.update(data)
    _FILE.write_text(json.dumps(merged, indent=2), encoding="utf-8")


def snapshot() -> dict:
    import psutil

    vm = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=0.4)
    hogs = list_hogs()
    cfg = load()
    ram_pct = float(vm.percent)
    over = ram_pct >= float(cfg["max_ram_percent"]) or cpu >= float(cfg["max_cpu_percent"])
    return {
        "ram_percent": ram_pct,
        "ram_used_gb": vm.used / (1024 ** 3),
        "ram_total_gb": vm.total / (1024 ** 3),
        "cpu_percent": cpu,
        "over_budget": over,
        "hogs": hogs,
        "config": cfg,
    }


def list_hogs() -> list[dict]:
    import psutil

    names = {
        "ollama": "Ollama",
        "ollama.exe": "Ollama",
        "ffmpeg": "ffmpeg / transcode",
        "ffmpeg.exe": "ffmpeg / transcode",
        "vlc": "VLC",
        "vlc.exe": "VLC",
        "javaw.exe": "Java (likely a game server)",
        "java.exe": "Java (likely a game server)",
    }
    found: dict[str, dict] = {}
    try:
        from importlib import import_module
        gsm = import_module("modules.Gaming.Game Server Manager.agent_api")
        for srv in gsm.load_servers_safe():
            if srv.get("running"):
                found[f"gsm:{srv.get('id')}"] = {
                    "name": f"Game server · {srv.get('name')}",
                    "kind": "game_server",
                    "detail": srv.get("game_type") or "",
                    "rss_mb": 0,
                }
    except Exception:
        pass

    for proc in psutil.process_iter(["name", "memory_info"]):
        try:
            raw = (proc.info.get("name") or "").lower()
            label = names.get(raw)
            if not label:
                continue
            rss = 0
            mem = proc.info.get("memory_info")
            if mem is not None:
                rss = int(mem.rss / (1024 * 1024))
            key = label
            if key in found:
                found[key]["rss_mb"] = found[key].get("rss_mb", 0) + rss
            else:
                found[key] = {"name": label, "kind": raw, "detail": raw, "rss_mb": rss}
        except (psutil.Error, OSError):
            continue
    return sorted(found.values(), key=lambda h: h.get("rss_mb", 0), reverse=True)


def allow_start(kind: str, label: str = "") -> tuple[bool, str]:
    """Return (ok, reason). kind is informational (game_server, ollama, transcode)."""
    cfg = load()
    if not cfg.get("enabled"):
        return True, ""
    if kind == "game_server" and not cfg.get("block_server_starts"):
        return True, ""
    snap = snapshot()
    if not snap["over_budget"]:
        return True, ""
    who = label or kind
    return False, (
        f"Resource governor blocked {who}: "
        f"CPU {snap['cpu_percent']:.0f}% / RAM {snap['ram_percent']:.0f}% "
        f"(limits {cfg['max_cpu_percent']}% / {cfg['max_ram_percent']}%). "
        f"Stop a hog or raise the budget."
    )
