"""
layouts.py — per-game custom editor layouts.

A GameLayout is a named set of FieldSpecs: label you choose ("Gold",
"Coins", whatever the game calls it) + where the value actually lives
+ a type/range. The UI renders these as a plain labeled form instead of
the generic tree/hex view, grouped into sections you name.

A FieldSpec points at a value one of two ways:
  - `path`   for structured saves (JSON/XML/YAML/INI/etc): a SaveFile
             path like "player.stats.gold".
  - `offset` for raw/unrecognized binary saves: a byte offset into the
             save's raw bytes, read/written with `type` + `size` +
             `endian` (int8..float64, "cstr", "utf16str", "bytes").
             This is the same field concept binary_template.Field uses;
             a layout is just a saved, named collection of them.
Exactly one of path/offset should be set on a given field — this is
what makes one layout system cover both a plain JSON save and a fully
proprietary binary one, for any game.

match_paths / match_bytes let a layout auto-select itself when a save
is opened: if every listed path resolves (structured saves) or every
listed byte signature matches at its offset (binary saves), this is
almost certainly that game's save, so the right view is shown
automatically instead of the generic tree/hex fallback.
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from typing import Optional

# Binary primitive types a FieldSpec can use when it has an `offset`
# instead of a `path`. Kept in sync with binary_template._STRUCT_CODES
# plus the string/bytes special cases.
BINARY_TYPES = [
    "int8", "uint8", "int16", "uint16", "int32", "uint32",
    "int64", "uint64", "float32", "float64", "cstr", "utf16str", "bytes",
]


@dataclass
class FieldSpec:
    label: str                    # what YOU want it called, e.g. "Gold"
    path: str = ""                 # SaveFile path (structured saves)
    type: str = "auto"            # "int"|"float"|"string"|"bool"|"auto" (path fields)
                                   # or one of BINARY_TYPES (offset fields)
    section: str = "General"      # groups fields under a heading in the UI
    min: Optional[float] = None
    max: Optional[float] = None
    step: float = 1
    # -- binary (offset) fields only --
    offset: Optional[int] = None  # byte offset into the save's raw bytes
    size: Optional[int] = None    # required for "cstr" / "utf16str" / "bytes"
    endian: str = "<"             # "<" little-endian (most common) | ">" big-endian

    @property
    def is_binary(self) -> bool:
        return self.offset is not None


@dataclass
class GameLayout:
    name: str
    match_paths: list = field(default_factory=list)   # paths that must all exist to auto-select this layout
    match_bytes: list = field(default_factory=list)   # [{"offset": int, "hex": "deadbeef"}, ...]
    fields: list = field(default_factory=list)         # list[FieldSpec]

    def matches(self, sf) -> int:
        """Returns how many match_paths/match_bytes resolve (0 = no match at all)."""
        hits = 0
        for p in self.match_paths:
            try:
                sf.get(p)
                hits += 1
            except Exception:
                return 0  # any required path missing -> not this layout
        if self.match_bytes:
            raw = sf.data.get("_raw") if isinstance(sf.data, dict) else None
            if raw is None:
                return 0
            for sig in self.match_bytes:
                try:
                    needle = bytes.fromhex(sig["hex"])
                    off = int(sig["offset"])
                except (KeyError, ValueError):
                    return 0
                if bytes(raw[off: off + len(needle)]) != needle:
                    return 0
                hits += 1
        return hits or (1 if not self.match_paths and not self.match_bytes else 0)


def find_layout_for(sf, layouts: list) -> Optional[GameLayout]:
    best, best_score = None, 0
    for layout in layouts:
        score = layout.matches(sf)
        if score > best_score:
            best, best_score = layout, score
    return best


# ----------------------------------------------------------------------
# Persistence — plain JSON, one file holding every layout you've built.
# ----------------------------------------------------------------------

def load_layouts(path: str) -> list:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out = []
    for l in raw:
        fields_ = [FieldSpec(**fs) for fs in l.get("fields", [])]
        out.append(GameLayout(
            name=l["name"],
            match_paths=l.get("match_paths", []),
            match_bytes=l.get("match_bytes", []),
            fields=fields_,
        ))
    return out


def save_layouts(path: str, layouts: list) -> None:
    raw = [{
        "name": l.name,
        "match_paths": l.match_paths,
        "match_bytes": l.match_bytes,
        "fields": [vars(f) for f in l.fields],
    } for l in layouts]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)
