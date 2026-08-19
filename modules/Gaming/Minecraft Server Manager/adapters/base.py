"""Base adapter interface for game server types."""

from __future__ import annotations

import abc
import platform
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
    kind: str = "text"  # text | number | menu | checkbox
    default: str = ""
    choices: list[str] = field(default_factory=list)
    width: int = 120


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

    def is_installed(self, server_dir: Path, config: dict | None = None) -> bool:
        return self.executable_marker(server_dir).exists()

    def readiness_message(self, server_dir: Path, config: dict | None = None) -> tuple[bool, str]:
        if not self.is_installed(server_dir, config):
            return False, f"{self.display_name} is not installed in this folder yet."
        ok, msg = self.pre_start_checks(server_dir, config or {})
        return ok, msg

    def pre_start_checks(self, server_dir: Path, config: dict) -> tuple[bool, str]:
        return True, "Ready to start."

    @abc.abstractmethod
    def build_start_command(self, server_dir: Path, config: dict) -> tuple[list[str], dict]:
        """Return argv and extra subprocess.Popen kwargs."""

    def graceful_stop_command(self) -> str:
        return "stop"

    def execute_remote_command(
        self, command: str, config: dict, server_dir: Path
    ) -> tuple[bool, str] | None:
        """If implemented, handle console input outside stdin (RCON, HTTPS API, etc.)."""
        return None

    def prefers_remote_console(self, config: dict) -> bool:
        """When True, the Console tab sends commands via execute_remote_command."""
        return False

    def graceful_stop_remote(self, config: dict, server_dir: Path) -> tuple[bool, str] | None:
        """Graceful shutdown via RCON/API when stdin is unavailable."""
        return None

    def parse_log_line(self, line: str) -> ServerEvent | None:
        return None

    def log_tag_rules(self) -> list[LogTagRule]:
        return [
            LogTagRule(re.compile(r"ERROR\]|\bException\b|\bFATAL\b"), "log_error"),
            LogTagRule(re.compile(r"WARN\]"), "log_warn"),
        ]

    def log_file_candidates(self, server_dir: Path) -> list[Path]:
        return [
            server_dir / "logs" / "latest.log",
            server_dir / "log.txt",
            server_dir / "server.log",
        ]

    def quick_commands(self) -> list[tuple[str, str]]:
        return []

    def config_fields(self, server_dir: Path) -> list[ConfigField]:
        return []

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

    def mods_directories(self, server_dir: Path) -> list[Path]:
        primary = self.mods_directory(server_dir)
        return [primary] if primary else []

    def mod_file_extensions(self) -> tuple[str, ...] | None:
        """File suffixes to list; None = top-level files only in each mods folder."""
        return None

    def mods_empty_message(self) -> str:
        return "No mods installed yet."

    def mods_browser_urls(self) -> dict[str, str]:
        return {}

    def collect_mod_files(self, server_dir: Path) -> list[Path]:
        mod_dirs = self.mods_directories(server_dir)
        exts = self.mod_file_extensions()
        found: list[Path] = []
        for mod_dir in mod_dirs:
            if not mod_dir.exists():
                continue
            if exts:
                for ext in exts:
                    found.extend(mod_dir.rglob(f"*{ext}"))
            else:
                found.extend(f for f in mod_dir.iterdir() if f.is_file())
        return sorted(set(found), key=lambda p: str(p).lower())

    def supports_install(self) -> bool:
        return False

    def supports_steam_install(self) -> bool:
        return False

    def steam_app_id_for(self, config: dict) -> str:
        return str(config.get("steam_app_id", "")).strip()

    def create_install_worker(
        self, server_dir: Path, config: dict, on_event: Any = None
    ) -> threading.Thread | None:
        return None

    def overview_rows(
        self,
        server_dir: Path,
        config: dict,
        *,
        running: bool = False,
    ) -> list[tuple[str, str]]:
        rows = [
            ("Game", self.display_name),
            ("Folder", str(server_dir)),
            ("Port", str(config.get("port") or self.default_port())),
            ("Protocol", self.port_protocol()),
        ]
        server_installed = self.is_installed(server_dir, config) or running
        ready, status = self.readiness_message(server_dir, config)

        if running:
            server_label = "Installed (running)"
        elif server_installed:
            server_label = "Installed"
        else:
            server_label = "Not installed"
        rows.append(("Server files", server_label))

        if ready:
            rows.append(("Ready", "Yes"))
        elif status:
            rows.append(("Ready", "No"))
            rows.append(("Status", status))
        return rows

    def setup_panel_hints(self) -> list[str]:
        return []

    def console_command_line(self, command: str) -> str:
        """Format a command before writing to the server process stdin."""
        stripped = command.rstrip("\r\n")
        if platform.system() == "Windows":
            return stripped + "\r\n"
        return stripped + "\n"
