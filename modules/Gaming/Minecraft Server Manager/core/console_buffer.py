"""Per-server console line buffer (line text + log tag)."""

from __future__ import annotations

MAX_LINES = 2000


class ConsoleBuffer:
    def __init__(self, max_lines: int = MAX_LINES) -> None:
        self._max_lines = max_lines
        self._buffers: dict[str, list[tuple[str, str]]] = {}

    def append(self, server_id: str, line: str, tag: str) -> None:
        buf = self._buffers.setdefault(server_id, [])
        buf.append((line, tag))
        if len(buf) > self._max_lines:
            del buf[: len(buf) - self._max_lines]

    def lines(self, server_id: str) -> list[tuple[str, str]]:
        return list(self._buffers.get(server_id, []))

    def clear(self, server_id: str) -> None:
        self._buffers[server_id] = []

    def remove_server(self, server_id: str) -> None:
        self._buffers.pop(server_id, None)
