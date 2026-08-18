"""Persistent settings for the Game Server Manager."""

from __future__ import annotations

import json
from pathlib import Path

try:
    from core import paths  # type: ignore

    def _servers_file() -> Path:
        return Path(paths.data_path("game_servers", "servers.json"))

    def _legacy_minecraft_file() -> Path:
        return Path(paths.data_path("minecraft_server", "settings.json"))
except ImportError:  # pragma: no cover
    import os

    def _servers_file() -> Path:
        base = Path(os.environ.get("APPDATA", Path.home())) / "ZsMultiTool" / "game_servers"
        base.mkdir(parents=True, exist_ok=True)
        return base / "servers.json"

    def _legacy_minecraft_file() -> Path:
        base = Path(os.environ.get("APPDATA", Path.home())) / "ZsMultiTool" / "minecraft_server"
        return base / "settings.json"


def load_servers() -> list[dict]:
    f = _servers_file()
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    migrated = _migrate_legacy_minecraft_settings()
    if migrated:
        save_servers(migrated)
    return migrated


def save_servers(servers: list[dict]) -> None:
    try:
        _servers_file().write_text(json.dumps(servers, indent=2), encoding="utf-8")
    except OSError:
        pass


def _migrate_legacy_minecraft_settings() -> list[dict]:
    legacy = _legacy_minecraft_file()
    if not legacy.exists():
        return []

    try:
        old = json.loads(legacy.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []

    if not isinstance(old, dict):
        return []

    servers: list[dict] = []
    default_java = str(Path.home() / "Documents" / "Minecraft Servers" / "My Server")
    default_bedrock = str(Path.home() / "Documents" / "Minecraft Servers" / "My Bedrock Server")
    java_dir = old.get("java_server_dir") or old.get("server_dir") or default_java
    bedrock_dir = old.get("bedrock_server_dir") or default_bedrock

    shared = {
        "min_mb": int(old.get("min_mb", 1024)),
        "max_mb": int(old.get("max_mb", 2048)),
        "java_path": old.get("java_path", "java"),
        "bedrock_channel": old.get("bedrock_channel", "stable"),
    }

    java_path = Path(java_dir)
    bedrock_path = Path(bedrock_dir)
    java_has_server = (java_path / "server.jar").exists()
    bedrock_exe = "bedrock_server.exe"  # migration runs before adapter import
    import platform
    if platform.system() != "Windows":
        bedrock_exe = "bedrock_server"
    bedrock_has_server = (bedrock_path / bedrock_exe).exists()
    edition = old.get("edition", "java")

    if java_has_server or (edition != "bedrock" and not bedrock_has_server):
        servers.append(
            {
                "id": "minecraft-java-legacy",
                "name": "My Java Server",
                "game_type": "minecraft_java",
                "server_dir": java_dir,
                "config": dict(shared),
            }
        )

    if bedrock_has_server or edition == "bedrock":
        servers.append(
            {
                "id": "minecraft-bedrock-legacy",
                "name": "My Bedrock Server",
                "game_type": "minecraft_bedrock",
                "server_dir": bedrock_dir,
                "config": dict(shared),
            }
        )

    return servers
