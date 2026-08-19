"""Minecraft Java Edition adapter — wraps existing backend logic."""

from __future__ import annotations

import re
from pathlib import Path

from .. import backend as mc
from ..core.events import ServerEvent
from .base import ConfigField, GameServerAdapter, LogTagRule

_DIFFICULTIES = ["peaceful", "easy", "normal", "hard"]
_GAMEMODES = ["survival", "creative", "adventure", "spectator"]

_READY_RE = re.compile(r"Done \([\d.]+s\)! For help")
_JOIN_RE = re.compile(r": ([A-Za-z0-9_]{1,16}) joined the game")
_LEAVE_RE = re.compile(r": ([A-Za-z0-9_]{1,16}) left the game")


class MinecraftJavaAdapter(GameServerAdapter):
    game_type = "minecraft_java"
    display_name = "Minecraft Java"
    icon = "⛏️"
    description = "Official Mojang Java server.jar with version picker and SHA1-verified downloads."

    def default_port(self) -> int:
        return 25565

    def executable_marker(self, server_dir: Path) -> Path:
        return server_dir / "server.jar"

    def pre_start_checks(self, server_dir: Path, config: dict) -> tuple[bool, str]:
        if not self.is_installed(server_dir):
            return False, "server.jar wasn't found — download it from the Config tab first."
        if not mc.eula_accepted(server_dir):
            return False, "Mojang's EULA hasn't been accepted for this server yet."
        return True, "Ready to start."

    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        min_mb = int(config.get("min_mb", 1024))
        max_mb = int(config.get("max_mb", 2048))
        java_path = config.get("java_path", "java")
        extra_args = config.get("extra_args", "")
        args = [java_path, f"-Xms{min_mb}M", f"-Xmx{max_mb}M"]
        if str(extra_args).strip():
            args += str(extra_args).split()
        args += ["-jar", "server.jar", "nogui"]
        return args, {}

    def parse_log_line(self, line: str) -> ServerEvent | None:
        if _READY_RE.search(line):
            return ServerEvent(kind="ready", message=line)
        m = _JOIN_RE.search(line)
        if m:
            return ServerEvent(kind="player_join", player=m.group(1))
        m = _LEAVE_RE.search(line)
        if m:
            return ServerEvent(kind="player_leave", player=m.group(1))
        return None

    def log_tag_rules(self) -> list[LogTagRule]:
        rules = super().log_tag_rules()
        rules.extend([
            LogTagRule(re.compile(r" joined the game"), "log_join"),
            LogTagRule(re.compile(r" left the game"), "log_leave"),
        ])
        return rules

    def quick_commands(self) -> list[tuple[str, str]]:
        return [
            ("list", "list"),
            ("save-all", "save-all"),
            ("save-off", "save-off"),
            ("save-on", "save-on"),
            ("weather clear", "weather clear"),
            ("weather rain", "weather rain"),
            ("time day", "time set day"),
            ("time night", "time set night"),
            ("difficulty easy", "difficulty easy"),
            ("difficulty normal", "difficulty normal"),
            ("difficulty hard", "difficulty hard"),
            ("gm survival", "defaultgamemode survival"),
            ("gm creative", "defaultgamemode creative"),
            ("gm adventure", "defaultgamemode adventure"),
            ("gm spectator", "defaultgamemode spectator"),
            ("whitelist on", "whitelist on"),
            ("whitelist off", "whitelist off"),
            ("whitelist list", "whitelist list"),
            ("say Hello!", "say Hello!"),
            ("banlist", "banlist"),
            ("banlist players", "banlist players"),
        ]

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        props = mc.read_server_properties(server_dir)
        return [
            ConfigField("server-port", "Port", "text", props.get("server-port", "25565"), width=100),
            ConfigField("max-players", "Max players", "text", props.get("max-players", "20"), width=100),
            ConfigField("motd", "MOTD", "text", props.get("motd", "A Minecraft Server"), width=160),
            ConfigField("difficulty", "Difficulty", "menu", props.get("difficulty", "easy"), _DIFFICULTIES),
            ConfigField("gamemode", "Gamemode", "menu", props.get("gamemode", "survival"), _GAMEMODES),
            ConfigField("online-mode", "Online mode", "checkbox", props.get("online-mode", "true")),
            ConfigField("white-list", "Whitelist only", "checkbox", props.get("white-list", "false")),
        ]

    def read_config(self, server_dir: Path) -> dict[str, str]:
        return mc.read_server_properties(server_dir)

    def write_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        mc.update_server_properties(server_dir, updates)

    def player_command(self, action: str, player: str) -> str | None:
        if action == "kick":
            return f"kick {player}"
        if action == "op":
            return f"op {player}"
        if action.startswith("gamemode_"):
            mode = action.removeprefix("gamemode_")
            return f"gamemode {mode} {player}"
        return None

    def player_actions(self) -> list[tuple[str, str]]:
        return [
            ("Kick", "kick"),
            ("OP", "op"),
            ("Creative", "gamemode_creative"),
            ("Survival", "gamemode_survival"),
            ("Adventure", "gamemode_adventure"),
            ("Spectator", "gamemode_spectator"),
        ]

    def supports_mods(self) -> bool:
        return True

    def mods_directory(self, server_dir: Path) -> Path | None:
        return server_dir / "mods"

    def mod_file_extensions(self) -> tuple[str, ...] | None:
        return (".jar",)

    def mods_browser_urls(self) -> dict[str, str]:
        return {
            "modrinth": "https://modrinth.com/mods?q=minecraft",
            "curseforge": "https://www.curseforge.com/minecraft/mc-mods",
        }

    def mods_empty_message(self) -> str:
        return "No mods installed yet.\nDrop .jar files into the mods folder or browse Modrinth / CurseForge."

    def supports_install(self) -> bool:
        return True

    def setup_panel_hints(self) -> list[str]:
        return [
            "Installs server.jar directly into your Game Servers folder.",
            "Requires Java 21+ for current releases.",
            "Pick a version from Mojang's official manifest — downloads are SHA1-verified.",
            "Accept Mojang's EULA before installing.",
        ]

    def overview_rows(
        self,
        server_dir: Path,
        config: dict,
        *,
        running: bool = False,
    ) -> list[tuple[str, str]]:
        rows = super().overview_rows(server_dir, config, running=running)
        if mc.eula_accepted(server_dir):
            rows.append(("EULA", "Accepted"))
        version = config.get("installed_version")
        if version:
            rows.append(("Version", version))
        rows.append(("Memory", f"{config.get('min_mb', 1024)}–{config.get('max_mb', 2048)} MB"))
        return rows
