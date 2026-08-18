"""Per-server console line buffers — survive tab/server switches."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConsoleLine:
    text: str
    tag: str | None = None


class ConsoleBuffer:
    """Ring buffer of tagged console lines for one server."""

    def __init__(self, max_lines: int = 2000):
        self.max_lines = max_lines
        self._lines: list[ConsoleLine] = []

    def append(self, text: str, tag: str | None = None) -> None:
        self._lines.append(ConsoleLine(text=text, tag=tag))
        if len(self._lines) > self.max_lines:
            self._lines.pop(0)

    def clear(self) -> None:
        self._lines.clear()

    def lines(self) -> list[ConsoleLine]:
        return list(self._lines)

    def __len__(self) -> int:
        return len(self._lines)
