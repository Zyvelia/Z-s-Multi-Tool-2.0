"""Source-style RCON client (Valve protocol — Factorio, Palworld, V Rising, etc.)."""

from __future__ import annotations

import socket
import struct
import time

SERVERDATA_AUTH = 3
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_RESPONSE_VALUE = 0


class SourceRconError(Exception):
    pass


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks: list[bytes] = []
    got = 0
    while got < size:
        part = sock.recv(size - got)
        if not part:
            raise SourceRconError("RCON connection closed unexpectedly.")
        chunks.append(part)
        got += len(part)
    return b"".join(chunks)


def _encode_packet(req_id: int, ptype: int, body: str) -> bytes:
    try:
        body_bytes = body.encode("ascii") + b"\x00\x00"
    except UnicodeEncodeError as e:
        raise SourceRconError("RCON commands must use ASCII characters only.") from e
    size = len(body_bytes) + 8
    return struct.pack("<iii", size, req_id, ptype) + body_bytes


def _read_packet(sock: socket.socket) -> tuple[int, int, str]:
    size = struct.unpack("<i", _recv_exact(sock, 4))[0]
    if size < 8:
        raise SourceRconError(f"Invalid RCON packet size: {size}")
    data = _recv_exact(sock, size)
    req_id, ptype = struct.unpack("<ii", data[:8])
    body = data[8:-2].decode("ascii", errors="replace")
    return req_id, ptype, body


class SourceRconClient:
    def __init__(self, host: str, port: int, password: str, *, timeout: float = 5.0):
        self.host = host
        self.port = int(port)
        self.password = password
        self.timeout = timeout

    def execute(self, command: str, *, max_attempts: int = 3) -> str:
        last_error: Exception | None = None
        for attempt in range(max(1, max_attempts)):
            try:
                return self._execute_once(command)
            except SourceRconError as e:
                last_error = e
                if attempt + 1 < max_attempts:
                    time.sleep(0.15)
        raise SourceRconError(str(last_error) if last_error else "RCON command failed.")

    def _execute_once(self, command: str) -> str:
        with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
            sock.settimeout(self.timeout)
            sock.sendall(_encode_packet(1, SERVERDATA_AUTH, self.password))
            req_id, _ptype, _body = _read_packet(sock)
            if req_id == -1:
                raise SourceRconError("RCON authentication failed — check password in Config.")

            sock.sendall(_encode_packet(2, SERVERDATA_EXECCOMMAND, command))
            chunks: list[str] = []
            while True:
                _req_id, ptype, body = _read_packet(sock)
                if ptype == SERVERDATA_AUTH_RESPONSE:
                    continue
                chunks.append(body)
                if ptype == SERVERDATA_RESPONSE_VALUE and not body:
                    break
            return "".join(chunks)
