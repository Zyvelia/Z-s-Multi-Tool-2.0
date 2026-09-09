"""Shared event types for downloads and running server processes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DownloadEvent:
    kind: str  # "progress" | "done" | "error"
    downloaded: int = 0
    total: int = 0
    message: str = ""


@dataclass
class ServerEvent:
    kind: str  # "log" | "ready" | "player_join" | "player_leave" | "stopped"
    message: str = ""
    player: str = ""
    exit_code: int | None = None
