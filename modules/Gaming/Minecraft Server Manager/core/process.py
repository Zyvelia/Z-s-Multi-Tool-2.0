"""Generic server process runner driven by a game adapter."""

from __future__ import annotations

import platform
import queue
import subprocess
import threading
import time
from pathlib import Path

from .events import ServerEvent
from ..adapters.base import GameServerAdapter

_CREATE_NO_WINDOW = 0x08000000


class ServerProcess:
    """One running (or most-recently-run) server process."""

    def __init__(self, adapter: GameServerAdapter | None = None):
        self.adapter = adapter
        self.config: dict = {}
        self.proc: subprocess.Popen | None = None
        self.events: queue.Queue[ServerEvent] = queue.Queue()
        self.players: set[str] = set()
        self.started_at: float | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, server_dir: Path, config: dict, adapter: GameServerAdapter) -> str:
        if self.running:
            return "Server is already running."

        ok, msg = adapter.pre_start_checks(server_dir, config)
        if not ok:
            return msg

        try:
            args, extra = adapter.build_start_command(server_dir, config)
        except Exception as e:  # noqa: BLE001
            return f"Couldn't build start command: {e}"

        popen_kwargs: dict = dict(
            cwd=str(server_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        if platform.system() == "Windows":
            popen_kwargs["creationflags"] = _CREATE_NO_WINDOW
        popen_kwargs.update(extra)

        try:
            self.proc = subprocess.Popen(args, **popen_kwargs)
        except OSError as e:
            self.proc = None
            return f"Couldn't start the server: {e}"

        self.adapter = adapter
        self.config = dict(config)
        self.players.clear()
        self.started_at = time.time()
        threading.Thread(target=self._read_loop, daemon=True).start()
        return ""

    def _read_loop(self) -> None:
        proc = self.proc
        adapter = self.adapter
        assert proc is not None and proc.stdout is not None

        for raw_line in proc.stdout:
            line = raw_line.rstrip("\r\n")
            if not line:
                continue
            self.events.put(ServerEvent(kind="log", message=line))
            if adapter is not None:
                parsed = adapter.parse_log_line(line)
                if parsed is not None:
                    if parsed.kind == "ready":
                        self.events.put(parsed)
                    elif parsed.kind == "player_join" and parsed.player:
                        self.players.add(parsed.player)
                        self.events.put(parsed)
                    elif parsed.kind == "player_leave" and parsed.player:
                        self.players.discard(parsed.player)
                        self.events.put(parsed)

        exit_code = proc.wait() if proc else None
        self.events.put(ServerEvent(kind="stopped", exit_code=exit_code))
        self.proc = None
        self.started_at = None

    def send(self, command: str) -> bool:
        if not self.running or self.proc.stdin is None:
            return False
        try:
            self.proc.stdin.write(command.rstrip("\n") + "\n")
            self.proc.stdin.flush()
            return True
        except OSError:
            return False

    def stop(self, graceful: bool = True) -> None:
        if not self.running:
            return
        if graceful and self.adapter is not None:
            cmd = str(self.config.get("stop_command", "")).strip()
            if not cmd:
                cmd = self.adapter.graceful_stop_command()
            if cmd:
                self.send(cmd)
                return
        self.proc.kill()
