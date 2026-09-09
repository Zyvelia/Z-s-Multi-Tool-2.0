"""Timeline of GSM backups, Gaming Hub saves, VSS shadows, and app-data copies."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from core import paths


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def gsm_backups() -> list[dict]:
    rows = []
    try:
        from importlib import import_module
        api = import_module("modules.Gaming.Game Server Manager.agent_api")
        for srv in api.load_servers_safe():
            root = Path(srv.get("server_dir") or "")
            folder = root / "_backups"
            if not folder.is_dir():
                continue
            for zip_path in folder.glob("*.zip"):
                rows.append({
                    "kind": "gsm",
                    "title": f"{srv.get('name')} · {zip_path.name}",
                    "path": str(zip_path),
                    "target": str(root),
                    "ts": _mtime(zip_path),
                })
    except Exception:
        pass
    return rows


def hub_backups() -> list[dict]:
    root = Path(paths.data_path("gaming_hub", "backups"))
    rows = []
    if not root.is_dir():
        return rows
    for zip_path in root.rglob("*.zip"):
        rows.append({
            "kind": "hub",
            "title": f"Game save · {zip_path.name}",
            "path": str(zip_path),
            "target": "",
            "ts": _mtime(zip_path),
        })
    return rows


def appdata_snapshots() -> list[dict]:
    """Important live files you may want to copy off before a restore."""
    candidates = [
        ("Notes", Path(paths.data_path("notes", "data.json"))),
        ("Messages", Path(paths.data_path("messages", "data.json"))),
        ("Activity log", Path(paths.data_path("activity", "log.json"))),
        ("GSM servers.json", Path(paths.data_path("game_servers", "servers.json"))),
        ("Settings", Path(paths.data_path("settings.json"))),
        ("Media library (legacy)", Path(os.environ.get("APPDATA", "")) / "MusicPlayerApp" / "library.db"),
        ("MangaDex library", Path(paths.data_path("MangaDex Reader", "library.db"))),
    ]
    rows = []
    for title, path in candidates:
        if path.is_file():
            rows.append({
                "kind": "file",
                "title": title,
                "path": str(path),
                "target": str(path),
                "ts": _mtime(path),
            })
    return rows


def vss_shadows() -> list[dict]:
    rows = []
    try:
        proc = subprocess.run(
            ["vssadmin", "list", "shadows"],
            capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        text = proc.stdout or ""
    except Exception:
        return rows
    current: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("shadow copy id:"):
            if current.get("path"):
                rows.append(current)
            current = {
                "kind": "vss",
                "title": line,
                "path": "",
                "target": "",
                "ts": 0.0,
            }
        elif "creation time:" in line.lower():
            current["title"] = (current.get("title") or "VSS") + " · " + line.split(":", 1)[-1].strip()
        elif "shadow copy volume:" in line.lower() or "original volume:" in line.lower():
            current["path"] = line.split(":", 1)[-1].strip()
            current["target"] = current["path"]
    if current.get("path") or current.get("title"):
        rows.append(current)
    return rows[:40]


def timeline() -> list[dict]:
    rows = gsm_backups() + hub_backups() + appdata_snapshots() + vss_shadows()
    rows.sort(key=lambda r: r.get("ts") or 0, reverse=True)
    return rows


def copy_snapshot(src: str, dest_dir: str) -> Path:
    src_path = Path(src)
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    if src_path.is_file():
        out = dest / src_path.name
        shutil.copy2(src_path, out)
        return out
    raise FileNotFoundError(src)


def restore_gsm_zip(zip_path: str, server_dir: str) -> None:
    from importlib import import_module
    files = import_module("modules.Gaming.Game Server Manager.server_files")
    files.restore_backup_zip(Path(server_dir), Path(zip_path))


def format_ts(ts: float) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
