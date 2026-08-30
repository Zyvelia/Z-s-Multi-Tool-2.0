"""Generic server process runner driven by a game adapter."""

from __future__ import annotations

import platform
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .events import ServerEvent

if TYPE_CHECKING:
    from ..adapters.base import GameServerAdapter

_CREATE_NO_WINDOW = 0x08000000


class ServerProcess:
    """One running (or most-recently-run) server process."""

    def __init__(self, adapter: Any = None):
        self.adapter = adapter
        self.config: dict = {}
        self.proc: subprocess.Popen | None = None
        self.events: queue.Queue[ServerEvent] = queue.Queue()
        self.players: set[str] = set()
        self.player_join_times: dict[str, float] = {}
        self.started_at: float | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, server_dir: Path, config: dict, adapter: Any) -> str:
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
        self.server_dir: Path | None = server_dir.resolve()
        self.players.clear()
        self.player_join_times.clear()
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
                        self.player_join_times[parsed.player] = time.time()
                        self.events.put(parsed)
                    elif parsed.kind == "player_leave" and parsed.player:
                        self.players.discard(parsed.player)
                        self.player_join_times.pop(parsed.player, None)
                        self.events.put(parsed)

        exit_code = proc.wait() if proc else None
        self.events.put(ServerEvent(kind="stopped", exit_code=exit_code))
        self.proc = None
        self.started_at = None

    def send(self, command: str) -> bool:
        if not self.running or self.proc.stdin is None:
            return False
        try:
            formatter = getattr(self.adapter, "console_command_line", None)
            if formatter is not None:
                line = formatter(command)
            else:
                line = command.rstrip("\n") + "\n"
            self.proc.stdin.write(line)
            self.proc.stdin.flush()
            return True
        except OSError:
            return False

    def stop(self, graceful: bool = True) -> None:
        if not self.running:
            return
        if graceful and self.adapter is not None:
            remote_stop = getattr(self.adapter, "graceful_stop_remote", None)
            if remote_stop is not None and self.server_dir is not None:
                result = remote_stop(self.config, self.server_dir)
                if result is not None:
                    ok, _msg = result
                    if ok:
                        return
            cmd = str(self.config.get("stop_command", "")).strip()
            if not cmd:
                cmd = self.adapter.graceful_stop_command()
            if cmd:
                remote = getattr(self.adapter, "execute_remote_command", None)
                if remote is not None and self.server_dir is not None:
                    result = remote(cmd, self.config, self.server_dir)
                    if result is not None and result[0]:
                        return
                if self.send(cmd):
                    return
        self.proc.kill()
