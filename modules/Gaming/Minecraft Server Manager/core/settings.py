"""Persistent settings for the Game Server Manager."""

from __future__ import annotations

import json
from pathlib import Path

GAME_SERVERS_ROOT = Path.home() / "Documents" / "Game Servers"

_DEFAULT_SERVER_NAMES: dict[str, str] = {
    "minecraft_java": "My Java Server",
    "minecraft_bedrock": "My Bedrock Server",
    "satisfactory": "My Satisfactory Server",
    "terraria": "My Terraria Server",
    "terraria_tmodloader": "My tModLoader Server",
    "valheim": "My Valheim Server",
    "palworld": "My Palworld Server",
    "project_zomboid": "My Project Zomboid Server",
    "rust": "My Rust Server",
    "ark_evolved": "My ARK Server",
    "ark_ascended": "My ARK Ascended Server",
    "cs2": "My CS2 Server",
    "gmod": "My GMod Server",
    "l4d2": "My L4D2 Server",
    "seven_days_to_die": "My 7 Days to Die Server",
    "factorio": "My Factorio Server",
    "enshrouded": "My Enshrouded Server",
    "vrising": "My V Rising Server",
    "dayz": "My DayZ Server",
    "sons_of_the_forest": "My Sons of the Forest Server",
    "the_forest": "My The Forest Server",
    "core_keeper": "My Core Keeper Server",
    "space_engineers": "My Space Engineers Server",
    "scum": "My SCUM Server",
    "eco": "My Eco Server",
    "necesse": "My Necesse Server",
    "raft": "My Raft Server",
    "icarus": "My Icarus Server",
    "barotrauma": "My Barotrauma Server",
    "unturned": "My Unturned Server",
    "empyrion": "My Empyrion Server",
    "avorion": "My Avorion Server",
    "squad": "My Squad Server",
    "hell_let_loose": "My HLL Server",
    "post_scriptum": "My Post Scriptum Server",
    "abiotic_factor": "My Abiotic Factor Server",
    "sunkenland": "My Sunkenland Server",
    "aska": "My ASKA Server",
    "insurgency_sandstorm": "My Sandstorm Server",
    "mordhau": "My Mordhau Server",
    "starbound": "My Starbound Server",
    "bannerlord": "My Bannerlord Server",
    "smalland": "My Smalland Server",
    "humanitz": "My HumanitZ Server",
    "once_human": "My Once Human Server",
    "holdfast": "My Holdfast Server",
    "pixark": "My PixARK Server",
    "atlas": "My Atlas Server",
    "dst": "My DST Cluster",
    "conan_exiles": "My Conan Exiles Server",
    "soulmask": "My Soulmask Server",
    "steamcmd": "My SteamCMD Server",
    "custom": "My Custom Server",
}


def _terraria_mode_folder_key(config: dict | None) -> str:
    if not config:
        return "terraria"
    raw = str(config.get("server_mode", "vanilla")).strip().lower().replace(" ", "")
    if raw in {"tmodloader", "tmod", "modded", "mods"}:
        return "terraria_tmodloader"
    return "terraria"


def default_server_folder_for(
    game_type: str,
    config: dict | None = None,
) -> tuple[str, str]:
    """Return (folder_path, suggested_name) under Documents/Game Servers."""
    if game_type == "terraria":
        name = _DEFAULT_SERVER_NAMES[_terraria_mode_folder_key(config)]
        return str(GAME_SERVERS_ROOT / name), name
    name = _default_folder_name(game_type)
    return str(GAME_SERVERS_ROOT / name), name


def align_terraria_server_folder(srv: dict) -> bool:
    """Point Terraria servers at the default folder for the current mode (separate vanilla/tModLoader folders)."""
    if srv.get("game_type") != "terraria":
        return False

    config = srv.setdefault("config", {})
    folder, name = default_server_folder_for("terraria", config)
    current = Path(srv.get("server_dir", "")).resolve()
    target = Path(folder).resolve()
    vanilla = Path(default_server_folder_for("terraria", {"server_mode": "Vanilla"})[0]).resolve()
    tmod = Path(default_server_folder_for("terraria", {"server_mode": "tModLoader"})[0]).resolve()

    if current not in (vanilla, tmod):
        return False

    changed = False
    if current != target:
        target.mkdir(parents=True, exist_ok=True)
        srv["server_dir"] = str(target)
        changed = True

    if srv.get("name") != name:
        srv["name"] = name
        changed = True
    return changed


def _default_folder_name(game_type: str) -> str:
    if game_type in _DEFAULT_SERVER_NAMES:
        return _DEFAULT_SERVER_NAMES[game_type]
    try:
        from ..adapters import get_adapter

        adapter = get_adapter(game_type)
        if adapter:
            display = adapter.display_name.strip()
            if display.lower().startswith("my "):
                return display
            if display.endswith(" Server"):
                return f"My {display}"
            return f"My {display} Server"
    except ImportError:
        pass
    return "My Server"


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
                return _normalize_minecraft_paths(data)
        except (json.JSONDecodeError, OSError):
            pass
    migrated = _migrate_legacy_minecraft_settings()
    if migrated:
        save_servers(migrated)
    return migrated


def _normalize_minecraft_paths(servers: list[dict]) -> list[dict]:
    """Point Java/Bedrock servers at Documents/Game Servers instead of Minecraft Servers."""
    changed = False
    for srv in servers:
        if srv.get("game_type") not in ("minecraft_java", "minecraft_bedrock"):
            continue
        old_dir = srv.get("server_dir", "")
        if "Minecraft Servers" not in old_dir:
            continue
        srv["server_dir"] = old_dir.replace("Minecraft Servers", "Game Servers")
        changed = True
    if changed:
        save_servers(servers)
    return servers


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
    java_dir, _ = default_server_folder_for("minecraft_java")
    bedrock_dir, _ = default_server_folder_for("minecraft_bedrock")
    java_dir = old.get("java_server_dir") or old.get("server_dir") or java_dir
    bedrock_dir = old.get("bedrock_server_dir") or bedrock_dir

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
