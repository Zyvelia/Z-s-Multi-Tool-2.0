"""
commands.py
Slash-command parsing and dispatch for the AI Terminal.

This module knows nothing about CustomTkinter - it only receives plain
strings and calls back into handler functions supplied by page.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional

HELP_TEXT = """Available commands:
  /help              Show this help message
  /clear             Clear the terminal output (keeps conversation history)
  /new               Start a new session (clears output AND conversation history)
  /build <prompt>    Ask the AI to design and generate a complete multi-file project
  /models            List models available from the current provider
  /test              Test the connection to the configured provider/key/model
  /output            Open the output folder in File Explorer (see Output panel above)
  /openlast          Open the most recently built project's folder in File Explorer

Anything else you type is sent directly to the AI as a chat message.
"""


@dataclass
class Command:
    name: str
    argument: str


def parse(raw_input: str) -> Optional[Command]:
    """
    Returns a Command if raw_input starts with '/', otherwise None
    (meaning: treat as a normal chat message).
    """
    text = raw_input.strip()
    if not text.startswith("/"):
        return None
    parts = text[1:].split(" ", 1)
    name = parts[0].lower().strip()
    argument = parts[1].strip() if len(parts) > 1 else ""
    return Command(name=name, argument=argument)


class CommandRouter:
    """
    Maps command names to handler callables of signature: (argument: str) -> None
    Handlers are expected to write their own output to the terminal via
    whatever mechanism page.py wires up.
    """

    def __init__(self):
        self._handlers: Dict[str, Callable[[str], None]] = {}

    def register(self, name: str, handler: Callable[[str], None]) -> None:
        self._handlers[name.lower()] = handler

    def dispatch(self, command: Command) -> bool:
        """Returns True if a handler was found and invoked."""
        handler = self._handlers.get(command.name)
        if handler is None:
            return False
        handler(command.argument)
        return True

    def known_commands(self):
        return sorted(self._handlers.keys())
