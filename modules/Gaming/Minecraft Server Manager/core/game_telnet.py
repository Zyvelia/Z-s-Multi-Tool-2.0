"""Simple telnet client for game admin consoles (7 Days to Die, etc.)."""

from __future__ import annotations

import socket
import time


class GameTelnetError(Exception):
    pass


class GameTelnetClient:
    def __init__(
        self,
        host: str,
        port: int,
        password: str,
        *,
        timeout: float = 5.0,
    ):
        self.host = host
        self.port = int(port)
        self.password = password
        self.timeout = timeout

    def execute(self, command: str) -> str:
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            banner = self._read_until_quiet(sock, max_wait=2.0)
            if "password" in banner.lower():
                sock.sendall((self.password + "\r\n").encode("ascii", errors="replace"))
                auth = self._read_until_quiet(sock, max_wait=2.0)
                if "denied" in auth.lower() or "invalid" in auth.lower():
                    raise GameTelnetError("Telnet authentication failed — check password in Config.")

            cmd = command.strip()
            if not cmd:
                return ""
            sock.sendall((cmd + "\r\n").encode("ascii", errors="replace"))
            time.sleep(0.25)
            return self._read_until_quiet(sock, max_wait=1.5).strip()

    def _read_until_quiet(self, sock: socket.socket, *, max_wait: float) -> str:
        chunks: list[str] = []
        deadline = time.time() + max_wait
        quiet_since: float | None = None
        while time.time() < deadline:
            try:
                data = sock.recv(4096)
            except socket.timeout:
                data = b""
            if data:
                chunks.append(data.decode("utf-8", errors="replace"))
                quiet_since = None
            else:
                if chunks:
                    if quiet_since is None:
                        quiet_since = time.time()
                    elif time.time() - quiet_since >= 0.2:
                        break
                time.sleep(0.05)
        return "".join(chunks)
