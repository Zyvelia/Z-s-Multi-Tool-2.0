"""Base adapter interface for game server types."""

from __future__ import annotations

import abc
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.events import DownloadEvent, ServerEvent


@dataclass
class ConfigField:
    key: str
    label: str
    kind: str = "text"  # text | number | menu | checkbox | password
    default: str = ""
    choices: list[str] = field(default_factory=list)
    width: int = 120
    hint: str = ""


@dataclass
class ConfigSection:
    title: str
    fields: list[ConfigField]
    hint: str = ""


@dataclass
class LogTagRule:
    pattern: re.Pattern[str]
    tag: str


class GameServerAdapter(abc.ABC):
    """Each supported game implements this interface."""

    game_type: str
    display_name: str
    icon: str
    description: str = ""

    @abc.abstractmethod
    def default_port(self) -> int:
        ...

    def port_protocol(self) -> str:
        return "TCP"

    @abc.abstractmethod
    def executable_marker(self, server_dir: Path) -> Path:
        """File that must exist for the server to be considered installed."""

    def is_installed(self, server_dir: Path) -> bool:
        return self.executable_marker(server_dir).exists()

    def readiness_message(self, server_dir: Path) -> tuple[bool, str]:
        if not self.is_installed(server_dir):
            return False, f"{self.display_name} is not installed in this folder yet."
        ok, msg = self.pre_start_checks(server_dir, {})
        return ok, msg

    def pre_start_checks(self, server_dir: Path, config: dict) -> tuple[bool, str]:
        return True, "Ready to start."

    @abc.abstractmethod
    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        """Return argv and extra subprocess.Popen kwargs."""

    def graceful_stop_command(self) -> str:
        return "stop"

    def parse_log_line(self, line: str) -> ServerEvent | None:
        return None

    def log_tag_rules(self) -> list[LogTagRule]:
        return [
            LogTagRule(re.compile(r"ERROR\]|\bException\b|\bFATAL\b"), "log_error"),
            LogTagRule(re.compile(r"WARN\]"), "log_warn"),
        ]

    def quick_commands(self) -> list[tuple[str, str]]:
        return []

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return []

    def config_sections(self, server_dir: Path) -> list[ConfigSection]:
        fields = self.config_fields(server_dir)
        if not fields:
            return []
        return [ConfigSection(title="Server Settings", fields=fields)]

    def supports_steam_install(self) -> bool:
        return False

    def steam_app_id(self, config: dict) -> str:
        return str(config.get("steam_app_id") or getattr(self, "steam_app_id", "") or "")

    def read_config(self, server_dir: Path) -> dict[str, str]:
        return {}

    def write_config(self, server_dir: Path, updates: dict[str, str]) -> None:
        pass

    def player_command(self, action: str, player: str) -> str | None:
        if action == "kick":
            return f"kick {player}"
        return None

    def player_actions(self) -> list[tuple[str, str]]:
        return [("Kick", "kick")]

    def supports_mods(self) -> bool:
        return False

    def mods_directory(self, server_dir: Path) -> Path | None:
        return None

    def supports_install(self) -> bool:
        return False

    def create_install_worker(
        self, server_dir: Path, config: dict, on_event: Any = None
    ) -> threading.Thread | None:
        return None

    def overview_rows(self, server_dir: Path, config: dict) -> list[tuple[str, str]]:
        rows = [
            ("Game", self.display_name),
            ("Folder", str(server_dir)),
            ("Port", str(config.get("port") or self.default_port())),
            ("Protocol", self.port_protocol()),
        ]
        installed, status = self.readiness_message(server_dir)
        rows.append(("Install", "Installed" if installed else "Not installed"))
        if status and not installed:
            rows.append(("Status", status))
        return rows

    def setup_panel_hints(self) -> list[str]:
        return []
