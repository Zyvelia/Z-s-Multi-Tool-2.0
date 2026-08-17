"""
template_loader.py
-------------------
Responsible for discovering and validating game folder-structure templates.

Templates live as individual *.json files inside a templates directory
(one file per game). Adding support for a new game is just a matter of
dropping a new JSON file into that folder - no code changes required.

Expected JSON schema:
{
    "name": "Game Name",
    "folders": ["Client", "Client/WindowsNoEditor", ...],
    "files": ["Client/WindowsNoEditor/HT/Binaries/Win64/HTGame.exe"]   # optional
}
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import List, Tuple


class TemplateValidationError(Exception):
    """Raised when a template JSON file does not conform to the expected schema."""


@dataclass
class GameTemplate:
    """In-memory representation of a single game's folder-structure template."""

    name: str
    folders: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)
    source_path: str = ""

    @property
    def folder_count(self) -> int:
        return len(self.folders)

    @property
    def file_count(self) -> int:
        return len(self.files)


class TemplateLoader:
    """
    Loads every *.json template file from a directory, validating structure
    and normalizing path separators so templates behave consistently across
    Windows, macOS, and Linux.
    """

    REQUIRED_KEYS: Tuple[str, ...] = ("name", "folders")

    def __init__(self, templates_dir: str):
        self.templates_dir = templates_dir

    def load_all(self) -> Tuple[List[GameTemplate], List[Tuple[str, str]]]:
        """
        Load every template in the templates directory.

        Returns a tuple of (templates, errors) where `errors` is a list of
        (filename, error_message) pairs for any files that failed to parse
        or validate. A broken template never prevents the others from loading.
        """
        templates: List[GameTemplate] = []
        errors: List[Tuple[str, str]] = []

        if not os.path.isdir(self.templates_dir):
            # Create it so the app has somewhere to look next time, rather
            # than failing outright on a fresh install.
            try:
                os.makedirs(self.templates_dir, exist_ok=True)
            except OSError as exc:
                errors.append((self.templates_dir, f"Could not create templates directory: {exc}"))
            return templates, errors

        for filename in sorted(os.listdir(self.templates_dir)):
            if not filename.lower().endswith(".json"):
                continue

            path = os.path.join(self.templates_dir, filename)
            try:
                templates.append(self._load_single(path))
            except (TemplateValidationError, json.JSONDecodeError, OSError) as exc:
                errors.append((filename, str(exc)))

        templates.sort(key=lambda t: t.name.lower())
        return templates, errors

    # ── internals ────────────────────────────────────────────────────────

    def _load_single(self, path: str) -> GameTemplate:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)

        self._validate(data, path)

        folders = [self._normalize(p) for p in data.get("folders", []) if self._normalize(p)]
        files = [self._normalize(p) for p in data.get("files", []) if self._normalize(p)]

        return GameTemplate(
            name=data["name"].strip(),
            folders=folders,
            files=files,
            source_path=path,
        )

    def _validate(self, data: dict, path: str) -> None:
        if not isinstance(data, dict):
            raise TemplateValidationError(f"root element must be a JSON object")

        for key in self.REQUIRED_KEYS:
            if key not in data:
                raise TemplateValidationError(f"missing required key '{key}'")

        if not isinstance(data["name"], str) or not data["name"].strip():
            raise TemplateValidationError("'name' must be a non-empty string")

        if not isinstance(data["folders"], list) or not all(isinstance(x, str) for x in data["folders"]):
            raise TemplateValidationError("'folders' must be a list of strings")

        if "files" in data:
            if not isinstance(data["files"], list) or not all(isinstance(x, str) for x in data["files"]):
                raise TemplateValidationError("'files' must be a list of strings")

    @staticmethod
    def _normalize(rel_path: str) -> str:
        """Convert backslashes to forward slashes and strip leading/trailing slashes."""
        return rel_path.strip().replace("\\", "/").strip("/")
