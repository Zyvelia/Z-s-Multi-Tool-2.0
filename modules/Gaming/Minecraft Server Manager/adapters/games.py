"""Shared helpers for Steam-based and generic dedicated servers."""

from __future__ import annotations

import os
import platform
import re
import subprocess
from pathlib import Path

from ..core.events import ServerEvent
from .base import ConfigField, GameServerAdapter, LogTagRule


def _exe(name_win: str, name_linux: str) -> str:
    return name_win if platform.system() == "Windows" else name_linux


def resolve_satisfactory_executable(server_dir: Path) -> Path:
    """Return a file that indicates Satisfactory finished installing."""
    if platform.system() == "Windows":
        launcher = server_dir / "FactoryServer.exe"
        if launcher.is_file():
            return launcher
        win64 = server_dir / "Engine" / "Binaries" / "Win64"
        for name in ("FactoryServer-Win64-Shipping-Cmd.exe", "FactoryServer-Win64-Shipping.exe"):
            path = win64 / name
            if path.is_file():
                return path
        return server_dir / "FactoryServer.exe"

    sh = server_dir / "FactoryServer.sh"
    if sh.is_file():
        return sh
    linux = server_dir / "Engine" / "Binaries" / "Linux"
    for name in ("FactoryServer-Linux-Shipping-Cmd", "FactoryServer-Linux-Shipping"):
        path = linux / name
        if path.is_file():
            return path
    return sh


def _satisfactory_win64_binary(server_dir: Path) -> Path | None:
    win64 = server_dir / "Engine" / "Binaries" / "Win64"
    for name in ("FactoryServer-Win64-Shipping-Cmd.exe", "FactoryServer-Win64-Shipping.exe"):
        path = win64 / name
        if path.is_file():
            return path
    matches = sorted(win64.glob("FactoryServer-*-Cmd.exe")) if win64.is_dir() else []
    return matches[0] if matches else None


def build_satisfactory_start_command(
    server_dir: Path, config: dict,
) -> tuple[list[str], dict]:
    """Build argv for Satisfactory — UE requires FactoryGame when bypassing the launcher."""
    port = str(config.get("port", "7777"))
    reliable = str(config.get("reliable_port", config.get("query_port", "8888")))
    user_extra = str(config.get("extra_args", "")).strip().split()
    # Port overrides must come before -log / -unattended (official wiki).
    port_flags = [f"-Port={port}", f"-ReliablePort={reliable}"]
    log_flags = ["-log", "-unattended"]
    local_api = ["-ini:Engine:[SystemSettings]:FG.DedicatedServer.AllowInsecureLocalAccess=1"]
    popen_extra = {"stdin": subprocess.DEVNULL}

    if platform.system() == "Windows":
        shipping = _satisfactory_win64_binary(server_dir)
        if shipping is not None:
            args = [str(shipping), "FactoryGame", "-stdout", *port_flags, *user_extra, *local_api, *log_flags]
            return args, popen_extra
        launcher = server_dir / "FactoryServer.exe"
        if launcher.is_file():
            args = [str(launcher), *port_flags, *user_extra, *local_api, *log_flags]
            return args, popen_extra
        raise FileNotFoundError("FactoryServer.exe was not found — install via SteamCMD first.")

    sh = server_dir / "FactoryServer.sh"
    if sh.is_file():
        return ["bash", str(sh), *port_flags, *user_extra, *local_api, *log_flags], popen_extra

    linux = server_dir / "Engine" / "Binaries" / "Linux"
    for name in ("FactoryServer-Linux-Shipping-Cmd", "FactoryServer-Linux-Shipping"):
        binary = linux / name
        if binary.is_file():
            args = [str(binary), "FactoryGame", "-stdout", *port_flags, *user_extra, *local_api, *log_flags]
            return args, popen_extra
    raise FileNotFoundError("FactoryServer.sh was not found — install via SteamCMD first.")


def find_terraria_executable(server_dir: Path) -> Path | None:
    """Locate TerrariaServer binary under common install layouts."""
    if not server_dir.is_dir():
        return None

    exe_name = "TerrariaServer.exe" if platform.system() == "Windows" else "TerrariaServer.bin.x86_64"
    search_dirs: list[Path] = [server_dir]
    seen: set[str] = {str(server_dir.resolve()).lower()}

    def add_dir(path: Path) -> None:
        key = str(path.resolve()).lower()
        if key not in seen and path.is_dir():
            seen.add(key)
            search_dirs.append(path)

    for sub in sorted(server_dir.iterdir()):
        if not sub.is_dir():
            continue
        add_dir(sub)
        if sub.name.lower() in {"windows", "linux", "1456"}:
            add_dir(sub / "Windows")
            add_dir(sub / "Linux")

    for folder in search_dirs:
        candidate = folder / exe_name
        if candidate.is_file():
            return candidate

    matches = sorted(server_dir.glob(f"**/{exe_name}"))
    return matches[0] if matches else None


def resolve_terraria_executable(server_dir: Path) -> Path:
    """TerrariaServer path — official zip, SteamCMD, or Steam library layouts."""
    found = find_terraria_executable(server_dir)
    if found is not None:
        return found
    if platform.system() == "Windows":
        return server_dir / "TerrariaServer.exe"
    return server_dir / "TerrariaServer.bin.x86_64"


TMOD_STEAM_APP_ID = "1281930"


def terraria_server_mode(config: dict) -> str:
    """Return ``vanilla`` or ``tmodloader`` from saved server config."""
    raw = str(config.get("server_mode", "vanilla")).strip().lower().replace(" ", "")
    if raw in {"tmodloader", "tmod", "modded", "mods"}:
        return "tmodloader"
    return "vanilla"


def find_tmodloader_executable(server_dir: Path) -> Path | None:
    """Return the launcher/binary used to start a tModLoader dedicated server."""
    if not server_dir.is_dir():
        return None

    if platform.system() == "Windows":
        names = ("start-tModLoaderServer.bat", "tModLoaderServer.exe")
    else:
        names = (
            "start-tModLoaderServer.sh",
            "tModLoaderServer",
            "tModLoaderServer.bin.x86_64",
        )

    search_dirs: list[Path] = [server_dir]
    seen: set[str] = {str(server_dir.resolve()).lower()}

    def add_dir(path: Path) -> None:
        key = str(path.resolve()).lower()
        if key not in seen and path.is_dir():
            seen.add(key)
            search_dirs.append(path)

    for sub in sorted(server_dir.iterdir()):
        if not sub.is_dir():
            continue
        add_dir(sub)
        if sub.name.lower() in {"tmodloader", "server"}:
            add_dir(sub)

    for folder in search_dirs:
        for name in names:
            candidate = folder / name
            if candidate.is_file():
                return candidate

    for name in names:
        matches = sorted(server_dir.glob(f"**/{name}"))
        if matches:
            return matches[0]

    script_caller = server_dir / "LaunchUtils" / "ScriptCaller.sh"
    if script_caller.is_file():
        if platform.system() == "Windows":
            bat = server_dir / "start-tModLoaderServer.bat"
            if bat.is_file():
                return bat
        else:
            sh = server_dir / "start-tModLoaderServer.sh"
            if sh.is_file():
                return sh
    return None


def find_terraria_server_executable(server_dir: Path, config: dict) -> Path | None:
    """Return the server binary for the configured Terraria mode."""
    if terraria_server_mode(config) == "tmodloader":
        return find_tmodloader_executable(server_dir)
    return find_terraria_executable(server_dir)


def resolve_terraria_server_executable(server_dir: Path, config: dict) -> Path:
    """Expected server binary path for the configured Terraria mode."""
    found = find_terraria_server_executable(server_dir, config)
    if found is not None:
        return found
    if terraria_server_mode(config) == "tmodloader":
        return server_dir / "start-tModLoaderServer.bat"
    return resolve_terraria_executable(server_dir)


def terraria_folder_has_tmodloader(server_dir: Path) -> bool:
    return find_tmodloader_executable(server_dir) is not None


def terraria_folder_has_vanilla(server_dir: Path) -> bool:
    return find_terraria_executable(server_dir) is not None


def terraria_folder_has_tmod_tree(server_dir: Path) -> bool:
    return (server_dir / "LaunchUtils" / "ScriptCaller.sh").is_file()


def detect_terraria_server_mode(server_dir: Path) -> str:
    """Detect Vanilla vs tModLoader from files installed in *server_dir*."""
    if not server_dir.is_dir():
        return "Vanilla"

    has_tmod = terraria_folder_has_tmodloader(server_dir)
    has_vanilla = terraria_folder_has_vanilla(server_dir)
    has_tmod_tree = terraria_folder_has_tmod_tree(server_dir)

    if has_tmod_tree or (has_tmod and (server_dir / ".tml-version").is_file()):
        return "tModLoader"
    if has_tmod and not has_vanilla:
        return "tModLoader"
    if has_vanilla and not has_tmod:
        return "Vanilla"
    if has_tmod and has_vanilla:
        return "tModLoader"
    return "Vanilla"


def terraria_install_warning(server_dir: Path) -> str | None:
    """Return a warning when vanilla and tModLoader files are mixed together."""
    if not server_dir.is_dir():
        return None
    has_tmod = terraria_folder_has_tmodloader(server_dir)
    has_vanilla = terraria_folder_has_vanilla(server_dir)
    if has_tmod and has_vanilla:
        return (
            "Both vanilla Terraria and tModLoader files are in this folder.\n\n"
            "Use separate folders:\n"
            "  • My Terraria Server — vanilla\n"
            "  • My tModLoader Server — modded\n\n"
            "Move your install or use Install Server Files in the matching folder "
            "so each one only has a single server type."
        )
    return None


def sync_terraria_server_mode(server_dir: Path, config: dict) -> tuple[bool, str]:
    """Update saved server_mode when it does not match the folder. Returns (changed, mode)."""
    detected = detect_terraria_server_mode(server_dir)
    stored = "tModLoader" if terraria_server_mode(config) == "tmodloader" else "Vanilla"
    if stored != detected:
        config["server_mode"] = detected
        return True, detected
    return False, detected


def infer_terraria_server_mode(server_dir: Path) -> str:
    """Alias for :func:`detect_terraria_server_mode`."""
    return detect_terraria_server_mode(server_dir)


def _subprocess_path(path: Path, base: Path) -> str:
    """Prefer a path relative to *base* so cmd.exe does not break on spaces."""
    try:
        return str(path.resolve().relative_to(base.resolve()))
    except ValueError:
        return str(path.resolve())


def terraria_client_worlds_dir() -> Path:
    """Default Terraria single-player worlds folder on this PC."""
    return Path.home() / "Documents" / "My Games" / "Terraria" / "Worlds"


def normalize_terraria_world_file(world_file: str) -> str:
    """Ensure world_file uses a .wld filename."""
    name = Path(str(world_file or "world.wld").strip() or "world.wld").name
    if not name.lower().endswith(".wld"):
        name = f"{name}.wld"
    return name


def list_terraria_world_files(server_dir: Path) -> list[Path]:
    """Return .wld files in the server folder (top level and common subfolders)."""
    if not server_dir.is_dir():
        return []
    found: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path.resolve()).lower()
        if key not in seen and path.is_file():
            seen.add(key)
            found.append(path)

    for pattern in ("*.wld", "Worlds/*.wld", "World/*.wld", "worlds/*.wld"):
        for path in server_dir.glob(pattern):
            add(path)
    return sorted(found, key=lambda p: p.name.lower())


def resolve_terraria_world(
    server_dir: Path,
    world_file: str,
) -> tuple[Path | None, str, list[Path]]:
    """Resolve which world file to use. Returns (path, filename, all_discovered)."""
    configured_name = normalize_terraria_world_file(world_file)
    discovered = list_terraria_world_files(server_dir)

    direct = server_dir / configured_name
    if direct.is_file():
        return direct, direct.name, discovered

    stem = Path(configured_name).stem.lower()
    for path in discovered:
        if path.name.lower() == configured_name.lower() or path.stem.lower() == stem:
            return path, path.name, discovered

    if len(discovered) == 1:
        path = discovered[0]
        return path, path.name, discovered

    if configured_name.lower() == "world.wld" and discovered:
        path = sorted(discovered, key=lambda p: p.name.lower())[0]
        return path, path.name, discovered

    return None, configured_name, discovered


class SteamDedicatedAdapter(GameServerAdapter):
    """Base for servers typically installed via SteamCMD."""

    steam_app_id: str = ""
    executable_win: str = ""
    executable_linux: str = ""
    default_stop_command: str = ""

    def executable_name(self) -> str:
        return _exe(self.executable_win, self.executable_linux)

    def executable_marker(self, server_dir: Path) -> Path:
        return server_dir / self.executable_name()

    def supports_steam_install(self) -> bool:
        return bool(self.steam_app_id)

    def steam_app_id_for(self, config: dict) -> str:
        return str(config.get("steam_app_id") or self.steam_app_id).strip()

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        exe = server_dir / self.executable_name()
        extra_args = str(config.get("extra_args", "")).strip()
        args = [str(exe)]
        if extra_args:
            args += extra_args.split()
        return args, {}

    def graceful_stop_command(self) -> str:
        return self.default_stop_command

    def pre_start_checks(self, server_dir: Path, config: dict) -> tuple[bool, str]:
        if not self.is_installed(server_dir):
            app_id = self.steam_app_id_for(config)
            hint = (
                f"Install via SteamCMD (App ID {app_id}) from the Config tab, "
                f"or place {self.executable_name()} in the server folder."
            )
            return False, hint
        return True, "Ready to start."

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("port", "Port", "text", str(self.default_port()), width=100),
            ConfigField("extra_args", "Extra startup args", "text", "", width=220),
            ConfigField("steam_app_id", "Steam App ID", "text", self.steam_app_id, width=120),
        ]

    def overview_rows(
        self,
        server_dir: Path,
        config: dict,
        *,
        running: bool = False,
    ) -> list[tuple[str, str]]:
        rows = super().overview_rows(server_dir, config, running=running)
        rows.append(("Steam App ID", self.steam_app_id_for(config) or "—"))
        if config.get("extra_args"):
            rows.append(("Extra args", config["extra_args"]))
        return rows

    def setup_panel_hints(self) -> list[str]:
        app_id = self.steam_app_id
        return [
            f"Use Install via SteamCMD in the Config tab (App ID {app_id}).",
            f"Expected executable: {self.executable_name()}",
        ]


class SatisfactoryAdapter(SteamDedicatedAdapter):
    game_type = "satisfactory"
    display_name = "Satisfactory"
    icon = "🏭"
    description = "Satisfactory dedicated server (Steam App ID 1690800)."
    steam_app_id = "1690800"
    executable_win = "FactoryServer.exe"
    executable_linux = "FactoryServer.sh"

    def default_port(self) -> int:
        return 7777

    def port_protocol(self) -> str:
        return "UDP"

    def executable_marker(self, server_dir: Path) -> Path:
        return resolve_satisfactory_executable(server_dir)

    def is_installed(self, server_dir: Path) -> bool:
        return resolve_satisfactory_executable(server_dir).is_file()

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("port", "Game port (UDP/TCP)", "text", "7777", width=100),
            ConfigField("reliable_port", "Reliable port (TCP)", "text", "8888", width=100),
            ConfigField("server_name", "Session name", "text", "Satisfactory Server", width=180),
            ConfigField("admin_password", "Admin password (API)", "text", "", width=140),
            ConfigField("api_token", "API token (optional)", "text", "", width=180),
            ConfigField("extra_args", "Extra startup args", "text", "", width=220),
        ]

    def execute_remote_command(
        self, command: str, config: dict, server_dir: Path
    ) -> tuple[bool, str] | None:
        from ..core.satisfactory_api import SatisfactoryApiError, satisfactory_api_client

        client = satisfactory_api_client(config)
        lowered = command.strip().lower()
        try:
            if lowered in {"quit", "stop", "exit", "shutdown"}:
                client.shutdown()
                return True, "Shutdown requested via HTTPS API."
            if lowered in {"save", "server.savegame"} or lowered.startswith("server.savegame"):
                save_name = str(config.get("server_name", "ManualSave")).strip() or "ManualSave"
                if lowered.startswith("server.savegame"):
                    parts = command.split(maxsplit=1)
                    if len(parts) > 1:
                        save_name = parts[1].strip().strip('"')
                client.save_game(save_name)
                return True, f"Save requested: {save_name}"
            if lowered in {"state", "serverstate", "querystate", "queryserverstate"}:
                state = client.query_server_state()
                return True, str(state) if state else "Server state retrieved."
            output = client.run_command(command)
            return True, output.strip() if output.strip() else f"> {command} (ok)"
        except SatisfactoryApiError as e:
            return False, str(e)

    def prefers_remote_console(self, config: dict) -> bool:
        return True

    def graceful_stop_remote(self, config: dict, server_dir: Path) -> tuple[bool, str] | None:
        return self.execute_remote_command("quit", config, server_dir)

    def quick_commands(self) -> list[tuple[str, str]]:
        return [
            ("Save", "server.SaveGame"),
            ("Query state", "querystate"),
            ("Generate API token", "server.GenerateAPIToken"),
            ("Shutdown", "quit"),
        ]

    def graceful_stop_command(self) -> str:
        return "quit"

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        return build_satisfactory_start_command(server_dir, config)

    def pre_start_checks(self, server_dir: Path, config: dict) -> tuple[bool, str]:
        if not self.is_installed(server_dir):
            app_id = self.steam_app_id_for(config)
            return False, (
                f"FactoryServer not found — use Install via SteamCMD (App ID {app_id}) on the Config tab."
            )
        if platform.system() == "Windows":
            if not (server_dir / "FactoryServer.exe").is_file() and _satisfactory_win64_binary(server_dir) is None:
                return False, "Install via SteamCMD — FactoryServer.exe is missing from the server folder."
        return True, "Ready to start."

    def parse_log_line(self, line: str) -> ServerEvent | None:
        if any(
            token in line
            for token in (
                "Server has been initialized",
                "Game state changed from Inactive to Active",
                "Server API listening",
                "Game Engine Initialized",
                "Engine is initialized",
                "Starting Game.",
            )
        ):
            return ServerEvent(kind="ready", message=line)
        return None

    def log_tag_rules(self) -> list[LogTagRule]:
        rules = super().log_tag_rules()
        rules.extend([
            LogTagRule(re.compile(r"LogServer: Display:"), "log_ready"),
            LogTagRule(re.compile(r"Match State Changed"), "log_save"),
        ])
        return rules

    def log_file_candidates(self, server_dir: Path) -> list[Path]:
        return [
            server_dir / "FactoryGame" / "Saved" / "Logs" / "FactoryGame.log",
            server_dir / "FactoryGame" / "Saved" / "Logs" / "FactoryGame_2.log",
            *super().log_file_candidates(server_dir),
        ]

    def supports_mods(self) -> bool:
        return True

    def mods_directory(self, server_dir: Path) -> Path | None:
        return server_dir / "FactoryGame" / "Mods"

    def mods_directories(self, server_dir: Path) -> list[Path]:
        return [server_dir / "FactoryGame" / "Mods"]

    def mod_file_extensions(self) -> tuple[str, ...] | None:
        return (".pak", ".ucas", ".utoc", ".dll")

    def collect_mod_files(self, server_dir: Path) -> list[Path]:
        found = list(super().collect_mod_files(server_dir))
        seen = {str(p).lower() for p in found}
        mods_root = server_dir / "FactoryGame" / "Mods"
        if mods_root.is_dir():
            for child in mods_root.iterdir():
                if child.is_dir():
                    key = str(child).lower()
                    if key not in seen:
                        found.append(child)
                        seen.add(key)
        return sorted(found, key=lambda p: str(p).lower())

    def mods_empty_message(self) -> str:
        return (
            "No mods found in FactoryGame/Mods.\n"
            "Use Satisfactory Mod Manager (Manage Servers) to install server builds — "
            "don't copy mods from your game client.\n"
            "See docs.ficsit.app for dedicated server mod setup."
        )

    def mods_browser_urls(self) -> dict[str, str]:
        return {
            "modrinth": "https://docs.ficsit.app/satisfactory-modding/latest/ForUsers/SatisfactoryModManager.html",
            "curseforge": "https://ficsit.app/",
        }

    def setup_panel_hints(self) -> list[str]:
        return super().setup_panel_hints() + [
            "Console commands use the HTTPS API on localhost (not stdin).",
            "Set Admin password after claiming the server in-game, or paste an API token from server.GenerateAPIToken.",
            "Forward UDP/TCP 7777 and TCP 8888 (reliable messaging port).",
            "Mods live in FactoryGame/Mods — use Satisfactory Mod Manager for server mods.",
            "Claim the server and set admin password from the in-game Server Manager on first join.",
            "Stop via Shutdown / quit — the API saves before exit.",
        ]


VALHEIM_SERVER_STEAM_APP_ID = "896660"
VALHEIM_GAME_STEAM_APP_ID = "892970"


def find_valheim_executable(server_dir: Path) -> Path | None:
    """Locate valheim_server binary under common SteamCMD install layouts."""
    if not server_dir.is_dir():
        return None

    exe_name = _exe("valheim_server.exe", "valheim_server.x86_64")
    search_dirs: list[Path] = [server_dir]
    seen: set[str] = {str(server_dir.resolve()).lower()}

    def add_dir(path: Path) -> None:
        key = str(path.resolve()).lower()
        if key not in seen and path.is_dir():
            seen.add(key)
            search_dirs.append(path)

    for sub in sorted(server_dir.iterdir()):
        if sub.is_dir():
            add_dir(sub)

    for folder in search_dirs:
        candidate = folder / exe_name
        if candidate.is_file():
            return candidate

    matches = sorted(server_dir.glob(f"**/{exe_name}"))
    return matches[0] if matches else None


def resolve_valheim_executable(server_dir: Path) -> Path:
    found = find_valheim_executable(server_dir)
    if found is not None:
        return found
    return server_dir / _exe("valheim_server.exe", "valheim_server.x86_64")


def ensure_valheim_steam_appid(server_dir: Path) -> None:
    """Valheim server binary expects game App ID 892970 at runtime."""
    (server_dir / "steam_appid.txt").write_text(f"{VALHEIM_GAME_STEAM_APP_ID}\n", encoding="utf-8")


def _valheim_public_flag(config: dict) -> str:
    raw = str(config.get("public", "1")).strip().lower()
    if raw in {"0", "private", "no", "false", "off"}:
        return "0"
    return "1"


def _valheim_crossplay_enabled(config: dict) -> bool:
    raw = str(config.get("crossplay", "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


class ValheimAdapter(SteamDedicatedAdapter):
    game_type = "valheim"
    display_name = "Valheim"
    icon = "⚔️"
    description = "Valheim dedicated server (Steam App ID 896660)."
    steam_app_id = VALHEIM_SERVER_STEAM_APP_ID
    executable_win = "valheim_server.exe"
    executable_linux = "valheim_server.x86_64"

    def default_port(self) -> int:
        return 2456

    def port_protocol(self) -> str:
        return "UDP"

    def executable_marker(self, server_dir: Path) -> Path:
        return resolve_valheim_executable(server_dir)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return find_valheim_executable(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        from .install import create_steamcmd_install_worker

        app_id = self.steam_app_id_for(config)
        inner = create_steamcmd_install_worker(
            server_dir,
            app_id,
            verify=lambda directory: find_valheim_executable(directory) is not None,
        )
        original_run = inner.run

        def run_with_appid():
            original_run()
            if find_valheim_executable(server_dir):
                ensure_valheim_steam_appid(server_dir)

        inner.run = run_with_appid
        return inner

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_name", "Server name", "text", "My Valheim Server", width=180),
            ConfigField("world_name", "World name", "text", "Dedicated", width=140),
            ConfigField("password", "Password", "text", "", width=140),
            ConfigField("port", "Port", "text", "2456", width=100),
            ConfigField(
                "public",
                "Server list",
                "menu",
                "Public",
                ["Private", "Public"],
                width=120,
            ),
            ConfigField(
                "crossplay",
                "Crossplay",
                "menu",
                "Off",
                ["Off", "On"],
                width=100,
            ),
            ConfigField("extra_args", "Extra startup args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        root = server_dir.resolve()
        exe = find_valheim_executable(root) or root / self.executable_name()
        try:
            exe_arg = str(exe.relative_to(root))
        except ValueError:
            exe_arg = str(exe.resolve())

        if platform.system() != "Windows":
            script = root / "start_server.sh"
            if script.is_file() and not str(config.get("extra_args", "")).strip():
                env = os.environ.copy()
                env["SteamAppId"] = VALHEIM_GAME_STEAM_APP_ID
                linux64 = root / "linux64"
                if linux64.is_dir():
                    env["LD_LIBRARY_PATH"] = (
                        str(linux64) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
                    )
                return ["bash", str(script)], {"cwd": str(root), "env": env}

        args = [
            exe_arg,
            "-nograb",
            "-batchmode",
            "-name", str(config.get("server_name", "My Valheim Server")),
            "-port", str(config.get("port", self.default_port())),
            "-world", str(config.get("world_name", "Dedicated")),
            "-password", str(config.get("password", "")),
            "-public", _valheim_public_flag(config),
        ]
        if _valheim_crossplay_enabled(config):
            args.append("-crossplay")
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()

        ensure_valheim_steam_appid(root)
        env = os.environ.copy()
        env["SteamAppId"] = VALHEIM_GAME_STEAM_APP_ID
        if platform.system() != "Windows":
            linux64 = root / "linux64"
            if linux64.is_dir():
                env["LD_LIBRARY_PATH"] = (
                    str(linux64) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
                )
        return args, {"cwd": str(root), "env": env}

    def pre_start_checks(self, server_dir: Path, config: dict) -> tuple[bool, str]:
        if not self.is_installed(server_dir):
            return False, (
                "valheim_server not found — use Install via SteamCMD on the Config tab."
            )
        password = str(config.get("password", "")).strip()
        if len(password) < 5:
            return False, "Valheim requires a password of at least 5 characters."
        server_name = str(config.get("server_name", "")).strip()
        if password.lower() in server_name.lower() and server_name:
            return False, "Password cannot appear inside the server name."
        ensure_valheim_steam_appid(server_dir.resolve())
        return True, "Ready to start."

    def parse_log_line(self, line: str) -> ServerEvent | None:
        if any(
            phrase in line
            for phrase in ("Game server connected", "Loaded world", "Done loading world")
        ):
            return ServerEvent(kind="ready", message=line)
        return None

    def log_tag_rules(self) -> list[LogTagRule]:
        return super().log_tag_rules() + [
            LogTagRule(re.compile(r"Game server connected", re.I), "log_ready"),
            LogTagRule(re.compile(r"Loaded world", re.I), "log_ready"),
            LogTagRule(re.compile(r"Done loading world", re.I), "log_ready"),
        ]

    def overview_rows(
        self,
        server_dir: Path,
        config: dict,
        *,
        running: bool = False,
    ) -> list[tuple[str, str]]:
        rows = super().overview_rows(server_dir, config, running=running)
        insert_at = next(
            (index + 1 for index, (label, _) in enumerate(rows) if label == "Port"),
            len(rows),
        )
        rows.insert(insert_at, ("World", str(config.get("world_name", "Dedicated"))))
        list_label = "Public" if _valheim_public_flag(config) == "1" else "Private"
        rows.insert(insert_at + 1, ("Listing", list_label))
        if _valheim_crossplay_enabled(config):
            rows.insert(insert_at + 2, ("Crossplay", "On"))
        return rows

    def setup_panel_hints(self) -> list[str]:
        return [
            "Use Install via SteamCMD on the Config tab (App ID 896660).",
            "Password must be at least 5 characters and not part of the server name.",
            "Forward UDP ports 2456–2457 (2458 if crossplay is off).",
            "Enable Crossplay to skip router port forwarding (uses PlayFab relay).",
        ]


class TerrariaAdapter(GameServerAdapter):
    game_type = "terraria"
    display_name = "Terraria"
    icon = "🌳"
    description = "Terraria dedicated server — vanilla or tModLoader (choose in Config)."
    steam_app_id = "105600"

    def default_port(self) -> int:
        return 7777

    def port_protocol(self) -> str:
        return "TCP"

    def supports_steam_install(self) -> bool:
        return True

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        from .install import create_terraria_install_worker

        mode = terraria_server_mode(config)
        return create_terraria_install_worker(
            server_dir,
            mode=mode,
            verify=lambda directory: find_terraria_server_executable(
                directory, {"server_mode": mode},
            ) is not None,
        )

    def steam_app_id_for(self, config: dict) -> str:
        if terraria_server_mode(config) == "tmodloader":
            return TMOD_STEAM_APP_ID
        return str(config.get("steam_app_id") or self.steam_app_id).strip()

    def executable_marker(self, server_dir: Path) -> Path:
        return resolve_terraria_executable(server_dir)

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return find_terraria_server_executable(server_dir, config or {}) is not None

    def supports_mods_for(self, config: dict) -> bool:
        return terraria_server_mode(config) == "tmodloader"

    def mods_directory(self, server_dir: Path) -> Path | None:
        return server_dir / "Mods"

    def mod_file_extensions(self) -> tuple[str, ...] | None:
        return (".tmod",)

    def collect_mod_files(self, server_dir: Path) -> list[Path]:
        mods_dir = server_dir / "Mods"
        if not mods_dir.is_dir():
            return []
        found = list(super().collect_mod_files(server_dir))
        seen = {str(path).lower() for path in found}
        for name in ("enabled.json", "install.txt"):
            path = mods_dir / name
            if path.is_file() and str(path).lower() not in seen:
                found.append(path)
        return sorted(set(found), key=lambda p: str(p).lower())

    def mods_empty_message(self) -> str:
        return (
            "No mods in Mods/ yet.\n"
            "Copy .tmod files into the Mods folder, or subscribe on Steam Workshop "
            "and copy them from your tModLoader install.\n"
            "Use enabled.json to control which mods load."
        )

    def mods_browser_urls(self) -> dict[str, str]:
        return {
            "steam": "https://steamcommunity.com/app/1281930/workshop/",
        }

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField(
                "server_mode",
                "Server type",
                "menu",
                "Vanilla",
                choices=["Vanilla", "tModLoader"],
                width=160,
            ),
            ConfigField("world_file", "World file", "text", "world.wld", width=160),
            ConfigField("port", "Port", "text", "7777", width=100),
            ConfigField("max_players", "Max players", "text", "8", width=100),
            ConfigField("password", "Password", "text", "", width=140),
            ConfigField("motd", "MOTD", "text", "Welcome!", width=180),
            ConfigField("extra_args", "Extra args", "text", "", width=200),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        root = server_dir.resolve()
        launcher = resolve_terraria_server_executable(root, config)
        world_path, world_name, _ = resolve_terraria_world(
            root,
            str(config.get("world_file", "world.wld")),
        )
        if world_path is None:
            raise FileNotFoundError(
                f"Terraria world file not found in {root}. "
                "Copy a .wld into the server folder or import one from Config/Files."
            )
        port = config.get("port", str(self.default_port()))
        max_players = config.get("max_players", "8")
        password = str(config.get("password", "")).strip()
        motd = str(config.get("motd", "Welcome!")).strip()
        world_arg = _subprocess_path(world_path, root)
        launch_args = [
            "-world", world_arg,
            "-port", str(port),
            "-maxplayers", str(max_players),
            "-motd", motd,
        ]
        if password:
            launch_args += ["-password", password]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            launch_args += extra.split()

        if terraria_server_mode(config) == "tmodloader":
            launch_args = ["-nosteam", *launch_args]
            popen_extra = {"cwd": str(root)}
            suffix = launcher.suffix.lower()
            if suffix == ".bat":
                return [str(launcher.resolve()), *launch_args], popen_extra
            if suffix == ".sh":
                return ["bash", str(launcher.resolve()), *launch_args], popen_extra
            return [str(launcher.resolve()), *launch_args], popen_extra

        exe = launcher.resolve()
        if not exe.is_file():
            exe = root / exe.name
        return [str(exe), *launch_args], {}

    def pre_start_checks(self, server_dir: Path, config: dict) -> tuple[bool, str]:
        mode = terraria_server_mode(config)
        if not self.is_installed(server_dir, config):
            if mode == "tmodloader":
                return False, (
                    "tModLoader server not found — use Install Server Files on the Config tab "
                    "(downloads the official GitHub release or copies from Steam)."
                )
            return False, (
                "TerrariaServer not found — use Install Server Files on the Config tab."
            )
        configured = str(config.get("world_file", "world.wld"))
        world_path, world_name, discovered = resolve_terraria_world(server_dir, configured)
        if world_path is not None:
            if normalize_terraria_world_file(configured) != world_name:
                return True, f"Ready to start with {world_name}."
            return True, "Ready to start."
        if discovered:
            names = ", ".join(path.name for path in discovered)
            return False, (
                f"World file '{normalize_terraria_world_file(configured)}' not found. "
                f"Available: {names}."
            )
        return False, (
            f"World file not found: {normalize_terraria_world_file(configured)}. "
            "Copy a .wld into the server folder or use Import world on the Files tab."
        )

    def readiness_message(self, server_dir: Path, config: dict | None = None) -> tuple[bool, str]:
        cfg = config or {}
        if not self.is_installed(server_dir, cfg):
            label = "tModLoader" if terraria_server_mode(cfg) == "tmodloader" else self.display_name
            return False, f"{label} is not installed in this folder yet."
        return self.pre_start_checks(server_dir, cfg)

    def quick_commands(self) -> list[tuple[str, str]]:
        return [
            ("save", "save"),
            ("say Hello!", "say Hello!"),
            ("exit", "exit"),
        ]

    def graceful_stop_command(self) -> str:
        return "exit"

    def log_tag_rules(self) -> list[LogTagRule]:
        return super().log_tag_rules() + [
            LogTagRule(re.compile(r"Listening on port", re.I), "log_ready"),
            LogTagRule(re.compile(r"\bServer started\b", re.I), "log_ready"),
            LogTagRule(re.compile(r"^Terraria Server v", re.I), "log_info"),
            LogTagRule(re.compile(r"^tModLoader v", re.I), "log_info"),
            LogTagRule(
                re.compile(
                    r"^(Resetting game objects|Loading world data|Settling liquids)\s+\d+%",
                    re.I,
                ),
                "log_save",
            ),
            LogTagRule(re.compile(r"^Error Logging Enabled|^Type 'help'", re.I), "log_debug"),
            LogTagRule(re.compile(r"^:\s"), "command"),
            LogTagRule(re.compile(r" has joined", re.I), "log_join"),
            LogTagRule(re.compile(r" has left", re.I), "log_leave"),
        ]

    def parse_log_line(self, line: str) -> ServerEvent | None:
        if "Listening on port" in line:
            return ServerEvent(kind="ready", message=line)
        m = re.search(r"([\w\s]+) has joined", line)
        if m:
            return ServerEvent(kind="player_join", player=m.group(1).strip())
        m = re.search(r"([\w\s]+) has left", line)
        if m:
            return ServerEvent(kind="player_leave", player=m.group(1).strip())
        return None

    def setup_panel_hints(self, config: dict | None = None) -> list[str]:
        if config and terraria_server_mode(config) == "tmodloader":
            return [
                "Server type is tModLoader — install downloads the official GitHub release.",
                "If you own tModLoader on Steam, the installer copies from your library first.",
                "First launch may download .NET — watch the console for progress.",
                "Place .tmod files in the Mods folder (see Mods tab). Worlds still use .wld files.",
                "Forward TCP port 7777 for friends to join.",
            ]
        return [
            "Install Server Files downloads the official package from terraria.org.",
            "If you own Terraria on Steam, the installer copies from your library first.",
            "Switch Server type to tModLoader in Config for modded servers.",
            "After install, copy a .wld world file into the server folder (or change world_file in Config).",
            "Forward TCP port 7777 for friends to join.",
        ]

    def overview_rows(
        self,
        server_dir: Path,
        config: dict,
        *,
        running: bool = False,
    ) -> list[tuple[str, str]]:
        rows = super().overview_rows(server_dir, config, running=running)
        mode_label = detect_terraria_server_mode(server_dir)
        insert_at = next(
            (index + 1 for index, (label, _) in enumerate(rows) if label == "Game"),
            1,
        )
        rows.insert(insert_at, ("Server type", mode_label))
        mixed = terraria_install_warning(server_dir)
        if mixed:
            rows.append(("Note", mixed))
        configured = str(config.get("world_file", "world.wld"))
        world_path, world_name, discovered = resolve_terraria_world(server_dir, configured)
        configured_label = normalize_terraria_world_file(configured)

        if world_path is not None:
            if world_name == configured_label:
                world_label = f"{world_name} (ready)"
            else:
                world_label = f"{world_name} (ready — config: {configured_label})"
        elif discovered:
            available = ", ".join(path.name for path in discovered[:4])
            if len(discovered) > 4:
                available += f", +{len(discovered) - 4} more"
            world_label = f"Not matched — config: {configured_label}. Available: {available}"
        else:
            world_label = f"No .wld in folder (config: {configured_label})"

        # Insert world details after server-files row.
        insert_at = next(
            (index + 1 for index, (label, _) in enumerate(rows) if label == "Server files"),
            len(rows),
        )
        rows.insert(insert_at, ("World", world_label))
        return rows


PZ_STEAM_APP_ID = "380870"


def _sanitize_pz_server_profile(name: str) -> str:
    cleaned = re.sub(r"[^\w\-]", "", str(name).replace(" ", ""))
    return (cleaned[:32] if cleaned else "servertest")


def pz_server_profile(config: dict) -> str:
    explicit = str(config.get("server_profile", "")).strip()
    if explicit:
        return _sanitize_pz_server_profile(explicit)
    return _sanitize_pz_server_profile(config.get("server_name", "servertest"))


def pz_zomboid_dir(server_dir: Path) -> Path:
    return server_dir.resolve() / "Zomboid"


def pz_server_config_dir(server_dir: Path) -> Path:
    return pz_zomboid_dir(server_dir) / "Server"


def find_pz_start_script(server_dir: Path) -> Path | None:
    """Locate StartServer64.bat / start-server.sh under nested SteamCMD layouts."""
    if not server_dir.is_dir():
        return None

    names = (
        ["StartServer64.bat", "StartServer32.bat", "start-server.sh"]
        if platform.system() == "Windows"
        else ["start-server.sh", "StartServer64.bat", "StartServer32.bat"]
    )
    search_dirs: list[Path] = [server_dir]
    seen: set[str] = {str(server_dir.resolve()).lower()}

    def add_dir(path: Path) -> None:
        key = str(path.resolve()).lower()
        if key not in seen and path.is_dir():
            seen.add(key)
            search_dirs.append(path)

    for sub in sorted(server_dir.iterdir()):
        if sub.is_dir():
            add_dir(sub)

    for folder in search_dirs:
        for name in names:
            candidate = folder / name
            if candidate.is_file():
                return candidate

    for name in names:
        matches = sorted(server_dir.glob(f"**/{name}"))
        if matches:
            return matches[0]
    return None


def _pz_port(config: dict) -> int:
    try:
        return int(str(config.get("port", 16261)).strip())
    except ValueError:
        return 16261


def _pz_udp_port(config: dict, game_port: int) -> int:
    raw = str(config.get("udp_port", "")).strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return game_port + 1


def _pz_public_enabled(config: dict) -> bool:
    raw = str(config.get("public", "Public")).strip().lower()
    return raw not in {"0", "private", "no", "false", "off"}


def _patch_pz_ini_line(text: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    line = f"{key}={value}"
    if pattern.search(text):
        return pattern.sub(line, text)
    trimmed = text.rstrip("\n")
    if trimmed:
        return trimmed + "\n" + line + "\n"
    return line + "\n"


def sync_pz_server_ini(server_dir: Path, config: dict) -> Path:
    """Write manager config into Zomboid/Server/<profile>.ini (under server folder)."""
    profile = pz_server_profile(config)
    config_dir = pz_server_config_dir(server_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    ini_path = config_dir / f"{profile}.ini"

    port = _pz_port(config)
    udp_port = _pz_udp_port(config, port)
    updates: dict[str, str] = {
        "PublicName": str(config.get("server_name", "PZ Server")),
        "DefaultPort": str(port),
        "UDPPort": str(udp_port),
        "Public": "true" if _pz_public_enabled(config) else "false",
    }
    admin_pw = str(config.get("admin_password", "")).strip()
    if admin_pw:
        updates["AdminPassword"] = admin_pw
    max_players = str(config.get("max_players", "")).strip()
    if max_players:
        updates["MaxPlayers"] = max_players

    if ini_path.is_file():
        text = ini_path.read_text(encoding="utf-8", errors="replace")
        for key, value in updates.items():
            text = _patch_pz_ini_line(text, key, value)
        ini_path.write_text(text, encoding="utf-8")
    else:
        ini_path.write_text("\n".join(f"{k}={v}" for k, v in updates.items()) + "\n", encoding="utf-8")
    return ini_path


def _split_pz_cmd_tokens(fragment: str) -> list[str]:
    return re.findall(r'"[^"]*"|\S+', fragment.strip())


def _build_pz_classpath(root: Path, script_text: str) -> str:
    match = re.search(r"SET\s+PZ_CLASSPATH=(.+)", script_text, re.I)
    if match:
        cp = match.group(1).strip()
        cp = cp.replace(".\\", str(root) + os.sep).replace("./", str(root) + os.sep)
        return cp

    java_dir = root / "java"
    if java_dir.is_dir():
        sep = ";" if platform.system() == "Windows" else ":"
        jars = [str(path) for path in sorted(java_dir.glob("*.jar"))]
        if jars:
            return sep.join(jars) + sep + str(java_dir) + sep
    return str(root / "java" / "")


def _default_pz_jvm_args(root: Path) -> list[str]:
    lib_path = "natives/;natives/win64/;." if platform.system() == "Windows" else "natives/:natives/linux64/:."
    return [
        "-Djava.awt.headless=true",
        "-Dzomboid.steam=1",
        "-Dzomboid.znetlog=1",
        "-XX:+UseZGC",
        "-XX:-CreateCoredumpOnCrash",
        "-XX:-OmitStackTraceInFastThrow",
        "-Xms4g",
        "-Xmx4g",
        f"-Djava.library.path={lib_path}",
        f"-Duser.home={root.resolve()}",
    ]


def _extract_pz_jvm_args(script_text: str, root: Path) -> list[str]:
    for line in script_text.splitlines():
        if "GameServer" not in line or "java" not in line.lower():
            continue
        cleaned = re.sub(r"%[12]", "", line)
        match = re.search(r'java(?:\.exe)?"\s+(.+?)\s+-cp\s+', cleaned, re.I)
        if not match:
            match = re.search(r"java(?:\.exe)?\s+(.+?)\s+-cp\s+", cleaned, re.I)
        if match:
            args = _split_pz_cmd_tokens(match.group(1))
            args = [arg for arg in args if not arg.startswith("-Duser.home=")]
            args.append(f"-Duser.home={root.resolve()}")
            return args
    return _default_pz_jvm_args(root)


def _pz_game_args(config: dict) -> list[str]:
    profile = pz_server_profile(config)
    port = _pz_port(config)
    udp_port = _pz_udp_port(config, port)
    args = [
        "-servername", profile,
        "-port", str(port),
        "-udpport", str(udp_port),
        "-statistic", "0",
    ]
    admin_pw = str(config.get("admin_password", "")).strip()
    if admin_pw:
        args += ["-adminpassword", admin_pw]
    extra = str(config.get("extra_args", "")).strip()
    if extra:
        args += extra.split()
    return args


def _find_pz_java(root: Path) -> Path | None:
    for rel in ("jre64/bin/java.exe", "jre/bin/java.exe", "jre64/bin/java", "jre/bin/java"):
        candidate = root / rel.replace("/", os.sep)
        if candidate.is_file():
            return candidate
    return None


def build_pz_start_command(server_dir: Path, config: dict) -> tuple[list[str], dict]:
    root = server_dir.resolve()
    script = find_pz_start_script(root)
    if script is None:
        raise FileNotFoundError(
            "StartServer64.bat / start-server.sh not found — install via SteamCMD first."
        )

    install_root = script.parent
    game_args = _pz_game_args(config)
    popen_extra = {"cwd": str(install_root)}

    if script.suffix.lower() == ".sh":
        return ["bash", str(script.resolve()), *game_args], popen_extra

    java = _find_pz_java(install_root)
    if java is None:
        return [str(script.resolve()), *game_args], popen_extra

    script_text = script.read_text(encoding="utf-8", errors="replace")
    jvm_args = _extract_pz_jvm_args(script_text, install_root)
    classpath = _build_pz_classpath(install_root, script_text)
    args = [
        str(java.resolve()),
        *jvm_args,
        "-cp",
        classpath,
        "zombie.network.GameServer",
        *game_args,
    ]
    return args, popen_extra


class ProjectZomboidAdapter(GameServerAdapter):
    game_type = "project_zomboid"
    display_name = "Project Zomboid"
    icon = "🧟"
    description = "Project Zomboid dedicated server (Steam App ID 380870)."
    steam_app_id = PZ_STEAM_APP_ID

    def default_port(self) -> int:
        return 16261

    def port_protocol(self) -> str:
        return "UDP"

    def supports_steam_install(self) -> bool:
        return True

    def steam_app_id_for(self, config: dict) -> str:
        return str(config.get("steam_app_id") or self.steam_app_id).strip()

    def executable_marker(self, server_dir: Path) -> Path:
        found = find_pz_start_script(server_dir)
        if found is not None:
            return found
        return server_dir / _exe("StartServer64.bat", "start-server.sh")

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return find_pz_start_script(server_dir) is not None

    def create_install_worker(self, server_dir: Path, config: dict, on_event=None):
        from .install import create_steamcmd_install_worker

        app_id = self.steam_app_id_for(config)
        return create_steamcmd_install_worker(
            server_dir,
            app_id,
            verify=lambda directory: find_pz_start_script(directory) is not None,
        )

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("server_profile", "Config profile", "text", "servertest", width=140),
            ConfigField("server_name", "Public name", "text", "PZ Server", width=160),
            ConfigField("admin_password", "Admin password", "text", "", width=140),
            ConfigField("port", "Game port (UDP)", "text", "16261", width=100),
            ConfigField("udp_port", "UDP port 2", "text", "", width=100),
            ConfigField("max_players", "Max players", "text", "32", width=80),
            ConfigField(
                "public",
                "Server list",
                "menu",
                "Public",
                ["Private", "Public"],
                width=120,
            ),
            ConfigField("extra_args", "Extra startup args", "text", "", width=220),
        ]

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        return build_pz_start_command(server_dir, config)

    def pre_start_checks(self, server_dir: Path, config: dict) -> tuple[bool, str]:
        if not self.is_installed(server_dir):
            return False, (
                "StartServer64.bat / start-server.sh not found — use Install via SteamCMD on the Config tab."
            )
        admin_pw = str(config.get("admin_password", "")).strip()
        if not admin_pw:
            return False, (
                "Set an admin password in Config — required for unattended start "
                "(avoids the first-run interactive prompt)."
            )
        if len(admin_pw) < 4:
            return False, "Admin password should be at least 4 characters."
        sync_pz_server_ini(server_dir, config)
        profile = pz_server_profile(config)
        return True, f"Ready — profile '{profile}', data in Zomboid/ under the server folder."

    def quick_commands(self) -> list[tuple[str, str]]:
        return [
            ("save", "save"),
            ('servermsg "Hello!"', 'servermsg "Hello!"'),
            ("players", "players"),
            ("showoptions", "showoptions"),
            ("reloadoptions", "reloadoptions"),
            ("quit", "quit"),
        ]

    def graceful_stop_command(self) -> str:
        return "quit"

    def player_command(self, action: str, player: str) -> str | None:
        if action == "kick":
            quoted = f'"{player}"' if " " in player else player
            return f"kickuser {quoted}"
        return None

    def parse_log_line(self, line: str) -> ServerEvent | None:
        if "SERVER STARTED" in line.upper():
            return ServerEvent(kind="ready", message=line)
        join = re.search(
            r"(?:Connected player|Player connected|joined).*?name=([^\s,\]]+)",
            line,
            re.I,
        )
        if join:
            return ServerEvent(kind="player_join", player=join.group(1).strip().strip("'\""))
        leave = re.search(
            r"(?:Disconnected|Player disconnected|left).*?name=([^\s,\]]+)",
            line,
            re.I,
        )
        if leave:
            return ServerEvent(kind="player_leave", player=leave.group(1).strip().strip("'\""))
        return None

    def log_tag_rules(self) -> list[LogTagRule]:
        return super().log_tag_rules() + [
            LogTagRule(re.compile(r"SERVER STARTED", re.I), "log_ready"),
            LogTagRule(re.compile(r"Connected player|Player connected", re.I), "log_join"),
            LogTagRule(re.compile(r"Disconnected|Player disconnected", re.I), "log_leave"),
            LogTagRule(re.compile(r"Saving|Save finished", re.I), "log_save"),
            LogTagRule(re.compile(r"^>", re.I), "command"),
        ]

    def log_file_candidates(self, server_dir: Path) -> list[Path]:
        zomboid = pz_zomboid_dir(server_dir)
        return [
            zomboid / "console.txt",
            zomboid / "Logs" / "logs.txt",
            *super().log_file_candidates(server_dir),
        ]

    def supports_mods(self) -> bool:
        return True

    def mods_directory(self, server_dir: Path) -> Path | None:
        return pz_zomboid_dir(server_dir) / "mods"

    def mods_empty_message(self) -> str:
        return (
            "No mods in Zomboid/mods.\n"
            "Add mod folders here and list them in Server/<profile>.ini (Mods=…, WorkshopItems=…).\n"
            "Sandbox settings live in Server/<profile>_SandboxVars.lua."
        )

    def overview_rows(
        self,
        server_dir: Path,
        config: dict,
        *,
        running: bool = False,
    ) -> list[tuple[str, str]]:
        rows = super().overview_rows(server_dir, config, running=running)
        profile = pz_server_profile(config)
        port = _pz_port(config)
        udp_port = _pz_udp_port(config, port)
        insert_at = next(
            (index + 1 for index, (label, _) in enumerate(rows) if label == "Port"),
            len(rows),
        )
        rows.insert(insert_at, ("Profile", profile))
        rows.insert(insert_at + 1, ("UDP ports", f"{port} / {udp_port}"))
        listing = "Public" if _pz_public_enabled(config) else "Private"
        rows.insert(insert_at + 2, ("Listing", listing))
        ini_path = pz_server_config_dir(server_dir) / f"{profile}.ini"
        if ini_path.is_file():
            try:
                settings_label = str(ini_path.relative_to(server_dir.resolve()))
            except ValueError:
                settings_label = str(ini_path)
        else:
            settings_label = f"Zomboid/Server/{profile}.ini (created on start)"
        rows.append(("Settings", settings_label))
        return rows

    def setup_panel_hints(self) -> list[str]:
        return [
            f"Install via SteamCMD on the Config tab (App ID {self.steam_app_id}).",
            "Set an admin password before the first start — login in-game as admin with that password.",
            "Server data is stored in Zomboid/ inside your server folder (not %USERPROFILE%).",
            "Edit Server/<profile>_SandboxVars.lua for gameplay; .ini for ports, mods, and listing.",
            "Forward UDP 16261–16262 (use the next pair for a second instance on the same machine).",
            "Stop with quit (or the Stop button) — never force-kill during a save.",
        ]


class SteamCmdAdapter(GameServerAdapter):
    game_type = "steamcmd"
    display_name = "SteamCMD Server"
    icon = "🎮"
    description = "Generic SteamCMD dedicated server — you specify the app ID and executable."

    def default_port(self) -> int:
        return 27015

    def supports_steam_install(self) -> bool:
        return True

    def steam_app_id_for(self, config: dict) -> str:
        return str(config.get("steam_app_id", "")).strip()

    def executable_marker(self, server_dir: Path) -> Path:
        exe = self._configured_exe(server_dir, {})
        return server_dir / exe if exe else server_dir / ".missing"

    def _configured_exe(self, server_dir: Path, config: dict) -> str:
        return str(config.get("executable") or "").strip()

    def is_installed(self, server_dir: Path) -> bool:
        exe = self._configured_exe(server_dir, {})
        return bool(exe) and (server_dir / exe).exists()

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        exe = self._configured_exe(server_dir, config)
        if not exe:
            raise ValueError("Set the server executable name in Config first.")
        args = [str(server_dir / exe)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {}

    def pre_start_checks(self, server_dir: Path, config: dict) -> tuple[bool, str]:
        if not self.is_installed(server_dir):
            app_id = self.steam_app_id_for(config)
            return False, f"Executable not found. Install with SteamCMD app {app_id or '(set App ID)'}."
        return True, "Ready to start."

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("steam_app_id", "Steam App ID", "text", "2394010", width=120),
            ConfigField("executable", "Executable (relative)", "text", "PalServer.exe", width=160),
            ConfigField("port", "Port", "text", str(self.default_port()), width=100),
            ConfigField("extra_args", "Extra startup args", "text", "", width=220),
            ConfigField("stop_command", "Graceful stop command", "text", "", width=140),
        ]

    def overview_rows(
        self,
        server_dir: Path,
        config: dict,
        *,
        running: bool = False,
    ) -> list[tuple[str, str]]:
        rows = super().overview_rows(server_dir, config, running=running)
        rows.append(("Steam App ID", config.get("steam_app_id", "—")))
        rows.append(("Executable", config.get("executable", "—")))
        return rows

    def setup_panel_hints(self) -> list[str]:
        return [
            "Install via SteamCMD in the Config tab, then set the relative executable path.",
            "Example: steamcmd +force_install_dir <folder> +login anonymous +app_update <id> validate +quit",
        ]


class CustomServerAdapter(GameServerAdapter):
    game_type = "custom"
    display_name = "Custom Server"
    icon = "⚙️"
    description = "Any dedicated server — specify executable, working directory, and arguments."

    def default_port(self) -> int:
        return 25565

    def executable_marker(self, server_dir: Path) -> Path:
        return server_dir

    def is_installed(self, server_dir: Path) -> bool:
        return server_dir.is_dir()

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        exe = str(config.get("executable", "")).strip()
        if not exe:
            raise ValueError("Set the server executable in Config first.")
        exe_path = Path(exe)
        if not exe_path.is_absolute():
            exe_path = server_dir / exe
        args = [str(exe_path)]
        startup = str(config.get("startup_args", "")).strip()
        if startup:
            args += startup.split()
        work_dir = str(config.get("work_dir", "")).strip()
        extra: dict = {}
        if work_dir:
            extra["cwd"] = str(Path(work_dir) if Path(work_dir).is_absolute() else server_dir / work_dir)
        return args, extra

    def pre_start_checks(self, server_dir: Path, config: dict) -> tuple[bool, str]:
        exe = str(config.get("executable", "")).strip()
        if not exe:
            return False, "Configure the executable path in the Config tab."
        exe_path = Path(exe)
        if not exe_path.is_absolute():
            exe_path = server_dir / exe
        if not exe_path.exists():
            return False, f"Executable not found: {exe_path}"
        return True, "Ready to start."

    def graceful_stop_command(self) -> str:
        return ""

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("executable", "Executable", "text", "server.exe", width=180),
            ConfigField("startup_args", "Startup arguments", "text", "", width=220),
            ConfigField("work_dir", "Working dir (optional)", "text", "", width=180),
            ConfigField("port", "Port (display)", "text", str(self.default_port()), width=100),
            ConfigField("stop_command", "Graceful stop command", "text", "stop", width=120),
        ]

    def overview_rows(
        self,
        server_dir: Path,
        config: dict,
        *,
        running: bool = False,
    ) -> list[tuple[str, str]]:
        rows = super().overview_rows(server_dir, config, running=running)
        rows.append(("Executable", config.get("executable", "—")))
        if config.get("startup_args"):
            rows.append(("Args", config["startup_args"]))
        return rows

    def setup_panel_hints(self) -> list[str]:
        return ["Point at any folder and specify the executable plus optional startup arguments."]
