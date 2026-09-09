"""
binary_scan.py — turn a raw, undocumented binary blob into something a
person can actually read.

Two tools, both game-agnostic:

  extract_strings()  finds printable text runs: plain ASCII, and
                      null-padded UTF-16LE (how most Unity/Unreal/.NET
                      titles store wide strings). This is what lets the
                      "Readable Text" view show "PlayerName", "Elder-
                      wood Blade", quest ids, etc. instead of hex noise.

  search_numeric()   the classic save-editor trick: you know a stat's
                      *value* (say Gold = 500) even though you don't
                      know its offset. Search for 500 encoded every
                      plausible width/signedness, spend or earn gold in
                      game so it becomes a different known value, search
                      again, and whichever offset shows up in both
                      result sets is your field.

Neither function needs to know anything about the game that produced
the bytes — that's what makes this useful before you've reverse
engineered a single field, and it's the same two tools regardless of
which game's save you opened.
"""

from __future__ import annotations
import struct
from dataclasses import dataclass
from typing import Iterable, Optional

_PRINTABLE = set(range(0x20, 0x7F))

NUMERIC_TYPES = {
    "int8": "b", "uint8": "B",
    "int16": "h", "uint16": "H",
    "int32": "i", "uint32": "I",
    "int64": "q", "uint64": "Q",
    "float32": "f", "float64": "d",
}


@dataclass
class StringHit:
    offset: int
    length: int           # length in bytes
    encoding: str          # "ascii" | "utf16le"
    text: str


def extract_strings(raw: bytes, min_length: int = 4) -> list:
    """Every printable ASCII run and UTF-16LE run of at least
    `min_length` characters, sorted by offset. Overlap is fine — this
    is a hit list to browse, not a partition of the file."""
    hits = _extract_ascii(raw, min_length) + _extract_utf16le(raw, min_length)
    hits.sort(key=lambda h: h.offset)
    return hits


def _extract_ascii(raw: bytes, min_length: int) -> list:
    hits = []
    start = None
    n = len(raw)
    for i in range(n):
        if raw[i] in _PRINTABLE:
            if start is None:
                start = i
        else:
            if start is not None and i - start >= min_length:
                hits.append(StringHit(start, i - start, "ascii",
                                       raw[start:i].decode("ascii", "replace")))
            start = None
    if start is not None and n - start >= min_length:
        hits.append(StringHit(start, n - start, "ascii",
                               raw[start:n].decode("ascii", "replace")))
    return hits


def _extract_utf16le(raw: bytes, min_length: int) -> list:
    """`min_length` counts characters (2 bytes each), not bytes."""
    hits = []
    n = len(raw)
    i = 0
    start = None
    count = 0

    def _flush(end):
        if start is not None and count >= min_length:
            hits.append(StringHit(start, end - start, "utf16le",
                                   raw[start:end].decode("utf-16-le", "replace")))

    while i + 1 < n:
        lo, hi = raw[i], raw[i + 1]
        if hi == 0x00 and lo in _PRINTABLE:
            if start is None:
                start = i
            count += 1
            i += 2
            continue
        _flush(i)
        start = None
        count = 0
        i += 1
    _flush(n)
    return hits


def search_numeric(raw: bytes, value, types: Optional[Iterable] = None, endian: str = "<") -> list:
    """[(offset, type_name), ...] for every offset where `value`,
    packed as each candidate numeric type, occurs in `raw`."""
    types = list(types) if types else list(NUMERIC_TYPES)
    hits = []
    for t in types:
        code = NUMERIC_TYPES.get(t)
        if code is None:
            continue
        try:
            needle = struct.pack(endian + code, float(value) if code in ("f", "d") else int(value))
        except (struct.error, ValueError, OverflowError):
            continue
        start = 0
        while True:
            idx = raw.find(needle, start)
            if idx == -1:
                break
            hits.append((idx, t))
            start = idx + 1
    hits.sort(key=lambda h: h[0])
    return hits


def read_numeric(raw: bytes, offset: int, type_name: str, endian: str = "<"):
    code = NUMERIC_TYPES[type_name]
    return struct.unpack_from(endian + code, raw, offset)[0]
