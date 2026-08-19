"""Server folder utilities — lists, LAN IP, whitelist/allowlist, text files."""

from __future__ import annotations

import json
import platform
import shutil
import socket
import time
import zipfile
from pathlib import Path

TEXT_EXTENSIONS = {
    ".json", ".properties", ".txt", ".yml", ".yaml", ".cfg", ".ini",
    ".md", ".log", ".toml", ".conf", ".mcfunction",
}

_folder_size_cache: dict[str, tuple[int, float]] = {}


def get_lan_ip() -> str:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return ""


def folder_size(path: Path, *, max_age: float = 30.0) -> int:
    """Total bytes under path. Cached — full tree walks are expensive."""
    if not path.exists():
        return 0
    key = str(path.resolve())
    now = time.time()
    cached = _folder_size_cache.get(key)
    if cached and now - cached[1] < max_age:
        return cached[0]
    total = 0
    try:
        for p in path.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    except OSError:
        return cached[0] if cached else 0
    _folder_size_cache[key] = (total, now)
    return total


def invalidate_folder_size_cache(path: Path | None = None) -> None:
    if path is None:
        _folder_size_cache.clear()
        return
    _folder_size_cache.pop(str(path.resolve()), None)


def detect_game_type(folder: Path) -> str | None:
    if not folder.is_dir():
        return None

    def _has_srcds() -> bool:
        if (folder / "srcds.exe").is_file() or (folder / "srcds_run").is_file():
            return True
        return any(folder.glob("**/srcds.exe")) or any(folder.glob("**/srcds_run"))

    if _has_srcds() or (folder / "gmod.exe").is_file():
        if (folder / "garrysmod").is_dir():
            return "gmod"
        if (folder / "left4dead2").is_dir():
            return "l4d2"
    if (folder / "gmod.exe").is_file() and (folder / "garrysmod").is_dir():
        return "gmod"

    checks: list[tuple[str, tuple[str, ...]]] = [
        ("palworld", ("PalServer.exe", "PalServer.sh")),
        ("soulmask", ("WDS.exe", "SoulmaskServer.exe", "SoulmaskServer.sh")),
        ("rust", ("RustDedicated.exe", "RustDedicated")),
        ("ark_ascended", ("ArkAscendedServer.exe", "ArkAscendedServer")),
        ("ark_evolved", ("ShooterGameServer.exe", "ShooterGameServer")),
        ("cs2", ("cs2.exe",)),
        ("gmod", ("gmod.exe",)),
        ("seven_days_to_die", ("7DaysToDieServer.exe", "7DaysToDieServer.x86_64")),
        ("factorio", ("factorio.exe",)),
        ("enshrouded", ("enshrouded_server.exe", "EnshroudedDedicated.exe", "enshrouded_server")),
        ("vrising", ("VRisingServer.exe", "VRisingServer")),
        ("dayz", ("DayZServer_x64.exe", "DayZServer")),
        ("sons_of_the_forest", ("SonsOfTheForestDedicatedServer.exe",)),
        ("the_forest", ("TheForestDedicatedServer.exe",)),
        ("core_keeper", ("CoreKeeperServer.exe",)),
        ("space_engineers", ("DedicatedServer64.exe", "SpaceEngineersDedicated.exe")),
        ("scum", ("SCUMServer.exe",)),
        ("eco", ("EcoServer.exe",)),
        ("necesse", ("NecesseServer.exe",)),
        ("raft", ("RaftDedicatedServer.exe",)),
        ("icarus", ("IcarusServer.exe",)),
        ("barotrauma", ("DedicatedServer.exe",)),
        ("unturned", ("Unturned.exe", "Unturned_Headless.x86_64")),
        ("empyrion", ("EmpyrionDedicated.exe",)),
        ("avorion", ("AvorionServer.exe",)),
        ("squad", ("SquadGameServer.exe",)),
        ("hell_let_loose", ("HLLServer.exe",)),
        ("post_scriptum", ("PostScriptumServer.exe",)),
        ("abiotic_factor", ("AbioticFactorServer.exe",)),
        ("sunkenland", ("SunkenlandDedicated.exe",)),
        ("aska", ("ASKAServer.exe",)),
        ("insurgency_sandstorm", ("InsurgencyServer.exe",)),
        ("mordhau", ("MordhauServer-Win64-Shipping.exe",)),
        ("starbound", ("starbound_server.exe", "starbound_server")),
        ("bannerlord", ("DedicatedCustomServer.Starter.exe",)),
        ("smalland", ("SmallandServer.exe",)),
        ("humanitz", ("HumanitZServer.exe",)),
        ("once_human", ("OnceHumanServer.exe",)),
        ("holdfast", ("HoldfastDedicatedServer.exe",)),
        ("pixark", ("ShooterGameServer.exe",)),
        ("atlas", ("ShooterGameServer.exe",)),
        ("dst", ("dontstarve_dedicated_server_nullrenderer.exe", "dontstarve_dedicated_server_nullrenderer")),
        ("conan_exiles", ("ConanSandboxServer.exe", "ConanSandboxServer")),
        ("minecraft_java", ("server.jar",)),
        ("minecraft_bedrock", ("bedrock_server.exe", "bedrock_server")),
        ("satisfactory", ("FactoryServer.exe", "FactoryServer.sh")),
        ("valheim", ("valheim_server.exe", "valheim_server.x86_64")),
        ("terraria", (
            "start-tModLoaderServer.bat",
            "start-tModLoaderServer.sh",
            "tModLoaderServer.exe",
            "TerrariaServer.exe",
            "TerrariaServer.bin.x86_64",
        )),
        ("project_zomboid", ("StartServer64.bat", "start-server.sh")),
    ]
    for game_type, names in checks:
        if any((folder / name).exists() for name in names):
            return game_type
        for name in names:
            if list(folder.glob(f"**/{name}")):
                return game_type
    return None


def is_editable_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in TEXT_EXTENSIONS


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def write_text_file(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _load_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _save_json_list(path: Path, entries: list[dict]) -> None:
    path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def read_player_list(server_dir: Path, game_type: str) -> list[str]:
    if game_type == "minecraft_java":
        return [e.get("name", "") for e in _load_json_list(server_dir / "whitelist.json") if e.get("name")]
    if game_type == "minecraft_bedrock":
        return [e.get("name", "") for e in _load_json_list(server_dir / "allowlist.json") if e.get("name")]
    return []


def write_player_list(server_dir: Path, game_type: str, names: list[str]) -> None:
    entries = [{"name": n, "uuid": ""} for n in names if n.strip()]
    if game_type == "minecraft_java":
        _save_json_list(server_dir / "whitelist.json", entries)
    elif game_type == "minecraft_bedrock":
        _save_json_list(server_dir / "allowlist.json", entries)


def add_player_list_name(server_dir: Path, game_type: str, name: str) -> None:
    names = read_player_list(server_dir, game_type)
    name = name.strip()
    if not name or name in names:
        return
    names.append(name)
    write_player_list(server_dir, game_type, names)


def remove_player_list_name(server_dir: Path, game_type: str, name: str) -> None:
    names = [n for n in read_player_list(server_dir, game_type) if n != name]
    write_player_list(server_dir, game_type, names)


def restore_backup_zip(server_dir: Path, zip_path: Path) -> None:
    """Extract backup zip into server folder (overwrites matching paths)."""
    server_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.namelist():
            if member.startswith("_backups/") or member.endswith("/"):
                continue
            dest = server_dir / member
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)


def prune_backups(backups_dir: Path, keep: int) -> None:
    if keep <= 0 or not backups_dir.exists():
        return
    zips = sorted(backups_dir.glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in zips[keep:]:
        try:
            old.unlink()
        except OSError:
            pass
