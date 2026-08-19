"""Minecraft Bedrock Edition adapter — wraps existing backend logic."""

from __future__ import annotations

import os
import platform
import re
from pathlib import Path

from .. import backend as mc
from ..core.events import ServerEvent
from .base import ConfigField, GameServerAdapter, LogTagRule

_DIFFICULTIES = ["peaceful", "easy", "normal", "hard"]
_GAMEMODES = ["survival", "creative", "adventure"]

_READY_RE = re.compile(r"Server started\.")
_JOIN_RE = re.compile(r"Player connected: ([^,]+),")
_LEAVE_RE = re.compile(r"Player disconnected: ([^,]+),")


class MinecraftBedrockAdapter(GameServerAdapter):
    game_type = "minecraft_bedrock"
    display_name = "Minecraft Bedrock"
    icon = "🪨"
    description = "Official Bedrock Dedicated Server from Mojang's download API."

    def default_port(self) -> int:
        return 19132

    def port_protocol(self) -> str:
        return "UDP"

    def executable_marker(self, server_dir: Path) -> Path:
        return server_dir / mc.bedrock_executable_name()

    def pre_start_checks(self, server_dir: Path, config: dict) -> tuple[bool, str]:
        if not self.is_installed(server_dir):
            return False, "bedrock_server wasn't found — download it from the Config tab first."
        if not mc.bedrock_eula_acknowledged(server_dir):
            return False, "Mojang's EULA acknowledgement hasn't been recorded for this server yet."
        mc.ensure_bedrock_server_properties(server_dir)
        return True, "Ready to start."

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        exe = server_dir / mc.bedrock_executable_name()
        extra: dict = {}
        if platform.system() != "Windows":
            env = os.environ.copy()
            env["LD_LIBRARY_PATH"] = "."
            extra["env"] = env
        return [str(exe)], extra

    def parse_log_line(self, line: str) -> ServerEvent | None:
        if _READY_RE.search(line):
            return ServerEvent(kind="ready", message=line)
        m = _JOIN_RE.search(line)
        if m:
            return ServerEvent(kind="player_join", player=m.group(1).strip())
        m = _LEAVE_RE.search(line)
        if m:
            return ServerEvent(kind="player_leave", player=m.group(1).strip())
        return None

    def log_tag_rules(self) -> list[LogTagRule]:
        rules = super().log_tag_rules()
        rules.extend([
            LogTagRule(re.compile(r"Player connected: "), "log_join"),
            LogTagRule(re.compile(r"Player disconnected: "), "log_leave"),
        ])
        return rules

    def quick_commands(self) -> list[tuple[str, str]]:
        return [
            ("list", "list"),
            ("save hold", "save hold"),
            ("save resume", "save resume"),
            ("allowlist list", "allowlist list"),
            ("weather clear", "weather clear"),
            ("time set day", "time set day"),
            ("time set night", "time set night"),
            ("difficulty easy", "difficulty easy"),
            ("difficulty normal", "difficulty normal"),
            ("difficulty hard", "difficulty hard"),
            ("say Hello!", "say Hello!"),
        ]

    def player_command(self, action: str, player: str) -> str | None:
        if action == "kick":
            return f"kick {player}"
        if action.startswith("gamemode_"):
            mode = action.removeprefix("gamemode_")
            return f"gamemode {mode} {player}"
        return None

    def player_actions(self) -> list[tuple[str, str]]:
        return [
            ("Kick", "kick"),
            ("Creative", "gamemode_creative"),
            ("Survival", "gamemode_survival"),
            ("Adventure", "gamemode_adventure"),
        ]

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        props = mc.read_server_properties(server_dir)
        return [
            ConfigField("server-name", "Server name", "text", props.get("server-name", "Dedicated Server"), width=160),
            ConfigField("server-port", "Port (IPv4)", "text", props.get("server-port", "19132"), width=100),
            ConfigField("max-players", "Max players", "text", props.get("max-players", "10"), width=100),
            ConfigField("difficulty", "Difficulty", "menu", props.get("difficulty", "easy"), _DIFFICULTIES),
            ConfigField("gamemode", "Gamemode", "menu", props.get("gamemode", "survival"), _GAMEMODES),
            ConfigField("online-mode", "Online mode (Xbox Live)", "checkbox", props.get("online-mode", "true")),
            ConfigField("allow-list", "Allow-list only", "checkbox", props.get("allow-list", "false")),
        ]

    def read_config(self, server_dir: Path) -> dict[str, str]:
        return mc.read_server_properties(server_dir)

    def write_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        mc.update_server_properties(server_dir, updates)

    def supports_install(self) -> bool:
        return True

    def setup_panel_hints(self) -> list[str]:
        return [
            "Installs bedrock_server into your Game Servers folder.",
            "Installs the latest build for Stable or Preview channel.",
            "Bedrock uses UDP — forward the port accordingly.",
            "Accept Mojang's EULA before installing.",
            "Addons: drop packs into behavior_packs/ and resource_packs/.",
        ]

    def supports_mods(self) -> bool:
        return True

    def mods_directory(self, server_dir: Path) -> Path | None:
        return server_dir / "behavior_packs"

    def mods_directories(self, server_dir: Path) -> list[Path]:
        root = server_dir
        dirs = [
            root / "behavior_packs",
            root / "resource_packs",
            root / "development_behavior_packs",
            root / "development_resource_packs",
        ]
        worlds = root / "worlds"
        if worlds.is_dir():
            for world in worlds.iterdir():
                if world.is_dir():
                    dirs.extend((world / "behavior_packs", world / "resource_packs"))
        return dirs

    def mod_file_extensions(self) -> tuple[str, ...] | None:
        return (".mcpack", ".mcaddon", ".zip")

    def collect_mod_files(self, server_dir: Path) -> list[Path]:
        found = list(super().collect_mod_files(server_dir))
        seen = {str(p).lower() for p in found}
        for mod_dir in self.mods_directories(server_dir):
            if not mod_dir.exists():
                continue
            for child in mod_dir.iterdir():
                if child.is_dir() and (child / "manifest.json").is_file():
                    key = str(child).lower()
                    if key not in seen:
                        found.append(child)
                        seen.add(key)
        return sorted(found, key=lambda p: str(p).lower())

    def mods_empty_message(self) -> str:
        return (
            "No behavior or resource packs found.\n"
            "Drop .mcpack / .mcaddon files into behavior_packs/ or resource_packs/, "
            "or extract pack folders (with manifest.json) there.\n"
            "Enable packs in worlds/<level>/world_behavior_packs.json after adding them."
        )

    def mods_browser_urls(self) -> dict[str, str]:
        return {
            "modrinth": "https://modrinth.com/mods?g=categories:bedrock",
            "curseforge": "https://www.curseforge.com/minecraft-bedrock/addons",
        }

    def overview_rows(
        self,
        server_dir: Path,
        config: dict,
        *,
        running: bool = False,
    ) -> list[tuple[str, str]]:
        rows = super().overview_rows(server_dir, config, running=running)
        if mc.bedrock_eula_acknowledged(server_dir):
            rows.append(("EULA", "Acknowledged"))
        version = config.get("installed_version")
        if version:
            rows.append(("Version", version))
        channel = config.get("bedrock_channel", "stable")
        rows.append(("Channel", channel.title()))
        return rows
