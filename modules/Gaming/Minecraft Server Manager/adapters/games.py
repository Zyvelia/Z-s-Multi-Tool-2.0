"""Shared helpers for Steam-based and generic dedicated servers."""

from __future__ import annotations

import platform
import re
from pathlib import Path

from .base import ConfigField, ConfigSection, GameServerAdapter, LogTagRule


def _exe(name_win: str, name_linux: str) -> str:
    return name_win if platform.system() == "Windows" else name_linux


class SteamDedicatedAdapter(GameServerAdapter):
    """Base for servers typically installed via SteamCMD."""

    steam_app_id: str = ""
    executable_win: str = ""
    executable_linux: str = ""
    default_stop_command: str = "quit"

    def executable_name(self) -> str:
        return _exe(self.executable_win, self.executable_linux)

    def executable_marker(self, server_dir: Path) -> Path:
        return server_dir / self.executable_name()

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
            hint = f"Install via SteamCMD (App ID {self.steam_app_id}) or place {self.executable_name()} in the server folder."
            return False, hint
        return True, "Ready to start."

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [
            ConfigField("port", "Port", "text", str(self.default_port()), width=100),
            ConfigField("extra_args", "Extra startup args", "text", "", width=220),
            ConfigField("steam_app_id", "Steam App ID", "text", self.steam_app_id, width=120),
        ]

    def overview_rows(self, server_dir: Path, config: dict) -> list[tuple[str, str]]:
        rows = super().overview_rows(server_dir, config)
        rows.append(("Steam App ID", self.steam_app_id or config.get("steam_app_id", "—")))
        if config.get("extra_args"):
            rows.append(("Extra args", config["extra_args"]))
        return rows

    def setup_panel_hints(self) -> list[str]:
        return [
            f"Use Install via SteamCMD in the Config tab, or run: steamcmd +app_update {self.steam_app_id} validate",
            f"Expected executable: {self.executable_name()}",
        ]

    def supports_steam_install(self) -> bool:
        return bool(self.steam_app_id)

    def config_sections(self, server_dir: Path) -> list[ConfigSection]:
        return [
            ConfigSection(
                title="Network",
                hint="Port and optional extra arguments passed to the server binary.",
                fields=[
                    ConfigField("port", "Port", "text", str(self.default_port()), width=100),
                    ConfigField("extra_args", "Extra startup args", "text", "", width=240,
                                hint="Appended after the executable."),
                ],
            ),
            ConfigSection(
                title="Steam",
                hint="Used by the one-click SteamCMD installer in Config.",
                fields=[
                    ConfigField("steam_app_id", "Steam App ID", "text", self.steam_app_id, width=120),
                ],
            ),
        ]


class SatisfactoryAdapter(SteamDedicatedAdapter):
    game_type = "satisfactory"
    display_name = "Satisfactory"
    icon = "🏭"
    description = "Satisfactory dedicated server (Steam App ID 1690800)."
    steam_app_id = "1690800"
    executable_win = "FactoryServer.exe"
    executable_linux = "FactoryServer.sh"
    default_stop_command = ""

    def default_port(self) -> int:
        return 7777

    def graceful_stop_command(self) -> str:
        return ""


class ValheimAdapter(SteamDedicatedAdapter):
    game_type = "valheim"
    display_name = "Valheim"
    icon = "⚔️"
    description = "Valheim dedicated server (Steam App ID 896660)."
    steam_app_id = "896660"
    executable_win = "valheim_server.exe"
    executable_linux = "valheim_server.x86_64"
    default_stop_command = ""

    def default_port(self) -> int:
        return 2456

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        name = config.get("world_name", "Dedicated")
        port = config.get("port", str(self.default_port()))
        password = config.get("password", "")
        public = "1" if str(config.get("public", "true")).lower() in ("true", "1", "yes") else "0"
        if platform.system() == "Windows" and self.executable_marker(server_dir).exists():
            exe = self.executable_marker(server_dir)
            args = [
                str(exe),
                "-name", str(config.get("server_name", "Valheim Server")),
                "-port", str(port),
                "-world", str(name),
                "-password", str(password),
                "-public", public,
            ]
            extra = str(config.get("extra_args", "")).strip()
            if extra:
                args += extra.split()
            return args, {}
        script = server_dir / "start_server.sh"
        if script.exists():
            args = ["bash", str(script)]
            extra = str(config.get("extra_args", "")).strip()
            if extra:
                args += extra.split()
            return args, {}
        return super().build_start_command(server_dir, config)

    def config_sections(self, server_dir: Path) -> list[ConfigSection]:
        return [
            ConfigSection(
                title="World",
                fields=[
                    ConfigField("server_name", "Server name", "text", "Valheim Server", width=180),
                    ConfigField("world_name", "World name", "text", "Dedicated", width=140),
                    ConfigField("password", "Password", "password", "", width=140,
                                hint="Leave empty for no password."),
                    ConfigField("public", "Public listing", "checkbox", "true"),
                ],
            ),
            ConfigSection(
                title="Network",
                fields=[
                    ConfigField("port", "Port", "text", str(self.default_port()), width=100),
                    ConfigField("extra_args", "Extra args", "text", "", width=240),
                ],
            ),
            ConfigSection(
                title="Steam",
                fields=[
                    ConfigField("steam_app_id", "Steam App ID", "text", self.steam_app_id, width=120),
                ],
            ),
        ]


class PalworldAdapter(SteamDedicatedAdapter):
    game_type = "palworld"
    display_name = "Palworld"
    icon = "🐾"
    description = "Palworld dedicated server (Steam App ID 2394010)."
    steam_app_id = "2394010"
    executable_win = "PalServer.exe"
    executable_linux = "PalServer.sh"
    default_stop_command = ""

    def default_port(self) -> int:
        return 8211

    def config_sections(self, server_dir: Path) -> list[ConfigSection]:
        return [
            ConfigSection(
                title="Server",
                fields=[
                    ConfigField("server_name", "Server name", "text", "Palworld Server", width=180),
                    ConfigField("admin_password", "Admin password", "password", "", width=160),
                    ConfigField("max_players", "Max players", "text", "32", width=80),
                ],
            ),
            ConfigSection(
                title="Network",
                fields=[
                    ConfigField("port", "Port", "text", str(self.default_port()), width=100),
                    ConfigField("extra_args", "Extra args", "text", "", width=240),
                ],
            ),
            ConfigSection(
                title="Steam",
                fields=[
                    ConfigField("steam_app_id", "Steam App ID", "text", self.steam_app_id, width=120),
                ],
            ),
        ]


class TerrariaAdapter(GameServerAdapter):
    game_type = "terraria"
    display_name = "Terraria"
    icon = "🌳"
    description = "Terraria dedicated server executable."

    def default_port(self) -> int:
        return 7777

    def executable_marker(self, server_dir: Path) -> Path:
        name = _exe("TerrariaServer.exe", "TerrariaServer.bin.x86_64")
        return server_dir / name

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        exe = self.executable_marker(server_dir)
        world = config.get("world_file", "world.wld")
        port = config.get("port", str(self.default_port()))
        args = [str(exe), "-world", str(server_dir / world), "-port", str(port)]
        extra = str(config.get("extra_args", "")).strip()
        if extra:
            args += extra.split()
        return args, {}

    def pre_start_checks(self, server_dir: Path, config: dict) -> tuple[bool, str]:
        if not self.is_installed(server_dir):
            return False, "TerrariaServer executable not found in the server folder."
        return True, "Ready to start."

    def config_sections(self, server_dir: Path) -> list[ConfigSection]:
        return [
            ConfigSection(
                title="World",
                hint="Place TerrariaServer.exe and your .wld file in the server folder.",
                fields=[
                    ConfigField("world_file", "World file", "text", "world.wld", width=180),
                    ConfigField("port", "Port", "text", str(self.default_port()), width=100),
                    ConfigField("max_players", "Max players", "text", "8", width=80),
                    ConfigField("extra_args", "Extra args", "text", "", width=200),
                ],
            ),
        ]

    def setup_panel_hints(self) -> list[str]:
        return ["Place TerrariaServer.exe and your .wld world file in the server folder."]


class ProjectZomboidAdapter(GameServerAdapter):
    game_type = "project_zomboid"
    display_name = "Project Zomboid"
    icon = "🧟"
    description = "Project Zomboid dedicated server."

    def default_port(self) -> int:
        return 16261

    def executable_marker(self, server_dir: Path) -> Path:
        name = _exe("StartServer64.bat", "start-server.sh")
        return server_dir / name

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        marker = self.executable_marker(server_dir)
        if platform.system() == "Windows":
            return ["cmd", "/c", str(marker)], {}
        return ["bash", str(marker)], {}

    def pre_start_checks(self, server_dir: Path, config: dict) -> tuple[bool, str]:
        if not self.is_installed(server_dir):
            return False, "StartServer64.bat / start-server.sh not found."
        return True, "Ready to start."

    def config_sections(self, server_dir: Path) -> list[ConfigSection]:
        ini_hint = "Edit Server/servertest.ini directly via the Files tab for advanced settings."
        return [
            ConfigSection(
                title="Server",
                hint=ini_hint,
                fields=[
                    ConfigField("server_name", "Server name", "text", "PZ Server", width=180),
                    ConfigField("port", "Port", "text", str(self.default_port()), width=100),
                    ConfigField("max_players", "Max players", "text", "16", width=80),
                    ConfigField("password", "Server password", "password", "", width=140),
                ],
            ),
        ]

    def setup_panel_hints(self) -> list[str]:
        return ["Use the official dedicated server files from Steam. Edit servertest.ini / ServerSettings.ini as needed."]


class SteamCmdAdapter(GameServerAdapter):
    game_type = "steamcmd"
    display_name = "SteamCMD Server"
    icon = "🎮"
    description = "Generic SteamCMD dedicated server — you specify the app ID and executable."

    def default_port(self) -> int:
        return 27015

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
            app_id = config.get("steam_app_id", "")
            return False, f"Executable not found. Install with SteamCMD app {app_id or '(set App ID)'}."
        return True, "Ready to start."

    def supports_steam_install(self) -> bool:
        return True

    def config_sections(self, server_dir: Path) -> list[ConfigSection]:
        return [
            ConfigSection(
                title="Steam Install",
                hint="Set App ID and executable, then use Install via SteamCMD below.",
                fields=[
                    ConfigField("steam_app_id", "Steam App ID", "text", "2394010", width=120),
                    ConfigField("executable", "Executable (relative path)", "text", "PalServer.exe", width=200),
                ],
            ),
            ConfigSection(
                title="Runtime",
                fields=[
                    ConfigField("port", "Port", "text", str(self.default_port()), width=100),
                    ConfigField("extra_args", "Extra startup args", "text", "", width=240),
                ],
            ),
        ]

    def overview_rows(self, server_dir: Path, config: dict) -> list[tuple[str, str]]:
        rows = super().overview_rows(server_dir, config)
        rows.append(("Steam App ID", config.get("steam_app_id", "—")))
        rows.append(("Executable", config.get("executable", "—")))
        return rows

    def setup_panel_hints(self) -> list[str]:
        return [
            "Install SteamCMD, then: steamcmd +force_install_dir <folder> +login anonymous +app_update <id> validate +quit",
            "Set the relative path to the server executable after install.",
        ]


class CustomServerAdapter(GameServerAdapter):
    game_type = "custom"
    display_name = "Custom Server"
    icon = "⚙️"
    description = "Any dedicated server — specify executable, working directory, and arguments."

    def default_port(self) -> int:
        return 25565

    def executable_marker(self, server_dir: Path) -> Path:
        return server_dir  # folder must exist

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

    def config_sections(self, server_dir: Path) -> list[ConfigSection]:
        return [
            ConfigSection(
                title="Launch",
                fields=[
                    ConfigField("executable", "Executable", "text", "server.exe", width=200),
                    ConfigField("startup_args", "Startup arguments", "text", "", width=260),
                    ConfigField("work_dir", "Working dir (optional)", "text", "", width=200),
                    ConfigField("stop_command", "Graceful stop command", "text", "stop", width=140),
                ],
            ),
            ConfigSection(
                title="Display",
                fields=[
                    ConfigField("port", "Port (for address display)", "text", str(self.default_port()), width=100),
                ],
            ),
        ]

    def build_start_command_with_stop(self, server_dir: Path, config: dict):
        return self.build_start_command(server_dir, config)

    def graceful_stop_command_from_config(self, config: dict) -> str:
        return str(config.get("stop_command", "")).strip()

    def overview_rows(self, server_dir: Path, config: dict) -> list[tuple[str, str]]:
        rows = super().overview_rows(server_dir, config)
        rows.append(("Executable", config.get("executable", "—")))
        if config.get("startup_args"):
            rows.append(("Args", config["startup_args"]))
        return rows

    def setup_panel_hints(self) -> list[str]:
        return ["Point at any folder and specify the executable plus optional startup arguments."]
