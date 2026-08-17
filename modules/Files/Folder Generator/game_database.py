"""
game_database.py
-----------------
Loads and validates the single `games.json` database that describes every
game (or application) this module can scaffold a folder structure for.

Instead of one JSON template file per game, everything lives in one file
that's easy to search, diff, and hand-edit:

    {
        "NTE: Neverness to Everness": {
            "category": "Game",
            "developer": "Hotta Studio",
            "publisher": "Perfect World Games",
            "platform": "PC",
            "exe": "Neverness To Everness/Client/WindowsNoEditor/HT/Binaries/Win64/HTGame.exe",
            "icon": "icons/nte.png"
        }
    }

Only "exe" - the relative path to the game's main executable - is required.
Every other field is optional metadata, and any field this module doesn't
know about is preserved on the record's `extra` dict rather than discarded,
so the database can grow without ever touching code.

The whole folder tree for a game is derived purely from its "exe" path: the
executable's parent directories *are* the folder structure. There is no
separate "folders" list to keep in sync.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Metadata fields the UI knows how to surface explicitly. Anything else in a
# record is kept in `extra` so new fields never require code changes.
_KNOWN_FIELDS = ("category", "developer", "publisher", "platform", "icon")

# "exe" is the preferred field name; "path" is accepted as a legacy synonym.
_EXE_FIELDS = ("exe", "path")


class GameDatabaseError(Exception):
    """Raised for problems reading games.json itself (not individual records)."""


@dataclass
class GameRecord:
    """A single game's metadata plus the relative path to its main executable."""

    name: str
    exe: str
    category: Optional[str] = None
    developer: Optional[str] = None
    publisher: Optional[str] = None
    platform: Optional[str] = None
    icon: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def exe_parts(self) -> List[str]:
        """The exe path split into segments, normalized to forward slashes first."""
        normalized = self.exe.replace("\\", "/").strip("/")
        return [p for p in normalized.split("/") if p]


class GameDatabase:
    """Loads, validates, and can persist games.json - the single source of truth."""

    def __init__(self, database_path: str):
        self.database_path = database_path

    def load(self) -> Tuple[List[GameRecord], List[str]]:
        """
        Load every record from games.json.

        Returns (games, warnings). An individual malformed record produces a
        warning and is skipped rather than aborting the whole load. A missing
        or unreadable file is also reported as a warning so the UI can show
        an empty-but-functional state instead of crashing.
        """
        games: List[GameRecord] = []
        warnings: List[str] = []

        if not os.path.isfile(self.database_path):
            warnings.append(f"Database not found: {self.database_path}")
            return games, warnings

        try:
            with open(self.database_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"Could not read {self.database_path}: {exc}")
            return games, warnings

        if not isinstance(data, dict):
            warnings.append(f"{self.database_path}: root element must be a JSON object of games")
            return games, warnings

        for name, record in data.items():
            try:
                games.append(self._parse_record(name, record))
            except GameDatabaseError as exc:
                warnings.append(str(exc))

        games.sort(key=lambda g: g.name.lower())
        return games, warnings

    def save_all(self, games: List[GameRecord]) -> None:
        """
        Persist in-memory records back to games.json, preserving any `extra`
        fields. Not wired into the UI by default, but available for scripts
        or an future "edit database" panel that wants to write changes back.
        """
        payload: Dict[str, Dict[str, Any]] = {}
        for game in games:
            entry: Dict[str, Any] = {"exe": game.exe}
            for field_name in _KNOWN_FIELDS:
                value = getattr(game, field_name)
                if value is not None:
                    entry[field_name] = value
            entry.update(game.extra)
            payload[game.name] = entry

        with open(self.database_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=4, ensure_ascii=False)

    # ── internals ────────────────────────────────────────────────────────

    def _parse_record(self, name: str, record: Any) -> GameRecord:
        if not isinstance(name, str) or not name.strip():
            raise GameDatabaseError("Skipped a record with an empty/invalid name")

        if not isinstance(record, dict):
            raise GameDatabaseError(f"'{name}': record must be a JSON object")

        exe = next(
            (record[f] for f in _EXE_FIELDS if isinstance(record.get(f), str) and record[f].strip()),
            None,
        )
        if not exe:
            raise GameDatabaseError(f"'{name}': missing required 'exe' (or legacy 'path') field")

        known = {k: record[k] for k in _KNOWN_FIELDS if isinstance(record.get(k), str)}
        extra = {k: v for k, v in record.items() if k not in _KNOWN_FIELDS and k not in _EXE_FIELDS}

        return GameRecord(name=name.strip(), exe=exe.strip(), extra=extra, **known)
