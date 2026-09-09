"""
binary_template.py — structured editing for proprietary binary saves.

No parser can guess a custom binary layout from nothing; someone has to
figure out the offsets (usually with a hex editor + trial and error, or by
diffing two saves that differ by one known value — see SaveFile.diff for
exactly that workflow). Once you know the layout, describe it here and get
named, typed, read/write access instead of hand-editing hex.

Example:
    tmpl = BinaryTemplate([
        Field("gold",      offset=0x10, type="uint32"),
        Field("level",     offset=0x14, type="uint8"),
        Field("player_name", offset=0x20, type="cstr", size=16),
        Field("hp_float",  offset=0x40, type="float32"),
    ])
    view = tmpl.load("save.bin")
    view["gold"] = 99999
    view.save("save_edited.bin")
"""

from __future__ import annotations
import struct
from dataclasses import dataclass
from typing import Any

_STRUCT_CODES = {
    "int8": "b", "uint8": "B",
    "int16": "h", "uint16": "H",
    "int32": "i", "uint32": "I",
    "int64": "q", "uint64": "Q",
    "float32": "f", "float64": "d",
}


def read_value(raw, type_: str, offset: int, size: int = None, endian: str = "<"):
    """Standalone read of one typed value out of any bytes-like object.
    Shared by BinaryView and by SaveFile.get_binary_field, so raw-binary
    saves get the exact same field types whether accessed through a
    full BinaryTemplate or a single ad-hoc offset from a GameLayout."""
    if type_ == "cstr":
        chunk = bytes(raw[offset: offset + size])
        return chunk.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
    if type_ == "utf16str":
        chunk = bytes(raw[offset: offset + size])
        text = chunk.decode("utf-16-le", errors="replace")
        return text.split("\x00", 1)[0]
    if type_ == "bytes":
        return bytes(raw[offset: offset + size])
    code = _STRUCT_CODES[type_]
    return struct.unpack_from(endian + code, raw, offset)[0]


def write_value(raw: bytearray, type_: str, offset: int, value, size: int = None, endian: str = "<"):
    """Standalone write of one typed value into a mutable bytearray-like
    object, in place. See read_value."""
    if type_ == "cstr":
        encoded = str(value).encode("utf-8")[: size - 1]
        raw[offset: offset + size] = encoded + b"\x00" * (size - len(encoded))
        return
    if type_ == "utf16str":
        encoded = str(value).encode("utf-16-le")[: max(size - 2, 0)]
        raw[offset: offset + size] = encoded + b"\x00" * (size - len(encoded))
        return
    if type_ == "bytes":
        if len(value) != size:
            raise ValueError(f"Expected exactly {size} bytes, got {len(value)}")
        raw[offset: offset + size] = value
        return
    code = endian + _STRUCT_CODES[type_]
    struct.pack_into(code, raw, offset, value)


@dataclass
class Field:
    name: str
    offset: int
    type: str            # one of _STRUCT_CODES, or "cstr" / "utf16str" / "bytes"
    size: int = None      # required for "cstr" / "utf16str" and "bytes"
    endian: str = "<"     # "<" little-endian (most common), ">" big-endian


class BinaryTemplate:
    def __init__(self, fields: list, checksum: "ChecksumRule | None" = None):
        self.fields = {f.name: f for f in fields}
        self.checksum = checksum

    def load(self, path: str) -> "BinaryView":
        with open(path, "rb") as f:
            raw = bytearray(f.read())
        return BinaryView(raw, self)

    def loads(self, raw: bytes) -> "BinaryView":
        return BinaryView(bytearray(raw), self)


class BinaryView:
    """A live view over a bytearray, exposing template fields dict-style."""

    def __init__(self, raw: bytearray, template: BinaryTemplate):
        self.raw = raw
        self.template = template

    def __getitem__(self, name: str) -> Any:
        f = self.template.fields[name]
        return read_value(self.raw, f.type, f.offset, f.size, f.endian)

    def __setitem__(self, name: str, value: Any) -> None:
        f = self.template.fields[name]
        write_value(self.raw, f.type, f.offset, value, f.size, f.endian)

    def as_dict(self) -> dict:
        return {name: self[name] for name in self.template.fields}

    def save(self, path: str) -> None:
        if self.template.checksum:
            self.template.checksum.apply(self.raw)
        with open(path, "wb") as f:
            f.write(self.raw)

    def to_bytes(self) -> bytes:
        if self.template.checksum:
            self.template.checksum.apply(self.raw)
        return bytes(self.raw)


# ----------------------------------------------------------------------
# Checksums — a lot of game saves reject the file if a checksum over the
# data doesn't match, so editing bytes without recalculating it just makes
# the game refuse to load the save.
# ----------------------------------------------------------------------

class ChecksumRule:
    """
    Recalculates and writes a checksum after edits.
    algo: "crc32" | "adler32" | "sum8" | "sum16" | "sum32"
    """

    def __init__(self, algo: str, data_range: tuple, write_offset: int,
                 write_type: str = "uint32", endian: str = "<"):
        self.algo = algo
        self.data_range = data_range      # (start, end) bytes the checksum covers
        self.write_offset = write_offset  # where to write the computed checksum
        self.write_type = write_type
        self.endian = endian

    def compute(self, raw: bytearray) -> int:
        import zlib
        start, end = self.data_range
        chunk = bytes(raw[start:end])
        if self.algo == "crc32":
            return zlib.crc32(chunk) & 0xFFFFFFFF
        elif self.algo == "adler32":
            return zlib.adler32(chunk) & 0xFFFFFFFF
        elif self.algo == "sum8":
            return sum(chunk) & 0xFF
        elif self.algo == "sum16":
            return sum(chunk) & 0xFFFF
        elif self.algo == "sum32":
            return sum(chunk) & 0xFFFFFFFF
        raise ValueError(f"Unknown checksum algo: {self.algo}")

    def apply(self, raw: bytearray) -> None:
        value = self.compute(raw)
        code = self.endian + _STRUCT_CODES[self.write_type]
        struct.pack_into(code, raw, self.write_offset, value)
