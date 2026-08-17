"""
security.py
Security utilities for the AI Terminal module.

Responsibilities
-----------------
- Provide a memory-only container for the API key so it is never
  accidentally logged, printed, or persisted to disk/config/DB.
- Validate that AI-generated file paths are safe (no path traversal,
  no absolute paths, no drive letters) before anything is written to disk.
- Sanitize project/file names produced by the AI builder.

Nothing in this file ever writes the API key to disk, a log file,
a config file, or a database. InMemorySecret is intentionally NOT
serializable and never reveals its value via repr()/str().
"""

from __future__ import annotations

import os
import re
import unicodedata


class SecurityError(Exception):
    """Raised when a requested filesystem operation is considered unsafe."""


# ---------------------------------------------------------------------------
# API key handling (memory-only)
# ---------------------------------------------------------------------------

class InMemorySecret:
    """
    Holds a secret (e.g. an API key) strictly in process memory.

    - Never written to disk, logs, or any persistence layer.
    - repr()/str() never reveal the raw value.
    - Call .get() explicitly to retrieve the raw value when needed
      (e.g. when constructing the OpenAI client).
    """

    __slots__ = ("_value",)

    def __init__(self, value: str = ""):
        self._value = value or ""

    def set(self, value: str) -> None:
        self._value = value or ""

    def get(self) -> str:
        return self._value

    def clear(self) -> None:
        self._value = ""

    def is_set(self) -> bool:
        return bool(self._value.strip())

    def masked(self) -> str:
        """A safe-to-display representation, e.g. for status labels."""
        v = self._value
        if not v:
            return "(not set)"
        if len(v) <= 8:
            return "*" * len(v)
        return f"{v[:4]}{'*' * (len(v) - 8)}{v[-4:]}"

    def __repr__(self) -> str:
        return "InMemorySecret(****)"

    def __str__(self) -> str:
        return "****"


# ---------------------------------------------------------------------------
# Path / filename safety for the AI Builder
# ---------------------------------------------------------------------------

_INVALID_WIN_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}

_SAFE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9 _.\-]+$")


def sanitize_name(name: str, fallback: str = "project") -> str:
    """
    Sanitize a project or file name coming from AI output or user input.
    Strips dangerous characters, collapses whitespace, prevents reserved
    Windows device names, and guards against empty results.
    """
    if not name:
        return fallback

    name = unicodedata.normalize("NFKD", name)
    name = name.strip()
    name = re.sub(r"[<>:\"|?*\x00-\x1f]", "", name)
    name = re.sub(r"\s+", "_", name)
    name = name.strip("._")

    if not name:
        return fallback

    if name.lower() in _INVALID_WIN_NAMES:
        name = f"_{name}"

    return name[:120]


def is_safe_relative_path(rel_path: str) -> bool:
    """
    Returns True only if rel_path is a "clean" relative path suitable
    for writing inside a sandboxed project directory:

    - Not empty
    - Not absolute (no leading '/', no leading '\\', no drive letter like 'C:')
    - No '..' path traversal segments
    - No null bytes
    - Each path segment only contains safe characters
    """
    if not rel_path or not isinstance(rel_path, str):
        return False

    if "\x00" in rel_path:
        return False

    normalized = rel_path.replace("\\", "/")

    if normalized.startswith("/"):
        return False

    if re.match(r"^[A-Za-z]:[/\\]", rel_path):
        return False

    parts = [p for p in normalized.split("/") if p != ""]

    if not parts:
        return False

    for part in parts:
        if part in ("..", "."):
            return False
        if not _SAFE_SEGMENT_RE.match(part):
            return False

    return True


def resolve_safe_path(base_dir: str, rel_path: str) -> str:
    """
    Resolve rel_path against base_dir and guarantee the resulting
    absolute path is still contained within base_dir.

    Raises SecurityError if the path is unsafe in any way.
    """
    if not is_safe_relative_path(rel_path):
        raise SecurityError(f"Unsafe or invalid path rejected: {rel_path!r}")

    base_abs = os.path.abspath(base_dir)
    target_abs = os.path.abspath(os.path.join(base_abs, rel_path))

    if os.path.commonpath([base_abs, target_abs]) != base_abs:
        raise SecurityError(f"Path escapes project sandbox: {rel_path!r}")

    return target_abs


# Shell command execution is intentionally NOT implemented anywhere in this
# module. The AI builder must only ever create files/folders via
# resolve_safe_path(); it must never call subprocess/os.system/exec with
# AI-generated content.
FORBIDDEN_EXECUTION_NOTICE = (
    "AI Terminal builder does not execute shell commands, scripts, or code "
    "produced by the AI. It only writes files to the sandboxed AI_Projects "
    "directory."
)
