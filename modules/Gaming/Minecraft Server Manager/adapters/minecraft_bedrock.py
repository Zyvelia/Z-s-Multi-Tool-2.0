"""Minecraft Bedrock Edition adapter — wraps existing backend logic."""

from __future__ import annotations

import os
import platform
import re
from pathlib import Path

from .. import backend as mc
from ..core.events import ServerEvent
from .base import ConfigField, ConfigSection, GameServerAdapter, LogTagRule

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
        return [("list", "list"), ("save hold", "save hold"), ("save resume", "save resume")]

    def config_sections(self, server_dir: Path) -> list[ConfigSection]:
        props = mc.read_server_properties(server_dir)
        return [
            ConfigSection(
                title="Server",
                fields=[
                    ConfigField("server-name", "Server name", "text", props.get("server-name", "Dedicated Server"), width=180),
                    ConfigField("max-players", "Max players", "text", props.get("max-players", "10"), width=100),
                    ConfigField("difficulty", "Difficulty", "menu", props.get("difficulty", "easy"), _DIFFICULTIES),
                    ConfigField("gamemode", "Gamemode", "menu", props.get("gamemode", "survival"), _GAMEMODES),
                ],
            ),
            ConfigSection(
                title="Network & Access",
                hint="Bedrock uses UDP — forward this port accordingly.",
                fields=[
                    ConfigField("server-port", "Port (IPv4)", "text", props.get("server-port", "19132"), width=100),
                    ConfigField("online-mode", "Online mode (Xbox Live)", "checkbox", props.get("online-mode", "true")),
                    ConfigField("allow-list", "Allow-list only", "checkbox", props.get("allow-list", "false")),
                ],
            ),
        ]

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return [f for sec in self.config_sections(server_dir) for f in sec.fields]

    def read_config(self, server_dir: Path) -> dict[str, str]:
        return mc.read_server_properties(server_dir)

    def write_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        mc.update_server_properties(server_dir, updates)

    def player_command(self, action: str, player: str) -> str | None:
        if action == "kick":
            return f"kick {player}"
        return None

    def supports_install(self) -> bool:
        return True

    def setup_panel_hints(self) -> list[str]:
        return [
            "Installs the latest build for Stable or Preview channel.",
            "Bedrock uses UDP — forward the port accordingly.",
            "Accept Mojang's EULA before installing.",
        ]

    def overview_rows(self, server_dir: Path, config: dict) -> list[tuple[str, str]]:
        rows = super().overview_rows(server_dir, config)
        if mc.bedrock_eula_acknowledged(server_dir):
            rows.append(("EULA", "Acknowledged"))
        version = config.get("installed_version")
        if version:
            rows.append(("Version", version))
        channel = config.get("bedrock_channel", "stable")
        rows.append(("Channel", channel.title()))
        return rows
