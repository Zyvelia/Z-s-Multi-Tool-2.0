"""
generator.py
------------
Pure business logic for creating a single game's folder structure.

A GameRecord describes one thing: the relative path to its main executable.
The entire folder tree for that game *is* just that path's parent
directories, so the core operation is intentionally tiny:

    full_path = Path(output_root) / game.exe
    full_path.parent.mkdir(parents=True, exist_ok=True)
    full_path.touch(exist_ok=True)

When a stub executable is supplied (e.g. a copy of mGBA), that last line
becomes a copy-and-rename instead of a touch:

    shutil.copy2(stub_exe_path, full_path)

...so every generated game folder ends up with a real, double-clickable
file named after that game's executable, rather than an empty placeholder.
If no stub is supplied (or it can't be found), generation falls back to the
empty-placeholder behavior automatically.

This module wraps that idea with structured results and per-folder progress
reporting (so the UI can show a live log and an accurate folder count), but
the underlying operation never gets more complicated than the snippets
above. It has no UI dependencies and can be reused from a CLI or test script.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from .game_database import GameRecord

ProgressCallback = Optional[Callable[[str], None]]


@dataclass
class GenerationResult:
    """Summary of what happened during a single generation run."""

    success: bool
    full_path: str
    folders_created: int = 0
    file_created: bool = False
    file_skipped: bool = False
    used_stub: bool = False
    errors: List[str] = field(default_factory=list)

    @property
    def total_errors(self) -> int:
        return len(self.errors)


class FolderStructureGenerator:
    """Creates the folder chain (and optional exe) for one GameRecord."""

    def __init__(
        self,
        game: GameRecord,
        output_root: str,
        create_placeholder_file: bool = True,
        overwrite_file: bool = False,
        stub_exe_path: Optional[str] = None,
    ):
        self.game = game
        self.output_root = Path(output_root)
        self.create_placeholder_file = create_placeholder_file
        self.overwrite_file = overwrite_file
        # Path to a template exe (e.g. mGba.exe) to copy and rename to the
        # game's real executable name. None/missing => empty placeholder.
        self.stub_exe_path = stub_exe_path

    def generate(self, progress_callback: ProgressCallback = None) -> GenerationResult:
        """
        Create every folder in the game's exe path, then optionally touch an
        empty placeholder for the executable itself. Never raises - all
        failures are collected into the returned GenerationResult.
        """

        def log(message: str) -> None:
            if progress_callback:
                progress_callback(message)

        parts = self.game.exe_parts
        if not parts:
            return GenerationResult(
                success=False,
                full_path=str(self.output_root),
                errors=[f"'{self.game.name}' has no executable path defined."],
            )

        full_path = self.output_root / Path(*parts)
        result = GenerationResult(success=True, full_path=str(full_path))

        # Walk the chain one folder at a time - functionally identical to a
        # single `full_path.parent.mkdir(parents=True, exist_ok=True)` call,
        # but lets us report progress and an accurate "folders created" count.
        current = self.output_root
        for segment in parts[:-1]:
            current = current / segment
            try:
                already_existed = current.exists()
                current.mkdir(exist_ok=True)
                if not already_existed:
                    result.folders_created += 1
                    log(f"✓ Folder: {segment}")
            except OSError as exc:
                result.errors.append(f"Could not create folder '{current}': {exc}")
                log(f"✕ Folder failed: {segment} ({exc})")

        # ── Optional executable file: copy+rename a stub, or touch empty ──
        if self.create_placeholder_file:
            try:
                if full_path.exists() and not self.overwrite_file:
                    result.file_skipped = True
                    log(f"⚠ Skipped existing file: {full_path.name}")
                elif self.stub_exe_path and Path(self.stub_exe_path).is_file():
                    # Copy the stub (e.g. mGba.exe) to the destination and
                    # rename it to the game's real executable name in one
                    # step, since the destination filename comes from
                    # `full_path` itself. copy2 preserves metadata like the
                    # stub's modified time.
                    shutil.copy2(self.stub_exe_path, full_path)
                    result.file_created = True
                    result.used_stub = True
                    log(f"✓ Copied stub → {full_path.name}")
                else:
                    if self.stub_exe_path:
                        log(f"⚠ Stub not found at '{self.stub_exe_path}', creating empty file instead")
                    full_path.touch(exist_ok=True)
                    result.file_created = True
                    log(f"✓ File: {full_path.name}")
            except OSError as exc:
                result.errors.append(f"Could not create file '{full_path}': {exc}")
                log(f"✕ File failed: {full_path.name} ({exc})")

        result.success = result.total_errors == 0
        return result
